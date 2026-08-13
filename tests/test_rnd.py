"""Tests for the Breeden-Litzenberger RND / crash-probability module (``vol.rnd``).

(a) Lognormal sanity: a synthetic FLAT-IV chain must return the closed-form lognormal RND and
    P(crash)=Phi(.) (Rotunno's own unit-test discipline).
(b) Round-trip: the RND must reprice the OBSERVED fixture chain within the acceptance band.
(c) Non-negativity + normalization gates hold on observed data.
"""

from __future__ import annotations

import math
import pathlib
from datetime import UTC, datetime

import numpy as np
from scipy.stats import norm

from vol.chain_surface import ChainSlice, ingest_chain_slices
from vol.rnd import extract_rnd
from vol.snapshot import load_snapshot

_FIX = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _flat_iv_slice(F: float, sigma: float, T: float, n: int = 41) -> ChainSlice:
    strikes = np.linspace(0.45 * F, 2.2 * F, n)
    iv = np.full(n, sigma)
    nan = np.full(n, np.nan)
    kinds = tuple("put" if K < F else "call" for K in strikes)
    return ChainSlice(
        expiry=datetime(2026, 9, 15, tzinfo=UTC), label="FLAT", T=T, forward=F,
        strikes=strikes, k=np.log(strikes / F), mark_iv=iv, bid_iv=nan, ask_iv=nan, kinds=kinds,
    )


def _lognormal_cdf(x: float, F: float, sigma: float, T: float) -> float:
    """Q-CDF of S_T under Black-76 (r=0, forward F): log S_T ~ N(ln F - 0.5 s^2 T, s^2 T)."""
    return float(norm.cdf((math.log(x / F) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))))


def test_lognormal_flat_iv_matches_closed_form() -> None:
    F, sigma, T = 60_000.0, 0.50, 45.0 / 365.0
    rep = extract_rnd([_flat_iv_slice(F, sigma, T)], spot=F, min_strikes=15)
    assert rep.n_slices == 1
    s = rep.slices[0]
    # density integrates to 1, is non-negative, and the mean equals the forward (r=0).
    assert abs(s.prenorm_mass - 1.0) < 1e-3
    assert s.min_density >= -1e-8
    assert abs(s.rnd_mean / F - 1.0) < 2e-3
    # crash ladder matches the closed-form lognormal CDF to <2e-3 (BL + SVI-fit numerical error).
    for theta, lbl in ((0.80, "-20%"), (0.70, "-30%"), (0.60, "-40%")):
        assert abs(s.crash_prob[lbl] - _lognormal_cdf(theta * F, F, sigma, T)) < 2e-3
    # flat IV => lognormal, whose skewness = (e^{s^2}+2)*sqrt(e^{s^2}-1), s=sigma*sqrt(T).
    s2 = math.exp((sigma * math.sqrt(T)) ** 2)
    lognormal_skew = (s2 + 2.0) * math.sqrt(s2 - 1.0)
    assert abs(s.rnd_skew - lognormal_skew) < 0.03


def test_roundtrip_reprices_observed_fixture() -> None:
    snap = load_snapshot(_FIX)
    slices = ingest_chain_slices(snap.instruments, snap.book_summaries, datetime(2026, 7, 30, tzinfo=UTC))
    rep = extract_rnd(slices, spot=snap.spot.price, objective="vega_price")
    assert rep.n_slices >= 1
    # at least one scored tenor reprices the observed chain within the acceptance band and passes gates.
    good = [s for s in rep.slices if s.roundtrip_arpe_core <= 0.05 and s.gates_pass]
    assert good, f"no tenor passed round-trip: {[(s.label, s.roundtrip_arpe_core) for s in rep.slices]}"


def test_density_nonneg_and_normalized_on_observed() -> None:
    snap = load_snapshot(_FIX)
    slices = ingest_chain_slices(snap.instruments, snap.book_summaries, datetime(2026, 7, 30, tzinfo=UTC))
    rep = extract_rnd(slices, spot=snap.spot.price)
    for s in rep.slices:
        assert s.min_density >= -1e-8, f"{s.label} negative density {s.min_density}"
        assert 0.97 <= s.prenorm_mass <= 1.03, f"{s.label} mass {s.prenorm_mass}"
        # crash ladder is a proper CDF: monotone decreasing as the threshold deepens.
        c = s.crash_prob
        assert c["-20%"] >= c["-30%"] >= c["-40%"] >= c["-50%"] >= 0.0
