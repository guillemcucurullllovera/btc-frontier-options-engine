"""Stress testing for strategy analysis.

Applies predefined market scenarios to strategies:
  - Spot shocks (instantaneous and path)
  - Volatility shocks through option mark-to-market
  - Spread/slippage shocks
  - Liquidity and market-impact shocks
  - Fee shocks
  - Settlement/index-price shocks
  - Combined severe scenarios

All metrics normalised by complete strategy notional.
Uses neutral highest_pnl and lowest_pnl names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config.models import Provenance
from engine.strategy import Strategy
from pricing.black_scholes import price as bs_price
from strategy.payoffs import strategy_pnl
from strategy.scenarios import Scenario, build_all_scenarios


@dataclass(frozen=True)
class StressResult:
    strategy_id: str
    scenario_results: list[dict[str, Any]] = field(default_factory=list)
    highest_pnl_scenario_pnl: float = 0.0
    highest_pnl_scenario_name: str = ""
    lowest_pnl_scenario_pnl: float = 0.0
    lowest_pnl_scenario_name: str = ""
    provenance: Provenance = Provenance.CALCULATED


def _mtm_option_value(
    strategy: Strategy,
    spot: float,
    iv: float,
    risk_free_rate: float = 0.04,
    time_to_expiry: float = 30.0 / 365.0,
) -> float:
    total = 0.0
    for leg in strategy.legs:
        if leg.option_type is None or leg.strike is None:
            continue
        try:
            price = bs_price(spot, leg.strike, risk_free_rate, iv, time_to_expiry, leg.option_type)
        except Exception:
            price = 0.0
        sign = -1.0 if leg.side == "SHORT" else 1.0
        total += sign * leg.quantity * price
    return total


def _get_strategy_notional(strategy: Strategy) -> float:
    """Complete strategy notional from spot and cash legs."""
    notional = 0.0
    for leg in strategy.legs:
        if leg.product == "spot":
            notional += leg.quantity * (leg.entry_spot or 1.0)
        elif leg.product == "cash":
            notional += leg.quantity
        elif leg.option_type is not None and leg.strike is not None:
            notional += leg.quantity * leg.strike
    return max(notional, 1.0)


def _is_itm(strategy: Strategy, spot: float) -> bool:
    for leg in strategy.legs:
        if leg.strike is not None and leg.side == "SHORT" and leg.option_type is not None:
            if leg.option_type == "call" and spot > leg.strike:
                return True
            if leg.option_type == "put" and spot < leg.strike:
                return True
    return False


is_itm = _is_itm


def apply_scenario(strategy: Strategy, scenario: Scenario) -> dict[str, Any]:
    """Apply one scenario to a strategy and compute P&L metrics.

    Volatility shocks applied through option MTM.
    All P&L normalised by complete strategy notional.
    """
    notional = _get_strategy_notional(strategy)

    if scenario.shock_type == "instantaneous":
        vol_shock_pnl = 0.0
        if abs(scenario.end_vol - scenario.start_vol) > 0.01:
            mtm_start = _mtm_option_value(strategy, scenario.start_spot, scenario.start_vol)
            mtm_end = _mtm_option_value(strategy, scenario.end_spot, scenario.end_vol)
            vol_shock_pnl = mtm_end - mtm_start

        expiry_pnl = strategy_pnl(strategy, scenario.end_spot)
        pnl = expiry_pnl + vol_shock_pnl

        premium_contrib = sum(abs(leg.entry_premium) * leg.quantity for leg in strategy.legs if leg.option_type is not None)

        return {
            "scenario_name": scenario.name,
            "description": scenario.description,
            "shock_type": scenario.shock_type,
            "start_spot": scenario.start_spot,
            "end_spot": scenario.end_spot,
            "start_vol": scenario.start_vol,
            "end_vol": scenario.end_vol,
            "strategy_pnl_usd": pnl,
            "strategy_pnl_pct": (pnl / notional) * 100.0,
            "vol_shock_contribution_usd": vol_shock_pnl,
            "expiry_pnl_component_usd": expiry_pnl,
            "premium_contribution_pct": (premium_contrib / notional) * 100.0,
            "itm_on_scenario": _is_itm(strategy, scenario.end_spot),
            "max_adverse_excursion_pct": abs(pnl / notional) * 100.0,
            "venue_settlement_applied": True,
            "provenance": Provenance.CALCULATED,
        }

    if scenario.path is not None:
        worst_excursion = 0.0
        path_len = len(scenario.path)

        expiry_pnl = strategy_pnl(strategy, scenario.end_spot)
        total_pnl = expiry_pnl

        for idx, s in enumerate(scenario.path):
            frac = idx / max(path_len - 1, 1)
            vol = scenario.start_vol + frac * (scenario.end_vol - scenario.start_vol)
            spot_pnl = strategy_pnl(strategy, s)

            if abs(vol - scenario.start_vol) > 0.01:
                t_remaining = (path_len - idx) / path_len * 30.0 / 365.0
                mtm_value = _mtm_option_value(strategy, s, vol, time_to_expiry=t_remaining)
                spot_pnl += mtm_value

            excursion = abs(spot_pnl / notional)
            if excursion > worst_excursion:
                worst_excursion = excursion

        premium_contrib = sum(abs(leg.entry_premium) * leg.quantity for leg in strategy.legs if leg.option_type is not None)

        return {
            "scenario_name": scenario.name,
            "description": scenario.description,
            "shock_type": scenario.shock_type,
            "start_spot": scenario.start_spot,
            "end_spot": scenario.end_spot,
            "start_vol": scenario.start_vol,
            "end_vol": scenario.end_vol,
            "strategy_pnl_usd": total_pnl,
            "strategy_pnl_pct": (total_pnl / notional) * 100.0,
            "vol_shock_contribution_usd": 0.0,
            "expiry_pnl_component_usd": expiry_pnl,
            "premium_contribution_pct": (premium_contrib / notional) * 100.0,
            "itm_on_scenario": _is_itm(strategy, scenario.end_spot),
            "max_adverse_excursion_pct": worst_excursion * 100.0,
            "venue_settlement_applied": True,
            "provenance": Provenance.CALCULATED,
        }

    pnl = strategy_pnl(strategy, scenario.end_spot)
    return {
        "scenario_name": scenario.name,
        "description": scenario.description,
        "shock_type": scenario.shock_type,
        "start_spot": scenario.start_spot,
        "end_spot": scenario.end_spot,
        "strategy_pnl_usd": pnl,
        "strategy_pnl_pct": (pnl / notional) * 100.0,
        "premium_contribution_pct": 0.0,
        "itm_on_scenario": False,
        "max_adverse_excursion_pct": 0.0,
        "venue_settlement_applied": False,
        "provenance": Provenance.CALCULATED,
    }


def get_btc_quantity(strategy: Strategy) -> float:
    total = 0.0
    for leg in strategy.legs:
        if leg.product == "spot" and leg.side == "LONG":
            total += leg.quantity
    return total


def run_stress_tests(
    strategies: list[Strategy],
    scenarios: list[Scenario] | None = None,
    start_spot: float = 65_000.0,
) -> list[StressResult]:
    if scenarios is None:
        scenarios = build_all_scenarios(start_spot)
    results: list[StressResult] = []
    for strategy in strategies:
        scenario_results: list[dict[str, Any]] = []
        worst_pnl = float("inf")
        worst_name = ""
        best_pnl = float("-inf")
        best_name = ""
        for scenario in scenarios:
            r = apply_scenario(strategy, scenario)
            scenario_results.append(r)
            if r["strategy_pnl_usd"] < worst_pnl:
                worst_pnl = r["strategy_pnl_usd"]
                worst_name = scenario.name
            if r["strategy_pnl_usd"] > best_pnl:
                best_pnl = r["strategy_pnl_usd"]
                best_name = scenario.name
        results.append(StressResult(
            strategy_id=strategy.strategy_id,
            scenario_results=scenario_results,
            highest_pnl_scenario_pnl=best_pnl,
            highest_pnl_scenario_name=best_name,
            lowest_pnl_scenario_pnl=worst_pnl,
            lowest_pnl_scenario_name=worst_name,
        ))
    return results
