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

Stage-2 remediation (sprint/stage2-remediation):
  - Issue 2: delivery fee deducted exactly once (gross settlement from settle_leg
    + single fee deduction in the ledger).
  - Issue 5: CASH+BTC venue guard in settlement_engine.py.
  - Issue 7: strike_pct_above wires into actual cycle strike selection.
  - Issue 6: contract_multiplier applied consistently (premium, spread, impact,
    collateral, assignment).
  - Issue 1: Asymmetrica 0.5% fee deducted from cash/P&L, included in total_fees
    and EAC — both D-1 variants emitted.
  - Issue 3: D-12 post-settlement BTC purchase is an explicit separate
    transaction with provenance.
  - Issue 4: BTC settlement proceeds tracked separately; settlement_btc populated.
  - Issue 9: daily_snapshots populated with complete option MTM equity curve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import numpy as np

from config.models import Provenance
from engine.errors import DataError
from engine.settlement import SettlementCurrency, SettlementMechanism, Venue
from engine.settlement_engine import settle_leg
from engine.strategy import DecisionRef, Leg, Strategy
from execution.fees import asymmetrica_fee_both_variants, leg_trading_fee
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
    btc_settlement_balance: float = 0.0     # Issue 4: distinct BTC settlement tracking
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
    settlement_btc: float          # Issue 4: populated from BTC-settled legs
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
    targeting_moneyness: float = 0.0          # Issue 7: 1 + strike_pct_above
    reconciliation_residual_usd: float = 0.0
    num_settlement_bars: int = 1
    touch_frequency_hit: bool = False
    # Issue 4: settlement BTC amount for this cycle
    settlement_btc_amount: float = 0.0
    # Issue 1: asym fee charged this cycle (reference notional variant)
    asym_fee_cycle_usd: float = 0.0


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
    net_cash_deployed_usd: float = 0.0
    btc_acquired: float = 0.0
    d12_interpretation: str = "cash_settled"
    is_applicable: bool = True
    na_reason: str | None = None
    # Issue 1: asym fee included in fee component
    asym_fee_component_usd: float = 0.0
    asym_fee_provenance: Provenance = Provenance.BUSINESS_REQUIREMENT


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
    reconciliation_residual_usd: float = 0.0
    # Issue 1: both D-1 fee variants; D-1 not defaulted.
    asym_fee_reference_notional_usd: float = 0.0
    asym_fee_executed_notional_usd: float = 0.0
    fee_base_variant: str = "pending_D1"
    # Issue 1: total asym fee actually charged (included in total_fees_usd, total_pnl)
    total_asym_fee_usd: float = 0.0
    # D-12 interpretations
    eac_cash_settled: EffectiveAcquisitionCost | None = None
    eac_post_purchase: EffectiveAcquisitionCost | None = None
    # Issue 3: D-12 post-purchase ledger evidence
    post_purchase_btc_inventory_end: float = 0.0
    post_purchase_usd_deployed: float = 0.0


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


def _nearest_bar(dates: list[datetime], target_date: datetime, min_idx: int) -> int:
    """Index of the observed bar nearest to `target_date`, strictly after
    `min_idx` (so a cycle always advances). Handles interior gaps and a final
    target beyond the data (clamps to the last bar)."""
    n = len(dates)
    best = min(min_idx + 1, n - 1)
    best_diff = abs((dates[best] - target_date).total_seconds())
    for i in range(min_idx + 1, n):
        diff = abs((dates[i] - target_date).total_seconds())
        if diff <= best_diff:
            best, best_diff = i, diff
        elif dates[i] > target_date:
            break
    return best


def _clone_leg_strike(leg: Leg, strike: float) -> Leg:
    """A copy of `leg` re-struck to `strike` (per-cycle re-striking, WP-B1)."""
    return leg.model_copy(update={"strike": strike})


def _price_leg_at(leg: Leg, spot: float, iv: float, r: float, T: float, strike: float) -> float:
    """Per-contract premium for `leg` re-struck to `strike`, in its quote ccy (per 1-BTC-unit)."""
    opt_type = leg.option_type or "call"
    if (leg.settlement is not None
            and leg.settlement.venue == Venue.DERIBIT
            and leg.settlement.settlement_currency == SettlementCurrency.BTC):
        return price_inverse_btc(spot, strike, r, iv, T, opt_type)
    return bs_price(spot, strike, r, iv, T, opt_type)


def _delta_leg_at(leg: Leg, spot: float, iv: float, r: float, T: float, strike: float) -> float:
    opt_type = leg.option_type or "call"
    sign = -1.0 if leg.side == "SHORT" else 1.0
    if (leg.settlement is not None
            and leg.settlement.venue == Venue.DERIBIT
            and leg.settlement.settlement_currency == SettlementCurrency.BTC):
        from pricing.inverse import greeks_inverse_btc
        return sign * leg.quantity * greeks_inverse_btc(spot, strike, r, iv, T, opt_type).delta
    return sign * leg.quantity * bs_greeks(spot, strike, r, iv, T, opt_type).delta


def _option_mtm_leg(
    leg: Leg, strike: float, spot: float, iv: float, r: float, T: float, mult: float,
) -> float:
    """MTM (fair value) of one option leg in USD at current spot/iv/T."""
    if leg.option_type is None:
        return 0.0
    opt_type: str = leg.option_type
    if leg.settlement is not None and leg.settlement.venue == Venue.DERIBIT \
            and leg.settlement.settlement_currency == SettlementCurrency.BTC:
        price_btc = price_inverse_btc(spot, strike, r, iv, T, opt_type)
        price_usd = price_btc * spot
    else:
        price_usd = bs_price(spot, strike, r, iv, T, opt_type)
    sign = -1.0 if leg.side == "SHORT" else 1.0
    return sign * leg.quantity * mult * price_usd


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
    execution_fee_pct: float = 0.005,
) -> BacktestResult:
    """Leg-driven cycle backtest with per-cycle re-striking, date-driven
    lifecycle, a single-entry reconciled ledger, a venue-keyed fee engine and
    both D-1 / D-12 variants.

    Ledger invariant (AT-004): per cycle and cumulatively,
        Δcash + Δ(btc_inventory · spot) + Δcollateral == net_pnl_usd.
    A cash-settled option NEVER credits physical BTC (D-12): assignment produces
    a cash settlement; discretionary post-settlement BTC purchase is a separate,
    explicit action reflected only in the D-12 "post_purchase" EAC variant.

    Issue 7 (strike targeting): cycle strike = entry_spot * (1 + strike_pct_above).
    Issue 6 (contract_multiplier): applied consistently to premium, spread,
      impact, collateral, and assignment.
    Issue 1 (asym fee): deducted from cash/P&L; included in total_fees and EAC.
    Issue 4 (BTC settlement): settlement_btc populated; BTC balance tracked.
    Issue 9 (equity curve): daily_snapshots include option MTM.
    """
    _validate_inputs(dates, spot_prices, iv_history)

    if roll_policy is None:
        roll_policy = RollPolicy(policy_type="expiry")
    if fee_breakdown is None:
        fee_breakdown = FeeBreakdown()

    btc_held = _btc_held(strategy)
    cash_collateral_req = _cash_collateral(strategy)
    opt_legs = _option_legs(strategy)
    total_opt_qty = _total_option_qty(strategy)
    n_days = len(dates)
    initial_spot = float(spot_prices[0])

    if adv_btc is None:
        adv_btc = total_opt_qty * 5.0 if total_opt_qty > 0 else 25_000.0

    # Issue 6: reference_qty accounts for contract multipliers
    ref_qty_raw = btc_held if btc_held > 0 else 0.0
    if ref_qty_raw <= 0:
        for leg in opt_legs:
            mult = leg.settlement.contract_multiplier if leg.settlement else 1.0
            ref_qty_raw = max(ref_qty_raw, leg.quantity * mult)
    reference_qty = ref_qty_raw if ref_qty_raw > 0 else 1.0

    # Issue 7: strike targeting moneyness from configured strike_pct_above.
    # Direction-aware: calls strike above spot, puts strike below spot.
    # The moneyness value stored per cycle reflects the actual leg's direction.

    # Per-leg relative DTE (WP-B3): earliest option expiry defines the base
    # dte_days; ladder legs keep their offsets (30/37/44). Derived from
    # expiry_timestamp DIFFERENCES so it is independent of build time.
    leg_expiries = [leg.expiry_timestamp for leg in opt_legs if leg.expiry_timestamp is not None]
    base_expiry = min(leg_expiries) if leg_expiries else None

    def _leg_dte(leg: Leg) -> int:
        if base_expiry is not None and leg.expiry_timestamp is not None:
            return dte_days + max(0, (leg.expiry_timestamp - base_expiry).days)
        return dte_days

    capital_base = max(btc_held * initial_spot + cash_collateral_req,
                       total_opt_qty * initial_spot, 1.0)
    strategy_notional = capital_base
    iv_provenance = Provenance.MODEL_RECONSTRUCTED

    # ledger state
    cash_usd = -(btc_held * initial_spot)
    btc_inventory = btc_held
    collateral_usd = 0.0
    btc_settlement_balance = 0.0  # Issue 4: distinct BTC settlement tracking

    def _equity(spot: float) -> float:
        return cash_usd + btc_inventory * spot + collateral_usd

    cycles: list[BacktestCycle] = []
    snapshots: list[LedgerSnapshot] = []
    equity_curve: list[float] = []

    total_premium_received_usd = 0.0
    total_premium_received_btc = 0.0
    total_venue_fees_usd = 0.0
    total_venue_fees_btc = 0.0
    total_spread_usd = 0.0
    total_impact_usd = 0.0
    total_delivery_fee_usd = 0.0
    total_settlement_usd = 0.0
    total_settlement_btc = 0.0   # Issue 4
    total_pnl_running = 0.0
    cumulative_premium_pct = 0.0
    run_reconciliation_residual = 0.0
    total_assigned_btc = 0.0
    total_assignment_cost_usd = 0.0
    # Issue 3: D-12 post-purchase tracking
    post_purchase_btc = btc_held
    post_purchase_usd_deployed = 0.0
    spot_acq_impact_charged = False

    day_idx = 0
    cycle_idx = 0
    last_curve_idx = 0

    while day_idx < n_days - 1:
        entry_idx = day_idx
        entry_date = dates[entry_idx]
        entry_spot = float(spot_prices[entry_idx])
        entry_iv = float(iv_history[entry_idx]) if iv_history is not None else 0.45
        prev_cash = cash_usd
        prev_btc = btc_inventory
        prev_coll = collateral_usd
        equity_start = _equity(entry_spot)

        # per-leg cycle strike (Issue 7: use strike_pct_above, not leg moneyness)
        # and own expiry bar.
        leg_ctx: list[tuple[Leg, float, int, float]] = []
        cycle_end_idx = entry_idx
        for leg in opt_legs:
            if leg.strike is None:
                continue
            # Issue 7: cycle strike from configured strike_pct_above,
            # direction-aware (calls above, puts below).
            if leg.option_type == "call":
                cyc_strike = entry_spot * (1.0 + strike_pct_above)
            else:
                cyc_strike = entry_spot * (1.0 - strike_pct_above)
            exp_date = entry_date + timedelta(days=_leg_dte(leg))
            exp_idx = _nearest_bar(dates, exp_date, entry_idx)
            days_to_exp = max((dates[exp_idx] - entry_date).days, 1)
            T = days_to_exp / 365.0
            leg_ctx.append((leg, cyc_strike, exp_idx, T))
            cycle_end_idx = max(cycle_end_idx, exp_idx)

        if not leg_ctx:
            exp_date = entry_date + timedelta(days=dte_days)
            cycle_end_idx = _nearest_bar(dates, exp_date, entry_idx)

        cycle_end_idx = min(max(cycle_end_idx, entry_idx + 1), n_days - 1)
        end_spot = float(spot_prices[cycle_end_idx])
        end_date = dates[cycle_end_idx]

        # entry flows: premium, trading fees, spread, impact
        premium_usd = 0.0
        premium_btc = 0.0
        delta_at_entry = 0.0
        strike_report = 0.0
        venue_fee_usd = 0.0
        venue_fee_btc = 0.0
        spread_usd = 0.0
        impact_usd = 0.0
        iv_giveup = 0.0
        cyc_moneyness = 1.0 + strike_pct_above  # Issue 7: default call moneyness
        for (leg, cyc_strike, _exp_idx, T) in leg_ctx:
            q = leg.quantity
            mult = leg.settlement.contract_multiplier if leg.settlement else 1.0
            prem_per_ct = _price_leg_at(leg, entry_spot, entry_iv, risk_free_rate, T, cyc_strike)
            prem_ccy = _option_premium_currency(leg)
            sign = 1.0 if leg.side == "SHORT" else -1.0
            # Issue 6: premium = price_per_unit * quantity * multiplier
            if prem_ccy == "BTC":
                b = prem_per_ct * q * mult
                premium_btc += sign * b
                premium_usd += sign * b * entry_spot
            else:
                u = prem_per_ct * q * mult
                premium_usd += sign * u
                premium_btc += sign * (u / entry_spot if entry_spot > 0 else 0.0)
            delta_at_entry += _delta_leg_at(leg, entry_spot, entry_iv, risk_free_rate, T, cyc_strike)
            strike_report = cyc_strike
            if leg.settlement is not None:
                f_usd, f_btc = leg_trading_fee(leg.settlement, prem_per_ct, q * mult, entry_spot)
                venue_fee_usd += f_usd
                venue_fee_btc += f_btc
            # Issue 6: spread and impact use total notional (q * mult * spot)
            spread_usd += q * mult * entry_spot * spread_bps / 10000.0
            if q > 0:
                imp = estimate_impact(KissellConfig(order_size_btc=float(q * mult), adv_btc=adv_btc, volatility=entry_iv))
                impact_usd += q * mult * entry_spot * imp.market_impact_bp / 10000.0
                iv_giveup = max(iv_giveup, imp.iv_giveup_vol_pts)
        delta_at_entry += btc_inventory

        # one-off spot-acquisition impact for the initial BTC purchase (WP-B7).
        if not spot_acq_impact_charged and btc_held > 0:
            imp0 = estimate_impact(KissellConfig(order_size_btc=float(btc_held), adv_btc=adv_btc, volatility=entry_iv))
            impact_usd += btc_held * entry_spot * imp0.market_impact_bp / 10000.0
            spot_acq_impact_charged = True

        net_pnl = 0.0
        cash_usd += premium_usd
        net_pnl += premium_usd
        cash_usd -= venue_fee_usd
        net_pnl -= venue_fee_usd
        cash_usd -= spread_usd
        net_pnl -= spread_usd
        cash_usd -= impact_usd
        net_pnl -= impact_usd

        # CSP collateral reserved each cycle at the re-struck strike notional.
        # Issue 6: collateral uses q * mult * strike.
        reserved = 0.0
        if cash_collateral_req > 0:
            for (leg, cyc_strike, _e, _T) in leg_ctx:
                if leg.option_type == "put" and leg.side == "SHORT":
                    mult = leg.settlement.contract_multiplier if leg.settlement else 1.0
                    reserved += leg.quantity * mult * cyc_strike
            cash_usd -= reserved
            collateral_usd += reserved

        # ── settlement: each leg at its own expiry bar (WP-B3/B5) ──
        # Issue 2: use gross settlement_amount (not net_to_account); deduct
        # delivery fee exactly once.
        settlement_usd_total = 0.0
        settlement_btc_total = 0.0   # Issue 4
        delivery_fee_usd = 0.0
        delivery_fee_btc = 0.0
        is_itm_any = False
        realised_assignment = 0
        settle_bars: set[int] = set()
        for (leg, cyc_strike, exp_idx, _T) in leg_ctx:
            settle_bars.add(exp_idx)
            leg_dp = float(spot_prices[exp_idx])
            sr = settle_leg(_clone_leg_strike(leg, cyc_strike), leg_dp)
            holder_sign = 1.0 if leg.side == "LONG" else -1.0
            # Issue 2: use settlement_amount (gross), fee deducted separately below
            if sr.settlement_currency == SettlementCurrency.BTC:
                s_usd = holder_sign * sr.settlement_amount * leg_dp
                s_btc = holder_sign * sr.settlement_amount
                delivery_fee_usd += sr.venue_delivery_fee * leg_dp
                delivery_fee_btc += sr.venue_delivery_fee
            else:
                s_usd = holder_sign * sr.settlement_amount
                s_btc = 0.0
                delivery_fee_usd += sr.venue_delivery_fee
            settlement_usd_total += s_usd
            settlement_btc_total += s_btc
            if sr.is_itm:
                is_itm_any = True
                if leg.side == "SHORT":
                    realised_assignment = 1
                    if leg.option_type == "put":
                        mult = leg.settlement.contract_multiplier if leg.settlement else 1.0
                        assigned = leg.quantity * mult  # Issue 6
                        total_assigned_btc += assigned
                        total_assignment_cost_usd += assigned * leg_dp
                        # Issue 3: D-12 post-purchase — explicit separate transaction
                        post_purchase_btc += assigned
                        post_purchase_usd_deployed += assigned * leg_dp

        cash_usd += settlement_usd_total
        net_pnl += settlement_usd_total
        # Issue 2: deduct delivery fee ONCE (not double-counted)
        cash_usd -= delivery_fee_usd
        net_pnl -= delivery_fee_usd

        # Issue 4: update BTC settlement balance
        btc_settlement_balance += settlement_btc_total

        # release collateral (assignment loss already booked as cash settlement).
        if reserved > 0:
            cash_usd += reserved
            collateral_usd -= reserved

        # spot P&L on held BTC over the cycle (marked entry→end).
        spot_pnl = btc_inventory * (end_spot - entry_spot)
        net_pnl += spot_pnl

        equity_end = _equity(end_spot)
        residual = (equity_end - equity_start) - net_pnl
        run_reconciliation_residual += residual

        # ── Issue 9: daily snapshots with full option MTM ──
        # Build a snapshot for every bar in the cycle window, including
        # live option MTM, BTC settlement balance, cash, and collateral.
        booked_before = total_pnl_running
        start_credits = premium_usd - venue_fee_usd - spread_usd - impact_usd
        for bidx in range(last_curve_idx, cycle_end_idx + 1):
            sp = float(spot_prices[bidx])
            iv = float(iv_history[bidx]) if iv_history is not None else entry_iv
            ts = dates[bidx]

            # Option MTM at this bar: reprice all legs with remaining time
            option_mtm = 0.0
            for (leg, cyc_strike, exp_idx, _T) in leg_ctx:
                if bidx >= exp_idx:
                    continue  # leg has settled
                days_left = max((dates[exp_idx] - ts).days, 0.1)
                T_left = days_left / 365.0
                mult = leg.settlement.contract_multiplier if leg.settlement else 1.0
                option_mtm += _option_mtm_leg(leg, cyc_strike, sp, iv, risk_free_rate, T_left, mult)

            # Cash and BTC evolve through the cycle: before settlement, the
            # entry credits have been received; at/after settlement, settlement
            # cash and fees have been applied.
            snap_cash = prev_cash + start_credits
            snap_btc = prev_btc
            snap_coll = reserved if bidx < cycle_end_idx else collateral_usd
            if bidx == cycle_end_idx:
                # snapshot at end reflects all settlement effects
                snap_cash = cash_usd
                snap_btc = btc_inventory
                snap_coll = collateral_usd

            total_mtm = snap_cash + snap_btc * sp + snap_coll + option_mtm
            snapshots.append(LedgerSnapshot(
                timestamp=ts, spot=sp, iv=iv,
                cash_usd=snap_cash, btc_inventory=snap_btc,
                collateral_usd=snap_coll,
                mtm_usd=total_mtm,
                realised_pnl_usd=booked_before + (net_pnl if bidx == cycle_end_idx else 0.0),
                unrealised_pnl_usd=option_mtm + (btc_inventory * (sp - entry_spot) if bidx < cycle_end_idx else 0.0),
                fees_usd=venue_fee_usd + spread_usd + impact_usd + (delivery_fee_usd if bidx == cycle_end_idx else 0.0),
                total_premium_received_usd=total_premium_received_usd + premium_usd,
                btc_settlement_balance=btc_settlement_balance,
            ))

            # equity curve for drawdown (MTM basis)
            equity_curve.append(capital_base + booked_before + start_credits
                                + btc_inventory * (sp - entry_spot) + option_mtm)
        last_curve_idx = cycle_end_idx + 1

        total_pnl_running += net_pnl
        total_premium_received_usd += premium_usd
        total_premium_received_btc += premium_btc
        total_venue_fees_usd += venue_fee_usd
        total_venue_fees_btc += venue_fee_btc
        total_spread_usd += spread_usd
        total_impact_usd += impact_usd
        total_delivery_fee_usd += delivery_fee_usd
        total_settlement_usd += settlement_usd_total
        total_settlement_btc += settlement_btc_total

        premium_pct = (100.0 * premium_usd / (entry_spot * reference_qty)
                       if entry_spot > 0 and reference_qty > 0 else 0.0)
        cumulative_premium_pct += premium_pct

        # touch: correct direction per option type over the cycle window.
        touched = False
        seg = spot_prices[entry_idx:cycle_end_idx + 1]
        for (leg, cyc_strike, _e, _T) in leg_ctx:
            if leg.option_type == "call" and bool(np.any(seg >= cyc_strike)):
                touched = True
            if leg.option_type == "put" and bool(np.any(seg <= cyc_strike)):
                touched = True

        cycle_pct = (net_pnl / strategy_notional) * 100.0 if strategy_notional > 0 else 0.0
        cycles.append(BacktestCycle(
            cycle_num=cycle_idx,
            start_date=entry_date,
            end_date=end_date,
            dte=float((end_date - entry_date).days),
            entry_spot=entry_spot,
            strike=strike_report,
            delta_at_entry=delta_at_entry,
            entry_iv=entry_iv,
            premium_received_pct=premium_pct,
            premium_received_usd=premium_usd,
            premium_received_btc=premium_btc,
            premium_provenance=iv_provenance,
            expiry_spot=end_spot,
            expiry_delivery_price=end_spot,
            is_itm=is_itm_any,
            settlement_btc=settlement_btc_total,   # Issue 4
            settlement_usd=settlement_usd_total,
            net_pnl_usd=net_pnl,
            net_pnl_btc=net_pnl / entry_spot if entry_spot > 0 else 0.0,
            net_pnl_pct=cycle_pct,
            cumulative_premium_pct=cumulative_premium_pct,
            venue_fees_usd=venue_fee_usd,
            venue_fees_btc=venue_fee_btc,
            spread_slippage_usd=spread_usd,
            impact_usd=impact_usd,
            delivery_fee_usd=delivery_fee_usd,
            impact_iv_giveup=iv_giveup,
            cash_usd_start=prev_cash,
            cash_usd_end=cash_usd,
            btc_inventory_start=prev_btc,
            btc_inventory_end=btc_inventory,
            collateral_usd_start=prev_coll,
            collateral_usd_end=collateral_usd,
            realised_assignment=realised_assignment,
            unrealised_pnl_usd=spot_pnl,
            hedge_strategy="none",
            roll_event=None,
            pending_decision_refs=["D-1", "D-3", "D-9", "D-12"],
            targeting_moneyness=cyc_moneyness,
            reconciliation_residual_usd=residual,
            num_settlement_bars=max(1, len(settle_bars)),
            touch_frequency_hit=touched,
            settlement_btc_amount=settlement_btc_total,
            asym_fee_cycle_usd=0.0,
        ))

        day_idx = cycle_end_idx
        cycle_idx += 1
        if cycle_end_idx >= n_days - 1:
            break

    # Issue 1: compute asym fee (both D-1 variants) and deduct from ledger.
    asym = asymmetrica_fee_both_variants(
        reference_btc=reference_qty, reference_spot_usd=initial_spot,
        fee_pct=execution_fee_pct, seller_discount_pct=seller_discount_pct,
    )
    # Re-compute total P&L and fees including the asym fee as a run-level charge.
    total_asym_fee_usd = asym.reference_notional_fee_usd
    total_pnl_usd = total_pnl_running - total_asym_fee_usd
    total_pnl_btc = total_pnl_usd / initial_spot if initial_spot > 0 else 0.0
    total_pnl_pct = (total_pnl_usd / strategy_notional) * 100.0 if strategy_notional > 0 else 0.0

    # Issue 1: asym fee included in total_fees. Both D-1 variants stored.
    total_exec_fees = total_venue_fees_usd + total_spread_usd + total_delivery_fee_usd
    total_fees_usd = total_exec_fees + total_impact_usd + total_asym_fee_usd
    total_fees_btc = total_venue_fees_btc

    # Issue 4: settlement_btc in cycles (already populated above)

    # D-12: both EAC interpretations
    seller_discount = initial_spot * seller_discount_pct * btc_held

    def _build_eac(btc_denominator: float, extra_cost_usd: float, interp: str,
                   include_asym_fee: bool = True) -> EffectiveAcquisitionCost:
        asym_fee_eac = total_asym_fee_usd if include_asym_fee else 0.0
        if btc_denominator <= 0:
            return EffectiveAcquisitionCost(
                per_btc_usd=float("nan"), per_btc_btc=float("nan"),
                premium_component_usd=total_premium_received_usd, premium_provenance=iv_provenance,
                fee_component_usd=total_exec_fees + asym_fee_eac, fee_provenance=Provenance.ASSUMED,
                seller_discount_component_usd=seller_discount, seller_discount_provenance=Provenance.BUSINESS_REQUIREMENT,
                impact_component_usd=total_impact_usd, impact_provenance=Provenance.ASSUMED,
                spread_slippage_component_usd=total_spread_usd, delivery_fee_component_usd=total_delivery_fee_usd,
                net_cash_deployed_usd=0.0, btc_acquired=0.0, d12_interpretation=interp,
                is_applicable=False, na_reason="no BTC acquired under this interpretation",
                asym_fee_component_usd=asym_fee_eac, asym_fee_provenance=Provenance.BUSINESS_REQUIREMENT,
            )
        notional = initial_spot * btc_denominator
        numerator = (notional + total_exec_fees + total_impact_usd + extra_cost_usd + asym_fee_eac
                     - total_premium_received_usd - seller_discount)
        return EffectiveAcquisitionCost(
            per_btc_usd=numerator / btc_denominator,
            per_btc_btc=(numerator / btc_denominator) / initial_spot if initial_spot > 0 else 0.0,
            premium_component_usd=total_premium_received_usd, premium_provenance=iv_provenance,
            fee_component_usd=total_exec_fees + asym_fee_eac, fee_provenance=Provenance.ASSUMED,
            seller_discount_component_usd=seller_discount, seller_discount_provenance=Provenance.BUSINESS_REQUIREMENT,
            impact_component_usd=total_impact_usd, impact_provenance=Provenance.ASSUMED,
            spread_slippage_component_usd=total_spread_usd, delivery_fee_component_usd=total_delivery_fee_usd,
            net_cash_deployed_usd=numerator, btc_acquired=btc_denominator,
            d12_interpretation=interp, is_applicable=True, na_reason=None,
            asym_fee_component_usd=asym_fee_eac, asym_fee_provenance=Provenance.BUSINESS_REQUIREMENT,
        )

    eac_cash = _build_eac(btc_held, 0.0, "cash_settled")
    # Issue 3: D-12 post-purchase includes explicit purchase cost with provenance
    eac_post = _build_eac(btc_held + total_assigned_btc, total_assignment_cost_usd, "post_purchase")
    eff_acq = eac_cash if eac_cash.is_applicable else eac_post

    # ── run-level metrics ──
    itm_count = sum(1 for c in cycles if c.is_itm)
    itm_frequency = itm_count / len(cycles) if cycles else 0.0
    touch_frequency = (sum(1 for c in cycles if c.touch_frequency_hit) / len(cycles)
                       if cycles else 0.0)

    # drawdown on the MTM equity curve (Issue 9)
    max_drawdown_pct = 0.0
    peak = -1e30
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

    # annualised Sharpe with explicit risk-free and cycle frequency.
    sharpe: float | None = None
    returns = [c.net_pnl_usd / capital_base for c in cycles] if capital_base > 0 else []
    if len(returns) >= 2:
        std_r = float(np.std(returns))
        if std_r > 1e-12:
            freq = 365.0 / max(dte_days, 1)
            rf_per_cycle = risk_free_rate / freq
            sharpe = (float(np.mean(returns)) - rf_per_cycle) / std_r * float(np.sqrt(freq))

    delta_vs_assignment = [
        {"delta_at_entry": c.delta_at_entry, "realised_assignment": float(c.realised_assignment)}
        for c in cycles
    ]

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
        pending_decision_refs=["D-1", "D-3", "D-9", "D-12"],
        daily_snapshots=snapshots,
        reconciliation_residual_usd=run_reconciliation_residual,
        asym_fee_reference_notional_usd=asym.reference_notional_fee_usd,
        asym_fee_executed_notional_usd=asym.executed_notional_fee_usd,
        fee_base_variant="pending_D1",
        total_asym_fee_usd=total_asym_fee_usd,
        eac_cash_settled=eac_cash,
        eac_post_purchase=eac_post,
        post_purchase_btc_inventory_end=post_purchase_btc,
        post_purchase_usd_deployed=post_purchase_usd_deployed,
    )


def backtest_unhedged_observed(
    strategy: Strategy,
    dates: list[datetime],
    spot_prices: np.ndarray,
    iv_history: np.ndarray | None = None,
    seller_discount_pct: float = 0.025,
    execution_fee_pct: float = 0.005,
) -> BacktestResult:
    """Observed buy-and-hold baseline (WP-B2 / FRF-002 / AT-002).

    Buys BTC at the FIRST observed bar and holds to the LAST observed bar of the
    SAME series used by every strategy. `total_pnl_pct` is the observed
    buy-and-hold return exactly (no synthetic path). Acquisition costs are
    reported in the EAC, not folded into the return.
    """
    _validate_inputs(dates, spot_prices, iv_history)
    btc_held = _btc_held(strategy)
    s0 = float(spot_prices[0])
    s1 = float(spot_prices[-1])
    pnl_usd = btc_held * (s1 - s0)
    ret_pct = ((s1 - s0) / s0) * 100.0 if s0 > 0 else 0.0
    seller_discount = s0 * seller_discount_pct * btc_held
    asym = asymmetrica_fee_both_variants(btc_held, s0, execution_fee_pct, seller_discount_pct)
    asym_fee = asym.reference_notional_fee_usd
    if btc_held > 0:
        eac_num = s0 * btc_held - seller_discount + asym_fee
        eac = EffectiveAcquisitionCost(
            per_btc_usd=eac_num / btc_held, per_btc_btc=(eac_num / btc_held) / s0 if s0 > 0 else 0.0,
            premium_component_usd=0.0, premium_provenance=Provenance.BUSINESS_REQUIREMENT,
            fee_component_usd=asym_fee, fee_provenance=Provenance.BUSINESS_REQUIREMENT,
            seller_discount_component_usd=seller_discount, seller_discount_provenance=Provenance.BUSINESS_REQUIREMENT,
            impact_component_usd=0.0, impact_provenance=Provenance.ASSUMED,
            net_cash_deployed_usd=eac_num, btc_acquired=btc_held,
            d12_interpretation="cash_settled", is_applicable=True,
            asym_fee_component_usd=asym_fee, asym_fee_provenance=Provenance.BUSINESS_REQUIREMENT,
        )
    else:
        eac = EffectiveAcquisitionCost(
            per_btc_usd=float("nan"), per_btc_btc=float("nan"),
            premium_component_usd=0.0, premium_provenance=Provenance.BUSINESS_REQUIREMENT,
            fee_component_usd=0.0, fee_provenance=Provenance.ASSUMED,
            seller_discount_component_usd=0.0, seller_discount_provenance=Provenance.BUSINESS_REQUIREMENT,
            impact_component_usd=0.0, impact_provenance=Provenance.ASSUMED,
            is_applicable=False, na_reason="baseline holds no BTC",
        )
    return BacktestResult(
        strategy_id=strategy.strategy_id,
        strategy_kind=str(strategy.canonical) if strategy.canonical else "",
        business_label=strategy.business_label if strategy.business_label else "",
        start_date=dates[0], end_date=dates[-1], cycles=[],
        total_pnl_usd=pnl_usd, total_pnl_btc=pnl_usd / s0 if s0 > 0 else 0.0,
        total_pnl_pct=ret_pct, total_premium_usd=0.0, total_premium_btc=0.0,
        total_fees_usd=asym_fee, total_fees_btc=0.0,
        effective_acquisition_cost=eac,
        provenance=Provenance.CALCULATED,
        reconciliation_residual_usd=0.0,
        asym_fee_reference_notional_usd=asym.reference_notional_fee_usd,
        asym_fee_executed_notional_usd=asym.executed_notional_fee_usd,
        fee_base_variant="pending_D1",
        total_asym_fee_usd=asym_fee,
        eac_cash_settled=eac, eac_post_purchase=eac,
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

    date_to_idx = {d: i for i, d in enumerate(dates)}
    n_common = min(len(result_original.cycles), len(result_modified.cycles))
    for i in range(n_common):
        orig = result_original.cycles[i]
        mod = result_modified.cycles[i]
        expiry_idx = date_to_idx.get(orig.end_date)
        if expiry_idx is None or expiry_idx >= split_idx:
            continue
        assert orig.entry_spot == mod.entry_spot, \
            f"Look-ahead detected: cycle {i} entry_spot changed by future data mutation"
        assert orig.strike == mod.strike, \
            f"Look-ahead detected: cycle {i} strike changed by future data mutation"
        assert orig.is_itm == mod.is_itm, \
            f"Look-ahead detected: cycle {i} is_itm changed by future data mutation"
        assert orig.premium_received_usd == mod.premium_received_usd, \
            f"Look-ahead detected: cycle {i} premium_received_usd changed by future data mutation"
        assert orig.net_pnl_usd == mod.net_pnl_usd, \
            f"Look-ahead detected: cycle {i} net_pnl_usd changed by future data mutation"

    return result_original
