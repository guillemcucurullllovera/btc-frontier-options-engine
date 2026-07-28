"""Deribit inverse-BTC option pricing and settlement functions.

Re-derived from official Deribit specification
(deribitfilesascopiedtxt.txt §"Inverse Options" lines 1-199).

Key characteristics:
  - Underlying:    Deribit BTC Index (USD per 1 BTC)
  - Premium:       paid/received in BTC
  - Settlement:    cash-settled in BTC
  - Multiplier:    1 BTC per contract
  - Delivery:      TWAP of Deribit BTC index, 07:30-08:00 UTC
  - Exercise:      European, automatic at expiry

Pricing derivation:
  Under risk-neutral valuation with zero convenience yield (q=0):
    F = S · exp(r · T)

  The inverse call pays the holder at expiry:
    max(F_T - K, 0) / F_T   BTC per 1 BTC contract

  Discounted expected value (Black's model):
    C_inv = exp(-rT) · [N(d₁) - (K/F) · N(d₂)]

  The inverse put via put-call parity:
    P_inv = exp(-rT) · [(K/F) · N(-d₂) - N(-d₁)]

  where:
    d₁ = [ln(F/K) + o^2T/2] / (o√T)
    d₂ = d₁ - o√T

  Greeks are computed via central finite differences on the analytical price.

  Do NOT implement formulas from the reconciled audit §10.8.
"""

from __future__ import annotations

import math

from pricing.black_scholes import OptionQuote


def settlement_inverse_call_holder(delivery_price: float, strike: float) -> float:
    """Gross BTC settlement per 1 contract to the long call holder.

    Formula:  max(delivery_price - strike, 0) / delivery_price

    Source: deribitfilesascopiedtxt.txt §"Inverse Options" lines 1-199.
    For the SHORT WRITER, the cash flow is the NEGATION of this amount.
    """

    return float(max(delivery_price - strike, 0.0) / delivery_price)


def settlement_inverse_put_holder(delivery_price: float, strike: float) -> float:
    """Gross BTC settlement per 1 contract to the long put holder.

    Formula:  max(strike - delivery_price, 0) / delivery_price

    For the SHORT WRITER, the cash flow is the NEGATION of this amount.
    """

    return float(max(strike - delivery_price, 0.0) / delivery_price)


def _d1_d2(F: float, K: float, sigma: float, T: float) -> tuple[float, float]:
    sqT = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqT)
    return d1, d1 - sigma * sqT


def _call_price_raw(F: float, K: float, r: float, sigma: float, T: float) -> float:
    """Core inverse BTC call price in BTC per 1 BTC contract (unquoted raw value).

    F is the forward price F = S · exp((r-q)·T).
    """

    import math as _m

    from scipy.stats import norm as _norm

    d1, d2 = _d1_d2(F, K, sigma, T)
    df = _m.exp(-r * T)

    return float(df * (_norm.cdf(d1) - (K / F) * _norm.cdf(d2)))


def _put_price_raw(F: float, K: float, r: float, sigma: float, T: float) -> float:
    """Core inverse BTC put price in BTC per 1 BTC contract (unquoted raw value).

    Via put-call parity: P_inv = C_inv - exp(-rT) · (1 - K/F).
    """

    import math as _m

    from scipy.stats import norm as _norm

    d1, d2 = _d1_d2(F, K, sigma, T)
    df = _m.exp(-r * T)

    return float(df * ((K / F) * _norm.cdf(-d2) - _norm.cdf(-d1)))


def price_inverse_btc(
    S: float, K: float, r: float, sigma: float, T: float, kind: str = "call",
    q: float = 0.0,
) -> float:
    """Inverse-BTC option price in BTC per 1 BTC contract.

    S     — spot price (USD per 1 BTC)
    K     — strike price (USD)
    r     — risk-free rate (decimal, continuous)
    sigma — volatility (annualised, decimal)
    T     — time to expiry in years
    kind  — "call" or "put"
    q     — convenience yield / BTC borrow rate (decimal, optional, default 0.0)

    Forward: F = S · exp((r - q) · T).

    Cross-check against Deribit spec example at line 22:
    S_T=125k, K=100k -> holder settlement = 0.2 BTC.
    """

    import math as _m

    F = S * _m.exp((r - q) * T)

    if kind == "call":
        return _call_price_raw(F, K, r, sigma, T)
    return _put_price_raw(F, K, r, sigma, T)


def greeks_inverse_btc(
    S: float, K: float, r: float, sigma: float, T: float, kind: str = "call",
    q: float = 0.0,
) -> OptionQuote:
    """Inverse-BTC option Greeks via central finite differences.

    Returns OptionQuote where:
      price  — in BTC per 1 BTC contract
      delta  — d(price_BTC)/dS
      gamma  — d^2(price_BTC)/dS^2
      vega   — d(price_BTC)/do  (per 1.00 absolute o change)
      theta  — -d(price_BTC)/dT (annualised)
      strike — K (USD)

    Finite-difference step sizes are chosen for numerical stability
    given typical BTC price range (10k-250k) and vol range (0.1-1.2).
    """


    price_val = price_inverse_btc(S, K, r, sigma, T, kind, q)

    # --- delta ----------------------------------------------------------------
    h_s = max(1e-4 * S, 1e-2)
    p_up = price_inverse_btc(S + h_s, K, r, sigma, T, kind, q)
    p_dn = price_inverse_btc(S - h_s, K, r, sigma, T, kind, q)
    delta_ = (p_up - p_dn) / (2.0 * h_s)

    # --- gamma ----------------------------------------------------------------
    gamma_ = (p_up - 2.0 * price_val + p_dn) / (h_s * h_s)

    # --- vega -----------------------------------------------------------------
    h_v = 1e-4
    p_v_up = price_inverse_btc(S, K, r, sigma + h_v, T, kind, q)
    p_v_dn = price_inverse_btc(S, K, r, sigma - h_v, T, kind, q)
    vega_ = (p_v_up - p_v_dn) / (2.0 * h_v)

    # --- theta (-dPrice/dT) ---------------------------------------------------
    h_t = 1e-6
    if h_t < T:
        p_t_up = price_inverse_btc(S, K, r, sigma, T + h_t, kind, q)
        p_t_dn = price_inverse_btc(S, K, r, sigma, T - h_t, kind, q)
        theta_ = -(p_t_up - p_t_dn) / (2.0 * h_t)
    else:
        theta_ = 0.0

    return OptionQuote(
        price=float(price_val),
        delta=float(delta_),
        gamma=float(gamma_),
        vega=float(vega_),
        theta=float(theta_),
        strike=float(K),
    )
