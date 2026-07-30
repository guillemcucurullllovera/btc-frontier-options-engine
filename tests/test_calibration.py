"""C9 · M2.1 — Heston calibration to the live Deribit smile.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Heston is stood up + validated
here; it is NOT the production scenario engine (M5) and model selection is M3 — no best/optimal claim.

Oracles: the vectorised slice pricer is checked against the M1 COS pricer (machine eps); a KNOWN
Heston parameter set is recovered from its own synthetic smile (ground truth); the live-snapshot
fit is reproducible across multi-starts and its Feller status / error quartet are reported.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime

import numpy as np
import pytest
from scipy.optimize import brentq

from pricing.black76 import price_black76
from pricing.cf.characteristic_functions import Heston
from pricing.cf.cos import cos_call
from vol.calibrate import (
    HestonCalParams,
    _heston_call_slice,
    calibrate_heston,
    calibration_manifest,
)
from vol.chain_surface import ChainSlice, ingest_chain_slices
from vol.snapshot import load_snapshot

FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_SNAP = load_snapshot(FIXTURE_DIR)
_SLICES = ingest_chain_slices(_SNAP.instruments, _SNAP.book_summaries, datetime(2026, 7, 30, tzinfo=UTC))
# One live-snapshot calibration, reused across tests (expensive).
_RESULT = calibrate_heston(_SLICES, snapshot_dir=str(FIXTURE_DIR), n_starts=3)


def _b76_iv(F: float, K: float, T: float, px: float) -> float:
    return float(brentq(lambda s: price_black76(F, K, 0.0, s, T, "call") - px, 1e-3, 5.0, xtol=1e-10))


def _synthetic_slices(true: dict[str, float], F: float = 60_000.0) -> list[ChainSlice]:
    """Build arbitrage-free smile slices from a KNOWN Heston (mark_iv = Black-76-inverted price)."""
    slices: list[ChainSlice] = []
    for days in (30, 60, 120, 240):
        T = days / 365.0
        m = Heston(r=0.0, q=0.0, v0=true["v0"], kappa=true["kappa"], theta=true["theta"],
                   sigma=true["vol_of_vol"], rho=true["rho"])
        strikes = np.array([F * x for x in (0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.35)])
        ivs = np.array([_b76_iv(F, float(K), T, cos_call(m, F, float(K), T, N=2048, L=16.0)) for K in strikes])
        kinds = tuple("put" if K < F else "call" for K in strikes)
        slices.append(ChainSlice(expiry=datetime(2026, 9, 1, tzinfo=UTC), label=f"{days}d", T=T,
                                 forward=F, strikes=strikes, k=np.log(strikes / F), mark_iv=ivs,
                                 bid_iv=ivs - 0.005, ask_iv=ivs + 0.005, kinds=kinds))
    return slices


def test_vectorised_slice_pricer_matches_cos() -> None:
    """The vectorised (over-strikes) Heston slice pricer matches the M1 COS pricer to machine eps."""
    p = np.array([0.2, 1.5, 0.2, 0.6, -0.4])
    strikes = np.array([50_000.0, 55_000.0, 60_000.0, 66_000.0, 72_000.0])
    vec = _heston_call_slice(p, 60_000.0, strikes, 0.25, N=192, L=14.0)
    m = Heston(r=0.0, q=0.0, v0=0.2, kappa=1.5, theta=0.2, sigma=0.6, rho=-0.4)
    for i, K in enumerate(strikes):
        assert vec[i] == pytest.approx(cos_call(m, 60_000.0, float(K), 0.25, N=2048, L=16.0), abs=1e-4)


def test_calibration_recovers_known_params() -> None:
    """A KNOWN Heston is recovered from its own synthetic smile (ground-truth identifiability)."""
    true = {"v0": 0.15, "kappa": 3.0, "theta": 0.22, "vol_of_vol": 1.8, "rho": -0.3}
    res = calibrate_heston(_synthetic_slices(true), n_starts=4, t_floor=0.0)
    p = res.params
    assert res.rmse_iv < 1e-3                       # reprices the synthetic chain to ~0
    assert p.v0 == pytest.approx(true["v0"], abs=0.02)
    assert p.theta == pytest.approx(true["theta"], abs=0.02)
    assert p.vol_of_vol == pytest.approx(true["vol_of_vol"], rel=0.1)
    assert p.rho == pytest.approx(true["rho"], abs=0.05)


def test_calibration_multistart_agreement_on_snapshot() -> None:
    """Weekly+ slices => all starts reach the same optimum (reproducible, well-identified)."""
    assert _RESULT.starts_obj_rel_spread < 1e-6
    assert _RESULT.n_starts >= 3


def test_calibration_feller_violated_on_btc() -> None:
    """BTC's calibrated Heston violates Feller (2*kappa*theta < volvol^2) — reported, not enforced."""
    assert not _RESULT.feller_ok
    assert _RESULT.feller_ratio < 1.0
    assert _RESULT.params.vol_of_vol > 1.0          # BTC's large vol-of-vol


def test_calibration_fit_quality_on_scale() -> None:
    """Error quartet is on the MaMaMoMaMa Heston-on-BTC scale (ARPE single-digit %, IV RMSE ~1-2 vp)."""
    assert _RESULT.rmse_iv < 0.03                   # < 3 vol points (global fit across expiries)
    assert 0.0 < _RESULT.arpe < 0.20                # single-to-low-double-digit % (Heston limit -> M3 Bates)
    assert _RESULT.rmse_usd > 0.0 and _RESULT.aae_usd > 0.0
    assert _RESULT.n_options > 100


def test_calibration_manifest_is_calibrated_labelled() -> None:
    man = calibration_manifest(_RESULT)
    assert man["provenance"] == "CALIBRATED"
    assert man["model"] == "Heston"
    params = man["params"]
    refs = man["pending_decision_refs"]
    assert isinstance(params, dict) and set(params) == {"v0", "kappa", "theta", "vol_of_vol", "rho"}
    assert man["feller_ok"] is False
    assert isinstance(refs, list) and "MS-26" in refs


def test_calibration_uses_r0_forward_marking() -> None:
    """B3: the market side is priced Black-76 on the observed forward with r=0 (no injected drift)."""
    from vol.calibrate import _prep_market

    ms = _prep_market(_SLICES[:1])[0]
    K = float(ms.strikes[0])
    expected = price_black76(ms.F, K, 0.0, float(ms.mark_iv[0]), ms.T, ms.kinds[0])
    assert ms.p_market[0] == pytest.approx(expected, rel=1e-12)


def test_heston_cal_params_feller_helpers() -> None:
    ok = HestonCalParams(v0=0.04, kappa=2.0, theta=0.04, vol_of_vol=0.3, rho=-0.5)
    assert ok.feller_ok and ok.feller_ratio >= 1.0
    bad = HestonCalParams(v0=0.2, kappa=1.5, theta=0.25, vol_of_vol=4.0, rho=-0.35)
    assert not bad.feller_ok and bad.feller_ratio < 1.0
