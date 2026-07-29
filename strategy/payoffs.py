"""Strategy payoff functions for every strategy type.

Pure, parameter-driven functions.  Separate economic payoff from venue
settlement per AC-1, AC-8.  All settlement amounts use the contracts.md §3.2
holder/writer sign convention.

Frozen contracts: contracts.md §9.3, §9.5, §9.6.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.settlement import SettlementCurrency, SettlementMechanism, Venue
from engine.strategy import Leg, Strategy, StrategyKind


@dataclass(frozen=True)
class PayoffPoint:
    """One point on the strategy payoff curve — frozen per contracts.md §9.3."""

    S_T: float
    payoff_usd: float
    pnl_usd: float
    settlement_btc: float


@dataclass(frozen=True)
class StrategyPayoff:
    """Full strategy payoff analysis including breakeven points."""

    strategy_id: str
    kind: StrategyKind
    payoff_curve: list[PayoffPoint]
    breakeven_points: list[float]
    max_gain: float | None
    max_loss: float
    upside_cap: float | None
    missed_upside_exposure: bool
    downside_slope: float
    strike_kinks: list[float]


@dataclass(frozen=True)
class StrategyGreeks:
    """Aggregate strategy-level Greek exposure."""

    delta: float
    gamma: float
    vega: float
    theta: float


def _settlement_holder(leg: Leg, S_T: float) -> float:
    """Gross settlement amount the LONG HOLDER would receive, in USD.

    Per contracts.md §3.2 sign convention: this is the gross settlement
    to the holder. For the SHORT WRITER, the net cash flow is the negation
    of this amount.
    """
    if leg.product == "spot" or leg.settlement is None:
        return S_T - (leg.entry_spot or 0.0)

    settlement = leg.settlement
    K = leg.strike or 0.0

    if (settlement.venue == Venue.DERIBIT
            and settlement.settlement_mechanism == SettlementMechanism.CASH
            and settlement.settlement_currency == SettlementCurrency.BTC):
        from pricing.inverse import (
            settlement_inverse_call_holder,
            settlement_inverse_put_holder,
        )
        if leg.option_type == "call":
            btc = settlement_inverse_call_holder(S_T, K)
        else:
            btc = settlement_inverse_put_holder(S_T, K)
        return btc * S_T

    if leg.option_type == "call":
        return float(max(S_T - K, 0.0))
    else:
        return float(max(K - S_T, 0.0))


def strategy_pnl(strategy: Strategy, S_T: float) -> float:
    """Strategy P&L at expiry spot S_T, in USD.

    Per contracts.md §3.2 formula:

      strategy_pnl = sum_underlying quantity*(S_T - entry_spot)
                   + sum_option_long quantity*(settlement_holder - entry_premium)
                   + sum_option_short quantity*(-settlement_holder + entry_premium)

    where entry_premium is per contracts.md §3.2:
      - Positive when PAID by the leg owner (long options: cost to buy).
      - For SHORT positions, entry_premium stores the amount the writer
        RECEIVED (positive credit). The strategy builder populates
        entry_premium as positive for both long and short legs — the
        short-side formula treats it as a credit: -settlement + premium.

    Do NOT pass negative entry_premium for short legs. All builders pass
    positive received premiums, and the formula adds them as credits.
    """
    total = 0.0
    for leg in strategy.legs:
        if leg.product == "spot":
            total += leg.quantity * (S_T - (leg.entry_spot or 0.0))
        elif leg.product == "cash":
            pass  # Cash legs do not generate P&L from spot movement
        elif leg.side == "LONG":
            settlement = _settlement_holder(leg, S_T)
            total += leg.quantity * (settlement - leg.entry_premium)
        elif leg.side == "SHORT":
            settlement = _settlement_holder(leg, S_T)
            total += leg.quantity * (-settlement + leg.entry_premium)
    return total


def strategy_payoff(strategy: Strategy, S_T: float) -> PayoffPoint:
    """Full payoff point at spot S_T."""
    pnl = strategy_pnl(strategy, S_T)

    total_payoff = 0.0
    settlement_btc = 0.0
    for leg in strategy.legs:
        if leg.product == "spot":
            total_payoff += leg.quantity * (S_T - (leg.entry_spot or 0.0))
        elif leg.side == "LONG":
            settlement = _settlement_holder(leg, S_T)
            total_payoff += leg.quantity * settlement
        elif leg.side == "SHORT":
            settlement = _settlement_holder(leg, S_T)
            total_payoff += leg.quantity * (-settlement)

        if (leg.settlement is not None
                and leg.settlement.settlement_currency == SettlementCurrency.BTC
                and leg.product != "spot"):
            from pricing.inverse import (
                settlement_inverse_call_holder,
                settlement_inverse_put_holder,
            )
            K = leg.strike or 0.0
            if leg.option_type == "call":
                btc = settlement_inverse_call_holder(S_T, K)
            else:
                btc = settlement_inverse_put_holder(S_T, K)
            if leg.side == "LONG":
                settlement_btc += leg.quantity * btc
            else:
                settlement_btc += leg.quantity * (-btc)

    return PayoffPoint(S_T=S_T, payoff_usd=total_payoff, pnl_usd=pnl, settlement_btc=settlement_btc)


def strategy_payoff_curve(strategy: Strategy, S_points: np.ndarray) -> list[PayoffPoint]:
    """Payoff curve across a range of spot prices."""
    return [strategy_payoff(strategy, float(s)) for s in S_points]


def breakeven_points(strategy: Strategy, lo: float = 0.01, hi: float = 500_000.0) -> list[float]:
    """Find all spot prices where strategy P&L crosses zero.

    Uses root-finding on the piecewise-linear payoff function.
    Returns ascending list. Empty if no crossing.
    """
    from scipy.optimize import brentq

    points = list(strategy.legs)
    strikes = sorted({leg.strike for leg in points if leg.strike is not None})
    if not strikes:
        strikes = [0.0]

    search_points = [lo, *strikes, hi]
    bes: list[float] = []

    for i in range(len(search_points) - 1):
        a = search_points[i]
        b = search_points[i + 1]
        if a >= b:
            continue
        pnl_a = strategy_pnl(strategy, a)
        pnl_b = strategy_pnl(strategy, b)
        if pnl_a * pnl_b <= 0:
            eps = max(b - a, 1e-6)
            try:
                root = float(brentq(
                    lambda x: strategy_pnl(strategy, x),
                    a + eps * 1e-6,
                    b - eps * 1e-6,
                    xtol=1e-8,
                ))
                bes.append(root)
            except (ValueError, RuntimeError):
                pass

    bes.sort()
    deduped: list[float] = []
    for be in bes:
        if not deduped or abs(be - deduped[-1]) > 1e-4:
            deduped.append(be)
    return deduped


def long_btc_plus_short_put_pnl(S0: float, K: float, P: float, ST: float) -> float:
    """Exact piecewise P&L for long BTC + short put (one BTC-equivalent unit).

    Above strike:  P&L = ST - S0 + P
    Below strike:  P&L = 2*ST - S0 - K + P

    P is the premium RECEIVED by the short put writer (positive).
    """
    if ST >= K:
        return ST - S0 + P
    else:
        return 2.0 * ST - S0 - K + P


def long_btc_plus_short_put_identities(S0: float, K: float, P: float) -> dict[str, float]:
    """Compute all analytical identities for long BTC + short put."""
    return {
        "pnl_at_ST_zero": -(S0 + K - P),
        "max_loss": S0 + K - P,
        "breakeven_below_strike": (S0 + K - P) / 2.0,
        "breakeven_above_strike": S0 - P,
        "upside_uncapped": float("inf"),
        "slope_above_K": 1.0,
        "slope_below_K": 2.0,
    }


def structural_max_loss(strategy: Strategy) -> float:
    """Structural maximum-loss MAGNITUDE (USD, positive) from the actual payoff.

    Derived from the leg identities, NOT a ±spot-window truncation (FRF-026).
    The strategy P&L is piecewise-linear in S_T, so its global minimum over
    S_T ∈ [0, ∞) occurs at a kink (S_T = 0 or a strike) — unless the P&L slope
    stays negative as S_T → ∞ (uncapped short-call exposure), in which case the
    loss is unbounded and `inf` is returned. Returned as a positive magnitude;
    0.0 if the strategy cannot lose over the domain.
    """
    strikes = sorted({leg.strike for leg in strategy.legs if leg.strike is not None})
    entry_spots = [leg.entry_spot for leg in strategy.legs if leg.entry_spot is not None]
    hi = strikes[-1] if strikes else (max(entry_spots) if entry_spots else 1.0)
    # Slope just above the highest kink; if it stays negative the loss is
    # unbounded to the upside (e.g. a naked short call).
    a = strategy_pnl(strategy, hi + 1.0)
    b = strategy_pnl(strategy, hi + 2.0)
    if (b - a) < -1e-6:
        return float("inf")
    candidates = [0.0, *strikes, hi + 1.0]
    min_pnl = min(strategy_pnl(strategy, float(s)) for s in candidates)
    return max(0.0, -min_pnl)


@dataclass(frozen=True)
class LossQuantities:
    """Mandated downside-exposure block (FRF-026)."""

    max_loss_usd: float          # positive magnitude (inf if unbounded)
    max_loss_per_btc: float      # USD per reference BTC
    max_loss_pct_notional: float # as a fraction of notional
    max_loss_pct_capital: float  # as a fraction of capital at risk


def loss_quantities(
    strategy: Strategy,
    reference_btc: float,
    notional_usd: float,
    capital_usd: float,
) -> LossQuantities:
    """Structural loss reported in USD, per-BTC, %notional and %capital."""
    sml = structural_max_loss(strategy)
    per_btc = sml / reference_btc if reference_btc > 0 and sml != float("inf") else sml
    pct_notional = sml / notional_usd if notional_usd > 0 and sml != float("inf") else sml
    pct_capital = sml / capital_usd if capital_usd > 0 and sml != float("inf") else sml
    return LossQuantities(
        max_loss_usd=sml,
        max_loss_per_btc=per_btc,
        max_loss_pct_notional=pct_notional,
        max_loss_pct_capital=pct_capital,
    )


def compute_strategy_payoff(
    strategy: Strategy,
    S0: float,
    spot_range_pct: float = 0.5,
    n_points: int = 500,
) -> StrategyPayoff:
    """Full strategy payoff analysis."""
    points = np.linspace(
        max(S0 * (1 - spot_range_pct), 0.01),
        S0 * (1 + spot_range_pct),
        n_points,
    )
    curve = strategy_payoff_curve(strategy, points)
    bes = breakeven_points(strategy)

    # FRF-026: structural (not ±window-truncated) max loss; consistent SIGN
    # (max_loss is the signed minimum P&L, i.e. negative for a loss).
    sml = structural_max_loss(strategy)
    max_loss = float("-inf") if sml == float("inf") else -sml
    max_gain: float | None = None
    upside_cap: float | None = None
    missed_upside_exposure = False
    downside_slope = 0.0

    if strategy.canonical in (StrategyKind.COVERED_CALL, StrategyKind.PARTIAL_OVERLAY,
                               StrategyKind.COLLAR):
        upside_cap = max(point.pnl_usd for point in curve)
        missed_upside_exposure = True
        max_gain = upside_cap
    elif strategy.canonical == StrategyKind.CASH_SECURED_PUT:
        max_gain = max(point.pnl_usd for point in curve)
    elif strategy.canonical == StrategyKind.LONG_BTC_PLUS_SHORT_PUT:
        downside_slope = 2.0

    if strategy.canonical not in (StrategyKind.COVERED_CALL, StrategyKind.PARTIAL_OVERLAY,
                                   StrategyKind.COLLAR):
        missed_upside_exposure = False
        upside_cap = None

    strikes = sorted({leg.strike for leg in strategy.legs if leg.strike is not None})

    return StrategyPayoff(
        strategy_id=strategy.strategy_id,
        kind=strategy.canonical,
        payoff_curve=curve,
        breakeven_points=bes,
        max_gain=max_gain,
        max_loss=max_loss,
        upside_cap=upside_cap,
        missed_upside_exposure=missed_upside_exposure,
        downside_slope=downside_slope,
        strike_kinks=strikes,
    )


def compute_strategy_greeks(
    strategy: Strategy,
    S: float,
    r: float,
    sigma: float,
    T: float,
) -> StrategyGreeks:
    """Aggregate strategy-level Greeks."""
    from pricing.black76 import greeks_black76
    from pricing.black_scholes import greeks as bs_greeks
    from pricing.inverse import greeks_inverse_btc

    delta_total = 0.0
    gamma_total = 0.0
    vega_total = 0.0
    theta_total = 0.0

    for leg in strategy.legs:
        q = leg.quantity
        if leg.product == "spot":
            if leg.side == "LONG":
                delta_total += q * 1.0
            else:
                delta_total += q * (-1.0)

        elif leg.settlement is not None and leg.strike is not None:
            K = leg.strike
            if (leg.settlement.venue == Venue.DERIBIT
                    and leg.settlement.settlement_mechanism == SettlementMechanism.CASH
                    and leg.settlement.settlement_currency == SettlementCurrency.BTC):
                g = greeks_inverse_btc(S, K, r, sigma, T, leg.option_type or "call")
            elif leg.settlement.settlement_mechanism == SettlementMechanism.FUTURES_DELIVERY_THEN_CASH:
                F = S * np.exp(r * T)
                g = greeks_black76(F, K, r, sigma, T, leg.option_type or "call")
            else:
                g = bs_greeks(S, K, r, sigma, T, leg.option_type or "call")

            sign = 1.0 if leg.side == "LONG" else -1.0
            delta_total += sign * q * g.delta
            gamma_total += sign * q * g.gamma
            vega_total += sign * q * g.vega
            theta_total += sign * q * g.theta

    return StrategyGreeks(
        delta=delta_total,
        gamma=gamma_total,
        vega=vega_total,
        theta=theta_total,
    )
