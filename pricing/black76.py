"""Black-76 pricing model for European options on futures/forwards.

Source: Haug §1.1.3; Hull §18.  All rates/vols are decimals.
The underlying F is the forward/futures price.
"""

from __future__ import annotations

import math

from scipy.stats import norm

from pricing.black_scholes import OptionQuote


def _d1_d2(F: float, X: float, sigma: float, T: float) -> tuple[float, float]:
    sqT = math.sqrt(T)
    d1 = (math.log(F / X) + 0.5 * sigma * sigma * T) / (sigma * sqT)
    return d1, d1 - sigma * sqT


def price_black76(
    F: float, X: float, r: float, sigma: float, T: float, kind: str = "call"
) -> float:
    """Black-76 call/put price on a forward/futures contract.

    F     — forward / futures price
    X     — strike price
    r     — risk-free rate (decimal, continuous)
    sigma — volatility (annualised, decimal)
    T     — time to expiry in years
    kind  — "call" or "put"
    """

    d1, d2 = _d1_d2(F, X, sigma, T)
    df = math.exp(-r * T)
    if kind == "call":
        return float(df * (F * norm.cdf(d1) - X * norm.cdf(d2)))
    return float(df * (X * norm.cdf(-d2) - F * norm.cdf(-d1)))


def greeks_black76(
    F: float, X: float, r: float, sigma: float, T: float, kind: str = "call",
) -> OptionQuote:
    """Black-76 Greeks for a European option on a forward/futures contract.

    Delta is dPrice/dF (the derivative w.r.t. the forward price).
    Vega  is dPrice/do, per 1.00 absolute vol change.
    Theta is -dPrice/dT, annualised.
    """

    d1, d2 = _d1_d2(F, X, sigma, T)
    sqT = math.sqrt(T)
    df = math.exp(-r * T)
    pdf_d1 = norm.pdf(d1)

    price_val = price_black76(F, X, r, sigma, T, kind)

    delta = df * norm.cdf(d1) if kind == "call" else df * (norm.cdf(d1) - 1.0)

    gamma = df * pdf_d1 / (F * sigma * sqT)

    # vega = df * F * sqT * n(d1) * exp(-rT)... wait, actually in Black-76
    # standard vega formula: vega = e^{-rT} * F * sqrt(T) * N'(d1)
    vega = df * F * pdf_d1 * sqT

    # theta = -dPrice/dT
    term1 = df * F * pdf_d1 * sigma / (2.0 * sqT)
    if kind == "call":
        theta_ = -term1 + r * df * F * norm.cdf(d1) - r * df * X * norm.cdf(d2)
    else:
        theta_ = -term1 - r * df * X * norm.cdf(-d2) + r * df * F * norm.cdf(-d1)

    return OptionQuote(
        price=float(price_val),
        delta=float(delta),
        gamma=float(gamma),
        vega=float(vega),
        theta=float(theta_),
        strike=float(X),
    )
