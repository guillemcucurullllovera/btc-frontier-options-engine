"""Strategy comparison — evidence-producing, no recommendations.

Produces structured machine-readable comparison results for all strategies.
Never calls any strategy best, optimal, safest, preferred, recommended, or winner.
All comparison outputs are evidence-based and carry provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config.models import Provenance
from engine.strategy import Strategy, StrategyKind


@dataclass(frozen=True)
class StrategyMetrics:
    strategy_id: str
    strategy_kind: StrategyKind
    business_label: str
    return_pct: float = 0.0
    pnl_per_btc: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float | None = None
    premium_income_pct: float = 0.0
    effective_acquisition_cost: float = 0.0
    upside_retained: bool = True
    downside_exposure_pct: float = 0.0
    itm_frequency: float = 0.0
    touch_frequency: float = 0.0
    fee_component_pct: float = 0.0
    impact_component_pct: float = 0.0
    operational_complexity: str = "low"
    settlement_complexity: str = "simple"
    data_quality: str = "high"
    provenance: Provenance = Provenance.CALCULATED


@dataclass(frozen=True)
class ComparisonResult:
    timestamp: str
    strategies: list[StrategyMetrics] = field(default_factory=list)
    benchmark_id: str = "unhedged_baseline"
    comparison_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: Provenance = Provenance.CALCULATED

    def get_rankings(self) -> dict[str, list[str]]:
        by_effective_cost = sorted(self.strategies, key=lambda s: s.effective_acquisition_cost)
        by_pnl = sorted(self.strategies, key=lambda s: s.pnl_per_btc, reverse=True)
        by_sharpe = sorted(
            [s for s in self.strategies if s.sharpe_ratio is not None],
            key=lambda s: s.sharpe_ratio or 0, reverse=True,
        )
        return {
            "lowest_effective_cost": [s.strategy_id for s in by_effective_cost],
            "highest_pnl_per_btc": [s.strategy_id for s in by_pnl],
            "highest_sharpe": [s.strategy_id for s in by_sharpe],
        }


def _extract_strategy_btc_quantity(strategy: Strategy) -> float:
    spot_qty = sum(leg.quantity for leg in strategy.legs if leg.product == "spot" and leg.side == "LONG")
    if spot_qty > 0:
        return spot_qty
    option_qty = 0.0
    for leg in strategy.legs:
        if leg.option_type is not None and leg.side == "SHORT":
            option_qty = max(option_qty, leg.quantity)
    if option_qty > 0:
        return option_qty
    return 0.0


def _extract_strategy_entry_spot(strategy: Strategy) -> float:
    for leg in strategy.legs:
        if leg.product == "spot" and leg.entry_spot is not None:
            return leg.entry_spot
    for leg in strategy.legs:
        if leg.option_type is not None and leg.strike is not None:
            return leg.strike / 1.15
    return 0.0


def compute_metrics_from_payoff(
    strategy: Strategy,
    pnl_usd: float,
    btc_quantity: float,
    entry_spot: float,
) -> StrategyMetrics:
    return StrategyMetrics(
        strategy_id=strategy.strategy_id,
        strategy_kind=strategy.canonical,
        business_label=strategy.business_label,
        pnl_per_btc=pnl_usd / max(btc_quantity, 1.0),
        effective_acquisition_cost=entry_spot - (pnl_usd / max(btc_quantity, 1.0)),
        upside_retained=strategy.canonical not in (StrategyKind.COVERED_CALL, StrategyKind.COLLAR),
        provenance=Provenance.CALCULATED,
    )


def compare_strategies(
    strategies: list[Strategy],
    payoff_results: dict[str, float],
    backtest_results: dict[str, Any] | None = None,
    monte_carlo_results: dict[str, Any] | None = None,
    stress_results: dict[str, Any] | None = None,
) -> ComparisonResult:
    from datetime import UTC, datetime

    metrics_list: list[StrategyMetrics] = []

    for strategy in strategies:
        pnl = payoff_results.get(strategy.strategy_id, 0.0)
        btc_qty = _extract_strategy_btc_quantity(strategy)
        entry = _extract_strategy_entry_spot(strategy)

        if btc_qty == 0 and strategy.canonical == StrategyKind.CASH_SECURED_PUT:
            cash_legs = [leg for leg in strategy.legs if leg.product == "cash"]
            if cash_legs:
                total_cash = sum(leg.quantity for leg in cash_legs)
                put_legs = [leg for leg in strategy.legs if leg.option_type == "put"]
                if put_legs and put_legs[0].strike:
                    btc_qty = total_cash / put_legs[0].strike
                    entry = put_legs[0].strike or 0.0

        m = compute_metrics_from_payoff(strategy, pnl, btc_qty, entry)

        if backtest_results and strategy.strategy_id in backtest_results:
            bt = backtest_results[strategy.strategy_id]
            eff_acq = getattr(bt, "effective_acquisition_cost", None)
            if eff_acq is not None and hasattr(eff_acq, "per_btc_usd"):
                eac_value = eff_acq.per_btc_usd
            else:
                eac_value = getattr(bt, "effective_acquisition_cost_per_btc", m.effective_acquisition_cost)

            m = StrategyMetrics(
                strategy_id=m.strategy_id, strategy_kind=m.strategy_kind,
                business_label=m.business_label,
                pnl_per_btc=m.pnl_per_btc,
                effective_acquisition_cost=eac_value,
                sharpe_ratio=getattr(bt, "sharpe_ratio", None),
                itm_frequency=getattr(bt, "itm_frequency", 0.0),
                max_drawdown_pct=getattr(bt, "max_drawdown_pct", 0.0),
                upside_retained=m.upside_retained,
                provenance=Provenance.CALCULATED,
            )

        metrics_list.append(m)

    return ComparisonResult(
        timestamp=datetime.now(UTC).isoformat(),
        strategies=metrics_list,
        comparison_metrics={},
    )
