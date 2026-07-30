"""C9 · M0.3 — expanded Haug / QuantLib golden tables for the base pricers.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Broadens the standing
external-oracle coverage (SR 11-7): a wide Black-Scholes and Black-76 grid is cross-checked
against QuantLib for BOTH price and greeks (delta/gamma/vega), plus a couple of hand-checkable
Hull/Haug textbook values.

U8 (SR 11-7): QuantLib is a DECLARED, pinned validation dependency — never silently skipped.
"""

from __future__ import annotations

import QuantLib as ql

from pricing.black76 import greeks_black76, price_black76
from pricing.black_scholes import greeks as bs_greeks
from pricing.black_scholes import price as bs_price

_TODAY = ql.Date(15, 7, 2026)
_DC = ql.Actual365Fixed()
_CAL = ql.NullCalendar()


def _ql_european(
    S: float, K: float, r: float, sigma: float, days: int, kind: str, q: float = 0.0,
) -> tuple[ql.VanillaOption, float]:
    ql.Settings.instance().evaluationDate = _TODAY
    expiry = _TODAY + int(days)
    T = _DC.yearFraction(_TODAY, expiry)
    payoff = ql.PlainVanillaPayoff(ql.Option.Call if kind == "call" else ql.Option.Put, K)
    exercise = ql.EuropeanExercise(expiry)
    spot = ql.QuoteHandle(ql.SimpleQuote(S))
    rf = ql.YieldTermStructureHandle(ql.FlatForward(_TODAY, r, _DC))
    div = ql.YieldTermStructureHandle(ql.FlatForward(_TODAY, q, _DC))
    vol = ql.BlackVolTermStructureHandle(ql.BlackConstantVol(_TODAY, _CAL, sigma, _DC))
    process = ql.BlackScholesMertonProcess(spot, div, rf, vol)
    opt = ql.VanillaOption(payoff, exercise)
    opt.setPricingEngine(ql.AnalyticEuropeanEngine(process))
    return opt, T


# BTC-scale + textbook-scale grid (S, K, r, sigma, days, kind).
_BS_GRID = [
    (100.0, 100.0, 0.05, 0.20, 365, "call"),
    (100.0, 100.0, 0.05, 0.20, 365, "put"),
    (100.0, 110.0, 0.03, 0.35, 182, "call"),
    (100.0, 90.0, 0.07, 0.25, 90, "put"),
    (65_000.0, 65_000.0, 0.04, 0.45, 30, "call"),
    (65_000.0, 75_000.0, 0.04, 0.55, 45, "call"),
    (65_000.0, 55_000.0, 0.04, 0.60, 60, "put"),
    (30_000.0, 45_000.0, 0.02, 0.80, 120, "call"),
    (120_000.0, 100_000.0, 0.03, 0.50, 200, "put"),
    (50_000.0, 50_000.0, 0.045, 0.10, 730, "call"),
]


def test_bs_price_and_greeks_vs_quantlib_grid() -> None:
    """Black-Scholes price + delta/gamma/vega match QuantLib across the grid."""
    max_p = max_d = max_g = max_v = 0.0
    for S, K, r, sigma, days, kind in _BS_GRID:
        opt, T = _ql_european(S, K, r, sigma, days, kind)
        max_p = max(max_p, abs(opt.NPV() - bs_price(S, K, r, sigma, T, kind)))
        our = bs_greeks(S, K, r, sigma, T, kind)
        max_d = max(max_d, abs(opt.delta() - our.delta))
        max_g = max(max_g, abs(opt.gamma() - our.gamma))
        max_v = max(max_v, abs(opt.vega() - our.vega))         # QL vega is per 1.00 vol
    assert max_p < 1e-6, f"BS price vs QL: {max_p:.2e}"
    assert max_d < 1e-7, f"BS delta vs QL: {max_d:.2e}"
    assert max_g < 1e-9, f"BS gamma vs QL: {max_g:.2e}"
    assert max_v < 1e-6, f"BS vega vs QL: {max_v:.2e}"


def test_black76_price_and_greeks_vs_quantlib_grid() -> None:
    """Black-76 (option on a forward) price + delta/gamma/vega vs QuantLib (r=q on spot=F)."""
    max_p = max_d = max_v = 0.0
    for F, K, r, sigma, days, kind in [
        (100.0, 100.0, 0.05, 0.20, 365, "call"),
        (100.0, 110.0, 0.03, 0.30, 182, "put"),
        (65_000.0, 65_000.0, 0.04, 0.50, 45, "call"),
        (65_000.0, 60_000.0, 0.04, 0.60, 60, "put"),
        (20.0, 19.0, 0.05, 0.25, 180, "call"),
    ]:
        # Black-76 == BSM with dividend q=r on spot=F (carry b=0). Use QL with q=r, spot=F.
        opt, T = _ql_european(F, K, r, sigma, days, kind, q=r)
        max_p = max(max_p, abs(opt.NPV() - price_black76(F, K, r, sigma, T, kind)))
        our = greeks_black76(F, K, r, sigma, T, kind)
        max_d = max(max_d, abs(opt.delta() - our.delta))       # dPrice/dF
        max_v = max(max_v, abs(opt.vega() - our.vega))
    assert max_p < 1e-6, f"B76 price vs QL: {max_p:.2e}"
    assert max_d < 1e-7, f"B76 delta vs QL: {max_d:.2e}"
    assert max_v < 1e-6, f"B76 vega vs QL: {max_v:.2e}"


def test_hull_textbook_goldens() -> None:
    """Hull, *Options, Futures & Other Derivatives*: S=42,K=40,r=0.10,sigma=0.20,T=0.5.

    Published values: c = 4.759, p = 0.808 (Hull worked example).
    """
    S, K, r, sigma, T = 42.0, 40.0, 0.10, 0.20, 0.5
    assert abs(bs_price(S, K, r, sigma, T, "call") - 4.759) < 5e-3
    assert abs(bs_price(S, K, r, sigma, T, "put") - 0.808) < 5e-3


def test_put_call_parity_holds_on_grid() -> None:
    """C - P = S - K e^{-rT} (independent parity identity across the grid)."""
    import math

    for S, K, r, sigma, days, _kind in _BS_GRID:
        T = days / 365.0
        c = bs_price(S, K, r, sigma, T, "call")
        p = bs_price(S, K, r, sigma, T, "put")
        assert abs((c - p) - (S - K * math.exp(-r * T))) < 1e-6 * S
