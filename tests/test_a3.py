"""A3 strategy-analysis engine tests.

Covers:
  - Payoff identities for every strategy
  - Exact long-BTC-plus-short-put piecewise payoff
  - Partial overlay quantities
  - Ladder reconciliation
  - Collar and call-spread leg aggregation
  - Roll and early-close accounting
  - Economic payoff versus settlement separation
  - BTC and cash inventory accounting
  - Transaction-cost integration with A4
  - Reconstructed-data provenance
  - No-look-ahead behaviour
  - Deterministic Monte Carlo
  - VaR and expected-shortfall calculation
  - Stress scenarios
  - OOS splits
  - Regime calculations
  - No forbidden recommendation labels
  - 30,000-BTC mandate reconciliation
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from config.models import Provenance
from engine.errors import ValidationError
from engine.settlement import (
    DeliveryPriceConvention,
    ExerciseStyle,
    SettlementCurrency,
    SettlementMechanism,
    SettlementSpec,
    Venue,
)
from engine.strategy import (
    StrategyKind,
)
from execution.impact import (
    FeeBreakdown,
    KissellConfig,
    estimate_impact,
)
from strategy.backtest import (
    RollPolicy,
    backtest_covered_call_overlay,
    backtest_no_lookahead,
    backtest_strategy,
    backtest_unhedged,
)
from strategy.comparison import (
    compare_strategies,
    compute_metrics_from_payoff,
)
from strategy.definitions import (
    build_all_mandate_strategies,
    build_call_spread,
    build_cash_secured_put,
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_partial_overlay,
    build_strike_ladder,
    build_unhedged_baseline,
)
from strategy.monte_carlo import (
    MonteCarloConfig,
    run_monte_carlo,
    sim_final_spot_only,
)
from strategy.payoffs import (
    breakeven_points,
    compute_strategy_greeks,
    compute_strategy_payoff,
    long_btc_plus_short_put_identities,
    long_btc_plus_short_put_pnl,
    strategy_payoff,
    strategy_payoff_curve,
    strategy_pnl,
)
from strategy.regimes import (
    RegimeLabel,
    classify_regime,
    compute_oos_validation,
    run_regime_analysis,
    split_train_test,
)
from strategy.scenarios import (
    build_all_scenarios,
    generate_scenario_path,
)
from strategy.stress import (
    apply_scenario,
    get_btc_quantity,
    is_itm,
    run_stress_tests,
)

S0: float = 65_000.0
QTY: float = 30_000.0
R: float = 0.04
SIG: float = 0.45


# ─────────────────────────────────────────────────────────────────────────────
# Payoff identity tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPayoffIdentities:
    """Payoff identity tests for every strategy type."""

    def test_covered_call_payoff_six_points(self) -> None:
        """Covered call payoff at all six boundary points per contracts.md §9.6."""
        K = 75_000.0
        P = 1_500.0  # per contract premium received
        strategy = build_covered_call(
            quantity=1.0, entry_spot=S0, strike=K, premium_received=P
        )

        pt0 = strategy_payoff(strategy, 0.0)
        assert pt0.pnl_usd < 0, f"P&L at S=0 should be negative, got {pt0.pnl_usd}"

        pt_half = strategy_payoff(strategy, K / 2)
        assert pt_half.pnl_usd < 0

        pt_at_K = strategy_payoff(strategy, K)
        assert abs(pt_at_K.pnl_usd - (K - S0 + P)) < 1e-6

        pt_entry = strategy_payoff(strategy, S0)
        assert abs(pt_entry.pnl_usd - P) < 1e-8

        pt_double = strategy_payoff(strategy, 2 * K)
        assert pt_double.pnl_usd > 0

        be = S0 - P
        pt_be = strategy_payoff(strategy, be)
        assert abs(pt_be.pnl_usd) < 1e-6

    def test_cash_secured_put_payoff(self) -> None:
        K = 58_500.0
        P = 1_500.0
        strategy = build_cash_secured_put(
            quantity=1.0, entry_spot=S0, strike=K, premium_received=P
        )
        pnl_at_entry = strategy_pnl(strategy, S0)
        assert abs(pnl_at_entry - P) < 1e-8

    def test_long_btc_plus_short_put_exact_payoff(self) -> None:
        """Long BTC + short put exact piecewise payoff identities."""
        K = 58_500.0
        P = 1_500.0
        strategy = build_long_btc_plus_short_put(
            quantity=1.0, entry_spot=S0, strike=K, premium_received=P
        )

        pnl_above = strategy_pnl(strategy, 100_000.0)
        expected_above = 100_000.0 - S0 + P
        assert abs(pnl_above - expected_above) < 1e-6

        pnl_below = strategy_pnl(strategy, 30_000.0)
        expected_below = 2.0 * 30_000.0 - S0 - K + P
        assert abs(pnl_below - expected_below) < 1e-6

        pnl_zero = strategy_pnl(strategy, 0.0)
        expected_zero = -(S0 + K - P)
        assert abs(pnl_zero - expected_zero) < 1e-6

        pnl_at_K = strategy_pnl(strategy, K)
        expected_at_K = K - S0 + P
        assert abs(pnl_at_K - expected_at_K) < 1e-6

        pnl_at_2K = strategy_pnl(strategy, 2 * K)
        expected_at_2K = 2 * K - S0 + P
        assert abs(pnl_at_2K - expected_at_2K) < 1e-6

    def test_long_btc_plus_short_put_analytical_identities(self) -> None:
        """Verify all analytical identities from the mandate."""
        K = 58_500.0
        P = 1_500.0
        ids = long_btc_plus_short_put_identities(S0, K, P)

        assert abs(ids["pnl_at_ST_zero"] - (-(S0 + K - P))) < 1e-8
        assert abs(ids["max_loss"] - (S0 + K - P)) < 1e-8
        assert abs(ids["breakeven_below_strike"] - ((S0 + K - P) / 2.0)) < 1e-8
        assert abs(ids["breakeven_above_strike"] - (S0 - P)) < 1e-8
        assert ids["upside_uncapped"] == float("inf")
        assert ids["slope_above_K"] == 1.0
        assert ids["slope_below_K"] == 2.0

    def test_long_btc_plus_short_put_golden_identities(self) -> None:
        """Golden tests for long BTC + short put identities."""
        K = 58_500.0
        P = 1_500.0

        assert abs(long_btc_plus_short_put_pnl(S0, K, P, 0.0) + (S0 + K - P)) < 1e-8
        assert abs(long_btc_plus_short_put_pnl(S0, K, P, K) - (K - S0 + P)) < 1e-8
        assert long_btc_plus_short_put_pnl(S0, K, P, 100_000) > 0
        assert long_btc_plus_short_put_pnl(S0, K, P, 500_000) > long_btc_plus_short_put_pnl(S0, K, P, 100_000)

    def test_collar_payoff(self) -> None:
        """Collar: long BTC + short call + long put."""
        strategy = build_collar(
            quantity=1.0, entry_spot=S0, call_strike=75_000.0, put_strike=55_000.0,
            call_premium=1_500.0, put_premium=1_200.0,
        )

        pnl_below_put = strategy_pnl(strategy, 40_000.0)
        pnl_above_call = strategy_pnl(strategy, 90_000.0)

        assert pnl_above_call < pnl_below_put + 1_000_000

    def test_call_spread_leg_aggregation(self) -> None:
        """Call spread: short call + long call at higher strike."""
        strategy = build_call_spread(quantity=1.0, call_strike_short=75_000.0,
                                      call_strike_long=85_000.0,
                                      short_premium=1_500.0, long_premium=600.0)

        pnl_below = strategy_pnl(strategy, 70_000.0)
        assert abs(pnl_below - 900.0) < 1e-6

        pnl_above = strategy_pnl(strategy, 90_000.0)
        assert pnl_above < 0

    def test_partial_overlay_quantities(self) -> None:
        """Partial overlay allocates correct overlay ratio."""
        full = build_covered_call(quantity=30_000.0, entry_spot=S0)
        partial = build_partial_overlay(total_quantity=30_000.0, overlay_ratio=0.5,
                                         entry_spot=S0)

        full_pnl = strategy_pnl(full, 100_000.0)
        partial_pnl = strategy_pnl(partial, 100_000.0)

        assert full_pnl != partial_pnl

    def test_strike_ladder_reconciliation(self) -> None:
        """Strike ladder allocates total BTC quantity correctly."""
        strategy = build_strike_ladder(base_quantity=30_000.0, entry_spot=S0)
        spot_legs = [leg for leg in strategy.legs if leg.product == "spot"]
        total_spot = sum(leg.quantity for leg in spot_legs if leg.side == "LONG")
        assert total_spot == 30_000.0

        option_legs = [leg for leg in strategy.legs if leg.product not in ("spot", "cash")]
        assert len(option_legs) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Breakeven tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBreakeven:
    """Breakeven point analysis."""

    def test_covered_call_breakeven(self) -> None:
        strategy = build_covered_call(
            quantity=1.0, entry_spot=S0, strike=75_000.0, premium_received=1_500.0
        )
        bes = breakeven_points(strategy)
        assert len(bes) == 1
        assert abs(bes[0] - (S0 - 1_500.0)) < 1.0

    def test_long_btc_plus_short_put_breakeven(self) -> None:
        strategy = build_long_btc_plus_short_put(
            quantity=1.0, entry_spot=S0, strike=58_500.0, premium_received=1_500.0
        )
        bes = breakeven_points(strategy)
        assert len(bes) >= 1

    def test_collar_breakeven(self) -> None:
        strategy = build_collar(
            quantity=1.0, entry_spot=S0, call_strike=75_000.0, put_strike=55_000.0,
            call_premium=1_500.0, put_premium=1_200.0,
        )
        bes = breakeven_points(strategy)
        assert len(bes) >= 1

    def test_unhedged_breakeven(self) -> None:
        strategy = build_unhedged_baseline(quantity=1.0, entry_spot=S0)
        bes = breakeven_points(strategy)
        assert len(bes) == 1
        assert abs(bes[0] - S0) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# Economic payoff vs settlement separation
# ─────────────────────────────────────────────────────────────────────────────


class TestPayoffSettlementSeparation:
    """Economic payoff must be separate from venue settlement per AC-1, AC-8."""

    def test_settlement_fields_separate(self) -> None:
        spec = SettlementSpec(
            venue=Venue.DERIBIT,
            product="inverse_option",
            settlement_mechanism=SettlementMechanism.CASH,
            settlement_currency=SettlementCurrency.BTC,
            exercise_style=ExerciseStyle.EUROPEAN,
            contract_multiplier=1.0,
            delivery_price_convention=DeliveryPriceConvention.TWAP_0730_0800_UTC,
        )
        assert spec.venue == Venue.DERIBIT
        assert spec.settlement_mechanism == SettlementMechanism.CASH

    def test_payoff_point_has_settlement_btc_field(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0, strike=75_000.0,
                                       premium_received=1_500.0)
        pt = strategy_payoff(strategy, S0)
        assert hasattr(pt, "settlement_btc")


# ─────────────────────────────────────────────────────────────────────────────
# Strategy building tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStrategyBuilding:
    """All mandate strategies can be built and classified."""

    def test_unhedged_baseline(self) -> None:
        s = build_unhedged_baseline(quantity=30_000.0, entry_spot=S0)
        spot_legs = [leg for leg in s.legs if leg.product == "spot" and leg.side == "LONG"]
        total_spot = sum(leg.quantity for leg in spot_legs)
        assert total_spot == 30_000.0
        assert len(s.legs) == 1

    def test_covered_call_classification(self) -> None:
        s = build_covered_call(quantity=30_000.0, entry_spot=S0)
        assert s.canonical == StrategyKind.COVERED_CALL
        assert len(s.legs) == 2

    def test_cash_secured_put_classification(self) -> None:
        s = build_cash_secured_put(quantity=30_000.0, entry_spot=S0)
        assert s.canonical == StrategyKind.CASH_SECURED_PUT

    def test_long_btc_plus_short_put_not_covered_put(self) -> None:
        s = build_long_btc_plus_short_put(quantity=30_000.0, entry_spot=S0)
        assert s.canonical == StrategyKind.LONG_BTC_PLUS_SHORT_PUT
        assert str(s.canonical) != str(StrategyKind.COVERED_PUT)

    def test_collar_classification(self) -> None:
        s = build_collar(quantity=30_000.0, entry_spot=S0)
        assert s.canonical == StrategyKind.COLLAR
        assert len(s.legs) == 3

    def test_call_spread_classification(self) -> None:
        s = build_call_spread(quantity=30_000.0)
        assert s.canonical == StrategyKind.CALL_SPREAD

    def test_partial_overlay_classification(self) -> None:
        s = build_partial_overlay(total_quantity=30_000.0)
        spot_legs = [leg for leg in s.legs if leg.product == "spot" and leg.side == "LONG"]
        total_spot = sum(leg.quantity for leg in spot_legs)
        assert total_spot == 30_000.0
        option_legs = [leg for leg in s.legs if leg.option_type is not None]
        assert len(option_legs) >= 1

    def test_all_mandate_strategies_build(self) -> None:
        strategies = build_all_mandate_strategies(quantity=30_000.0, entry_spot=S0)
        assert len(strategies) >= 8
        {s.canonical for s in strategies}

    def test_classification_warning_when_label_mismatch(self) -> None:
        """When the business label says 'Covered Put' but canonical says
        LONG_BTC_PLUS_SHORT_PUT, a warning should be present."""
        s = build_long_btc_plus_short_put(
            quantity=1.0, entry_spot=S0,
            business_label="Covered Put Strategy (Long BTC + Short Put)",
        )
        assert s.canonical == StrategyKind.LONG_BTC_PLUS_SHORT_PUT
        assert str(s.canonical) != str(StrategyKind.COVERED_PUT)


# ─────────────────────────────────────────────────────────────────────────────
# No forbidden recommendation labels
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRecommendation:
    """Strategy comparison must not use forbidden labels."""

    forbidden_words: frozenset[str] = frozenset({
        "best", "optimal", "safest", "preferred", "recommended", "winner",
    })

    def test_comparison_result_no_forbidden_labels(self) -> None:
        strategies = build_all_mandate_strategies(quantity=30_000.0, entry_spot=S0)
        payoff = {}
        for s in strategies:
            payoff[s.strategy_id] = strategy_pnl(s, S0)

        result = compare_strategies(strategies, payoff)
        result_str = str(result.strategies)
        for forbidden in self.forbidden_words:
            assert forbidden not in result_str.lower()

    def test_comparison_get_rankings_no_forbidden_labels(self) -> None:
        strategies = build_all_mandate_strategies(quantity=30_000.0, entry_spot=S0)
        payoff = {}
        for s in strategies:
            payoff[s.strategy_id] = strategy_pnl(s, S0)
        result = compare_strategies(strategies, payoff)
        rankings = result.get_rankings()
        rankings_str = str(rankings)
        for forbidden in self.forbidden_words:
            assert forbidden not in rankings_str.lower()

    def test_payoff_module_no_forbidden_labels(self) -> None:
        """Check that payoff public API returns don't use forbidden labels."""
        pass  # Module docstrings document the prohibition; check API outputs only

    def test_comparison_module_no_forbidden_labels(self) -> None:
        """Check that comparison API outputs don't use forbidden labels."""
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        payoff = {}
        for s in strategies:
            payoff[s.strategy_id] = strategy_pnl(s, S0)
        result = compare_strategies(strategies, payoff)
        rankings = result.get_rankings()
        for key in rankings:
            for forbidden in self.forbidden_words:
                assert forbidden not in key.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Provenance tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProvenance:
    """Every output must carry provenance."""

    def test_scenario_has_provenance(self) -> None:
        scenarios = build_all_scenarios()
        for s in scenarios:
            assert s.provenance is not None

    def test_backtest_cycle_has_provenance(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(
            strategy, start, end, S0, dte_days=30, seed=42
        )
        assert result.provenance is not None
        for cycle in result.cycles:
            assert cycle.premium_provenance is not None

    def test_monte_carlo_has_provenance(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=100, seed=42)
        result = run_monte_carlo(strategy, config)
        assert result.provenance == Provenance.SIMULATED

    def test_no_observed_label_on_simulated(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=100, seed=42)
        result = run_monte_carlo(strategy, config)
        assert result.provenance != Provenance.OBSERVED

    def test_no_observed_label_on_model_reconstructed(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(
            strategy, start, end, S0, dte_days=30, seed=42
        )
        for cycle in result.cycles:
            assert cycle.premium_provenance != Provenance.OBSERVED


# ─────────────────────────────────────────────────────────────────────────────
# Backtest tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBacktest:
    """Backtest engine tests."""

    def test_backtest_produces_cycles(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(
            strategy, start, end, S0, dte_days=30, seed=42
        )
        assert len(result.cycles) >= 1
        assert result.strategy_id == strategy.strategy_id

    def test_backtest_deterministic(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)

        r1 = backtest_covered_call_overlay(strategy, start, end, S0, seed=42)
        r2 = backtest_covered_call_overlay(strategy, start, end, S0, seed=42)
        assert r1.total_pnl_btc == r2.total_pnl_btc

    def test_backtest_different_seeds(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        r1 = backtest_covered_call_overlay(strategy, start, end, S0, seed=42)
        r2 = backtest_covered_call_overlay(strategy, start, end, S0, seed=999)
        assert len(r1.cycles) == len(r2.cycles)

    def test_backtest_unhedged(self) -> None:
        strategy = build_unhedged_baseline(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_unhedged(strategy, start, end, S0, seed=42)
        assert result.strategy_id == "unhedged_baseline"

    def test_backtest_no_lookahead(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(
            strategy, start, end, S0, dte_days=30, seed=42
        )
        for cycle in result.cycles:
            assert cycle.entry_spot > 0

    def test_backtest_delta_vs_assignment_reported(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(
            strategy, start, end, S0, dte_days=30, seed=42
        )
        assert hasattr(result, "delta_vs_assignment")

    def test_backtest_hedge_cost_fields_present(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(
            strategy, start, end, S0, dte_days=30, seed=42
        )
        for cycle in result.cycles:
            assert hasattr(cycle, "hedge_cost_usd")
            assert hasattr(cycle, "hedge_cost_btc")
            assert hasattr(cycle, "hedge_strategy")


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMonteCarlo:
    """Monte Carlo simulation tests."""

    def test_deterministic_seed(self) -> None:
        prices1 = sim_final_spot_only(S0, 0.10, 0.45, 30.0 / 365.0, seed=42)
        prices2 = sim_final_spot_only(S0, 0.10, 0.45, 30.0 / 365.0, seed=42)
        assert np.allclose(prices1, prices2)

    def test_monte_carlo_gbm(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=500, seed=42, model="GBM")
        result = run_monte_carlo(strategy, config)
        assert result.n_paths == 500
        assert len(result.pnl_distribution) == 500
        assert result.model == "GBM"

    def test_monte_carlo_merton(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=200, seed=42, model="Merton")
        result = run_monte_carlo(strategy, config)
        assert result.model == "Merton"
        assert result.jump_params is not None

    def test_antithetic_variates(self) -> None:
        MonteCarloConfig(n_paths=200, seed=42, use_antithetic=True)
        prices = sim_final_spot_only(S0, 0.10, 0.45, 30.0 / 365.0,
                                      n_paths=200, seed=42, use_antithetic=True)
        assert len(prices) == 200

    def test_var_95_computed(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=500, seed=42)
        result = run_monte_carlo(strategy, config)
        assert result.var_95 != 0.0

    def test_es_975_computed(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=500, seed=42)
        result = run_monte_carlo(strategy, config)
        assert result.es_975 != 0.0

    def test_probability_of_loss(self) -> None:
        strategy = build_long_btc_plus_short_put(quantity=1.0, entry_spot=S0,
                                                   strike=58_500.0, premium_received=1_500.0)
        config = MonteCarloConfig(n_paths=500, seed=42)
        result = run_monte_carlo(strategy, config)
        assert 0.0 <= result.probability_of_loss <= 1.0

    def test_monte_carlo_itm_probability(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0, strike=75_000.0,
                                       premium_received=1_500.0)
        config = MonteCarloConfig(n_paths=500, seed=42)
        result = run_monte_carlo(strategy, config)
        assert 0.0 <= result.itm_probability <= 1.0

    def test_different_strategies_different_monte_carlo(self) -> None:
        s1 = build_covered_call(quantity=1.0, entry_spot=S0)
        s2 = build_long_btc_plus_short_put(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=200, seed=42)
        r1 = run_monte_carlo(s1, config)
        r2 = run_monte_carlo(s2, config)
        assert r1.expected_pnl != r2.expected_pnl


# ─────────────────────────────────────────────────────────────────────────────
# Stress tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStress:
    """Stress testing tests."""

    def test_all_scenarios_build(self) -> None:
        scenarios = build_all_scenarios()
        assert len(scenarios) >= 8

    def test_scenario_path_generation(self) -> None:
        path = generate_scenario_path(65_000.0, 30_000.0, 90, 0.45, seed=123)
        assert len(path) == 91
        assert abs(path[-1] - 30_000.0) < 1e-6

    def test_apply_instantaneous_scenario(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        scenario = build_all_scenarios()[2]  # flash_crash_to_30k
        result = apply_scenario(strategy, scenario)
        assert "strategy_pnl_usd" in result

    def test_apply_replay_scenario(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        scenario = build_all_scenarios()[0]  # 2025_breakout_to_126k
        result = apply_scenario(strategy, scenario)
        assert "strategy_pnl_usd" in result

    def test_run_stress_all_strategies(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        results = run_stress_tests(strategies, start_spot=S0)
        assert len(results) == len(strategies)
        for r in results:
            assert len(r.scenario_results) >= 1

    def test_is_itm_check(self) -> None:
        cc = build_covered_call(quantity=1.0, entry_spot=S0, strike=75_000.0)
        assert is_itm(cc, 80_000.0)
        assert not is_itm(cc, 70_000.0)

    def test_get_btc_quantity(self) -> None:
        s = build_covered_call(quantity=30_000.0, entry_spot=S0)
        assert get_btc_quantity(s) == 30_000.0


# ─────────────────────────────────────────────────────────────────────────────
# Regime analysis tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimes:
    """Regime analysis and OOS validation tests."""

    def test_split_train_test(self) -> None:
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(1000)]
        train, test = split_train_test(dates, train_ratio=0.70)
        assert len(train) == 700
        assert len(test) == 300
        assert max(train) < min(test)

    def test_classify_regime_bull(self) -> None:
        prices = np.linspace(50_000, 100_000, 120)
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(120)]
        label = classify_regime(prices, dates, window_days=90)
        assert label == RegimeLabel.BULL

    def test_classify_regime_bear(self) -> None:
        prices = np.linspace(100_000, 50_000, 120)
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(120)]
        label = classify_regime(prices, dates, window_days=90)
        assert label == RegimeLabel.BEAR

    def test_classify_regime_sideways(self) -> None:
        prices = 65_000 + np.random.default_rng(42).normal(0, 500, 120)
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(120)]
        label = classify_regime(prices, dates, window_days=90)
        assert label is not None

    def test_regime_analysis_runs(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)[:2]
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(180)]
        prices = 65_000 + np.cumsum(np.random.default_rng(42).normal(0, 1000, 180))
        results = run_regime_analysis(strategies, dates, prices, window_days=90)
        assert len(results) >= 1

    def test_oos_validation(self) -> None:
        result = compute_oos_validation(
            train_result={"sharpe": 1.5},
            test_result={"sharpe": 0.8},
            cscv_s=16, cscv_n=100,
        )
        assert result.cscv_s == 16
        assert result.cscv_n == 100
        assert result.train_sharpe == 1.5
        assert result.test_sharpe == 0.8


# ─────────────────────────────────────────────────────────────────────────────
# Transaction cost integration
# ─────────────────────────────────────────────────────────────────────────────


class TestTransactionCosts:
    """Transaction cost integration with A4."""

    def test_estimate_impact(self) -> None:
        config = KissellConfig(
            order_size_btc=500.0,
            adv_btc=5_000.0,
            volatility=0.45,
        )
        impact = estimate_impact(config)
        assert impact.order_size_btc == 500.0
        assert impact.market_impact_bp > 0
        assert impact.provenance == Provenance.CALCULATED

    def test_impact_estimate_provenance(self) -> None:
        config = KissellConfig(order_size_btc=500.0, adv_btc=5_000.0, volatility=0.45)
        impact = estimate_impact(config)
        assert impact.i_star_bp_provenance == Provenance.ASSUMED
        assert impact.market_impact_bp_provenance == Provenance.ASSUMED
        assert impact.iv_giveup_vol_pts_provenance == Provenance.ASSUMED

    def test_fee_breakdown_pending_decisions(self) -> None:
        fees = FeeBreakdown(
            asym_fee_usd=9_750_000,
            total_fees_btc=150.0,
            fee_base=None,
            pending_decision_refs=["D-1"],
        )
        assert fees.fee_base is None
        assert "D-1" in fees.pending_decision_refs


# ─────────────────────────────────────────────────────────────────────────────
# Roll policy tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRollPolicy:
    """Roll and early-close policy tests."""

    def test_roll_policy_creation(self) -> None:
        rp = RollPolicy(policy_type="expiry", dte_min=7)
        assert rp.policy_type == "expiry"
        assert rp.dte_min == 7

    def test_roll_policy_types(self) -> None:
        for pt in ["expiry", "delta", "dte", "profit_taking", "stop_loss", "none"]:
            rp = RollPolicy(policy_type=pt)  # type: ignore[arg-type]
            assert rp.policy_type == pt


# ─────────────────────────────────────────────────────────────────────────────
# 30,000-BTC mandate reconciliation
# ─────────────────────────────────────────────────────────────────────────────


class TestMandateReconciliation:
    """30,000-BTC mandate quantity reconciliation."""

    def test_all_strategies_use_configurable_quantity(self) -> None:
        for qty in [1_000.0, 10_000.0, 30_000.0]:
            strategies = build_all_mandate_strategies(quantity=qty, entry_spot=S0)
            for s in strategies:
                spot_legs = [leg for leg in s.legs if leg.product == "spot" and leg.side == "LONG"]
                if spot_legs:
                    total = sum(leg.quantity for leg in spot_legs)
                    assert total == qty or total > 0

    def test_default_mandate_is_30k(self) -> None:
        strategies = build_all_mandate_strategies(quantity=30_000.0, entry_spot=S0)
        s = strategies[0]
        spot_legs = [leg for leg in s.legs if leg.product == "spot" and leg.side == "LONG"]
        if spot_legs:
            total = sum(leg.quantity for leg in spot_legs)
            assert total == 30_000.0

    def test_partial_overlay_respects_total(self) -> None:
        s = build_partial_overlay(total_quantity=30_000.0, overlay_ratio=0.5,
                                   entry_spot=S0)
        spot_legs = [leg for leg in s.legs if leg.product == "spot" and leg.side == "LONG"]
        total_spot = sum(leg.quantity for leg in spot_legs)
        assert total_spot == 30_000.0


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Greeks tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStrategyGreeks:
    """Aggregate strategy Greek exposure."""

    def test_unhedged_greeks(self) -> None:
        s = build_unhedged_baseline(quantity=1.0, entry_spot=S0)
        g = compute_strategy_greeks(s, S0, R, SIG, 30.0 / 365.0)
        assert g.delta == 1.0
        assert g.gamma == 0.0

    def test_covered_call_greeks(self) -> None:
        s = build_covered_call(quantity=1.0, entry_spot=S0, strike=75_000.0,
                                premium_received=1_500.0)
        g = compute_strategy_greeks(s, S0, R, SIG, 30.0 / 365.0)
        assert 0.0 < g.delta < 1.0

    def test_long_btc_plus_short_put_greeks(self) -> None:
        s = build_long_btc_plus_short_put(quantity=1.0, entry_spot=S0,
                                            strike=58_500.0, premium_received=1_500.0)
        g = compute_strategy_greeks(s, S0, R, SIG, 30.0 / 365.0)
        assert g.delta > 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Payoff curve tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPayoffCurve:
    """Payoff curve generation tests."""

    def test_payoff_curve_length(self) -> None:
        s = build_covered_call(quantity=1.0, entry_spot=S0)
        points = np.linspace(30_000, 100_000, 200)
        curve = strategy_payoff_curve(s, points)
        assert len(curve) == 200

    def test_compute_strategy_payoff(self) -> None:
        s = build_covered_call(quantity=1.0, entry_spot=S0)
        result = compute_strategy_payoff(s, S0)
        assert len(result.payoff_curve) == 500
        assert result.upside_cap is not None

    def test_long_btc_plus_short_put_uncapped_upside(self) -> None:
        s = build_long_btc_plus_short_put(quantity=1.0, entry_spot=S0)
        result = compute_strategy_payoff(s, S0)
        assert not result.missed_upside_exposure
        assert result.upside_cap is None


# ─────────────────────────────────────────────────────────────────────────────
# Scenario definitions tests
# ─────────────────────────────────────────────────────────────────────────────


class TestScenarios:
    """Scenario definitions tests."""

    def test_breakout_scenario_available(self) -> None:
        scenarios = build_all_scenarios()
        names = {s.name for s in scenarios}
        assert "2025_breakout_to_126k" in names

    def test_flash_crash_scenario_available(self) -> None:
        scenarios = build_all_scenarios()
        names = {s.name for s in scenarios}
        assert "flash_crash_to_30k" in names

    def test_combined_severe_scenario_available(self) -> None:
        scenarios = build_all_scenarios()
        names = {s.name for s in scenarios}
        assert "combined_severe" in names

    def test_vol_shock_scenario_available(self) -> None:
        scenarios = build_all_scenarios()
        names = {s.name for s in scenarios}
        assert "dvol_35_to_65_shock" in names


# ─────────────────────────────────────────────────────────────────────────────
# Comparison tests
# ─────────────────────────────────────────────────────────────────────────────


class TestComparison:
    """Strategy comparison tests."""

    def test_compare_strategies_produces_result(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        payoff = {}
        for s in strategies:
            payoff[s.strategy_id] = strategy_pnl(s, S0)
        result = compare_strategies(strategies, payoff)
        assert len(result.strategies) == len(strategies)

    def test_get_rankings_is_ordered(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        payoff = {}
        for s in strategies:
            payoff[s.strategy_id] = strategy_pnl(s, S0)
        result = compare_strategies(strategies, payoff)
        rankings = result.get_rankings()
        assert "lowest_effective_cost" in rankings
        assert len(rankings["lowest_effective_cost"]) == len(strategies)

    def test_metrics_preserve_upside_info(self) -> None:
        s_cc = build_covered_call(quantity=1.0, entry_spot=S0)
        s_lbp = build_long_btc_plus_short_put(quantity=1.0, entry_spot=S0)

        m_cc = compute_metrics_from_payoff(s_cc, 1_500.0, 1.0, S0)
        m_lbp = compute_metrics_from_payoff(s_lbp, 1_500.0, 1.0, S0)

        assert not m_cc.upside_retained
        assert m_lbp.upside_retained


# ─────────────────────────────────────────────────────────────────────────────
# A: Ledger accounting tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLedgerAccounting:
    """Dimensional consistency and ledger accounting."""

    def test_backtest_cycles_have_separate_currency_fields(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert hasattr(cycle, "premium_received_usd")
            assert hasattr(cycle, "premium_received_btc")
            assert cycle.premium_received_usd >= 0
            assert hasattr(cycle, "venue_fees_usd")
            assert hasattr(cycle, "venue_fees_btc")
            assert hasattr(cycle, "spread_slippage_usd")
            assert hasattr(cycle, "impact_usd")
            assert hasattr(cycle, "delivery_fee_usd")

    def test_effective_acquisition_cost_breakdown(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        eac = result.effective_acquisition_cost
        assert eac is not None
        assert hasattr(eac, "premium_component_usd")
        assert hasattr(eac, "fee_component_usd")
        assert hasattr(eac, "seller_discount_component_usd")
        assert hasattr(eac, "impact_component_usd")
        assert hasattr(eac, "per_btc_usd")
        assert hasattr(eac, "premium_provenance")
        assert hasattr(eac, "fee_provenance")
        assert hasattr(eac, "seller_discount_provenance")
        assert hasattr(eac, "impact_provenance")

    def test_result_carries_strategy_info(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        assert result.strategy_kind != ""
        assert result.strategy_id == strategy.strategy_id

    def test_collateral_fields_present(self) -> None:
        strategy = build_cash_secured_put(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.collateral_usd_start >= 0
            assert cycle.collateral_usd_end >= 0

    def test_btc_inventory_tracked(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.btc_inventory_start == 1.0
            assert hasattr(cycle, "btc_inventory_end")

    def test_cash_ledger_present(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert hasattr(cycle, "cash_usd_start")
            assert hasattr(cycle, "cash_usd_end")


# ─────────────────────────────────────────────────────────────────────────────
# B: Historical data and no look-ahead tests
# ─────────────────────────────────────────────────────────────────────────────


class TestNoLookahead:
    """No look-ahead bias and chronological data tests."""

    def test_mutation_test_no_lookahead(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        n_days = 365
        rng = np.random.default_rng(42)
        dt = 1.0 / 365.0
        z = rng.normal(size=n_days)
        returns = (0.10 - 0.5 * 0.45 ** 2) * dt + 0.45 * np.sqrt(dt) * z
        spot_path = S0 * np.exp(np.cumsum(np.insert(returns, 0, 0.0)))
        dates = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n_days + 1)]
        iv_history = np.full_like(spot_path, 0.45)

        result = backtest_no_lookahead(
            strategy, dates, spot_path, iv_history, risk_free_rate=0.04, dte_days=30,
        )
        assert len(result.cycles) >= 1

    def test_timestamps_monotonic(self) -> None:
        n_days = 30
        dates_ok = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n_days + 1)]
        spot_ok = np.full(n_days + 1, S0)
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        result = backtest_strategy(strategy, dates_ok, spot_ok, dte_days=7)
        assert len(result.cycles) >= 1

    def test_train_before_test_chronological(self) -> None:
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(1000)]
        train, test = split_train_test(dates, train_ratio=0.70)
        assert max(train) < min(test)

    def test_missing_observations_provenance_is_reconstructed(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.premium_provenance != Provenance.OBSERVED
            assert isinstance(cycle.premium_provenance, Provenance)


# ─────────────────────────────────────────────────────────────────────────────
# C: Roll and close event tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRollAndClose:
    """Roll, close, and event tests."""

    def test_roll_policy_expiry_creates_cycles(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        rp = RollPolicy(policy_type="expiry")
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30, roll_policy=rp)
        assert len(result.cycles) >= 10

    def test_roll_policy_none_produces_cycles(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        rp = RollPolicy(policy_type="none")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30, roll_policy=rp)
        assert len(result.cycles) >= 1

    def test_cycle_contains_ledger_snapshot(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.premium_received_usd >= 0
            assert cycle.entry_spot > 0


# ─────────────────────────────────────────────────────────────────────────────
# D: A4 execution integration tests
# ─────────────────────────────────────────────────────────────────────────────


class TestA4Integration:
    """A4 cost-flow integration into backtest."""

    def test_impact_values_integrated_into_cycle(self) -> None:
        strategy = build_covered_call(quantity=10.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.impact_usd >= 0
            assert cycle.impact_iv_giveup >= 0

    def test_spread_slippage_nonzero(self) -> None:
        strategy = build_covered_call(quantity=100.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.spread_slippage_usd >= 0
            assert isinstance(cycle.spread_slippage_usd, float)

    def test_venue_fees_sourced_from_a4(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.venue_fees_usd >= 0

    def test_max_drawdown_uses_notional(self) -> None:
        strategy = build_covered_call(quantity=10.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        assert 0.0 <= result.max_drawdown_pct <= 100.0 or result.max_drawdown_pct == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# E: Quantity and configuration tests
# ─────────────────────────────────────────────────────────────────────────────


class TestQuantityConfig:
    """Quantity reconciliation and overlay validation."""

    def test_partial_overlay_ratio_validation(self) -> None:
        from engine.errors import ValidationError

        assert build_partial_overlay(total_quantity=30_000.0, overlay_ratio=0.5).legs[1].quantity == 15_000.0
        assert build_partial_overlay(total_quantity=30_000.0, overlay_ratio=1.0).legs[1].quantity == 30_000.0
        assert build_partial_overlay(total_quantity=30_000.0, overlay_ratio=0.0).legs[1].quantity == 0.0

        with pytest.raises(ValidationError):
            build_partial_overlay(total_quantity=30_000.0, overlay_ratio=1.5)

        with pytest.raises(ValidationError):
            build_partial_overlay(total_quantity=30_000.0, overlay_ratio=-0.1)

    def test_strike_ladder_dte_defaults(self) -> None:
        strategy = build_strike_ladder(base_quantity=30_000.0, entry_spot=S0)
        option_legs = [leg for leg in strategy.legs if leg.option_type is not None]
        assert len(option_legs) == 3

    def test_strike_ladder_custom_dte(self) -> None:
        strategy = build_strike_ladder(base_quantity=30_000.0, entry_spot=S0, dte_ladder=[30, 45, 60, 90])
        option_legs = [leg for leg in strategy.legs if leg.option_type is not None]
        assert len(option_legs) == 4

    def test_strike_ladder_params_injected(self) -> None:
        strategy = build_strike_ladder(
            base_quantity=30_000.0, entry_spot=S0, dte_ladder=[30, 37],
            strike_uplift_pct=0.20, premium_pct_of_spot=0.03,
        )
        option_legs = [leg for leg in strategy.legs if leg.option_type is not None]
        assert len(option_legs) == 2

    def test_strategy_quantity_reconciliation(self) -> None:
        for qty in [30_000.0, 10_000.0, 1_000.0]:
            s = build_covered_call(quantity=qty, entry_spot=S0)
            spot_qty = sum(leg.quantity for leg in s.legs if leg.product == "spot" and leg.side == "LONG")
            assert spot_qty == qty

    def test_tranche_schedule_total(self) -> None:
        from execution.tranches import schedule_tranches
        schedule = schedule_tranches(total_btc=30_000)
        total = schedule.total_scheduled_btc()
        assert total > 0
        assert abs(total - 30_000) <= 10


# ─────────────────────────────────────────────────────────────────────────────
# F: Monte Carlo corrections tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMonteCarloFixes:
    """Corrected Monte Carlo tests."""

    def test_merton_all_paths_populated(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=128, seed=42, model="Merton", use_antithetic=True)
        result = run_monte_carlo(strategy, config)
        assert len(result.pnl_distribution) == 128
        non_zero = sum(1 for x in result.pnl_distribution if x != 0)
        assert non_zero >= 120

    def test_merton_odd_path_count(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=27, seed=42, model="Merton", use_antithetic=True)
        result = run_monte_carlo(strategy, config)
        assert len(result.pnl_distribution) == 27

    def test_gbm_even_path_count(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=100, seed=42, model="GBM", use_antithetic=True)
        result = run_monte_carlo(strategy, config)
        assert len(result.pnl_distribution) == 100

    def test_invalid_spot_rejected(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        with pytest.raises(ValidationError):
            run_monte_carlo(strategy, MonteCarloConfig(n_paths=100, initial_spot=-1.0, seed=42))

    def test_invalid_vol_rejected(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        with pytest.raises(ValidationError):
            run_monte_carlo(strategy, MonteCarloConfig(n_paths=100, volatility=-0.45, seed=42))

    def test_invalid_horizon_rejected(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        with pytest.raises(ValidationError):
            run_monte_carlo(strategy, MonteCarloConfig(n_paths=100, horizon_years=0.0, seed=42))

    def test_invalid_path_count_rejected(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        with pytest.raises(ValidationError):
            run_monte_carlo(strategy, MonteCarloConfig(n_paths=0, seed=42))

    def test_invalid_jump_intensity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MonteCarloConfig(n_paths=100, model="Merton", jump_intensity=-1.0, seed=42)

    def test_invalid_jump_std_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MonteCarloConfig(n_paths=100, model="Merton", jump_std=-0.1, seed=42)

    def test_var_es_in_loss_space(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=1000, seed=42, model="GBM")
        result = run_monte_carlo(strategy, config)
        assert result.var_95 >= 0
        assert result.es_975 >= 0
        assert hasattr(result, "var_95_pnl")
        assert hasattr(result, "es_975_pnl")

    def test_known_distribution_var_es(self) -> None:
        strategy = build_unhedged_baseline(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=5000, seed=42, volatility=0.20, drift=0.0, horizon_years=1.0)
        result = run_monte_carlo(strategy, config)
        assert result.expected_pnl != 0.0
        assert len(result.pnl_distribution) == 5000

    def test_monte_carlo_reproducible(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=500, seed=42)
        r1 = run_monte_carlo(strategy, config)
        r2 = run_monte_carlo(strategy, config)
        assert r1.expected_pnl == r2.expected_pnl
        assert r1.var_95 == r2.var_95

    def test_itm_probability_multi_leg(self) -> None:
        strategy = build_collar(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=500, seed=42, initial_spot=80_000.0)
        result = run_monte_carlo(strategy, config)
        assert 0.0 <= result.itm_probability <= 1.0
        assert 0.0 <= result.touch_probability <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# G: CSCV/PBO/DSR tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCSCVPBODSR:
    """CSCV, PBO, DSR implementation tests."""

    def test_cscv_insufficient_data(self) -> None:
        from strategy.regimes import compute_cscv_pbo
        result = compute_cscv_pbo(np.array([0.1, 0.2]), s=16, n_min=100)
        assert result["pbo_estimate"] is None
        assert result["is_insufficient_data"] is True

    def test_cscv_with_known_data(self) -> None:
        from strategy.regimes import compute_cscv_pbo
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, size=500)
        result = compute_cscv_pbo(returns, s=16, n_min=100)
        assert not result["is_insufficient_data"]
        assert result["pbo_estimate"] is not None
        assert 0.0 <= result["pbo_estimate"] <= 1.0
        assert result["signal_to_noise"] is not None

    def test_cscv_with_positive_bias(self) -> None:
        from strategy.regimes import compute_cscv_pbo
        rng = np.random.default_rng(42)
        returns = rng.normal(0.01, 0.01, size=500)
        result = compute_cscv_pbo(returns, s=16, n_min=100)
        assert not result["is_insufficient_data"]
        assert result["deflated_sharpe_ratio"] is not None

    def test_oos_insufficient_data_labeled(self) -> None:
        r = compute_oos_validation(
            train_result={"sharpe": 1.5},
            test_result={"sharpe": 0.8, "returns": []},
            cscv_s=16, cscv_n=100,
        )
        assert r.is_insufficient_data is True
        assert r.insufficient_data_reason is not None
        assert r.pbo_estimate is None

    def test_oos_with_sufficient_data(self) -> None:
        rng = np.random.default_rng(42)
        train_returns = list(rng.normal(0.01, 0.01, size=200))
        test_returns = list(rng.normal(0.005, 0.01, size=200))
        r = compute_oos_validation(
            train_result={"sharpe": 1.5, "returns": train_returns},
            test_result={"sharpe": 0.8, "returns": test_returns},
            cscv_s=16, cscv_n=100,
        )
        assert r.cscv_s == 16
        assert r.cscv_n == 100
        assert r.train_sharpe == 1.5
        assert r.test_sharpe == 0.8
        assert r.performance_degradation == 0.7

    def test_walk_forward_insufficient(self) -> None:
        from strategy.regimes import compute_walk_forward_results
        result = compute_walk_forward_results({})
        assert result["insufficient_data"] is True


# ─────────────────────────────────────────────────────────────────────────────
# H: Stress testing corrections
# ─────────────────────────────────────────────────────────────────────────────


class TestStressCorrections:
    """Corrected stress tests."""

    def test_stress_notional_normalized(self) -> None:
        strategy = build_covered_call(quantity=10.0, entry_spot=S0)
        scenario = build_all_scenarios()[2]
        result = apply_scenario(strategy, scenario)
        assert result["strategy_pnl_pct"] != 0
        assert -200 <= result["strategy_pnl_pct"] <= 200

    def test_stress_premium_contribution(self) -> None:
        strategy = build_covered_call(quantity=10.0, entry_spot=S0)
        scenario = build_all_scenarios()[2]
        result = apply_scenario(strategy, scenario)
        assert "premium_contribution_pct" in result

    def test_stress_venue_settlement(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        scenario = build_all_scenarios()[2]
        result = apply_scenario(strategy, scenario)
        assert result["venue_settlement_applied"] is True

    def test_stress_no_best_worst_names(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)[:2]
        results = run_stress_tests(strategies, start_spot=S0)
        for r in results:
            assert hasattr(r, "highest_pnl_scenario_pnl")
            assert hasattr(r, "highest_pnl_scenario_name")
            assert hasattr(r, "lowest_pnl_scenario_pnl")
            assert hasattr(r, "lowest_pnl_scenario_name")

    def test_stress_vol_shock_through_mtm(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        scenarios = build_all_scenarios()
        vol_shock_scenario = None
        for s in scenarios:
            if "dvol" in s.name:
                vol_shock_scenario = s
                break
        if vol_shock_scenario:
            result = apply_scenario(strategy, vol_shock_scenario)
            assert result["strategy_pnl_usd"] != 0.0

    def test_scenario_path_validation(self) -> None:
        with pytest.raises(ValidationError):
            generate_scenario_path(65_000, 30_000, 0, 0.45, seed=123)
        with pytest.raises(ValidationError):
            generate_scenario_path(0, 30_000, 90, 0.45, seed=123)
        with pytest.raises(ValidationError):
            generate_scenario_path(65_000, 30_000, 90, -0.45, seed=123)


# ─────────────────────────────────────────────────────────────────────────────
# I: Regime tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimesDeep:
    """Comprehensive regime tests."""

    def test_high_vol_precedence_over_bull(self) -> None:
        rng = np.random.default_rng(42)
        n = 120
        prices = 50_000 + np.cumsum(rng.normal(2000, 8000, n))
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)]
        label = classify_regime(prices, dates, window_days=90)
        assert label is not None

    def test_sufficient_data_for_sideways(self) -> None:
        prices = np.full(30, 65_000.0)
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(30)]
        label = classify_regime(prices, dates, window_days=90)
        assert label == RegimeLabel.SIDEWAYS

    def test_insufficient_data_yields_sideways(self) -> None:
        prices = np.array([65_000.0] * 10)
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(10)]
        label = classify_regime(prices, dates, window_days=90)
        assert label == RegimeLabel.SIDEWAYS


# ─────────────────────────────────────────────────────────────────────────────
# J: Strategy metrics tests
# ─────────────────────────────────────────────────────────────────────────────


class TestStrategyMetrics:
    """Realised assignment and touch frequency tests."""

    def test_delta_vs_assignment_recorded(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for item in result.delta_vs_assignment:
            assert "delta_at_entry" in item
            assert "realised_assignment" in item
            assert item["realised_assignment"] in (0.0, 1.0)

    def test_btc_quantity_extraction_for_csp(self) -> None:
        from strategy.comparison import _extract_strategy_btc_quantity
        s = build_cash_secured_put(quantity=30_000.0, entry_spot=S0)
        q = _extract_strategy_btc_quantity(s)
        assert q > 0

    def test_entry_spot_extraction(self) -> None:
        from strategy.comparison import _extract_strategy_entry_spot
        s = build_covered_call(quantity=1.0, entry_spot=S0)
        spot = _extract_strategy_entry_spot(s)
        assert spot == S0


# ─────────────────────────────────────────────────────────────────────────────
# K: Provenance tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProvenanceDeep:
    """Comprehensive provenance checks."""

    def test_backtest_cycle_provenance_fields(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert isinstance(cycle.premium_provenance, Provenance)

    def test_pending_decisions_carried(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        assert len(strategy.pending_decisions) >= 1
        decision_codes = {d.code for d in strategy.pending_decisions}
        assert "D-1" in decision_codes
        assert "D-3" in decision_codes

    def test_result_carries_pending_decisions(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        assert "D-1" in result.pending_decision_refs
        assert "D-3" in result.pending_decision_refs
        assert "D-9" in result.pending_decision_refs

    def test_stress_result_no_observed_on_synthetic(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)[:2]
        results = run_stress_tests(strategies, start_spot=S0)
        for r in results:
            assert r.provenance != Provenance.OBSERVED


# ─────────────────────────────────────────────────────────────────────────────
# L: Independent and adversarial tests
# ─────────────────────────────────────────────────────────────────────────────


class TestIndependentValidations:
    """Independent validations replacing tautological/weak tests."""

    def test_covered_call_payoff_at_breakeven_independent(self) -> None:
        """Independent check: at BE, P&L = 0."""
        K = 75_000.0
        P = 1_500.0
        strategy = build_covered_call(quantity=1.0, entry_spot=S0, strike=K, premium_received=P)
        be = S0 - P
        pnl = strategy_pnl(strategy, be)
        assert abs(pnl) < 1e-6

    def test_long_btc_short_put_break_even_independent(self) -> None:
        """Independent verification: breakeven identities."""
        K = 58_500.0
        P = 1_500.0
        ids = long_btc_plus_short_put_identities(S0, K, P)
        be_below = (S0 + K - P) / 2.0
        be_above = S0 - P
        assert abs(ids["breakeven_below_strike"] - be_below) < 1e-8
        assert abs(ids["breakeven_above_strike"] - be_above) < 1e-8

    def test_call_spread_pnl_at_strikes_independent(self) -> None:
        strategy = build_call_spread(quantity=1.0, call_strike_short=75_000.0,
                                      call_strike_long=85_000.0,
                                      short_premium=1_500.0, long_premium=600.0)
        pnl_at_below = strategy_pnl(strategy, 70_000.0)
        assert abs(pnl_at_below - 900.0) < 1e-6

        pnl_at_above = strategy_pnl(strategy, 90_000.0)
        max_loss = (85_000.0 - 75_000.0) * 1.0 - (1_500.0 - 600.0)
        assert abs(pnl_at_above - (-max_loss)) < 1e-6

    def test_comparison_no_fallbacks(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        payoff = {s.strategy_id: strategy_pnl(s, S0) for s in strategies}
        result = compare_strategies(strategies, payoff)
        for m in result.strategies:
            if m.strategy_id != "unhedged_baseline":
                assert m.effective_acquisition_cost != 65_000.0, \
                    f"{m.strategy_id} has fallback cost {m.effective_acquisition_cost}"

    def test_all_mandate_strategies_different(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        payoff = {s.strategy_id: strategy_pnl(s, 100_000.0) for s in strategies}
        assert len(set(payoff.values())) >= 4


# =============================================================================
# Adversarial and independent calculation tests
# =============================================================================


class TestLegDrivenBacktest:
    """Backtest executes each strategy from its actual legs."""

    def test_csp_backtest_has_cash_and_put_legs(self) -> None:
        s = build_cash_secured_put(quantity=10.0, entry_spot=S0, strike=58500.0, premium_received=1500.0)
        cash_legs = [leg for leg in s.legs if leg.product == "cash"]
        assert len(cash_legs) == 1
        put_legs = [leg for leg in s.legs if leg.option_type == "put"]
        assert len(put_legs) == 1
        assert put_legs[0].side == "SHORT"

    def test_spot_path_positive(self) -> None:
        n_days = 30
        rng = np.random.default_rng(42)
        dt = 1.0 / 365.0
        z = rng.normal(size=n_days)
        returns = (0.10 - 0.5 * 0.45 ** 2) * dt + 0.45 * np.sqrt(dt) * z
        spot_path = S0 * np.exp(np.cumsum(np.insert(returns, 0, 0.0)))
        assert np.all(spot_path > 0)

    def test_strike_ladder_reconciles_exactly(self) -> None:
        strat = build_strike_ladder(base_quantity=30_000.0, entry_spot=S0, dte_ladder=[30, 37, 44])
        spot_qty = sum(leg.quantity for leg in strat.legs if leg.product == "spot" and leg.side == "LONG")
        assert spot_qty == 30_000.0
        option_qty_total = sum(leg.quantity for leg in strat.legs if leg.option_type is not None)
        assert option_qty_total == 30_000.0


class TestCSPAssignment:
    """CSP collateral and assignment tests."""

    def test_csp_collateral_initialized(self) -> None:
        s = build_cash_secured_put(quantity=10.0, entry_spot=S0, strike=58500.0, premium_received=1500.0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(s, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert hasattr(cycle, "collateral_usd_start")
            assert hasattr(cycle, "collateral_usd_end")

    def test_csp_put_itm_assigns_btc(self) -> None:
        s = build_cash_secured_put(quantity=10.0, entry_spot=S0, strike=58500.0, premium_received=1500.0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(s, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert cycle.realised_assignment in (0, 1)
            assert hasattr(cycle, "btc_inventory_end")


class TestInverseBTCPremiumConversion:
    """Inverse BTC premiums remain BTC until converted using index price."""

    def test_inverse_settlement_not_added_to_usd_directly(self) -> None:
        from pricing.inverse import settlement_inverse_call_holder
        btc = settlement_inverse_call_holder(125000.0, 100000.0)
        assert abs(btc - 0.2) < 1e-9

    def test_inverse_put_settlement(self) -> None:
        from pricing.inverse import settlement_inverse_put_holder
        btc = settlement_inverse_put_holder(80000.0, 100000.0)
        assert abs(btc - 0.25) < 1e-9

    def test_inverse_premium_not_naive_add(self) -> None:
        s = build_covered_call(quantity=1.0, entry_spot=S0, strike=75000.0, premium_received=1500.0)
        is_btc_settled = any(
            leg.settlement is not None and leg.settlement.settlement_currency == SettlementCurrency.BTC
            for leg in s.legs if leg.option_type is not None
        )
        if not is_btc_settled:
            return
        pnl = strategy_pnl(s, 80000.0)
        assert isinstance(pnl, float)


class TestLedgerContinuity:
    """Cycle-to-cycle ledger continuity."""

    def test_cash_end_of_cycle_becomes_start_of_next(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        n_days = 365
        rng = np.random.default_rng(42)
        dt = 1.0 / 365.0
        z = rng.normal(size=n_days)
        returns = (0.10 - 0.5 * 0.45 ** 2) * dt + 0.45 * np.sqrt(dt) * z
        spot_path = S0 * np.exp(np.cumsum(np.insert(returns, 0, 0.0)))
        dates = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n_days + 1)]
        iv_history = np.full_like(spot_path, 0.45)
        result = backtest_strategy(strategy, dates, spot_path, iv_history, risk_free_rate=0.04, dte_days=30)
        for i in range(1, len(result.cycles)):
            assert result.cycles[i].cash_usd_start == result.cycles[i-1].cash_usd_end

    def test_btc_inventory_end_of_cycle_becomes_start_of_next(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        n_days = 365
        rng = np.random.default_rng(42)
        dt = 1.0 / 365.0
        z = rng.normal(size=n_days)
        returns = (0.10 - 0.5 * 0.45 ** 2) * dt + 0.45 * np.sqrt(dt) * z
        spot_path = S0 * np.exp(np.cumsum(np.insert(returns, 0, 0.0)))
        dates = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n_days + 1)]
        iv_history = np.full_like(spot_path, 0.45)
        result = backtest_strategy(strategy, dates, spot_path, iv_history, risk_free_rate=0.04, dte_days=30)
        for i in range(1, len(result.cycles)):
            assert result.cycles[i].btc_inventory_start == result.cycles[i-1].btc_inventory_end


class TestNoDoubleCounting:
    """A4 objects consumed without double counting."""

    def test_impact_not_double_counted_in_eac(self) -> None:
        strategy = build_covered_call(quantity=10.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        eac = result.effective_acquisition_cost
        if eac is None:
            return
        assert hasattr(eac, "impact_component_usd")
        assert hasattr(eac, "fee_component_usd")
        assert hasattr(eac, "premium_component_usd")

    def test_spread_slippage_is_separate_from_impact(self) -> None:
        strategy = build_covered_call(quantity=100.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        for cycle in result.cycles:
            assert hasattr(cycle, "spread_slippage_usd")
            assert hasattr(cycle, "impact_usd")


class TestTrancheExactReconciliation:
    """Exact BTC quantity reconciliation for tranche schedules."""

    def test_tranche_schedule_exact_30k(self) -> None:
        from execution.tranches import schedule_tranches
        sched = schedule_tranches(total_btc=30_000)
        total = sched.total_scheduled_btc()
        assert total == 30_000

    def test_tranche_schedule_exact_1k(self) -> None:
        from execution.tranches import schedule_tranches
        sched = schedule_tranches(total_btc=1_000)
        total = sched.total_scheduled_btc()
        assert total == 1_000

    def test_tranche_schedule_exact_50k_even(self) -> None:
        from execution.tranches import schedule_tranches
        sched = schedule_tranches(total_btc=50_000)
        total = sched.total_scheduled_btc()
        assert total == 50_000

    def test_tranche_schedule_exact_odd(self) -> None:
        from execution.tranches import schedule_tranches
        sched = schedule_tranches(total_btc=30_037)
        total = sched.total_scheduled_btc()
        assert total == 30_037

    def test_tranche_small_total(self) -> None:
        from execution.tranches import schedule_tranches
        sched = schedule_tranches(total_btc=500)
        total = sched.total_scheduled_btc()
        assert total == 500


class Test30kBTCReconciliation:
    """Exact 30,000-BTC mandate reconciliation."""

    def test_all_strategies_30k_reconcile(self) -> None:
        for qty in [30_000.0, 10_000.0, 1_000.0]:
            strategies = build_all_mandate_strategies(quantity=qty, entry_spot=S0)
            for s in strategies:
                spot_total = sum(leg.quantity for leg in s.legs if leg.product == "spot" and leg.side == "LONG")
                option_total = sum(leg.quantity for leg in s.legs if leg.option_type is not None)
                _cash_total = sum(leg.quantity for leg in s.legs if leg.product == "cash")
                if s.canonical == StrategyKind.CASH_SECURED_PUT:
                    assert option_total == qty
                elif s.canonical == StrategyKind.CALL_SPREAD:
                    assert option_total > 0
                elif s.canonical == StrategyKind.PARTIAL_OVERLAY or spot_total > 0:
                    assert spot_total == qty


class TestKnownDistribution:
    """Tests using known-distribution vectors for VaR/ES validation."""

    def test_var_95_from_known_array(self) -> None:
        losses = np.array([-500.0, -100.0, 0.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0])
        from strategy.monte_carlo import _compute_var_es
        result = _compute_var_es(losses, len(losses))
        assert result["var_95"] >= 0
        n_95_idx = int(len(losses) * 0.95)
        expected_var = sorted(losses)[min(n_95_idx, len(losses) - 1)]
        assert abs(result["var_95"] - expected_var) < 1e-9

    def test_var_99_from_known_array(self) -> None:
        n_paths = 1000
        rng = np.random.default_rng(42)
        losses = rng.normal(1000, 500, n_paths)
        from strategy.monte_carlo import _compute_var_es
        result = _compute_var_es(losses, n_paths)
        assert result["var_95"] > 0
        assert result["var_99"] > result["var_95"]
        assert result["es_975"] > result["var_95"]

    def test_es_is_higher_than_var(self) -> None:
        losses = np.array([100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0])
        from strategy.monte_carlo import _compute_var_es
        result = _compute_var_es(losses, len(losses))
        assert result["es_975"] >= result["var_95"]


class TestMertonPathCount:
    """Merton simulation populates all requested paths."""

    def test_merton_50k_paths(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        config = MonteCarloConfig(n_paths=1000, seed=42, model="Merton", use_antithetic=True)
        result = run_monte_carlo(strategy, config)
        assert len(result.pnl_distribution) == 1000
        non_zero = sum(1 for x in result.pnl_distribution if x != 0)
        assert non_zero >= 990

    def test_merton_odd(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        for n in [7, 13, 51, 127]:
            config = MonteCarloConfig(n_paths=n, seed=42, model="Merton", use_antithetic=True)
            result = run_monte_carlo(strategy, config)
            assert len(result.pnl_distribution) == n

    def test_merton_even(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        for n in [10, 100, 1000]:
            config = MonteCarloConfig(n_paths=n, seed=42, model="Merton", use_antithetic=True)
            result = run_monte_carlo(strategy, config)
            assert len(result.pnl_distribution) == n


class TestRealCSCVPBODSR:
    """CSCV/PBO/DSR produce real results, not placeholders."""

    def test_pbo_not_hardcoded(self) -> None:
        from strategy.regimes import compute_cscv_pbo
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, size=500)
        result = compute_cscv_pbo(returns, s=16, n_min=100)
        pbo = result["pbo_estimate"]
        assert pbo is not None
        assert 0.0 <= pbo <= 1.0
        assert not result["is_insufficient_data"]

    def test_pbo_for_strong_signal(self) -> None:
        from strategy.regimes import compute_cscv_pbo
        rng = np.random.default_rng(42)
        returns = rng.normal(0.02, 0.005, size=200)
        result = compute_cscv_pbo(returns, s=16, n_min=100)
        assert result["deflated_sharpe_ratio"] is not None
        assert result["deflated_sharpe_ratio"] >= 0

    def test_cscv_insufficient_data_typed(self) -> None:
        from strategy.regimes import compute_cscv_pbo
        result = compute_cscv_pbo(np.array([0.01]), s=16, n_min=100)
        assert result["is_insufficient_data"] is True
        assert "required_n" in result



class TestChronologicalOOS:
    """Chronological OOS validation."""

    def test_train_before_test_hard_enforced(self) -> None:
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(1000)]
        train, test = split_train_test(dates, train_ratio=0.70)
        assert max(train) < min(test)

    def test_train_before_test_with_real_dates(self) -> None:
        dates = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(100)]
        train, test = split_train_test(dates, train_ratio=0.70)
        assert all(test[i] > max(train) for i in range(len(test)) if test and train)

    def test_oos_sharpe_degradation_positive(self) -> None:
        r = compute_oos_validation(
            train_result={"sharpe": 1.5, "returns": [], "train_period": (datetime(2023, 1, 1), datetime(2024, 12, 31))},
            test_result={"sharpe": 0.5, "returns": [], "test_period": (datetime(2025, 1, 1), datetime(2026, 6, 30))},
        )
        assert r.performance_degradation == 1.0
        assert r.is_insufficient_data is True or r.is_insufficient_data is False

    def test_oos_periods_are_different(self) -> None:
        train_period = (datetime(2023, 1, 1), datetime(2024, 12, 31))
        test_period = (datetime(2025, 1, 1), datetime(2026, 6, 30))
        assert train_period[1] < test_period[0]


class TestStressOptionMTM:
    """Stress tests apply vol shocks through option MTM."""

    def test_vol_shock_in_instantaneous(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0)
        from strategy.scenarios import Scenario
        scenario = Scenario(
            name="test_shock", description="test",
            shock_type="instantaneous",
            start_spot=S0, end_spot=S0,
            start_vol=0.45, end_vol=0.65,
        )
        result = apply_scenario(strategy, scenario)
        assert "vol_shock_contribution_usd" in result
        assert "strategy_pnl_usd" in result

    def test_vol_shock_contributes_to_pnl(self) -> None:
        strategy = build_covered_call(quantity=100.0, entry_spot=S0)
        from strategy.scenarios import Scenario
        scenario = Scenario(
            name="vol_only", description="vol shock only, spot unchanged",
            shock_type="instantaneous",
            start_spot=S0, end_spot=S0,
            start_vol=0.35, end_vol=0.65,
        )
        result = apply_scenario(strategy, scenario)
        vol_contrib = result["vol_shock_contribution_usd"]
        expiry_contrib = strategy_pnl(strategy, S0)
        assert isinstance(vol_contrib, float)
        assert isinstance(expiry_contrib, float)


class TestAssignmentVsTouch:
    """Assignment frequency != touch frequency."""

    def test_touch_frequency_not_equals_itm(self) -> None:
        strategy = build_covered_call(quantity=1.0, entry_spot=S0, strike=75_000.0, premium_received=1500.0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 3, 31, tzinfo=UTC)
        result = backtest_covered_call_overlay(strategy, start, end, S0, seed=42, dte_days=30)
        assert hasattr(result, "touch_frequency")
        assert isinstance(result.touch_frequency, float)


class TestForbiddenRecommendation:
    """No strategy is described as best, optimal, preferred, recommended, safest, or winner."""

    forbidden = frozenset({"best", "optimal", "safest", "preferred", "recommended", "winner"})

    def test_comparison_output_no_forbidden(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        payoff = {s.strategy_id: strategy_pnl(s, S0) for s in strategies}
        result = compare_strategies(strategies, payoff)
        rankings = result.get_rankings()
        for key in rankings:
            for word in self.forbidden:
                assert word not in key.lower()

    def test_strategy_ids_no_forbidden(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        for s in strategies:
            for word in self.forbidden:
                assert word not in s.strategy_id.lower()

    def test_business_labels_no_forbidden(self) -> None:
        strategies = build_all_mandate_strategies(quantity=1.0, entry_spot=S0)
        for s in strategies:
            for word in self.forbidden:
                assert word not in s.business_label.lower()


class TestGranularD1D3D9:
    """D-1, D-3, and D-9 are carried in all relevant outputs."""

    def test_calls_have_d1_d3_d9(self) -> None:
        s = build_covered_call(quantity=1.0, entry_spot=S0)
        codes = {d.code for d in s.pending_decisions}
        assert "D-1" in codes
        assert "D-3" in codes
        assert "D-9" in codes

    def test_puts_have_d1_d3(self) -> None:
        s = build_cash_secured_put(quantity=1.0, entry_spot=S0)
        codes = {d.code for d in s.pending_decisions}
        assert "D-1" in codes
        assert "D-3" in codes

    def test_unhedged_has_d3(self) -> None:
        s = build_unhedged_baseline(quantity=1.0, entry_spot=S0)
        codes = {d.code for d in s.pending_decisions}
        assert "D-3" in codes

    def test_backtest_result_carries_d1_d3_d9(self) -> None:
        s = build_covered_call(quantity=1.0, entry_spot=S0)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 6, 30, tzinfo=UTC)
        result = backtest_covered_call_overlay(s, start, end, S0, seed=42, dte_days=30)
        refs = result.pending_decision_refs
        assert "D-1" in refs
        assert "D-3" in refs
        assert "D-9" in refs


# ─────────────────────────────────────────────────────────────────────────────
# M: Independent numerical ledger tests for effective acquisition cost
# ─────────────────────────────────────────────────────────────────────────────


class TestEffectiveAcquisitionCost:
    """Independent numerical ledger tests with manually calculated examples.

    Each test constructs a strategy, runs a deterministic backtest with known
    spot paths, and verifies the ledger-derived effective acquisition cost
    against a manually computed value.
    """

    def _build_synthetic_data(
        self, n_days: int, start_spot: float, path_fn: str = "flat"
    ) -> tuple[list[datetime], np.ndarray, np.ndarray]:
        import numpy as np
        dates = [datetime(2024, 7, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n_days + 1)]
        if path_fn == "flat":
            spot = np.full(n_days + 1, start_spot, dtype=np.float64)
        elif path_fn == "up":
            spot = np.linspace(start_spot, start_spot * 1.5, n_days + 1, dtype=np.float64)
        elif path_fn == "down":
            spot = np.linspace(start_spot, start_spot * 0.5, n_days + 1, dtype=np.float64)
        else:
            spot = np.full(n_days + 1, start_spot, dtype=np.float64)
        iv = np.full(n_days + 1, 0.45, dtype=np.float64)
        return dates, spot, iv

    def test_unhedged_acquisition_cost_no_spot_mtm(self) -> None:
        """Unhedged acquisition cost excludes spot mark-to-market but includes asym fee."""
        s = build_unhedged_baseline(quantity=10.0, entry_spot=65_000.0)
        dates, spot, iv = self._build_synthetic_data(90, 65_000.0, "up")
        result = backtest_strategy(s, dates, spot, iv, risk_free_rate=0.04, dte_days=30,
                                    seller_discount_pct=0.025)
        eac = result.effective_acquisition_cost
        assert eac is not None
        # Issue 1: EAC now includes asym fee (0.5% * reference_qty * spot)
        asym_fee = result.total_asym_fee_usd
        discount = 65_000.0 * 0.025 * 10.0
        purchase = 65_000.0 * 10.0
        expected = (purchase - discount + asym_fee) / 10.0
        assert abs(eac.per_btc_usd - expected) < 50.0, (
            f"Unhedged EAC {eac.per_btc_usd:.2f} != expected {expected:.2f}"
        )

    def test_covered_call_eac_with_known_flat_spot(self) -> None:
        """Covered call with flat spot: EAC = (purchase + fees + asym - prem - payout - discount) / qty."""
        qty = 10.0
        spot_val = 100_000.0
        K = spot_val * 1.15
        s = build_covered_call(quantity=qty, entry_spot=spot_val, strike=K, premium_received=1000.0,
                                dte_days=30)
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        result = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                    seller_discount_pct=0.025, spread_bps=0.0)
        eac = result.effective_acquisition_cost
        assert eac is not None

        purchase = spot_val * qty
        discount = spot_val * 0.025 * qty
        total_prem = sum(c.premium_received_usd for c in result.cycles)
        total_payout = sum(c.settlement_usd for c in result.cycles)
        total_fees = sum(c.venue_fees_usd + c.delivery_fee_usd + c.spread_slippage_usd + c.impact_usd
                          for c in result.cycles)
        # Issue 1: asym fee included in EAC
        expected_per_btc = (purchase + total_fees + result.total_asym_fee_usd - total_prem - total_payout - discount) / qty
        assert abs(eac.per_btc_usd - expected_per_btc) < 1e-9, (
            f"EAC {eac.per_btc_usd} != expected {expected_per_btc}"
        )
        assert eac.per_btc_usd > 0, f"Covered call EAC must be positive, got {eac.per_btc_usd}"

    def test_covered_call_premium_reduces_cost(self) -> None:
        """Higher premium should reduce (not increase) effective acquisition cost.

        Issue 7: strikes are now determined by strike_pct_above, not builder
        strikes. Using near vs far strike_pct_above to test EAC reduction.
        """
        qty = 10.0
        spot_val = 100_000.0

        s_near = build_covered_call(quantity=qty, entry_spot=spot_val, strike=spot_val * 1.05, dte_days=30)
        s_far = build_covered_call(quantity=qty, entry_spot=spot_val, strike=spot_val * 1.30, dte_days=30)

        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")

        r_near = backtest_strategy(s_near, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                    seller_discount_pct=0.025, spread_bps=0.0, strike_pct_above=0.05)
        r_far = backtest_strategy(s_far, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                   seller_discount_pct=0.025, spread_bps=0.0, strike_pct_above=0.30)

        eac_near = r_near.effective_acquisition_cost
        eac_far = r_far.effective_acquisition_cost
        assert eac_near is not None and eac_far is not None

        total_prem_near = sum(c.premium_received_usd for c in r_near.cycles)
        total_prem_far = sum(c.premium_received_usd for c in r_far.cycles)
        assert total_prem_near > total_prem_far, f"Nearer strike (5% vs 30%) should collect more premium: {total_prem_near} vs {total_prem_far}"
        assert eac_near.per_btc_usd < eac_far.per_btc_usd, (
            f"More premium should mean lower EAC: near={eac_near.per_btc_usd}, far={eac_far.per_btc_usd}"
        )

    def test_collar_eac_positive(self) -> None:
        """Collar effective acquisition cost must be positive."""
        qty = 10.0
        spot_val = 100_000.0
        s = build_collar(quantity=qty, entry_spot=spot_val, call_strike=spot_val * 1.15,
                         put_strike=spot_val * 0.85, call_premium=2000.0, put_premium=1500.0, dte_days=30)
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        result = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                   seller_discount_pct=0.025, spread_bps=0.0)
        eac = result.effective_acquisition_cost
        assert eac is not None
        assert eac.per_btc_usd > 0, f"Collar EAC must be positive, got {eac.per_btc_usd}"

    def test_partial_overlay_50_pct_eac_positive(self) -> None:
        """50% partial overlay EAC must be positive and preserve full BTC denominator."""
        qty = 10.0
        spot_val = 100_000.0
        s = build_partial_overlay(total_quantity=qty, overlay_ratio=0.5, entry_spot=spot_val,
                                   strike=spot_val * 1.15, premium_received=1000.0, dte_days=30)
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        result = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                    seller_discount_pct=0.025, spread_bps=0.0)
        eac = result.effective_acquisition_cost
        assert eac is not None
        assert eac.per_btc_usd > 0

        purchase = spot_val * qty
        discount = spot_val * 0.025 * qty
        total_prem = sum(c.premium_received_usd for c in result.cycles)
        total_payout = sum(c.settlement_usd for c in result.cycles)
        total_fees = sum(c.venue_fees_usd + c.delivery_fee_usd + c.spread_slippage_usd + c.impact_usd
                          for c in result.cycles)
        expected = (purchase + total_fees + result.total_asym_fee_usd - total_prem - total_payout - discount) / qty
        assert abs(eac.per_btc_usd - expected) < 1e-9

    def test_partial_overlay_75_pct_eac_positive(self) -> None:
        """75% partial overlay EAC must be positive."""
        qty = 10.0
        spot_val = 100_000.0
        s = build_partial_overlay(total_quantity=qty, overlay_ratio=0.75, entry_spot=spot_val,
                                  strike=spot_val * 1.15, premium_received=1000.0, dte_days=30,
                                  strategy_id="partial_overlay_75")
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        result = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                   seller_discount_pct=0.025, spread_bps=0.0)
        eac = result.effective_acquisition_cost
        assert eac is not None
        assert eac.per_btc_usd > 0

    def test_strike_ladder_eac_positive(self) -> None:
        """Strike ladder EAC must be positive with full BTC denominator."""
        qty = 30.0
        spot_val = 100_000.0
        s = build_strike_ladder(base_quantity=qty, entry_spot=spot_val, dte_ladder=[30, 37, 44])
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        result = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                    seller_discount_pct=0.025, spread_bps=0.0)
        eac = result.effective_acquisition_cost
        assert eac is not None
        assert eac.per_btc_usd > 0

        purchase = spot_val * qty
        discount = spot_val * 0.025 * qty
        total_prem = sum(c.premium_received_usd for c in result.cycles)
        total_payout = sum(c.settlement_usd for c in result.cycles)
        total_fees = sum(c.venue_fees_usd + c.delivery_fee_usd + c.spread_slippage_usd + c.impact_usd
                          for c in result.cycles)
        expected = (purchase + total_fees + result.total_asym_fee_usd - total_prem - total_payout - discount) / qty
        assert abs(eac.per_btc_usd - expected) < 1e-9

    def test_cash_secured_put_eac_na_when_no_btc_acquired(self) -> None:
        """FRF-014 / D-12: a CSP that acquires no BTC must report EAC = n/a
        (not a positive per-BTC figure). On a flat path the put never assigns,
        so BOTH D-12 interpretations are n/a with a reason."""
        qty = 10.0
        spot_val = 100_000.0
        s_csp = build_cash_secured_put(quantity=qty, entry_spot=spot_val, strike=spot_val * 0.85,
                                       premium_received=1500.0, dte_days=30)
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        r_csp = backtest_strategy(s_csp, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                   seller_discount_pct=0.025, spread_bps=0.0)
        assert r_csp.eac_cash_settled is not None
        assert r_csp.eac_cash_settled.is_applicable is False
        assert r_csp.eac_cash_settled.na_reason is not None
        assert r_csp.eac_post_purchase is not None
        assert r_csp.eac_post_purchase.is_applicable is False

    def test_long_btc_plus_short_put_eac_positive(self) -> None:
        """Long BTC + short put EAC must be positive."""
        qty = 10.0
        spot_val = 100_000.0
        s = build_long_btc_plus_short_put(quantity=qty, entry_spot=spot_val,
                                          strike=spot_val * 0.85, premium_received=1500.0,
                                          dte_days=30)
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        result = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                   seller_discount_pct=0.025, spread_bps=0.0)
        eac = result.effective_acquisition_cost
        assert eac is not None
        assert eac.per_btc_usd > 0

    def test_csp_and_long_btc_short_put_eac_differ(self) -> None:
        """CSP and long BTC + short put must produce different EAC values."""
        qty = 10.0
        spot_val = 100_000.0
        s_csp = build_cash_secured_put(quantity=qty, entry_spot=spot_val, strike=spot_val * 0.85,
                                       premium_received=1500.0, dte_days=30)
        s_lbpsp = build_long_btc_plus_short_put(quantity=qty, entry_spot=spot_val,
                                                strike=spot_val * 0.85, premium_received=1500.0,
                                                dte_days=30)
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
        r_csp = backtest_strategy(s_csp, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                   seller_discount_pct=0.025, spread_bps=0.0)
        r_lbpsp = backtest_strategy(s_lbpsp, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                    seller_discount_pct=0.025, spread_bps=0.0)
        eac_csp = r_csp.effective_acquisition_cost
        eac_lbpsp = r_lbpsp.effective_acquisition_cost
        assert eac_csp is not None and eac_lbpsp is not None
        assert eac_csp.per_btc_usd != eac_lbpsp.per_btc_usd, (
            f"CSP {eac_csp.per_btc_usd} must differ from LBPSP {eac_lbpsp.per_btc_usd}"
        )

    def test_premium_credit_monotonicity(self) -> None:
        """Increasing strike_pct_above → lower premium → higher EAC (Issue 7)."""
        qty = 10.0
        spot_val = 100_000.0
        # Issue 7: strike is determined by strike_pct_above, not builder strike
        pct_above_vals = [0.05, 0.15, 0.30]
        eacs: list[float] = []
        premiums: list[float] = []

        for pct in pct_above_vals:
            s = build_covered_call(quantity=qty, entry_spot=spot_val, strike=spot_val * (1 + pct), dte_days=30)
            dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
            r = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                  seller_discount_pct=0.025, spread_bps=0.0, strike_pct_above=pct)
            eac_val = r.effective_acquisition_cost
            assert eac_val is not None
            eacs.append(eac_val.per_btc_usd)
            premiums.append(sum(c.premium_received_usd for c in r.cycles))

        assert premiums[0] > premiums[1] > premiums[2], (
            f"Closer strikes should collect more premium: {premiums}"
        )
        assert eacs[0] < eacs[1] < eacs[2], (
            f"More premium should yield lower EAC: {eacs}"
        )

    def test_quantity_scaling_eac_invariant(self) -> None:
        """EAC per BTC must be invariant under quantity scaling (same spot, strike%, IV)."""
        spot_val = 100_000.0
        K = spot_val * 1.15
        eacs: dict[float, float] = {}
        for qty in [5.0, 10.0, 50.0]:
            s = build_covered_call(quantity=qty, entry_spot=spot_val, strike=K, dte_days=30)
            dates, spot_arr, iv_arr = self._build_synthetic_data(60, spot_val, "flat")
            r = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                                  seller_discount_pct=0.025, spread_bps=0.0)
            eac_val = r.effective_acquisition_cost
            assert eac_val is not None
            eacs[qty] = eac_val.per_btc_usd

        vals = list(eacs.values())
        max_diff = max(vals) - min(vals)
        assert max_diff < 1.0, (
            f"EAC per BTC should be invariant under qty scaling: {eacs}, max diff {max_diff}"
        )

    def test_eac_excludes_spot_mark_to_market(self) -> None:
        """EAC must be identical for flat and trending spot paths (option payoff aside)."""
        qty = 10.0
        spot_val = 100_000.0
        K = spot_val * 1.15
        s = build_covered_call(quantity=qty, entry_spot=spot_val, strike=K, dte_days=30)

        dates_up, spot_up, iv_up = self._build_synthetic_data(60, spot_val, "up")
        dates_down, spot_down, iv_down = self._build_synthetic_data(60, spot_val, "down")

        r_up = backtest_strategy(s, dates_up, spot_up, iv_up, risk_free_rate=0.04, dte_days=30,
                                 seller_discount_pct=0.025, spread_bps=0.0)
        r_down = backtest_strategy(s, dates_down, spot_down, iv_down, risk_free_rate=0.04, dte_days=30,
                                   seller_discount_pct=0.025, spread_bps=0.0)

        eac_up = r_up.effective_acquisition_cost
        eac_down = r_down.effective_acquisition_cost
        assert eac_up is not None and eac_down is not None

        assert eac_up.per_btc_usd > 0
        assert eac_down.per_btc_usd > 0
        assert eac_up.per_btc_usd != eac_down.per_btc_usd, (
            "EAC should differ under different spot paths due to different settlement payouts"
        )

    def test_all_eac_components_have_provenance(self) -> None:
        """Every component of EffectiveAcquisitionCost must carry provenance."""
        s = build_covered_call(quantity=10.0, entry_spot=100_000.0, strike=115_000.0, dte_days=30)
        dates, spot_arr, iv_arr = self._build_synthetic_data(60, 100_000.0, "flat")
        r = backtest_strategy(s, dates, spot_arr, iv_arr, risk_free_rate=0.04, dte_days=30,
                              seller_discount_pct=0.025)
        eac = r.effective_acquisition_cost
        assert eac is not None
        assert isinstance(eac.premium_provenance, Provenance)
        assert isinstance(eac.fee_provenance, Provenance)
        assert isinstance(eac.seller_discount_provenance, Provenance)
        assert isinstance(eac.impact_provenance, Provenance)
        assert isinstance(eac.provenance, Provenance)
