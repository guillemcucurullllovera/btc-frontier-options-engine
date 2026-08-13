"""C9 · M5.4 — P-vol regime fix + full-structure risk (methodology fix, not new modeling).

SIMULATED / diagnostic; MS-26-gated; holder-basis; frozen anchor. Corrects the M5.1 P-vol choice
(the 2-year unconditional) to a GARCH conditional FORWARD forecast, presented across a vol-regime
band; runs ALL structures; and surfaces the honest regime-dependence of the VRP (its sign is a
realized-vol-window artifact).

Oracle: the GARCH forward forecast mean-reverts between the current and unconditional levels; the
leg-based P&L matches the manual formula; the VRP flips sign across the vol band; the defined-risk
collar's tail is capped well below the amplified-downside LBSP.
"""

from __future__ import annotations

import math

import numpy as np

from strategy.bates_risk import (
    STRUCTURES,
    PhysicalRiskConfig,
    regime_risk_table,
    structure_pnl,
    structure_vrp,
)
from vol.garch import GarchEstimator, forward_forecast_vol


def _garch_series(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = [0.0]
    s2 = 1e-4
    for _ in range(n):
        s2 = 5e-5 + 0.10 * r[-1] ** 2 + 0.85 * s2
        r.append(math.sqrt(s2) * rng.standard_normal())
    return np.array(r[1:], dtype=np.float64)


def test_forward_forecast_mean_reverts_between_current_and_unconditional() -> None:
    """The GARCH forward forecast lies between the current conditional and the unconditional vol."""
    r = _garch_series(1500, seed=3)
    g = GarchEstimator(r).fit()
    current = math.sqrt(g.conditional_variances[-1]) * math.sqrt(365)
    uncond = math.sqrt(g.params.unconditional_variance) * math.sqrt(365)
    fwd = forward_forecast_vol(g, float(r[-1]), horizon_days=45)
    lo, hi = min(current, uncond), max(current, uncond)
    assert lo - 1e-9 <= fwd <= hi + 1e-9              # forward forecast between current and long-run
    assert fwd > 0.0


def test_structure_pnl_matches_manual_collar() -> None:
    S0, T = 100.0, 0.25
    st = np.array([70.0, 100.0, 130.0])
    sdef = STRUCTURES["collar"]                        # short call +5%, long put -10%
    from strategy.bates_risk import q_bates_premium

    kc, kp = S0 * 1.05, S0 * 0.90
    prem_c, prem_p = q_bates_premium(S0, kc, T, "call"), q_bates_premium(S0, kp, T, "put")
    manual = (st - S0) + (prem_c - np.maximum(st - kc, 0.0)) - (prem_p - np.maximum(kp - st, 0.0))
    assert np.allclose(structure_pnl(sdef, S0, st, T), manual)


def test_vrp_sign_flips_across_vol_band() -> None:
    """VRP is positive under a calm P-vol and negative under a stressed one (window artifact)."""
    cfg = PhysicalRiskConfig(n_paths=60_000, n_steps=45)
    from dataclasses import replace

    st_calm = __import__("strategy.bates_risk", fromlist=["simulate_terminal"]).simulate_terminal(
        replace(cfg, p_vol=0.28), "Bates")
    st_stress = __import__("strategy.bates_risk", fromlist=["simulate_terminal"]).simulate_terminal(
        replace(cfg, p_vol=0.50), "Bates")
    sdef = STRUCTURES["long_btc_plus_short_put"]
    vrp_calm = structure_vrp(sdef, cfg.S0, st_calm, cfg.T)
    vrp_stress = structure_vrp(sdef, cfg.S0, st_stress, cfg.T)
    assert vrp_calm > 0.0                              # implied ~37% > realized 28% => positive VRP
    assert vrp_stress < 0.0                            # implied ~37% < realized 50% => negative VRP


def test_all_structures_run_with_se_ci() -> None:
    cfg = PhysicalRiskConfig(n_paths=40_000, n_steps=45)
    vol_band = {"current": 0.31, "forecast": 0.43, "stress": 0.46}
    rows = regime_risk_table(cfg, vol_band, (0.0,), n_boot=60)
    assert {r.structure for r in rows} == set(STRUCTURES)
    assert {r.vol_regime for r in rows} == {"current", "forecast", "stress"}
    for r in rows:
        assert r.cvar95_se >= 0.0                                  # SE present (0 for capped defined-risk tails)
        # ES >= VaR (coherence); equality within float epsilon for capped defined-risk structures.
        assert 0.0 <= r.prob_loss <= 1.0 and r.es975 >= r.var95 - 1e-6 * max(abs(r.var95), 1.0)


def test_collar_tail_capped_below_lbsp() -> None:
    """The defined-risk collar's tail (protective put) is far below the amplified-downside LBSP."""
    cfg = PhysicalRiskConfig(n_paths=60_000, n_steps=45)
    rows = regime_risk_table(cfg, {"stress": 0.46}, (0.0,),
                             structures=("collar", "long_btc_plus_short_put"), n_boot=60)
    by = {r.structure: r for r in rows}
    assert by["collar"].es975 < 0.5 * by["long_btc_plus_short_put"].es975


def test_drift_band_shifts_mean() -> None:
    cfg = PhysicalRiskConfig(n_paths=40_000, n_steps=45)
    rows = regime_risk_table(cfg, {"forecast": 0.43}, (-0.10, 0.0, 0.10),
                             structures=("covered_call",), n_boot=40)
    means = [r.mean_pnl for r in sorted(rows, key=lambda x: x.drift)]
    assert means[0] < means[1] < means[2]              # constructive drift raises the mean
