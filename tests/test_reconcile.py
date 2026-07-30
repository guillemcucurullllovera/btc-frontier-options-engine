"""C9 · M4.5 — Q-vs-P reconciliation (resolves the M3 degenerate-jump finding).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Ties together the Q calibration
(M2 Heston theta, M3 Bates jumps) and the P estimation (M4.2 filtered vol, M4.3 realized jumps),
and asserts the resolution: the Q Bates jumps are degenerate and the tail-jump source is the
P-identified realized jumps.
"""

from __future__ import annotations

import json
import pathlib

import numpy as np

from vol.filter import unscented_kalman_sv
from vol.jumps import estimate_jump_params, lee_mykland, log_returns
from vol.reconcile import reconcile_q_vs_p

_DT = 1.0 / 365.0


def _btc_returns() -> np.ndarray:
    path = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "2026-07-30T104316Z" / "spot_history.json"
    rows = json.loads(path.read_text())
    if isinstance(rows, dict):
        rows = rows.get("result", rows)
    return log_returns(np.array([x["close"] for x in rows], dtype=np.float64))


def test_reconciliation_routes_tail_to_p_identified_jumps() -> None:
    """Q Bates jumps degenerate => the tail-jump source is the P-identified realized jumps."""
    r = _btc_returns()
    p_jumps = estimate_jump_params(r, lee_mykland(r, window=10, alpha=0.05))
    p_vol = float(np.sqrt(unscented_kalman_sv(r, 9.0, 0.25, 1.0, _DT, v0=float(np.var(r) / _DT))
                          .filtered_variance.mean()))
    # Q side: M2 Heston theta ~ 0.25; M3 Bates jumps lambda~16.4 (at bound), sigma_j~0.001 (degenerate).
    rec = reconcile_q_vs_p(q_theta=0.254, p_vol_annual=p_vol,
                           q_bates_lam=16.4, q_bates_sigma_j=0.0010, p_jumps=p_jumps)
    assert rec.q_jump.degenerate                                   # M3 Q-jumps flagged unidentified
    assert rec.tail_jump_source == "P-identified realized jumps"   # the resolution
    assert p_jumps.frac_downward >= 0.5                             # P jumps skew down (Xia-Li)
    assert any("DEGENERATE" in n for n in rec.notes)


def test_reconciliation_sv_levels_comparable() -> None:
    """The Q long-run vol (sqrt(theta)) and the P-filtered vol are the same order of magnitude."""
    r = _btc_returns()
    p_vol = float(np.sqrt(unscented_kalman_sv(r, 9.0, 0.25, 1.0, _DT, v0=float(np.var(r) / _DT))
                          .filtered_variance.mean()))
    rec = reconcile_q_vs_p(0.254, p_vol, 16.4, 0.0010, estimate_jump_params(r, lee_mykland(r, window=10)))
    assert 0.3 < rec.q_vol_level < 0.8                              # Q vol ~50%
    assert 0.5 < rec.vol_ratio_q_over_p < 2.0                       # Q and P within a factor of 2


def test_reconciliation_uses_q_jumps_when_identified() -> None:
    """Sanity: a NON-degenerate Q-jump fit would (hypothetically) feed the tail — control case."""
    r = _btc_returns()
    rec = reconcile_q_vs_p(0.254, 0.45, q_bates_lam=2.0, q_bates_sigma_j=0.12,
                           p_jumps=estimate_jump_params(r, lee_mykland(r, window=10)))
    assert not rec.q_jump.degenerate
    assert rec.tail_jump_source == "Q Bates jumps"
