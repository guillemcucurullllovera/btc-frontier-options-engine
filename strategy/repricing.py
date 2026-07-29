"""Instrument repricing for evaluation contexts (WP-B6 / FRF-005 / AT-005).

MC, stress and regime evaluators must NOT consume the static builder placeholder
premiums (e.g. 1500 USD). `reprice_strategy` returns a copy of the strategy whose
option legs carry premiums repriced from the evaluation context (spot / IV / T)
through the pricing layer, so downstream `strategy_pnl` uses fair premiums.
"""

from __future__ import annotations

from engine.settlement import SettlementCurrency, Venue
from engine.strategy import Strategy
from pricing.black_scholes import price as bs_price
from pricing.inverse import price_inverse_btc


def repriced_leg_premium(
    leg_option_type: str,
    is_deribit_btc: bool,
    spot: float,
    strike: float,
    r: float,
    iv: float,
    T: float,
) -> float:
    if is_deribit_btc:
        return price_inverse_btc(spot, strike, r, iv, T, leg_option_type)
    return bs_price(spot, strike, r, iv, T, leg_option_type)


def reprice_strategy(
    strategy: Strategy,
    spot: float,
    iv: float,
    risk_free_rate: float = 0.04,
    time_to_expiry: float = 30.0 / 365.0,
) -> Strategy:
    """Return a copy of `strategy` with every option leg's `entry_premium`
    repriced (magnitude, unsigned-with-side) at the given evaluation context."""
    new_legs = []
    for leg in strategy.legs:
        if leg.option_type is not None and leg.strike is not None:
            is_der = (leg.settlement is not None
                      and leg.settlement.venue == Venue.DERIBIT
                      and leg.settlement.settlement_currency == SettlementCurrency.BTC)
            prem = repriced_leg_premium(
                leg.option_type, is_der, spot, leg.strike, risk_free_rate, iv, time_to_expiry)
            new_legs.append(leg.model_copy(update={"entry_premium": abs(prem)}))
        else:
            new_legs.append(leg)
    return strategy.model_copy(update={"legs": new_legs})
