"""Instrument repricing for evaluation contexts (WP-B6 / FRF-005 / AT-005).

MC, stress and regime evaluators must NOT consume the static builder placeholder
premiums (e.g. 1500 USD). `reprice_strategy` returns a copy of the strategy whose
option legs carry premiums repriced from the evaluation context (spot / IV / T)
through the pricing layer, so downstream `strategy_pnl` uses fair premiums.

C9 · M0.1 / B3 marking convention: Deribit-inverse (BTC-settled) legs are marked with
r = q = 0 off the OBSERVED forward (Black-76 on F, ``price_inverse_btc_forward``), not
r=0.04-off-spot which injects a forward drift the exchange never applies. The forward
defaults to the evaluation spot (Deribit r=q=0 ⇒ F ≈ S); pass an observed per-expiry
forward when available. A nonzero carry q is an ASSUMED input (MS-11) and is tagged by
the caller. Linear/USD (e.g. CME) legs keep the standard Black-Scholes r discounting.
"""

from __future__ import annotations

from engine.settlement import SettlementCurrency, Venue
from engine.strategy import Strategy
from pricing.black_scholes import price as bs_price
from pricing.inverse import price_inverse_btc_forward


def repriced_leg_premium(
    leg_option_type: str,
    is_deribit_btc: bool,
    spot: float,
    strike: float,
    r: float,
    iv: float,
    T: float,
    forward: float | None = None,
    carry_q: float = 0.0,
) -> float:
    """Fair premium for one option leg (magnitude, BTC or USD per convention).

    Deribit-inverse legs mark off the observed forward with r=q=0 (B3); ``forward``
    defaults to ``spot``. Linear/USD legs use Black-Scholes with the supplied ``r``.
    """
    if is_deribit_btc:
        F = forward if forward is not None else spot
        return price_inverse_btc_forward(F, strike, iv, T, leg_option_type, carry_q)
    return bs_price(spot, strike, r, iv, T, leg_option_type)


def reprice_strategy(
    strategy: Strategy,
    spot: float,
    iv: float,
    risk_free_rate: float = 0.04,
    time_to_expiry: float = 30.0 / 365.0,
    forward: float | None = None,
    carry_q: float = 0.0,
) -> Strategy:
    """Return a copy of `strategy` with every option leg's `entry_premium`
    repriced (magnitude, unsigned-with-side) at the given evaluation context.

    Inverse (Deribit BTC) legs are marked r=q=0 off ``forward`` (default: ``spot``);
    ``risk_free_rate`` applies only to linear/USD legs (B3)."""
    new_legs = []
    for leg in strategy.legs:
        if leg.option_type is not None and leg.strike is not None:
            is_der = (leg.settlement is not None
                      and leg.settlement.venue == Venue.DERIBIT
                      and leg.settlement.settlement_currency == SettlementCurrency.BTC)
            prem = repriced_leg_premium(
                leg.option_type, is_der, spot, leg.strike, risk_free_rate, iv,
                time_to_expiry, forward=forward, carry_q=carry_q)
            new_legs.append(leg.model_copy(update={"entry_premium": abs(prem)}))
        else:
            new_legs.append(leg)
    return strategy.model_copy(update={"legs": new_legs})
