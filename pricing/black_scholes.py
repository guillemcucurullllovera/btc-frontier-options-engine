"""Black-Scholes baseline pricer (Hull) with Greeks, delta->strike inversion,
and implied volatility. Test vectors: Haug, 'Complete Guide to Option Pricing
Formulas'. Cross-check target: QuantLib parity suite (Agent A6).

All rates/vols are decimals (0.45 = 45%). T in years.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.optimize import brentq
from scipy.stats import norm


@dataclass(frozen=True)
class OptionQuote:
    price: float
    delta: float
    gamma: float
    vega: float      # per 1.00 vol (divide by 100 for per-vol-point)
    theta: float     # per year (divide by 365 for per-day)
    strike: float


def _d1_d2(S: float, K: float, r: float, sigma: float, T: float) -> tuple[float, float]:
    sqT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqT)
    return d1, d1 - sigma * sqT


def price(S: float, K: float, r: float, sigma: float, T: float, kind: str = "call") -> float:
    d1, d2 = _d1_d2(S, K, r, sigma, T)
    df = math.exp(-r * T)
    if kind == "call":
        return float(S * norm.cdf(d1) - K * df * norm.cdf(d2))
    return float(K * df * norm.cdf(-d2) - S * norm.cdf(-d1))


def greeks(S: float, K: float, r: float, sigma: float, T: float, kind: str = "call") -> OptionQuote:
    d1, d2 = _d1_d2(S, K, r, sigma, T)
    sqT = math.sqrt(T)
    df = math.exp(-r * T)
    pdf = norm.pdf(d1)
    delta = norm.cdf(d1) if kind == "call" else norm.cdf(d1) - 1.0
    gamma = pdf / (S * sigma * sqT)
    vega = S * pdf * sqT
    if kind == "call":
        theta = -(S * pdf * sigma) / (2 * sqT) - r * K * df * norm.cdf(d2)
    else:
        theta = -(S * pdf * sigma) / (2 * sqT) + r * K * df * norm.cdf(-d2)
    return OptionQuote(price(S, K, r, sigma, T, kind), delta, gamma, vega, theta, K)


def strike_for_delta(S: float, target_delta: float, r: float, sigma: float, T: float,
                     kind: str = "call") -> float:
    """Invert N(d1)=delta analytically: ln(K/S) = (r+sigma^2/2)T - d1*sigma*sqrt(T)."""
    d1 = norm.ppf(target_delta) if kind == "call" else norm.ppf(1.0 + target_delta)
    lnKS = (r + 0.5 * sigma * sigma) * T - d1 * sigma * math.sqrt(T)
    return S * math.exp(lnKS)


def implied_vol(target_price: float, S: float, K: float, r: float, T: float,
                kind: str = "call", lo: float = 1e-4, hi: float = 5.0) -> float:
    def _diff(sig: float) -> float:
        return price(S, K, r, sig, T, kind) - target_price
    return float(brentq(_diff, lo, hi, xtol=1e-8))


def premium_pct_at_delta(S: float, delta: float, r: float, sigma: float, dte_days: float,
                         kind: str = "call") -> tuple[float, float]:
    """Return (premium as % of spot, strike) for a fixed-delta structure.
    This is the function that answers 'what does the mandate structure yield'."""
    T = dte_days / 365.0
    K = strike_for_delta(S, delta, r, sigma, T, kind)
    return (100.0 * price(S, K, r, sigma, T, kind) / S, K)
