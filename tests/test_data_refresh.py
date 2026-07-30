"""C9 · M4.6 — data-refresh: full 2-year Massive daily history + robust P-estimation.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. A DATA fix, not new modeling: the
physical-measure estimation is re-run on the full ~728-bar OBSERVED daily history (vs the 64-bar
snapshot diagnostic), so the P-estimates are no longer small-sample degenerate. The frozen
option-chain / DVOL anchor is untouched (the Q-calibration is unaffected).

Key refresh finding (asserted below): the 64-bar "100% downward" jump signature was a small-sample
artifact — over 2 years the realized jumps are roughly symmetric, and GARCH no longer degenerates.
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np

from vol.filter import filter_consistency, unscented_kalman_sv
from vol.garch import GarchEstimator
from vol.jumps import bipower_variation, estimate_jump_params, lee_mykland, log_returns

_HIST = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "history_full"
_DT = 1.0 / 365.0


def _closes() -> np.ndarray:
    rows = json.loads((_HIST / "spot_history.json").read_text())
    return np.array([x["close"] for x in rows], dtype=np.float64)


def test_full_history_loaded_observed() -> None:
    """The refreshed history is ~2 years of OBSERVED daily bars (frozen anchor untouched)."""
    rows = json.loads((_HIST / "spot_history.json").read_text())
    meta = json.loads((_HIST / "spot_history_meta.json").read_text())
    assert len(rows) > 600                                  # ~728 daily bars, ~2 years
    assert all(row["provenance"] == "observed" for row in rows[:20])
    assert meta["source"] == "massive" and meta["provenance"] == "OBSERVED"
    assert all(row["close"] > 0 for row in rows)


def test_garch_not_degenerate_on_full_history() -> None:
    """On ~727 obs GARCH converges with finite, positive SE (no small-sample degeneracy)."""
    r = log_returns(_closes())
    g = GarchEstimator(r).fit()
    assert g.convergence
    assert 0.0 < g.params.persistence < 1.0
    assert g.params.alpha > 0.0                             # ARCH effect identified (was ~0 on 63 obs)
    for se in (g.param_std_errors, g.param_std_errors_fisher):
        assert math.isfinite(se["alpha"]) and se["alpha"] > 0.0
        assert math.isfinite(se["beta"]) and se["beta"] > 0.0    # Fisher SE finite (was nan on 63 obs)


def test_refreshed_jumps_less_asymmetric_than_64bar() -> None:
    """Over 2 years the realized jumps are roughly symmetric (the 64-bar 100%-down was an artifact)."""
    r = log_returns(_closes())
    jp = estimate_jump_params(r, lee_mykland(r, window=20, alpha=0.05))
    assert jp.n_jumps >= 3                                  # multiple jumps over 2 years
    assert 0.25 < jp.frac_downward < 0.75                   # NOT 100% down — roughly balanced
    assert 0.0 < bipower_variation(r).relative_jump < 0.5   # a sane jump-variance share


def test_refreshed_ukf_consistent_on_full_history() -> None:
    """The UKF on the full history is consistent (white innovations, NIS ~ 1, plausible vol)."""
    r = log_returns(_closes())
    res = unscented_kalman_sv(r, kappa=9.0, theta=0.25, vol_of_vol=1.0, dt=_DT,
                              v0=float(np.var(r) / _DT))
    fc = filter_consistency(res, lags=10)
    assert fc.innovations_white and fc.nis_in_band
    assert 0.2 < float(np.sqrt(res.filtered_variance.mean())) < 1.0    # plausible ~2yr BTC vol
