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

Pricing derivation (Amendment A-2026-07-29 / FRF-015):
  An inverse option SETTLES IN BTC and pays max(F_T - K, 0)/F_T BTC per contract.
  It must therefore be priced under the STOCK (BTC) numeraire, NOT the USD
  money-market numeraire — so the discount factor is exp(-qT) (BTC convenience
  yield / borrow), NOT exp(-rT).

    F = S · exp((r - q) · T)

  The inverse call pays the holder at expiry:
    max(F_T - K, 0) / F_T   BTC per 1 BTC contract

  Present value in BTC (stock numeraire):
    C_inv = exp(-qT) · [N(d₁) - (K/F) · N(d₂)]

  The inverse put via put-call parity:
    P_inv = C_inv - exp(-qT) · (1 - K/F)

  where:
    d₁ = [ln(F/K) + sigma²T/2] / (sigma√T)
    d₂ = d₁ - sigma√T

  Verification anchors (no official pre-expiry mark vector — MS-9/MS-10):
    - No-arbitrage at q=0:  price_BTC · S == Black-Scholes USD price.
    - Deep-ITM (K→0):       C_inv → exp(-qT)  (→ 1.0 BTC at q=0).
  q=0 is an ASSUMED default (no observed BTC convenience-yield source — MS-11).

  Greeks are computed via central finite differences on the analytical price.
  Do NOT implement formulas from the reconciled audit §10.8.

C9 · M0.1 amendment (SIMULATED / diagnostic; MS-26-gated; deck parked — does not
touch canonical main). Three cross-cutting inverse-layer corrections:

  * B2 — premium-adjusted exchange delta. ``greeks_inverse_btc().delta`` now reports
    the Deribit/coin-margined convention Δ_BTC = Δ_USD - V_USD/S (Lucic-Sepp,
    "Applied Bitcoin Options", Cor.1), where Δ_USD is the USD-value delta derived
    from the Black-76 forward greek and V_USD = price_BTC·S. The raw d(price_BTC)/dS
    (the old return) is retained but SEPARATELY LABELLED in ``InverseGreeksReport``.
    Identity: Δ_BTC = Δ_USD - price_BTC = S·d(price_BTC)/dS.
  * B3 — marking convention. Deribit marks inverse options with r = q = 0 off the
    OBSERVED forward (Black-76 on F), not r=0.04-off-spot. ``price_inverse_btc_forward``
    prices directly off an observed forward; nonzero r/q must be provenance-tagged.
  * B4 — carry q is an ASSUMED assumption (MS-11). ``carry_sensitivity`` reports the
    CALCULATED USD-equivalent price shift at q=2/5/10% for the actual (S,K,sigma,T),
    replacing the previously hard-coded constant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.errors import PricingError
from pricing.black76 import greeks_black76
from pricing.black_scholes import OptionQuote


def settlement_inverse_call_holder(delivery_price: float, strike: float) -> float:
    """Gross BTC settlement per 1 contract to the long call holder.

    Formula:  max(delivery_price - strike, 0) / delivery_price

    Source: deribitfilesascopiedtxt.txt §"Inverse Options" lines 1-199.
    For the SHORT WRITER, the cash flow is the NEGATION of this amount.

    Degenerate boundary (FRF-029 / AT-029): a non-positive delivery_price
    (e.g. the S_T→0 payoff-curve point) yields 0.0 rather than raising
    ZeroDivisionError. The USD-equivalent (btc x delivery_price) is 0 there.
    """
    if delivery_price <= 0.0:
        return 0.0
    return float(max(delivery_price - strike, 0.0) / delivery_price)


def settlement_inverse_put_holder(delivery_price: float, strike: float) -> float:
    """Gross BTC settlement per 1 contract to the long put holder.

    Formula:  max(strike - delivery_price, 0) / delivery_price

    For the SHORT WRITER, the cash flow is the NEGATION of this amount.
    Non-positive delivery_price yields 0.0 (see call variant; AT-029).
    """
    if delivery_price <= 0.0:
        return 0.0
    return float(max(strike - delivery_price, 0.0) / delivery_price)


def _validate_pricing_inputs(S: float, K: float, sigma: float, T: float, kind: str) -> None:
    if kind not in ("call", "put"):
        raise PricingError(f"kind must be 'call' or 'put', got {kind!r}")
    if not (S > 0.0 and K > 0.0 and sigma > 0.0 and T > 0.0):
        raise PricingError(
            "price_inverse_btc requires strictly positive S, K, sigma, T; got "
            f"S={S}, K={K}, sigma={sigma}, T={T}"
        )


def _d1_d2(F: float, K: float, sigma: float, T: float) -> tuple[float, float]:
    sqT = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqT)
    return d1, d1 - sigma * sqT


def _call_price_raw(F: float, K: float, q: float, sigma: float, T: float) -> float:
    """Core inverse BTC call price in BTC per 1 BTC contract.

    C_inv = exp(-qT) · [N(d₁) - (K/F) · N(d₂)],  F = S · exp((r-q)·T).
    Discount is exp(-qT) (BTC/stock numeraire), NOT exp(-rT); deep-ITM K→0
    limit is exp(-qT). See module docstring / contracts §7.3 amendment.
    """

    import math as _m

    from scipy.stats import norm as _norm

    d1, d2 = _d1_d2(F, K, sigma, T)
    btc_df = _m.exp(-q * T)

    return float(btc_df * (_norm.cdf(d1) - (K / F) * _norm.cdf(d2)))


def _put_price_raw(F: float, K: float, q: float, sigma: float, T: float) -> float:
    """Core inverse BTC put price in BTC per 1 BTC contract.

    Via put-call parity: P_inv = C_inv - exp(-qT) · (1 - K/F).
    """

    import math as _m

    from scipy.stats import norm as _norm

    d1, d2 = _d1_d2(F, K, sigma, T)
    btc_df = _m.exp(-q * T)

    return float(btc_df * ((K / F) * _norm.cdf(-d2) - _norm.cdf(-d1)))


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

    Forward: F = S · exp((r - q) · T). Discount factor exp(-qT) (BTC numeraire).
    No-arbitrage anchor (q=0): price_inverse_btc · S == Black-Scholes USD price.
    Raises PricingError on non-positive S/K/sigma/T or an invalid `kind`.
    """

    import math as _m

    _validate_pricing_inputs(S, K, sigma, T, kind)
    F = S * _m.exp((r - q) * T)

    if kind == "call":
        return _call_price_raw(F, K, q, sigma, T)
    return _put_price_raw(F, K, q, sigma, T)


def price_inverse_btc_forward(
    F: float, K: float, sigma: float, T: float, kind: str = "call", q: float = 0.0,
) -> float:
    """Inverse-BTC price marked off an OBSERVED forward F (B3 / Deribit convention).

    Deribit marks inverse options with r = q = 0 off the observed future (Black-76
    on F), NOT r=0.04-off-spot which injects a forward drift the exchange never
    applies. This is the canonical marking entry point: pass the observed forward
    (Deribit ``book_summary.underlying_price`` for that expiry) directly.

    Discount is exp(-qT) under the BTC (stock) numeraire; q=0 (the ASSUMED default,
    MS-11) gives an undiscounted Black-76-on-F price. Any nonzero r/q used to *derive*
    F must be provenance-tagged by the caller (the exchange uses neither).

    At q=0 the no-arbitrage identity holds: price_inverse_btc_forward(F,...)·F equals
    the Black-76 USD price on F (undiscounted, r=0).
    """
    _validate_pricing_inputs(F, K, sigma, T, kind)
    if kind == "call":
        return _call_price_raw(F, K, q, sigma, T)
    return _put_price_raw(F, K, q, sigma, T)


@dataclass(frozen=True)
class InverseGreeksReport:
    """Fully-labelled inverse-option greek reconciliation (B2).

    Keeps the exchange-convention delta and the raw price-sensitivity as DISTINCT,
    explicitly-named quantities so neither is silently conflated (orchestration §5.4).
    """

    price_btc: float             # option premium, BTC per 1 BTC contract
    value_usd: float             # V_USD = price_btc · S
    delta_exchange_btc: float    # Δ_BTC = Δ_USD - V_USD/S  (Deribit / Lucic-Sepp Cor.1)
    delta_usd: float             # Δ_USD = d(V_USD)/dS, from the Black-76 forward greek
    dprice_btc_dS: float         # raw d(price_BTC)/dS = Δ_BTC / S (the pre-B2 return)
    gamma_btc: float             # d²(price_BTC)/dS²
    vega_btc: float              # d(price_BTC)/dsigma, per 1.00 absolute sigma
    theta_btc: float             # -d(price_BTC)/dT, annualised
    q: float                     # carry used (ASSUMED default 0.0, MS-11)
    reconciliation_residual: float  # |Δ_BTC - (Δ_USD - V_USD/S)|, must be ~0


def _btc_price_fd_greeks(
    S: float, K: float, r: float, sigma: float, T: float, kind: str, q: float,
) -> tuple[float, float, float, float, float]:
    """Central-difference (price_btc, d/dS, d²/dS², d/dsigma, -d/dT) of the BTC price."""
    price_val = price_inverse_btc(S, K, r, sigma, T, kind, q)

    h_s = max(1e-4 * S, 1e-2)
    p_up = price_inverse_btc(S + h_s, K, r, sigma, T, kind, q)
    p_dn = price_inverse_btc(S - h_s, K, r, sigma, T, kind, q)
    dprice_dS = (p_up - p_dn) / (2.0 * h_s)
    gamma_ = (p_up - 2.0 * price_val + p_dn) / (h_s * h_s)

    h_v = 1e-4
    p_v_up = price_inverse_btc(S, K, r, sigma + h_v, T, kind, q)
    p_v_dn = price_inverse_btc(S, K, r, sigma - h_v, T, kind, q)
    vega_ = (p_v_up - p_v_dn) / (2.0 * h_v)

    h_t = 1e-6
    if h_t < T:
        p_t_up = price_inverse_btc(S, K, r, sigma, T + h_t, kind, q)
        p_t_dn = price_inverse_btc(S, K, r, sigma, T - h_t, kind, q)
        theta_ = -(p_t_up - p_t_dn) / (2.0 * h_t)
    else:
        theta_ = 0.0
    return price_val, dprice_dS, gamma_, vega_, theta_


def _delta_usd(S: float, K: float, r: float, sigma: float, T: float, kind: str, q: float) -> float:
    """Δ_USD = d(V_USD)/dS for an inverse option, derived from the Black-76 forward greek.

    V_USD(S) = price_black76(F(S), K, r, sigma, T) with F = S·exp((r-q)T), so
    Δ_USD = (dPrice76/dF)·(dF/dS) = greeks_black76(...).delta · exp((r-q)T)
          = exp(-qT)·N(d1) (call). Uses black76 greeks per the M0.1 mandate.
    """
    F = S * math.exp((r - q) * T)
    b76 = greeks_black76(F, K, r, sigma, T, kind)
    return float(b76.delta * math.exp((r - q) * T))


def inverse_greeks_report(
    S: float, K: float, r: float, sigma: float, T: float, kind: str = "call",
    q: float = 0.0,
) -> InverseGreeksReport:
    """Full B2 reconciliation: exchange delta, USD delta, and the raw price greek.

    Δ_BTC = Δ_USD - V_USD/S is the premium-adjusted exchange delta Deribit reports for
    coin-margined (inverse) options; V_USD/S = price_btc, so Δ_BTC = Δ_USD - price_btc.
    Validate vs an independent oracle (QuantLib div-yield delta - NPV/S) in tests.
    """
    price_val, dprice_dS, gamma_, vega_, theta_ = _btc_price_fd_greeks(S, K, r, sigma, T, kind, q)
    value_usd = price_val * S
    delta_usd = _delta_usd(S, K, r, sigma, T, kind, q)
    delta_btc = delta_usd - price_val  # = delta_usd - value_usd/S
    return InverseGreeksReport(
        price_btc=float(price_val),
        value_usd=float(value_usd),
        delta_exchange_btc=float(delta_btc),
        delta_usd=float(delta_usd),
        dprice_btc_dS=float(dprice_dS),
        gamma_btc=float(gamma_),
        vega_btc=float(vega_),
        theta_btc=float(theta_),
        q=float(q),
        reconciliation_residual=abs(delta_btc - (delta_usd - value_usd / S)),
    )


def greeks_inverse_btc(
    S: float, K: float, r: float, sigma: float, T: float, kind: str = "call",
    q: float = 0.0,
) -> OptionQuote:
    """Inverse-BTC option Greeks (B2: premium-adjusted exchange delta).

    Returns OptionQuote where:
      price  — in BTC per 1 BTC contract
      delta  — Δ_BTC = Δ_USD - V_USD/S, the Deribit premium-adjusted EXCHANGE delta
               (coin-margined convention, Lucic-Sepp Cor.1). This is the BTC-equivalent
               hedge/aggregation delta — consistent units with a +1-per-BTC spot leg.
               The raw d(price_BTC)/dS (= Δ_BTC/S, the pre-B2 value) is available,
               separately labelled, via ``inverse_greeks_report``.
      gamma  — d^2(price_BTC)/dS^2   (BTC-price sensitivity, unchanged)
      vega   — d(price_BTC)/do       (per 1.00 absolute o change)
      theta  — -d(price_BTC)/dT      (annualised)
      strike — K (USD)

    Finite-difference step sizes are chosen for numerical stability given the typical
    BTC price range (10k-250k) and vol range (0.1-1.2). Δ_USD is analytic (Black-76).
    """
    price_val, _dprice_dS, gamma_, vega_, theta_ = _btc_price_fd_greeks(S, K, r, sigma, T, kind, q)
    delta_btc = _delta_usd(S, K, r, sigma, T, kind, q) - price_val

    return OptionQuote(
        price=float(price_val),
        delta=float(delta_btc),
        gamma=float(gamma_),
        vega=float(vega_),
        theta=float(theta_),
        strike=float(K),
    )


def carry_sensitivity(
    S: float, K: float, r: float, sigma: float, T: float, kind: str = "call",
    qs: tuple[float, ...] = (0.02, 0.05, 0.10),
) -> dict[str, float]:
    """B4: CALCULATED USD-equivalent inverse-price shift vs the q=0 baseline, per carry q.

    Carry q (BTC convenience yield/borrow) is an ASSUMED input (MS-11) defaulting to 0,
    at which the USD-equivalent price equals the linear Black-Scholes USD price exactly.
    A nonzero q shifts the USD-equivalent price V_USD(q) = price_inverse_btc(...,q)·S;
    this returns 100·(V_USD(q) - V_USD(0))/V_USD(0) for each q in ``qs``.

    Keys are ``q_2pct`` etc. (percent of the carry). Values are provenance CALCULATED —
    they replace the previously hard-coded {-1.4,-3.4,-6.7} constant, which was an
    illustrative short-dated approximation and is tenor/strike-dependent.
    """
    base = price_inverse_btc(S, K, r, sigma, T, kind, 0.0) * S
    if base <= 0.0:
        raise PricingError("carry_sensitivity requires a positive q=0 baseline price")
    out: dict[str, float] = {}
    for q in qs:
        v = price_inverse_btc(S, K, r, sigma, T, kind, q) * S
        out[f"q_{round(q * 100)}pct"] = 100.0 * (v - base) / base
    return out
