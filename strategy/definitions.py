"""Standard strategy definitions for the BTC acquisition mandate.

Each function builds a Strategy with proper legs, ensuring correct
classification, premium signs, and settlement specs.

Never call any strategy 'best', 'optimal', 'safest', 'preferred',
'recommended' or 'winner'.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from engine.errors import ClassificationError, ValidationError
from engine.settlement import (
    DeliveryPriceConvention,
    ExerciseStyle,
    SettlementCurrency,
    SettlementMechanism,
    SettlementSpec,
    Venue,
)
from engine.strategy import DecisionRef, Leg, Strategy, StrategyKind, classify

PENDING_D1 = DecisionRef(code="D-1", owner="Mandate issuer", impact="$243,750 swing on $9.75M fee")
PENDING_D3 = DecisionRef(code="D-3", owner="Mandate issuer", impact="Determines settlement mechanics, margin, instrument-type modelling")
PENDING_D9 = DecisionRef(code="D-9", owner="Mandate issuer", impact="A3 cannot compute delta-hedge P&L until resolved")


def _make_spot_leg(quantity: float, entry_price: float) -> Leg:
    return Leg(
        instrument="BTC-spot", venue=Venue.OTC, product="spot",
        side="LONG", quantity=quantity, entry_spot=entry_price,
    )


def _make_cash_leg(quantity: float) -> Leg:
    return Leg(
        instrument="USD-cash", venue=Venue.OTC, product="cash",
        side="LONG", quantity=quantity,
    )


def _make_deribit_option_leg(
    option_type: Literal["call", "put"],
    side: Literal["LONG", "SHORT"],
    quantity: float,
    strike: float,
    premium: float,
    dte_days: int = 30,
    expiry: datetime | None = None,
) -> Leg:
    if expiry is None:
        expiry = datetime.now(UTC) + timedelta(days=dte_days)
    settlement = SettlementSpec(
        venue=Venue.DERIBIT, product="inverse_option",
        settlement_mechanism=SettlementMechanism.CASH,
        settlement_currency=SettlementCurrency.BTC,
        exercise_style=ExerciseStyle.EUROPEAN,
        contract_multiplier=1.0,
        delivery_price_convention=DeliveryPriceConvention.TWAP_0730_0800_UTC,
    )
    return Leg(
        instrument=f"BTC-{expiry.strftime('%d%b%y').upper()}-{int(strike)}-{option_type[0].upper()}",
        venue=Venue.DERIBIT,
        product="call_option" if option_type == "call" else "put_option",
        side=side, quantity=quantity, entry_premium=premium,
        settlement=settlement, option_type=option_type, strike=strike,
        expiry_timestamp=expiry,
    )


def _make_cme_option_leg(
    option_type: Literal["call", "put"],
    side: Literal["LONG", "SHORT"],
    quantity: float,
    strike: float,
    premium: float,
    dte_days: int = 30,
    expiry: datetime | None = None,
) -> Leg:
    if expiry is None:
        expiry = datetime.now(UTC) + timedelta(days=dte_days)
    settlement = SettlementSpec(
        venue=Venue.CME, product="option_on_futures",
        settlement_mechanism=SettlementMechanism.FUTURES_DELIVERY_THEN_CASH,
        settlement_currency=SettlementCurrency.USD,
        exercise_style=ExerciseStyle.EUROPEAN,
        contract_multiplier=5.0,
        delivery_price_convention=DeliveryPriceConvention.BRR_1600_LONDON,
    )
    return Leg(
        instrument=f"CME-BTC-{expiry.strftime('%d%b%y').upper()}-{int(strike)}-{option_type[0].upper()}",
        venue=Venue.CME, product="call_option" if option_type == "call" else "put_option",
        side=side, quantity=quantity, entry_premium=premium,
        settlement=settlement, option_type=option_type, strike=strike,
        expiry_timestamp=expiry,
    )


def _make_usd_option_leg(
    option_type: Literal["call", "put"],
    side: Literal["LONG", "SHORT"],
    quantity: float,
    strike: float,
    premium: float,
    dte_days: int = 30,
    expiry: datetime | None = None,
) -> Leg:
    if expiry is None:
        expiry = datetime.now(UTC) + timedelta(days=dte_days)
    settlement = SettlementSpec(
        venue=Venue.OTC, product="otc_option",
        settlement_mechanism=SettlementMechanism.CASH,
        settlement_currency=SettlementCurrency.USD,
        exercise_style=ExerciseStyle.EUROPEAN,
        contract_multiplier=1.0,
        delivery_price_convention=DeliveryPriceConvention.NEGOTIATED,
    )
    return Leg(
        instrument=f"OTC-BTC-{expiry.strftime('%d%b%y').upper()}-{int(strike)}-{option_type[0].upper()}",
        venue=Venue.OTC, product="call_option" if option_type == "call" else "put_option",
        side=side, quantity=quantity, entry_premium=premium,
        settlement=settlement, option_type=option_type, strike=strike,
        expiry_timestamp=expiry,
    )


def build_unhedged_baseline(
    quantity: float = 30_000.0,
    entry_spot: float = 65_000.0,
    strategy_id: str = "unhedged_baseline",
    business_label: str = "Unhedged BTC Acquisition",
) -> Strategy:
    legs = [_make_spot_leg(quantity, entry_spot)]
    try:
        canonical = classify(legs)
    except ClassificationError:
        canonical = StrategyKind.BESPOKE
    return Strategy(
        strategy_id=strategy_id, business_label=business_label,
        canonical=canonical, legs=legs,
        structural_max_loss=quantity * entry_spot,
        pending_decisions=[PENDING_D3],
    )


def build_covered_call(
    quantity: float = 30_000.0,
    entry_spot: float = 65_000.0,
    strike: float = 75_000.0,
    premium_received: float = 1_500.0,
    dte_days: int = 30,
    strategy_id: str = "covered_call",
    business_label: str = "Covered Call (Long BTC + Short Call)",
) -> Strategy:
    legs = [
        _make_spot_leg(quantity, entry_spot),
        _make_usd_option_leg("call", "SHORT", quantity, strike, premium_received, dte_days),
    ]
    canonical = classify(legs)
    return Strategy(
        strategy_id=strategy_id, business_label=business_label,
        canonical=canonical, legs=legs,
        structural_max_loss=quantity * (entry_spot - premium_received),
        pending_decisions=[PENDING_D1, PENDING_D3, PENDING_D9],
    )


def build_cash_secured_put(
    quantity: float = 30_000.0,
    entry_spot: float = 65_000.0,
    strike: float = 58_500.0,
    premium_received: float = 1_500.0,
    dte_days: int = 30,
    strategy_id: str = "cash_secured_put",
    business_label: str = "Cash-Secured Put",
) -> Strategy:
    cash_required = quantity * strike
    legs = [
        _make_cash_leg(cash_required),
        _make_usd_option_leg("put", "SHORT", quantity, strike, premium_received, dte_days),
    ]
    canonical = classify(legs)
    return Strategy(
        strategy_id=strategy_id, business_label=business_label,
        canonical=canonical, legs=legs,
        structural_max_loss=quantity * (strike - premium_received),
        pending_decisions=[PENDING_D1, PENDING_D3],
    )


def build_long_btc_plus_short_put(
    quantity: float = 30_000.0,
    entry_spot: float = 65_000.0,
    strike: float = 58_500.0,
    premium_received: float = 1_500.0,
    dte_days: int = 30,
    strategy_id: str = "long_btc_plus_short_put",
    business_label: str = "Long BTC + Short Put",
) -> Strategy:
    legs = [
        _make_spot_leg(quantity, entry_spot),
        _make_usd_option_leg("put", "SHORT", quantity, strike, premium_received, dte_days),
    ]
    canonical = classify(legs)
    if canonical != StrategyKind.LONG_BTC_PLUS_SHORT_PUT:
        raise ClassificationError(f"Expected LONG_BTC_PLUS_SHORT_PUT but got {canonical}")
    return Strategy(
        strategy_id=strategy_id, business_label=business_label,
        canonical=canonical, legs=legs,
        classification_warning=(
            "W-CLASSIFY-MISMATCH: business_label 'Covered Put Strategy' differs from canonical LONG_BTC_PLUS_SHORT_PUT"
            if "covered" in business_label.lower() else None
        ),
        structural_max_loss=quantity * (entry_spot + strike - premium_received),
        pending_decisions=[PENDING_D3, PENDING_D9],
    )


def build_collar(
    quantity: float = 30_000.0,
    entry_spot: float = 65_000.0,
    call_strike: float = 75_000.0,
    put_strike: float = 55_000.0,
    call_premium: float = 1_500.0,
    put_premium: float = 1_200.0,
    dte_days: int = 30,
    strategy_id: str = "collar",
    business_label: str = "Collar (Long BTC + Short Call + Long Put)",
) -> Strategy:
    legs = [
        _make_spot_leg(quantity, entry_spot),
        _make_usd_option_leg("call", "SHORT", quantity, call_strike, call_premium, dte_days),
        _make_usd_option_leg("put", "LONG", quantity, put_strike, put_premium, dte_days),
    ]
    canonical = classify(legs)
    return Strategy(
        strategy_id=strategy_id, business_label=business_label,
        canonical=canonical, legs=legs,
        structural_max_loss=quantity * (entry_spot - put_strike + put_premium - call_premium),
        pending_decisions=[PENDING_D1, PENDING_D3, PENDING_D9],
    )


def build_call_spread(
    quantity: float = 30_000.0,
    call_strike_short: float = 75_000.0,
    call_strike_long: float = 85_000.0,
    short_premium: float = 1_500.0,
    long_premium: float = 600.0,
    dte_days: int = 30,
    strategy_id: str = "call_spread",
    business_label: str = "Call Spread",
) -> Strategy:
    legs = [
        _make_usd_option_leg("call", "SHORT", quantity, call_strike_short, short_premium, dte_days),
        _make_usd_option_leg("call", "LONG", quantity, call_strike_long, long_premium, dte_days),
    ]
    canonical = classify(legs)
    spread_width = call_strike_long - call_strike_short
    return Strategy(
        strategy_id=strategy_id, business_label=business_label,
        canonical=canonical, legs=legs,
        structural_max_loss=quantity * (spread_width - short_premium + long_premium),
        pending_decisions=[PENDING_D1, PENDING_D3],
    )


def build_partial_overlay(
    total_quantity: float = 30_000.0,
    overlay_ratio: float = 0.5,
    entry_spot: float = 65_000.0,
    strike: float = 75_000.0,
    premium_received: float = 1_500.0,
    dte_days: int = 30,
    strategy_id: str = "partial_overlay",
    business_label: str = "Partial Covered Call Overlay",
) -> Strategy:
    if not 0.0 <= overlay_ratio <= 1.0:
        raise ValidationError(f"overlay_ratio must be in [0, 1], got {overlay_ratio}")

    overlay_qty = total_quantity * overlay_ratio
    legs = [
        _make_spot_leg(total_quantity, entry_spot),
        _make_usd_option_leg("call", "SHORT", overlay_qty, strike, premium_received, dte_days),
    ]
    canonical = classify(legs)
    # A fractional overlay (ratio < 1) classifies as PARTIAL_OVERLAY; a full
    # overlay (ratio == 1) as COVERED_CALL. Both are consistent with the
    # "Partial Covered Call Overlay" business label, so no mismatch warning.
    expected = (StrategyKind.PARTIAL_OVERLAY if overlay_ratio < 1.0
                else StrategyKind.COVERED_CALL)
    return Strategy(
        strategy_id=strategy_id, business_label=business_label,
        canonical=canonical, legs=legs,
        classification_warning=(
            None if canonical == expected
            else f"W-CLASSIFY-MISMATCH: canonical {canonical} != expected {expected}"
        ),
        structural_max_loss=total_quantity * entry_spot - overlay_qty * premium_received,
        pending_decisions=[PENDING_D1, PENDING_D3, PENDING_D9],
    )


def build_strike_ladder(
    base_quantity: float = 30_000.0,
    entry_spot: float = 65_000.0,
    contract_mult: float = 1.0,
    dte_days: int = 30,
    dte_ladder: list[int] | None = None,
    strike_uplift_pct: float = 0.15,
    premium_pct_of_spot: float = 0.02,
) -> Strategy:
    """Build a strike-ladder strategy with multiple short calls across DTE values.

    Parameters injected from configuration; no hardcoded business assumptions.
    Default DTE ladder is [30, 37, 44].
    """
    if dte_ladder is None:
        dte_ladder = [30, 37, 44]
    num_tranches = len(dte_ladder)
    tranche_qty = base_quantity / num_tranches

    legs = [_make_spot_leg(base_quantity, entry_spot)]

    for dte in dte_ladder:
        strike = entry_spot * (1.0 + strike_uplift_pct)
        premium = entry_spot * premium_pct_of_spot
        legs.append(
            _make_usd_option_leg("call", "SHORT", tranche_qty, strike, premium, dte)
        )

    canonical = classify(legs)
    # Structural max loss occurs at S_T=0 (all calls OTM): lose the full spot
    # position net of the premiums collected across the ladder (FRF-026).
    total_premium = sum(tranche_qty * (entry_spot * premium_pct_of_spot) for _ in dte_ladder)
    return Strategy(
        strategy_id="strike_ladder",
        business_label="Strike & Expiry Ladder",
        canonical=canonical, legs=legs,
        structural_max_loss=base_quantity * entry_spot - total_premium,
        pending_decisions=[PENDING_D1, PENDING_D3, PENDING_D9],
    )


STRATEGY_BUILDERS: dict[str, Callable[..., Strategy]] = {
    "unhedged_baseline": build_unhedged_baseline,
    "covered_call": build_covered_call,
    "cash_secured_put": build_cash_secured_put,
    "long_btc_plus_short_put": build_long_btc_plus_short_put,
    "collar": build_collar,
    "call_spread": build_call_spread,
    "partial_overlay": build_partial_overlay,
    "strike_ladder": build_strike_ladder,
}


def build_all_mandate_strategies(
    quantity: float = 30_000.0,
    entry_spot: float = 65_000.0,
) -> list[Strategy]:
    strategies: list[Strategy] = [
        build_unhedged_baseline(quantity, entry_spot),
        build_covered_call(quantity, entry_spot),
        build_cash_secured_put(quantity, entry_spot),
        build_long_btc_plus_short_put(quantity, entry_spot),
        build_collar(quantity, entry_spot),
        build_call_spread(quantity),
        build_partial_overlay(quantity, overlay_ratio=0.5, entry_spot=entry_spot),
        build_partial_overlay(quantity, overlay_ratio=0.75, entry_spot=entry_spot,
                              strategy_id="partial_overlay_75"),
        build_strike_ladder(quantity, entry_spot),
    ]
    return strategies
