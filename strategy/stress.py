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

Stage-2 remediation (Issue 10): supports two valuation bases:
  - expiry_settlement: P&L from expiry payoff only.
  - mtm_revaluation: MTM difference (end_spot/end_vol vs start_spot/start_vol).
  The vol_shock_contribution_usd is populated for MTM basis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from config.models import Provenance
from engine.errors import PricingError
from engine.settlement import SettlementCurrency, Venue
from engine.strategy import Strategy
from pricing.black_scholes import price as bs_price
from pricing.inverse import price_inverse_btc
from strategy.payoffs import strategy_pnl
from strategy.repricing import reprice_strategy
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
    """Total MTM (fair value) of all option legs in USD."""
    total = 0.0
    for leg in strategy.legs:
        if leg.option_type is None or leg.strike is None:
            continue
        # Issue 10: do NOT swallow pricing exceptions to 0.0.
        if leg.settlement is not None and leg.settlement.venue == Venue.DERIBIT \
                and leg.settlement.settlement_currency == SettlementCurrency.BTC:
            price_btc = price_inverse_btc(spot, leg.strike, risk_free_rate, iv, time_to_expiry, leg.option_type)
            price = price_btc * spot
        else:
            price = bs_price(spot, leg.strike, risk_free_rate, iv, time_to_expiry, leg.option_type)
        if price != price:  # NaN guard
            raise PricingError(f"non-finite MTM for leg {leg.instrument} at spot={spot}, iv={iv}")
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


def apply_scenario(
    strategy: Strategy,
    scenario: Scenario,
    valuation_basis: Literal["expiry_settlement", "mtm_revaluation"] = "expiry_settlement",
) -> dict[str, Any]:
    """Apply one scenario using a SINGLE valuation basis (FRF-006 / AT-006).

    Two explicit bases (Issue 10):
      - expiry_settlement: P&L is the settlement payoff at scenario end-spot.
        vol_shock_contribution_usd = 0.0 (vol only matters via premium repricing).
      - mtm_revaluation: P&L = MTM at end - MTM at start. vol_shock_contribution
        = (MTM at end_spot/end_vol) - (MTM at end_spot/start_vol). The two bases
        are NOT combined.

    Premiums are repriced at the scenario's START context (FRF-005) so the
    settlement-payoff basis reflects fair premiums, never the static builder
    placeholder. max_adverse_excursion is the worst SIGNED loss.
    Pricing exceptions are not swallowed to 0.
    """
    notional = _get_strategy_notional(strategy)
    repriced = reprice_strategy(strategy, scenario.start_spot, scenario.start_vol)

    if valuation_basis == "mtm_revaluation":
        _mtm_start = _mtm_option_value(repriced, scenario.start_spot, scenario.start_vol)
        _mtm_end = _mtm_option_value(repriced, scenario.end_spot, scenario.end_vol)
        # Vol shock contribution: MTM change from vol change alone (same spot, different vol)
        _mtm_end_spot_only = _mtm_option_value(repriced, scenario.end_spot, scenario.start_vol)
        vol_shock_contrib = _mtm_end - _mtm_end_spot_only

        # Spot P&L from underlying holdings
        spot_pnl = 0.0
        for leg in repriced.legs:
            if leg.product == "spot" and leg.side == "LONG":
                spot_pnl += leg.quantity * (scenario.end_spot - scenario.start_spot)
            elif leg.product == "spot" and leg.side == "SHORT":
                spot_pnl -= leg.quantity * (scenario.end_spot - scenario.start_spot)

        pnl = _mtm_end - _mtm_start + spot_pnl

        # Worst signed excursion over path
        if scenario.path is not None and len(scenario.path) > 0:
            worst = float("inf")
            for s in scenario.path:
                spot_mtm_s = _mtm_option_value(repriced, float(s), scenario.start_vol)
                spot_pnl_s = 0.0
                for leg in repriced.legs:
                    if leg.product == "spot" and leg.side == "LONG":
                        spot_pnl_s += leg.quantity * (float(s) - scenario.start_spot)
                    elif leg.product == "spot" and leg.side == "SHORT":
                        spot_pnl_s -= leg.quantity * (float(s) - scenario.start_spot)
                worst = min(worst, spot_mtm_s - _mtm_start + spot_pnl_s)
        else:
            worst = pnl
        adverse = min(0.0, worst)

        premium_contrib = sum(
            abs(leg.entry_premium) * leg.quantity
            for leg in repriced.legs if leg.option_type is not None
        )

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
            "vol_shock_contribution_usd": vol_shock_contrib,
            "expiry_pnl_component_usd": pnl,
            "valuation_basis": "mtm_revaluation",
            "premium_contribution_pct": (premium_contrib / notional) * 100.0,
            "itm_on_scenario": _is_itm(strategy, scenario.end_spot),
            "max_adverse_excursion_usd": adverse,
            "max_adverse_excursion_pct": (adverse / notional) * 100.0,
            "venue_settlement_applied": False,
            "mtm_start_usd": _mtm_start,
            "mtm_end_usd": _mtm_end,
            "provenance": Provenance.CALCULATED,
        }

    # Default: expiry_settlement (single valuation basis)
    pnl = strategy_pnl(repriced, scenario.end_spot)
    premium_contrib = sum(
        abs(leg.entry_premium) * leg.quantity
        for leg in repriced.legs if leg.option_type is not None
    )

    # worst signed loss over the (optional) intra-scenario path, else the shock.
    if scenario.path is not None and len(scenario.path) > 0:
        worst_signed = min(strategy_pnl(repriced, float(s)) for s in scenario.path)
    else:
        worst_signed = pnl
    adverse = min(0.0, worst_signed)

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
        "vol_shock_contribution_usd": 0.0,
        "expiry_pnl_component_usd": pnl,
        "valuation_basis": "expiry_settlement",
        "premium_contribution_pct": (premium_contrib / notional) * 100.0,
        "itm_on_scenario": _is_itm(strategy, scenario.end_spot),
        "max_adverse_excursion_usd": adverse,
        "max_adverse_excursion_pct": (adverse / notional) * 100.0,
        "venue_settlement_applied": True,
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
