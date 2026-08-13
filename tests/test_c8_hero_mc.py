"""C8 Phase 3 tests - rolling-lifecycle hero MC with an independent oracle.

Reconciliation:
  * base P&L distribution reconciles to the C7 engine (strategy.multi_cycle_mc) to
    rtol 1e-9 (same deterministic paths, independently re-implemented economics);
  * a scalar single-path oracle reconciles the extended Slide-5 per-path metrics
    (max drawdown, ITM/touch counts, leg decomposition) exactly.

Campaign gates are exercised at test scale: determinism, non-zero cross-seed
variance, zero non-finite outputs.  All MC outputs are SIMULATED / diagnostic.
"""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.errors import ValidationError
from strategy.definitions import (
    build_call_spread,
    build_cash_secured_put,
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_partial_overlay,
    build_strike_ladder,
)
from strategy.hero_lifecycle_mc import (
    _extended_cycles_vectorized,
    _extended_path_scalar,
    run_hero_lifecycle_mc,
    unit_premiums_for,
)
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    _generate_chunk_paths,
    run_multi_cycle_monte_carlo,
)

S0: float = 64_509.34
CAPITAL: float = S0 * 30_000


def _cfg(seed: int = 7, n_paths: int = 6_000, **kw: object) -> MultiCycleMCConfig:
    base: dict[str, object] = {
        "n_paths": n_paths, "n_cycles": 12, "cycle_length_years": 29.0 / 365.0,
        "n_steps_per_cycle": 29, "initial_spot": S0, "volatility": 0.34,
        "risk_free_rate": 0.0, "drift": 0.10, "model": "GBM", "seed": seed,
        "d12_interpretation": "cash_settled", "capital_base": CAPITAL,
    }
    base.update(kw)
    return MultiCycleMCConfig(**base)  # type: ignore[arg-type]


CC = build_covered_call()
LB = build_long_btc_plus_short_put()
CO = build_collar()
PO = build_partial_overlay()
ARCHETYPES = (CC, LB, CO, PO)


# ── base reconciliation to the C7 engine ────────────────────────────────────


def test_base_reconciles_c7_engine() -> None:
    cfg = _cfg()
    for strat in ARCHETYPES:
        hero = run_hero_lifecycle_mc(strat, cfg)
        c7 = run_multi_cycle_monte_carlo(strat, cfg)
        assert hero.mean_outcome_usd == pytest.approx(c7.mean_outcome_usd, rel=1e-9)
        assert hero.median_outcome_usd == pytest.approx(c7.median_outcome_usd, rel=1e-9)
        assert hero.std_outcome_usd == pytest.approx(c7.std_outcome_usd, rel=1e-9)
        assert hero.percentile_5_usd == pytest.approx(c7.percentile_5_usd, rel=1e-9)
        assert hero.percentile_1_usd == pytest.approx(c7.percentile_1_usd, rel=1e-9)


# ── scalar-vs-vectorized oracle for the extended per-path metrics ────────────


def test_scalar_oracle_matches_vectorized() -> None:
    cfg = _cfg(n_paths=64)
    fee = cfg.asym_fee_usd
    kinds = ("covered_call", "long_btc_plus_short_put", "collar", "partial_overlay",
             "cash_secured_put", "call_spread", "strike_ladder")
    for kind in kinds:
        up = unit_premiums_for(kind, cfg, cfg.volatility)
        paths = _generate_chunk_paths(cfg, 0, 40)
        ext = _extended_cycles_vectorized(kind, paths, cfg, fee, up)
        for i in range(paths.shape[0]):
            pnl, hold, overlay, dd, itm, touch, eac = _extended_path_scalar(
                kind, paths[i], cfg, fee, up
            )
            assert ext.pnl_post_fee[i] == pytest.approx(pnl, rel=1e-9, abs=1e-3)
            assert ext.holding_pnl[i] == pytest.approx(hold, rel=1e-9, abs=1e-3)
            assert ext.overlay_gross[i] == pytest.approx(overlay, rel=1e-9, abs=1e-3)
            assert ext.max_drawdown[i] == pytest.approx(dd, rel=1e-9, abs=1e-3)
            assert int(ext.itm_count[i]) == itm
            assert int(ext.touch_count[i]) == touch
            if math.isnan(eac):
                assert math.isnan(ext.eac[i])  # CSP / call spread: no BTC -> undefined EAC
            else:
                assert ext.eac[i] == pytest.approx(eac, rel=1e-9, abs=1e-6)


def test_leg_decomposition_identity() -> None:
    hero = run_hero_lifecycle_mc(CC, _cfg())
    # total (post-fee) = holding + overlay_gross - fee, in the means.
    assert hero.mean_total_pnl_post_fee_usd == pytest.approx(
        hero.mean_holding_pnl_usd + hero.mean_overlay_gross_pnl_usd - hero.structuring_fee_usd,
        rel=1e-9, abs=1e-3,
    )
    assert hero.mean_total_pnl_pre_fee_usd == pytest.approx(
        hero.mean_total_pnl_post_fee_usd + hero.structuring_fee_usd, rel=1e-9, abs=1e-3
    )


# ── campaign-gate behaviours ────────────────────────────────────────────────


def test_determinism() -> None:
    a = run_hero_lifecycle_mc(CC, _cfg(seed=11))
    b = run_hero_lifecycle_mc(CC, _cfg(seed=11))
    assert a.mean_outcome_usd == b.mean_outcome_usd
    assert a.var_95_usd == b.var_95_usd
    assert a.mean_max_drawdown_usd == b.mean_max_drawdown_usd


def test_cross_seed_variance_nonzero() -> None:
    means = [run_hero_lifecycle_mc(CC, _cfg(seed=s)).mean_outcome_usd for s in (1, 2, 3, 4)]
    assert float(np.std(means)) > 0.0  # genuine cross-seed dispersion


def test_zero_non_finite() -> None:
    for strat in ARCHETYPES:
        for model in ("GBM", "Merton"):
            for drift in (-0.10, 0.0, 0.10):
                hero = run_hero_lifecycle_mc(strat, _cfg(model=model, drift=drift))
                assert hero.n_non_finite == 0


def test_pnl_and_eac_fields() -> None:
    hero = run_hero_lifecycle_mc(CC, _cfg())
    # Explicit P&L: per-BTC and % of block are consistent with the USD figures.
    assert hero.total_pnl_mean_per_btc == pytest.approx(hero.total_pnl_mean_usd / 30_000, rel=1e-9)
    assert hero.total_pnl_p5_per_btc == pytest.approx(hero.total_pnl_p5_usd / 30_000, rel=1e-9)
    assert hero.total_pnl_p5_usd <= hero.total_pnl_median_usd <= hero.total_pnl_p95_usd
    assert hero.total_pnl_mean_usd == pytest.approx(hero.mean_outcome_usd, rel=1e-12)
    # EAC is relabelled as a diagnostic rolling-programme effective cost (not Slide-1 EAC).
    assert "rolling-programme" in hero.eac_note
    assert "distinct from the Slide-1" in hero.eac_note


def test_collar_tail_floored_vs_lbsp() -> None:
    # Diagnostic (not a ranking): the collar's long-put floor collapses the tail relative to
    # the un-floored short-put structure at the same drift/strike/model/seed.
    cfg = _cfg(seed=101)
    collar = run_hero_lifecycle_mc(CO, cfg)
    lbsp = run_hero_lifecycle_mc(LB, cfg)
    assert collar.expected_shortfall_975_usd < lbsp.expected_shortfall_975_usd
    assert collar.mean_max_drawdown_usd < lbsp.mean_max_drawdown_usd


# ── metric sanity + calibration wiring ──────────────────────────────────────


def test_var95_and_es975_relationship() -> None:
    hero = run_hero_lifecycle_mc(LB, _cfg())
    assert hero.var_95_usd == pytest.approx(-hero.percentile_5_usd, rel=1e-12)
    # ES at the 97.5% tail is at least as deep as the 95% VaR (deeper tail).
    assert hero.expected_shortfall_975_usd >= hero.var_95_usd


def test_itm_within_touch() -> None:
    for strat in (CC, LB):
        hero = run_hero_lifecycle_mc(strat, _cfg())
        # Expiring ITM requires having touched the strike -> touch freq >= ITM freq.
        assert 0.0 <= hero.mean_itm_frequency <= hero.mean_touch_frequency <= 1.0


def test_calibrated_vol_wiring() -> None:
    hero = run_hero_lifecycle_mc(
        CC, _cfg(volatility=0.34),
        volatility_source="calibrated: 28AUG26 ATM IV (snapshot)",
    )
    assert hero.volatility == 0.34  # NOT the ASSUMED 0.45
    assert "calibrated" in hero.volatility_source
    assert hero.risk_free_rate == 0.0
    assert "observed" in hero.risk_free_source
    assert hero.assumptions["provenance"] == "SIMULATED"


def test_unsupported_kind_raises() -> None:
    cfg = _cfg(n_paths=64)
    paths = _generate_chunk_paths(cfg, 0, 8)
    up = [0.01]
    with pytest.raises(ValidationError):  # protective_put is not modelled by the rolling MC
        _extended_cycles_vectorized("protective_put", paths, cfg, cfg.asym_fee_usd, up)


def test_full_grid_runs_and_reconciles() -> None:
    # Every grid structure runs; the C7-supported kinds reconcile in fair-value.
    from strategy.multi_cycle_mc import run_multi_cycle_monte_carlo
    cfg = _cfg()
    cases = [
        (CC, None), (LB, None), (CO, None), (PO, None),
        (build_cash_secured_put(), None), (build_call_spread(), None),
        (build_strike_ladder(), "strike_ladder"),
    ]
    for strat, kind in cases:
        hero = run_hero_lifecycle_mc(strat, cfg, kind=kind)
        assert hero.n_non_finite == 0
        if kind is None and strat.canonical.value in (
            "covered_call", "long_btc_plus_short_put", "collar",
            "partial_overlay", "cash_secured_put",
        ):
            c7 = run_multi_cycle_monte_carlo(strat, cfg)
            assert hero.mean_outcome_usd == pytest.approx(c7.mean_outcome_usd, rel=1e-9)


def test_strike_ladder_distinct_from_covered_call() -> None:
    # kind override is required: the ladder's legs classify as covered_call.
    cfg = _cfg(seed=101)
    ladder = run_hero_lifecycle_mc(build_strike_ladder(), cfg, kind="strike_ladder")
    covered = run_hero_lifecycle_mc(CC, cfg)
    assert ladder.strategy_kind == "strike_ladder"
    assert ladder.mean_overlay_gross_pnl_usd != covered.mean_overlay_gross_pnl_usd


def test_vrp_edge_positive_fair_value_zero() -> None:
    # Fair-value (implied==diffusion): overlay edge ~ 0 (minus fee). VRP (sell implied,
    # realise physical): overlay edge strictly positive. The tail must remain in both.
    implied, realised = 0.34, 0.297
    fv = run_hero_lifecycle_mc(CC, _cfg(volatility=implied))                       # fair value
    vrp = run_hero_lifecycle_mc(CC, _cfg(volatility=realised), pricing_vol=implied)  # VRP
    assert fv.vol_regime == "fair_value" and vrp.vol_regime == "vrp"
    assert vrp.pricing_vol == implied and vrp.diffusion_vol == realised
    assert vrp.mean_overlay_gross_pnl_usd > fv.mean_overlay_gross_pnl_usd
    assert vrp.mean_overlay_gross_pnl_usd > 0.0
    assert abs(fv.mean_overlay_gross_pnl_usd) < abs(vrp.mean_overlay_gross_pnl_usd)
    assert vrp.expected_shortfall_975_usd > 0.0  # crash-risk tail remains under realised vol


def test_bootstrap_se_ci_present_and_bracket() -> None:
    hero = run_hero_lifecycle_mc(LB, _cfg(), bootstrap_samples=200)
    for m in ("mean_pnl", "var_95_usd", "es_975_usd", "prob_loss", "pnl_p5", "pnl_p95"):
        assert m in hero.metric_ci
        ci = hero.metric_ci[m]
        assert ci["se"] > 0.0
        assert ci["ci_lo"] <= ci["ci_hi"]
    # The point estimate lies within its own 95% CI (sanity).
    var_ci = hero.metric_ci["var_95_usd"]
    assert var_ci["ci_lo"] <= hero.var_95_usd <= var_ci["ci_hi"]
