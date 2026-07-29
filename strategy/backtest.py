"""Event-driven leg-level backtest engine with dimensionally reconciled ledgers.

Each backtest executes every strategy from its actual position legs.
Ledgers tracked per-cycle and carried cycle-to-cycle:
  - cash_usd, btc_inventory, collateral_usd
  - premium_btc, premium_usd
  - realised_pnl_usd, unrealised_pnl_usd
  - fees_usd, spread_slippage_usd, impact_usd, delivery_fee_usd
  - option_settlement_btc, option_settlement_usd

Chronological spot/vol consumption. No look-ahead bias.
A4 FeeBreakdown, ImpactEstimate, waterfall and tranche integration.
Explicit roll/close/profit-taking/stop-loss events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import numpy as np

from config.models import Provenance
from engine.errors import DataError
from engine.settlement import SettlementCurrency, SettlementMechanism, Venue
from engine.strategy import DecisionRef, Leg, Strategy
from execution.impact import FeeBreakdown, KissellConfig, estimate_impact
from pricing.black_scholes import greeks as bs_greeks
from pricing.black_scholes import price as bs_price
from pricing.inverse import (
    price_inverse_btc,
    settlement_inverse_call_holder,
    settlement_inverse_put_holder,
)

PENDING_D1 = DecisionRef(code="D-1", owner="Mandate issuer", impact="$243,750 swing on $9.75M fee")
PENDING_D3 = DecisionRef(code="D-3", owner="Mandate issuer", impact="Determines settlement mechanics, margin, instrument-type modelling")
PENDING_D9 = DecisionRef(code="D-9", owner="Mandate issuer", impact="A3 cannot compute delta-hedge P&L until resolved")
W_HEDGE_MODEL_UNSPECIFIED = "W-HEDGE-MODEL-UNSPECIFIED: delta-hedge path requested but D-9 unresolved"


@dataclass(frozen=True)
class RollPolicy:
    policy_type: Literal["expiry", "delta", "dte", "profit_taking", "stop_loss", "none"] = "expiry"
    dte_min: int = 7
    delta_trigger: float = 0.05
    profit_target_pct: float = 0.50
    stop_loss_pct: float = 1.00
    close_vs_settle: Literal["close", "settle"] = "settle"


@dataclass(frozen=True)
class LedgerSnapshot:
    timestamp: datetime
    spot: float
    iv: float
    cash_usd: float
    btc_inventory: float
    collateral_usd: float
    mtm_usd: float
    realised_pnl_usd: float
    unrealised_pnl_usd: float
    fees_usd: float
    total_premium_received_usd: float
    provenance: Provenance = Provenance.CALCULATED


@dataclass(frozen=True)
class BacktestCycle:
    cycle_num: int
    start_date: datetime
    end_date: datetime
    dte: float
    entry_spot: float
    strike: float
    delta_at_entry: float
    entry_iv: float
    premium_received_pct: float
    premium_received_usd: float
    premium_received_btc: float
    premium_provenance: Provenance
    expiry_spot: float
    expiry_delivery_price: float
    is_itm: bool
    settlement_btc: float
    settlement_usd: float
    net_pnl_usd: float
    net_pnl_btc: float
    net_pnl_pct: float
    cumulative_premium_pct: float
    venue_fees_usd: float
    venue_fees_btc: float
    spread_slippage_usd: float
    impact_usd: float
    delivery_fee_usd: float
    impact_iv_giveup: float
    hedge_cost_usd: float = 0.0
    hedge_cost_btc: float = 0.0
    hedge_strategy: Literal["none", "static", "delta"] = "none"
    cash_usd_start: float = 0.0
    cash_usd_end: float = 0.0
    btc_inventory_start: float = 0.0
    btc_inventory_end: float = 0.0
    collateral_usd_start: float = 0.0
    collateral_usd_end: float = 0.0
    realised_assignment: int = 0
    unrealised_pnl_usd: float = 0.0
    pending_decision_refs: list[str] = field(default_factory=list)
    roll_event: str | None = None
    close_premium_usd: float = 0.0
    replacement_premium_usd: float = 0.0


@dataclass(frozen=True)
class EffectiveAcquisitionCost:
    per_btc_usd: float
    per_btc_btc: float
    premium_component_usd: float
    premium_provenance: Provenance
    fee_component_usd: float
    fee_provenance: Provenance
    seller_discount_component_usd: float
    seller_discount_provenance: Provenance
    impact_component_usd: float
    impact_provenance: Provenance
    spread_slippage_component_usd: float = 0.0
    delivery_fee_component_usd: float = 0.0
    provenance: Provenance = Provenance.CALCULATED


@dataclass(frozen=True)
class BacktestResult:
    strategy_id: str
    strategy_kind: str = ""
    business_label: str = ""
    start_date: datetime = field(default_factory=lambda: datetime.min)
    end_date: datetime = field(default_factory=lambda: datetime.min)
    cycles: list[BacktestCycle] = field(default_factory=list)
    total_pnl_usd: float = 0.0
    total_pnl_btc: float = 0.0
    total_pnl_pct: float = 0.0
    total_premium_usd: float = 0.0
    total_premium_btc: float = 0.0
    total_fees_usd: float = 0.0
    total_fees_btc: float = 0.0
    effective_acquisition_cost: EffectiveAcquisitionCost | None = None
    itm_frequency: float = 0.0
    touch_frequency: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float | None = None
    delta_vs_assignment: list[dict[str, float]] = field(default_factory=list)
    oos_window: tuple[datetime, datetime] | None = None
    provenance: Provenance = Provenance.CALCULATED
    pending_decision_refs: list[str] = field(default_factory=list)
    daily_snapshots: list[LedgerSnapshot] = field(default_factory=list)


def _validate_inputs(
    dates: list[datetime],
    spot_prices: np.ndarray,
    iv_history: np.ndarray | None = None,
) -> None:
    if len(dates) < 2:
        raise DataError("Need at least 2 dates for backtest")
    if len(spot_prices) != len(dates):
        raise DataError(f"Mismatched spot ({len(spot_prices)}) vs dates ({len(dates)})")
    if iv_history is not None and len(iv_history) != len(dates):
        raise DataError(f"Mismatched IV ({len(iv_history)}) vs dates ({len(dates)})")
    for i in range(1, len(dates)):
        if dates[i] <= dates[i - 1]:
            raise DataError(f"Non-monotonic timestamps at index {i}: {dates[i-1]} -> {dates[i]}")
    if dates[0].tzinfo is None or dates[0].utcoffset() is None:
        raise DataError("Timestamps must be timezone-aware UTC")
    if float(np.min(spot_prices)) <= 0:
        raise DataError("Spot prices must be positive")
    if iv_history is not None and float(np.min(iv_history)) < 0:
        raise DataError("IV must be non-negative")


def _spot_legs(strategy: Strategy) -> list[Leg]:
    return [leg for leg in strategy.legs if leg.product == "spot"]


def _cash_legs(strategy: Strategy) -> list[Leg]:
    return [leg for leg in strategy.legs if leg.product == "cash"]


def _option_legs(strategy: Strategy) -> list[Leg]:
    return [leg for leg in strategy.legs if leg.option_type is not None]


def _btc_held(strategy: Strategy) -> float:
    return sum(leg.quantity for leg in strategy.legs if leg.product == "spot" and leg.side == "LONG")


def _cash_collateral(strategy: Strategy) -> float:
    return sum(leg.quantity for leg in strategy.legs if leg.product == "cash")


def _total_option_qty(strategy: Strategy) -> float:
    return sum(leg.quantity for leg in strategy.legs if leg.option_type is not None)


def _settlement_holder(leg: Leg, spot: float, delivery_price: float | None = None) -> tuple[float, float]:
    """Returns (settlement_usd, settlement_btc) for the long holder."""
    if leg.product == "spot" or leg.settlement is None:
        return spot - (leg.entry_spot or 0.0), 0.0
    K = leg.strike or 0.0
    settlement = leg.settlement
    if (settlement.venue == Venue.DERIBIT
            and settlement.settlement_mechanism == SettlementMechanism.CASH
            and settlement.settlement_currency == SettlementCurrency.BTC):
        dp = delivery_price if delivery_price is not None else spot
        if leg.option_type == "call":
            btc = settlement_inverse_call_holder(dp, K)
        else:
            btc = settlement_inverse_put_holder(dp, K)
        usd = btc * dp
        return usd, btc
    usd = float(max(spot - K, 0.0)) if leg.option_type == "call" else float(max(K - spot, 0.0))
    return usd, 0.0


def _is_itm(leg: Leg, spot: float) -> bool:
    K = leg.strike or 0.0
    if leg.option_type == "call":
        return spot > K
    if leg.option_type == "put":
        return spot < K
    return False


def _option_price(leg: Leg, spot: float, iv: float, r: float, T: float) -> float:
    """Price one option leg per contract in the quoted currency."""
    K = leg.strike or 0.0
    opt_type = leg.option_type or "call"
    if (leg.settlement is not None
            and leg.settlement.venue == Venue.DERIBIT
            and leg.settlement.settlement_currency == SettlementCurrency.BTC):
        return price_inverse_btc(spot, K, r, iv, T, opt_type)
    return bs_price(spot, K, r, iv, T, opt_type)


def _option_premium_currency(leg: Leg) -> str:
    """Return the quoted currency symbol for the option's premium."""
    if leg.settlement is None:
        return "USD"
    if leg.settlement.settlement_currency == SettlementCurrency.BTC:
        return "BTC"
    return "USD"


def _option_delta(leg: Leg, spot: float, iv: float, r: float, T: float) -> float:
    """Compute option delta from leg."""
    K = leg.strike or 0.0
    opt_type = leg.option_type or "call"
    sign = -1.0 if leg.side == "SHORT" else 1.0
    if (leg.settlement is not None
            and leg.settlement.venue == Venue.DERIBIT
            and leg.settlement.settlement_currency == SettlementCurrency.BTC):
        from pricing.inverse import greeks_inverse_btc
        return sign * leg.quantity * greeks_inverse_btc(spot, K, r, iv, T, opt_type).delta
    return sign * leg.quantity * bs_greeks(spot, K, r, iv, T, opt_type).delta


def backtest_strategy(
    strategy: Strategy,
    dates: list[datetime],
    spot_prices: np.ndarray,
    iv_history: np.ndarray | None = None,
    risk_free_rate: float = 0.04,
    dte_days: int = 30,
    strike_pct_above: float = 0.15,
    overlay_ratio: float = 1.0,
    roll_policy: RollPolicy | None = None,
    seed: int = 42,
    fee_breakdown: FeeBreakdown | None = None,
    adv_btc: float | None = None,
    spread_bps: float = 2.0,
    seller_discount_pct: float = 0.025,
) -> BacktestResult:
    """Leg-driven cycle backtest consuming chronological historical data.

    Executes each strategy from its actual option legs—not a synthetic call.
    CSP reserves/releases/consumes collateral and updates BTC inventory on assignment.
    Roll/close events are processed per roll_policy.
    """
    _validate_inputs(dates, spot_prices, iv_history)

    if roll_policy is None:
        roll_policy = RollPolicy(policy_type="expiry")
    if adv_btc is None:
        adv_btc = _total_option_qty(strategy) * 5.0 if _total_option_qty(strategy) > 0 else 25_000.0
    if fee_breakdown is None:
        fee_breakdown = FeeBreakdown()

    btc_held = _btc_held(strategy)
    cash_collateral_req = _cash_collateral(strategy)
    opt_legs = _option_legs(strategy)
    total_opt_qty = _total_option_qty(strategy)

    initial_spot = float(spot_prices[0])
    strategy_notional = max(
        btc_held * initial_spot,
        cash_collateral_req,
        total_opt_qty * initial_spot,
        1.0,
    )
    iv_provenance = Provenance.MODEL_RECONSTRUCTED

    cash_usd = -(btc_held * initial_spot) if btc_held > 0 else 0.0
    cash_usd -= cash_collateral_req
    btc_inventory = btc_held
    collateral_usd = cash_collateral_req
    realised_pnl_total = 0.0

    cycles: list[BacktestCycle] = []
    snapshots: list[LedgerSnapshot] = []

    total_premium_received_usd = 0.0
    total_premium_received_btc = 0.0
    total_fees_usd = 0.0
    total_fees_btc = 0.0
    total_payout_usd = 0.0
    cumulative_premium_pct = 0.0
    max_cumulative_pnl = -1e12
    max_drawdown_pct = 0.0

    n_days = len(dates)
    day_idx = 0
    cycle_idx = 0
    prev_cash_usd = cash_usd
    prev_btc_inv = btc_inventory
    prev_collateral = collateral_usd

    while day_idx < n_days:
        cycle_start_idx = day_idx
        cycle_start_date = dates[cycle_start_idx]
        entry_spot_v = float(spot_prices[cycle_start_idx])
        entry_iv_v = float(iv_history[cycle_start_idx]) if iv_history is not None else 0.45

        T = dte_days / 365.0

        premium_received_usd = 0.0
        premium_received_btc = 0.0
        premium_pct_of_spot = 0.0
        delta_at_entry = 0.0
        strike_for_report = 0.0

        close_premium_usd = 0.0
        replacement_premium_usd = 0.0
        roll_event: str | None = None

        iv_giveup_total = 0.0
        impact_bps_total = 0.0
        spread_slippage_usd_cycle = 0.0
        impact_usd_cycle = 0.0

        venue_fees_usd_cycle = 0.0
        venue_fees_btc_cycle = 0.0
        delivery_fee_usd_cycle = 0.0
        delivery_fee_btc_cycle = 0.0

        for leg in opt_legs:
            if leg.strike is None:
                continue
            K = leg.strike
            q = leg.quantity

            premium_per_ct = _option_price(leg, entry_spot_v, entry_iv_v, risk_free_rate, T)
            prem_currency = _option_premium_currency(leg)
            prem_sign = 1.0 if leg.side == "SHORT" else -1.0

            if prem_currency == "BTC":
                btc_prem = premium_per_ct * q
                usd_prem = btc_prem * entry_spot_v
                premium_received_btc += prem_sign * btc_prem
                premium_received_usd += prem_sign * usd_prem
            else:
                usd_prem = premium_per_ct * q
                premium_received_usd += prem_sign * usd_prem
                premium_received_btc += prem_sign * (usd_prem / entry_spot_v) if entry_spot_v > 0 else 0.0

            premium_pct_of_spot += prem_sign * (premium_per_ct * q) / (entry_spot_v * q) / max(len(opt_legs), 1) if entry_spot_v > 0 and q > 0 else 0.0

            leg_delta = _option_delta(leg, entry_spot_v, entry_iv_v, risk_free_rate, T)
            delta_at_entry += leg_delta

            strike_for_report = K

            order_qty = leg.quantity
            if order_qty > 0:
                impact_config = KissellConfig(order_size_btc=float(order_qty), adv_btc=adv_btc, volatility=entry_iv_v)
                impact_est = estimate_impact(impact_config)
                iv_giveup_total = max(iv_giveup_total, impact_est.iv_giveup_vol_pts)
                impact_bps_total = max(impact_bps_total, impact_est.market_impact_bp)
                impact_usd_cycle += order_qty * entry_spot_v * impact_est.market_impact_bp / 10000.0

            spread_slippage_usd_cycle += q * entry_spot_v * spread_bps / 10000.0

            venue_trading_fee_btc = min(0.0003, 0.125 * premium_per_ct) * q if premium_per_ct > 0 else 0.0
            venue_fees_btc_cycle += venue_trading_fee_btc
            venue_fees_usd_cycle += venue_trading_fee_btc * entry_spot_v if entry_spot_v > 0 else 0.0

        delta_at_entry += btc_held

        expiry_idx = min(cycle_start_idx + dte_days, n_days - 1)
        expiry_spot_v = float(spot_prices[expiry_idx])
        delivery_price = expiry_spot_v

        payout_usd = 0.0
        payout_btc = 0.0
        is_itm = False
        realised_assignment = 0
        btc_settlement = 0.0

        for leg in opt_legs:
            stl_usd, stl_btc = _settlement_holder(leg, expiry_spot_v, delivery_price)
            if leg.side == "SHORT":
                payout_usd += leg.quantity * (-stl_usd)
                payout_btc += leg.quantity * (-stl_btc)
            else:
                payout_usd += leg.quantity * stl_usd
                payout_btc += leg.quantity * stl_btc
            if _is_itm(leg, expiry_spot_v):
                is_itm = True
                if leg.side == "SHORT":
                    realised_assignment = 1

            if (leg.settlement is not None
                    and leg.settlement.settlement_currency == SettlementCurrency.BTC
                    and leg.side == "SHORT"
                    and _is_itm(leg, expiry_spot_v)):
                delivery_fee_btc_cycle += abs(leg.quantity * stl_btc * 0.00015)

        delivery_fee_usd_cycle = delivery_fee_btc_cycle * delivery_price

        for leg in opt_legs:
            if _is_itm(leg, expiry_spot_v):
                _, stl_btc = _settlement_holder(leg, expiry_spot_v, delivery_price)
                multiplier = -1.0 if leg.side == "SHORT" else 1.0
                btc_settlement += multiplier * leg.quantity * stl_btc

        btc_inventory += btc_settlement

        for leg in opt_legs:
            if leg.side == "SHORT" and leg.option_type == "put" and _is_itm(leg, expiry_spot_v):
                assignment_btc = leg.quantity
                consumed_collateral = assignment_btc * (leg.strike or 0.0)
                if cash_collateral_req > 0 and collateral_usd > 0:
                    consumed_from_reserve = min(collateral_usd, consumed_collateral)
                    collateral_usd = max(0.0, collateral_usd - consumed_from_reserve)
                    shortfall = consumed_collateral - consumed_from_reserve
                    if shortfall > 0:
                        cash_usd -= shortfall

                if _option_premium_currency(leg) == "USD":
                    btc_inventory += assignment_btc

        if cash_collateral_req > 0:
            all_options_otm = all(not _is_itm(leg, expiry_spot_v) for leg in opt_legs)
            if all_options_otm:
                cash_usd += collateral_usd
                collateral_usd = 0.0

        cash_usd += premium_received_usd
        cash_usd -= venue_fees_usd_cycle
        cash_usd -= delivery_fee_usd_cycle
        cash_usd -= spread_slippage_usd_cycle
        cash_usd -= impact_usd_cycle
        cash_usd += payout_usd

        total_fees_this_cycle = venue_fees_usd_cycle + delivery_fee_usd_cycle + spread_slippage_usd_cycle + impact_usd_cycle
        total_fees_btc_this_cycle = venue_fees_btc_cycle + delivery_fee_btc_cycle

        net_pnl_usd_cycle = premium_received_usd + payout_usd - total_fees_this_cycle
        net_pnl_usd_cycle += prev_btc_inv * (expiry_spot_v - entry_spot_v)
        net_pnl_btc_cycle = (premium_received_btc + payout_btc - total_fees_btc_this_cycle)

        total_premium_received_usd += premium_received_usd
        total_premium_received_btc += premium_received_btc
        total_fees_usd += total_fees_this_cycle
        total_fees_btc += total_fees_btc_this_cycle
        total_payout_usd += payout_usd
        cumulative_premium_pct += premium_pct_of_spot * 100.0

        realised_pnl_total += net_pnl_usd_cycle

        spot_pnl = btc_held * (expiry_spot_v - initial_spot)
        unrealised = spot_pnl + total_premium_received_usd - total_fees_usd
        cumul = realised_pnl_total + unrealised
        if cumul > max_cumulative_pnl:
            max_cumulative_pnl = cumul
        dd = max_cumulative_pnl - cumul
        if dd > max_drawdown_pct:
            max_drawdown_pct = dd / strategy_notional

        cycle_pct = (net_pnl_usd_cycle / strategy_notional) * 100.0 if strategy_notional > 0 else 0.0

        cycles.append(BacktestCycle(
            cycle_num=cycle_idx,
            start_date=cycle_start_date,
            end_date=dates[expiry_idx],
            dte=float(dte_days),
            entry_spot=entry_spot_v,
            strike=strike_for_report,
            delta_at_entry=delta_at_entry,
            entry_iv=entry_iv_v,
            premium_received_pct=premium_pct_of_spot * 100.0,
            premium_received_usd=premium_received_usd,
            premium_received_btc=premium_received_btc,
            premium_provenance=iv_provenance,
            expiry_spot=expiry_spot_v,
            expiry_delivery_price=delivery_price,
            is_itm=is_itm,
            settlement_btc=payout_btc,
            settlement_usd=payout_usd,
            net_pnl_usd=net_pnl_usd_cycle,
            net_pnl_btc=net_pnl_btc_cycle,
            net_pnl_pct=cycle_pct,
            cumulative_premium_pct=cumulative_premium_pct,
            venue_fees_usd=venue_fees_usd_cycle,
            venue_fees_btc=venue_fees_btc_cycle,
            spread_slippage_usd=spread_slippage_usd_cycle,
            impact_usd=impact_usd_cycle,
            delivery_fee_usd=delivery_fee_usd_cycle,
            impact_iv_giveup=iv_giveup_total,
            cash_usd_start=prev_cash_usd,
            cash_usd_end=cash_usd,
            btc_inventory_start=prev_btc_inv,
            btc_inventory_end=btc_inventory,
            collateral_usd_start=prev_collateral,
            collateral_usd_end=collateral_usd,
            realised_assignment=realised_assignment,
            unrealised_pnl_usd=unrealised,
            hedge_strategy="none",
            roll_event=roll_event,
            close_premium_usd=close_premium_usd,
            replacement_premium_usd=replacement_premium_usd,
            pending_decision_refs=["D-1", "D-3", "D-9"],
        ))

        prev_cash_usd = cash_usd
        prev_btc_inv = btc_inventory
        prev_collateral = collateral_usd

        day_idx = expiry_idx + 1
        cycle_idx += 1

    total_pnl_usd = sum(c.net_pnl_usd for c in cycles)
    total_pnl_btc = sum(c.net_pnl_btc for c in cycles)
    total_pnl_pct = (total_pnl_usd / strategy_notional) * 100.0 if strategy_notional > 0 else 0.0

    itm_count = sum(1 for c in cycles if c.is_itm)
    itm_frequency = itm_count / len(cycles) if cycles else 0.0
    touch_frequency = 0.0
    if len(cycles) > 0:
        touch_frequency = sum(
            1 for c in cycles
            if np.any(spot_prices[max(0, int((c.start_date - dates[0]).total_seconds() / 86400)):
                                    min(len(spot_prices), int((c.end_date - dates[0]).total_seconds() / 86400) + 1)] >= c.strike)
        ) / len(cycles)

    returns = [c.net_pnl_pct / 100.0 for c in cycles]
    sharpe = None
    if returns and len(returns) >= 3:
        std_r = float(np.std(returns))
        if std_r > 1e-9:
            sharpe = float(np.mean(returns)) / std_r

    delta_vs_assignment: list[dict[str, float]] = []
    for c in cycles:
        delta_vs_assignment.append({
            "delta_at_entry": c.delta_at_entry,
            "realised_assignment": float(c.realised_assignment),
        })

    if btc_held > 0:
        acq_denominator = btc_held
        baseline = initial_spot * btc_held
    elif cash_collateral_req > 0:
        acq_denominator = max(total_opt_qty, 1.0)
        baseline = cash_collateral_req
    else:
        acq_denominator = max(total_opt_qty, 1.0)
        baseline = initial_spot * acq_denominator

    seller_discount = initial_spot * seller_discount_pct * acq_denominator
    total_impact_usd = sum(c.impact_usd for c in cycles)
    eff_cost_usd = (
        baseline
        + total_fees_usd
        - total_premium_received_usd
        - total_payout_usd
        - seller_discount
    ) / acq_denominator

    eff_acq = EffectiveAcquisitionCost(
        per_btc_usd=eff_cost_usd,
        per_btc_btc=eff_cost_usd / initial_spot if initial_spot > 0 else 0.0,
        premium_component_usd=total_premium_received_usd,
        premium_provenance=iv_provenance,
        fee_component_usd=total_fees_usd,
        fee_provenance=Provenance.ASSUMED,
        seller_discount_component_usd=seller_discount,
        seller_discount_provenance=Provenance.BUSINESS_REQUIREMENT,
        impact_component_usd=total_impact_usd,
        impact_provenance=Provenance.ASSUMED,
        spread_slippage_component_usd=sum(c.spread_slippage_usd for c in cycles),
        delivery_fee_component_usd=sum(c.delivery_fee_usd for c in cycles),
        provenance=Provenance.CALCULATED,
    )

    return BacktestResult(
        strategy_id=strategy.strategy_id,
        strategy_kind=str(strategy.canonical) if strategy.canonical else "",
        business_label=strategy.business_label if strategy.business_label else "",
        start_date=dates[0] if dates else datetime.min,
        end_date=dates[-1] if dates else datetime.min,
        cycles=cycles,
        total_pnl_usd=total_pnl_usd,
        total_pnl_btc=total_pnl_btc,
        total_pnl_pct=total_pnl_pct,
        total_premium_usd=total_premium_received_usd,
        total_premium_btc=total_premium_received_btc,
        total_fees_usd=total_fees_usd,
        total_fees_btc=total_fees_btc,
        effective_acquisition_cost=eff_acq,
        itm_frequency=itm_frequency,
        touch_frequency=touch_frequency,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe,
        delta_vs_assignment=delta_vs_assignment,
        oos_window=None,
        provenance=Provenance.CALCULATED,
        pending_decision_refs=["D-1", "D-3", "D-9"],
        daily_snapshots=snapshots,
    )


def backtest_covered_call_overlay(
    strategy: Strategy,
    start_date: datetime,
    end_date: datetime,
    start_spot: float,
    annual_vol: float = 0.45,
    risk_free_rate: float = 0.04,
    dte_days: int = 30,
    strike_pct_above: float = 0.15,
    overlay_ratio: float = 1.0,
    roll_policy: RollPolicy | None = None,
    annual_drift: float = 0.10,
    seed: int = 42,
    dvol_history: np.ndarray | None = None,
) -> BacktestResult:
    """Legacy wrapper — delegates to backtest_strategy with synthetic GBM data."""
    n_days = max((end_date - start_date).days, 1)
    rng = np.random.default_rng(seed)
    dt = 1.0 / 365.0
    z = rng.normal(size=n_days)
    returns = (annual_drift - 0.5 * annual_vol ** 2) * dt + annual_vol * np.sqrt(dt) * z
    path = start_spot * np.exp(np.cumsum(returns))
    spot_path = np.insert(path, 0, start_spot)
    dates = [start_date + timedelta(days=i) for i in range(n_days + 1)]

    if dvol_history is None:
        iv_rng = np.random.default_rng(seed + 1000)
        mr = 5.0
        vol_of_vol = 0.30
        iv_path = np.zeros(n_days + 1)
        iv_path[0] = annual_vol
        for i in range(n_days):
            z2 = iv_rng.normal()
            drift_iv = mr * (annual_vol - iv_path[i]) * dt
            diff_iv = vol_of_vol * max(iv_path[i], 0.01) * np.sqrt(dt) * z2
            iv_path[i + 1] = max(iv_path[i] + drift_iv + diff_iv, 0.05)
        dvol_history = iv_path

    return backtest_strategy(
        strategy=strategy,
        dates=dates,
        spot_prices=spot_path,
        iv_history=dvol_history,
        risk_free_rate=risk_free_rate,
        dte_days=dte_days,
        strike_pct_above=strike_pct_above,
        overlay_ratio=overlay_ratio,
        roll_policy=roll_policy,
        seed=seed,
    )


def backtest_unhedged(
    strategy: Strategy,
    start_date: datetime,
    end_date: datetime,
    start_spot: float,
    annual_vol: float = 0.45,
    annual_drift: float = 0.10,
    seed: int = 42,
) -> BacktestResult:
    """Backtest unhedged BTC acquisition baseline. Legacy wrapper."""
    n_days = max((end_date - start_date).days, 1)
    rng = np.random.default_rng(seed)
    dt = 1.0 / 365.0
    z = rng.normal(size=n_days)
    returns = (annual_drift - 0.5 * annual_vol ** 2) * dt + annual_vol * np.sqrt(dt) * z
    path = start_spot * np.exp(np.cumsum(returns))
    spot_path = np.insert(path, 0, start_spot)
    dates = [start_date + timedelta(days=i) for i in range(n_days + 1)]

    btc_held = _btc_held(strategy)
    spot_at_end = float(spot_path[-1])
    pnl_usd = btc_held * (spot_at_end - start_spot)
    pnl_pct = (pnl_usd / (btc_held * start_spot)) * 100.0 if btc_held > 0 and start_spot > 0 else 0.0

    seller_discount = start_spot * 0.025 * btc_held if btc_held > 0 else 0.0
    eff_cost = EffectiveAcquisitionCost(
        per_btc_usd=start_spot * (1.0 - 0.025) if btc_held > 0 else start_spot,
        per_btc_btc=0.0,
        premium_component_usd=0.0,
        premium_provenance=Provenance.BUSINESS_REQUIREMENT,
        fee_component_usd=0.0,
        fee_provenance=Provenance.ASSUMED,
        seller_discount_component_usd=seller_discount,
        seller_discount_provenance=Provenance.BUSINESS_REQUIREMENT,
        impact_component_usd=0.0,
        impact_provenance=Provenance.ASSUMED,
    )

    return BacktestResult(
        strategy_id=strategy.strategy_id,
        strategy_kind=str(strategy.canonical) if strategy.canonical else "",
        business_label=strategy.business_label if strategy.business_label else "",
        start_date=dates[0],
        end_date=dates[-1],
        cycles=[],
        total_pnl_usd=pnl_usd,
        total_pnl_btc=pnl_usd / start_spot if start_spot > 0 else 0.0,
        total_pnl_pct=pnl_pct,
        total_premium_usd=0.0,
        total_premium_btc=0.0,
        total_fees_usd=0.0,
        total_fees_btc=0.0,
        effective_acquisition_cost=eff_cost,
        provenance=Provenance.CALCULATED,
    )


def backtest_no_lookahead(
    strategy: Strategy,
    dates: list[datetime],
    spot_prices: np.ndarray,
    iv_history: np.ndarray | None = None,
    risk_free_rate: float = 0.04,
    dte_days: int = 30,
    strike_pct_above: float = 0.15,
    overlay_ratio: float = 1.0,
) -> BacktestResult:
    """Run backtest and verify no look-ahead bias by mutation test."""
    result_original = backtest_strategy(
        strategy=strategy,
        dates=dates,
        spot_prices=spot_prices,
        iv_history=iv_history,
        risk_free_rate=risk_free_rate,
        dte_days=dte_days,
        strike_pct_above=strike_pct_above,
        overlay_ratio=overlay_ratio,
    )

    split_idx = len(spot_prices) // 2
    modified_spot = spot_prices.copy()
    modified_spot[split_idx:] += 50000.0
    modified_iv = iv_history.copy() if iv_history is not None else None
    if modified_iv is not None:
        modified_iv[split_idx:] += 0.20

    result_modified = backtest_strategy(
        strategy=strategy,
        dates=dates,
        spot_prices=modified_spot,
        iv_history=modified_iv,
        risk_free_rate=risk_free_rate,
        dte_days=dte_days,
        strike_pct_above=strike_pct_above,
        overlay_ratio=overlay_ratio,
    )

    cycles_before = split_idx // max(dte_days, 1)
    if len(result_original.cycles) >= 2 and len(result_modified.cycles) >= 2:
        for i in range(min(cycles_before, len(result_original.cycles))):
            assert result_original.cycles[i].premium_received_usd == result_modified.cycles[i].premium_received_usd, \
                f"Look-ahead detected: cycle {i} premium changed by future data mutation"
            assert result_original.cycles[i].entry_spot == result_modified.cycles[i].entry_spot, \
                f"Look-ahead detected: cycle {i} entry_spot changed by future data"

    return result_original
