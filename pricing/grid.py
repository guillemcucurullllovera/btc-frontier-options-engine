"""Vectorised NumPy pricing over strike and expiry grids.

Provides batched Black-Scholes pricing for efficient surface creation,
scenario analysis and option-chain evaluation.

All prices are in USD (standard Black-Scholes). For inverse-BTC pricing,
use pricing/inverse.py.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm as _scipy_norm

from engine.errors import PricingError


def price_grid(
    S: float,
    Ks: np.ndarray,
    r: float,
    sigma: float,
    Ts: np.ndarray,
    kind: str = "call",
) -> np.ndarray:
    """Vectorised Black-Scholes price over a grid of strikes and expiries.

    S     — spot price (float, scalar)
    Ks    — strike prices (1-D array of shape (M,))
    r     — risk-free rate (decimal, continuous)
    sigma — volatility (annualised, decimal, scalar)
    Ts    — times to expiry in years (1-D array of shape (N,))
    kind  — "call" or "put"

    Returns a 2-D array of shape (M, N) where element [i, j] is the
    Black-Scholes price for strike Ks[i] and expiry Ts[j].
    """

    Ks = np.asarray(Ks, dtype=np.float64)
    Ts = np.asarray(Ts, dtype=np.float64)

    if Ks.ndim != 1:
        raise ValueError("Ks must be 1-D")
    if Ts.ndim != 1:
        raise ValueError("Ts must be 1-D")
    # FRF-029 / AT-029: reject degenerate inputs up front rather than masking
    # the resulting non-finite prices to 0.0 downstream.
    # sigma == 0 is a valid deterministic limit (finite intrinsic value); only
    # genuinely non-finite OUTPUTS raise (checked after the computation).
    if not (S > 0 and sigma >= 0):
        raise PricingError(f"price_grid requires positive S and non-negative sigma; got S={S}, sigma={sigma}")
    if Ks.size and float(np.min(Ks)) <= 0:
        raise PricingError("price_grid requires strictly positive strikes")
    if Ts.size and float(np.min(Ts)) <= 0:
        raise PricingError("price_grid requires strictly positive times to expiry")

    M = Ks.shape[0]  # noqa: F841
    N_ = Ts.shape[0]  # noqa: F841

    K_grid = Ks[:, np.newaxis]          # (M, 1)
    T_grid = Ts[np.newaxis, :]          # (1, N)

    with np.errstate(divide="ignore", invalid="ignore"):
        sqT = np.sqrt(T_grid)
        d1 = (np.log(S / K_grid) + (r + 0.5 * sigma * sigma) * T_grid) / (sigma * sqT)
        d2 = d1 - sigma * sqT

    df = np.exp(-r * T_grid)

    if kind == "call":
        prices = S * _scipy_norm.cdf(d1) - K_grid * df * _scipy_norm.cdf(d2)
    else:
        prices = K_grid * df * _scipy_norm.cdf(-d2) - S * _scipy_norm.cdf(-d1)

    if not bool(np.all(np.isfinite(prices))):
        raise PricingError("non-finite price produced in price_grid")

    return prices.astype(np.float64)
