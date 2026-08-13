"""C9 · M4.3 — physical-measure realized-jump estimation + Q identifiability guard.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Resolves the M3 degenerate-jump
finding: the tail jump component is identified from the OBSERVED return series, not the Q-calibration.

Oracles: known jumps injected into a simulated series are recovered (intensity, size, downward
asymmetry) with a controlled false-positive rate; the two detectors agree; the guard flags the M3
degenerate params. The real 64-bar BTC series is reported as a small-sample diagnostic.
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np
import pytest

from vol.jumps import (
    bipower_variation,
    estimate_jump_params,
    flag_jump_degeneracy,
    lee_mykland,
    log_returns,
    threshold_jumps,
)

_SIG_D = 0.5 / math.sqrt(365.0)          # ~50% annual vol, daily


def _sim_with_jumps(n: int, n_jumps: int, jmean: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, _SIG_D, n)
    jidx = np.sort(rng.choice(np.arange(30, n - 1), n_jumps, replace=False))
    r[jidx] += rng.normal(jmean, 0.03, n_jumps)
    return r, jidx


def test_lee_mykland_recovers_injected_jumps() -> None:
    """Clear jumps (~5.7 sigma, all down) are recovered with high recall + correct params."""
    r, jidx = _sim_with_jumps(1500, 15, jmean=-0.15, seed=7)
    det = lee_mykland(r, window=20, alpha=0.05)
    detected = set(det.jump_index.astype(int))
    recall = len(detected & set(jidx.tolist())) / len(jidx)
    assert recall >= 0.8                                   # >= 12/15 detected
    jp = estimate_jump_params(r, det)
    assert jp.lam_annual == pytest.approx(det.n_jumps * 365.0 / 1500.0)
    assert jp.jump_mean < -0.1                              # recovered the negative mean
    assert jp.frac_downward > 0.9                           # essentially all downward


def test_false_positive_rate_controlled() -> None:
    """A no-jump Gaussian series yields few false jumps (Gumbel max-test controls the FWER)."""
    rng = np.random.default_rng(11)
    fps = [lee_mykland(rng.normal(0.0, _SIG_D, 1500), window=20, alpha=0.05).n_jumps for _ in range(20)]
    assert float(np.mean(fps)) < 4.0                       # ~1-2 per series, not dozens


def test_bipower_isolates_jump_variation() -> None:
    """RV-BV (jump variation) is large for a jumpy series and ~0 for a continuous one."""
    r_jump, _ = _sim_with_jumps(1500, 15, jmean=-0.15, seed=7)
    r_cont = np.random.default_rng(3).normal(0.0, _SIG_D, 1500)
    assert bipower_variation(r_jump).relative_jump > 0.10
    assert bipower_variation(r_cont).relative_jump < 0.05


def test_threshold_and_lee_mykland_agree_on_clear_jumps() -> None:
    r, _ = _sim_with_jumps(1500, 15, jmean=-0.18, seed=5)
    lm = set(lee_mykland(r, window=20, alpha=0.05).jump_index.astype(int))
    th = set(threshold_jumps(r, c=4.0, window=20).jump_index.astype(int))
    assert len(lm & th) >= 0.7 * min(len(lm), len(th))     # substantial overlap


def test_downward_asymmetry_detected() -> None:
    """Down-biased jumps => frac_downward high and eta_downward > 1 (Xia-Li)."""
    r, _ = _sim_with_jumps(2000, 25, jmean=-0.12, seed=9)
    jp = estimate_jump_params(r, lee_mykland(r, window=20, alpha=0.05))
    assert jp.frac_downward >= 0.75
    assert jp.eta_downward > 1.0                            # downside-driven tail


def test_real_btc_jumps_are_downward_small_sample() -> None:
    """Real 64-bar BTC: detected jumps are downward-asymmetric (diagnostic; small sample)."""
    path = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "2026-07-30T104316Z" / "spot_history.json"
    rows = json.loads(path.read_text())
    if isinstance(rows, dict):
        rows = rows.get("result", rows)
    closes = np.array([row["close"] for row in rows], dtype=np.float64)
    r = log_returns(closes)
    det = lee_mykland(r, window=10, alpha=0.05)
    jp = estimate_jump_params(r, det)
    bp = bipower_variation(r)
    assert det.n_jumps >= 1                                 # at least one jump in the window
    assert jp.frac_downward >= 0.5                          # BTC jumps skew down
    assert 0.0 <= bp.relative_jump < 1.0                    # a sane jump-variance share


def test_identifiability_guard_flags_m3_degenerate_jumps() -> None:
    """The M3 Bates Q-jumps (lambda~16 at bound, sigma_j~0.001) are flagged degenerate."""
    degen = flag_jump_degeneracy(lam=16.4, sigma_j=0.0010, lam_ub=20.0, sigma_j_floor=0.02)
    assert degen.degenerate and degen.sigma_j_below_floor
    assert "sigma_j" in degen.reason
    # A healthy, identified jump fit is not flagged.
    ok = flag_jump_degeneracy(lam=2.5, sigma_j=0.12, lam_ub=20.0, sigma_j_floor=0.02)
    assert not ok.degenerate and ok.reason == "identified"
