"""C9 · M5.1 — calibrated-model risk integration (physical-simulate, Q-mark).

SIMULATED / diagnostic; MS-26-gated; holder-basis; frozen anchor. No best/optimal language.

Oracles: the holder-basis P&L formulas are unit-checked; the Bates SV+jumps scenario produces
demonstrably fatter tails than GBM (the model effect on VaR/ES/CVaR); every metric carries a
bootstrap SE/CI; the engine is reproducible; the drift band shifts the mean monotonically. The VRP
SIGN is snapshot-dependent and reported (not asserted) — for this anchor it is negative.
"""

from __future__ import annotations

import numpy as np

from strategy.bates_risk import (
    PARAM_PROVENANCE,
    PhysicalRiskConfig,
    bates_risk,
    cvar_frontier,
    holder_basis_pnl,
    q_bates_premium,
    simulate_terminal,
)

_CFG = PhysicalRiskConfig(n_paths=60_000, n_steps=45)
_K = _CFG.S0 * 0.90                       # 10% OTM put
_RISK = bates_risk("long_btc_plus_short_put", _CFG, _K, kind="put", n_boot=120)


def test_holder_basis_pnl_formulas() -> None:
    S0, K = 100.0, 90.0
    st = np.array([70.0, 90.0, 110.0])
    prem = 2.0
    assert np.allclose(holder_basis_pnl("unhedged", S0, K, st, 0.0), st - S0)
    # long BTC + short put: (S_T - S0) + prem - max(K - S_T, 0)
    assert np.allclose(holder_basis_pnl("long_btc_plus_short_put", S0, K, st, prem),
                       (st - S0) + prem - np.maximum(K - st, 0.0))
    # covered call: (S_T - S0) + prem - max(S_T - K, 0)
    assert np.allclose(holder_basis_pnl("covered_call", S0, K, st, prem),
                       (st - S0) + prem - np.maximum(st - K, 0.0))


def test_bates_tails_fatter_than_gbm() -> None:
    """The calibrated Bates (SV + jumps) gives materially fatter tails than GBM — the model effect."""
    g, m, b = _RISK["GBM"], _RISK["Merton"], _RISK["Bates"]
    assert b.es975 > 1.3 * g.es975            # ES97.5 clearly fatter under Bates
    assert b.cvar95.cvar > 1.2 * g.cvar95.cvar
    assert m.es975 > g.es975                    # Merton (jumps) also fatter than GBM


def test_every_metric_carries_se_ci() -> None:
    b = _RISK["Bates"]
    assert b.mean_pnl_se > 0.0
    assert b.cvar95.cvar_se > 0.0 and b.cvar95.cvar_ci[0] <= b.cvar95.cvar <= b.cvar95.cvar_ci[1]
    assert b.evt_tail.var_se is not None and b.evt_tail.var_se > 0.0
    assert b.evt_tail.es_ci is not None


def test_engine_reproducible() -> None:
    a = simulate_terminal(_CFG, "Bates")
    c = simulate_terminal(_CFG, "Bates")
    assert np.array_equal(a, c)


def test_drift_band_shifts_mean_monotonically() -> None:
    """The ASSUMED drift band {-0.10, 0, +0.10} shifts the holder-basis mean P&L monotonically."""
    from dataclasses import replace

    means = []
    for mu in (-0.10, 0.0, 0.10):
        st = simulate_terminal(replace(_CFG, drift=mu), "Bates")
        prem = q_bates_premium(_CFG.S0, _K, _CFG.T, "put")
        means.append(float(np.mean(holder_basis_pnl("long_btc_plus_short_put", _CFG.S0, _K, st, prem))))
    assert means[0] < means[1] < means[2]      # more drift => higher mean (holding appreciation)


def test_vrp_carry_computed_and_provenance_labelled() -> None:
    """VRP carry is computed (sign snapshot-dependent — reported, not asserted) with provenance tags."""
    b = _RISK["Bates"]
    assert np.isfinite(b.vrp_carry)
    assert "Q-CALIBRATED" in PARAM_PROVENANCE["premium_mark"]
    assert "P-ESTIMATED" in PARAM_PROVENANCE["p_vol"]
    assert "ASSUMED" in PARAM_PROVENANCE["drift"]


def test_cvar_frontier_points_have_se_and_vary() -> None:
    pts = cvar_frontier(_CFG, "long_btc_plus_short_put", (-3.0, -5.0, -10.0, -15.0), kind="put", n_boot=100)
    assert len(pts) == 4
    assert all(p.cvar95_se > 0.0 for p in pts)
    cvars = [p.cvar95 for p in pts]
    assert max(cvars) - min(cvars) > 0.0        # the frontier is non-degenerate across strikes


def test_prob_loss_in_unit_interval() -> None:
    for r in _RISK.values():
        assert 0.0 <= r.prob_loss <= 1.0
        assert r.var95 >= 0.0 and r.es975 >= r.var95   # ES >= VaR (coherence)
