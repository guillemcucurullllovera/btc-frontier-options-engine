"""C9 · M1.2 — COS pricer validation (the primary CF pricer).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. No calibration/live data.

Oracles: (1) COS-GBM vs the analytical Black-Scholes to machine epsilon; (2) COS-Heston vs
QuantLib's independent AnalyticHestonEngine + the pinned Fang-Oosterlee golden 5.785155;
(3) COS-VG vs the Fang-Oosterlee golden 19.099355; (4) COS digital vs analytic N(d2)e^{-rT}.
"""

from __future__ import annotations

import math

import pytest
import QuantLib as ql
from scipy.stats import norm

from pricing.black_scholes import price as bs_price
from pricing.cf.characteristic_functions import CGMY, GBM, Heston, VarianceGamma
from pricing.cf.cos import cos_call, cos_digital, cos_price, cos_put


def _ql_heston_call(S0: float, K: float, T_days: int, r: float, q: float,
                    v0: float, kappa: float, theta: float, sigma: float, rho: float) -> tuple[float, float]:
    today = ql.Date(1, 1, 2020)
    ql.Settings.instance().evaluationDate = today
    dc = ql.Actual365Fixed()
    mat = today + ql.Period(T_days, ql.Days)
    spot = ql.QuoteHandle(ql.SimpleQuote(S0))
    rf = ql.YieldTermStructureHandle(ql.FlatForward(today, r, dc))
    dv = ql.YieldTermStructureHandle(ql.FlatForward(today, q, dc))
    proc = ql.HestonProcess(rf, dv, spot, v0, kappa, theta, sigma, rho)
    eng = ql.AnalyticHestonEngine(ql.HestonModel(proc))
    opt = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call, K), ql.EuropeanExercise(mat))
    opt.setPricingEngine(eng)
    return float(opt.NPV()), float(dc.yearFraction(today, mat))


# ── (1) COS-GBM vs Black-Scholes: machine epsilon ─────────────────────────────


def test_cos_gbm_matches_black_scholes_machine_eps() -> None:
    S0, r, sigma = 100.0, 0.05, 0.25
    max_err = 0.0
    for T in (0.1, 0.5, 1.0, 2.0):
        m = GBM(r=r, q=0.0, sigma=sigma)
        for K in (70.0, 85.0, 100.0, 115.0, 130.0):
            for kind in ("call", "put"):
                err = abs(cos_price(m, S0, K, T, kind, N=256, L=10.0) - bs_price(S0, K, r, sigma, T, kind))
                max_err = max(max_err, err)
    assert max_err < 1e-11, f"max |COS-BS| = {max_err:.2e}"


def test_cos_gbm_with_dividend_yield() -> None:
    """COS with q>0 matches BS-with-carry via the forward (spot discounted by q)."""
    S0, K, r, q, sigma, T = 100.0, 100.0, 0.05, 0.03, 0.30, 1.0
    m = GBM(r=r, q=q, sigma=sigma)
    # BS-with-dividend: price on forward-adjusted spot.
    fwd_spot = S0 * math.exp(-q * T)
    disc_bs = bs_price(fwd_spot, K * math.exp(-r * T), 0.0, sigma, T, "call")
    assert cos_price(m, S0, K, T, "call", N=512, L=12.0) == pytest.approx(disc_bs, abs=1e-9)


# ── (2) COS-Heston vs QuantLib + Fang-Oosterlee golden ────────────────────────


def test_cos_heston_matches_quantlib() -> None:
    """COS-Heston matches QuantLib's independent AnalyticHestonEngine across strikes."""
    p = {"v0": 0.0175, "kappa": 1.5768, "theta": 0.0398, "sigma": 0.5751, "rho": -0.5711}
    m = Heston(r=0.0, q=0.0, **p)
    max_err = 0.0
    for K in (80.0, 90.0, 100.0, 110.0, 120.0):
        ql_px, T = _ql_heston_call(100.0, K, 365, 0.0, 0.0, **p)
        cos_px = cos_call(m, 100.0, K, T, N=2048, L=16.0)
        max_err = max(max_err, abs(cos_px - ql_px))
    assert max_err < 1e-5, f"max |COS-QuantLib Heston| = {max_err:.2e}"


def test_cos_heston_fang_oosterlee_golden() -> None:
    """Pinned Fang-Oosterlee / QuantLib golden: K=100 call = 5.785155."""
    m = Heston(r=0.0, q=0.0, v0=0.0175, kappa=1.5768, theta=0.0398, sigma=0.5751, rho=-0.5711)
    assert cos_call(m, 100.0, 100.0, 1.0, N=2048, L=16.0) == pytest.approx(5.785155, abs=1e-5)


def test_cos_heston_needs_larger_L_documented() -> None:
    """Heston uses c4=0, so truncation error shrinks with L (documents the knob)."""
    m = Heston(r=0.0, q=0.0, v0=0.0175, kappa=1.5768, theta=0.0398, sigma=0.5751, rho=-0.5711)
    err_l10 = abs(cos_call(m, 100.0, 100.0, 1.0, N=2048, L=10.0) - 5.785155)
    err_l16 = abs(cos_call(m, 100.0, 100.0, 1.0, N=2048, L=16.0) - 5.785155)
    assert err_l16 < err_l10          # larger L => tighter (c4=0 truncation shrinks)
    assert err_l16 < 1e-5


# ── (3) COS-VG / CGMY published references ────────────────────────────────────


def test_cos_vg_fang_oosterlee_golden() -> None:
    """Fang-Oosterlee VG golden: S0=100,K=90,r=0.1,T=1,sigma=0.12,theta=-0.14,nu=0.2 -> 19.099355."""
    m = VarianceGamma(r=0.1, q=0.0, sigma=0.12, theta=-0.14, nu=0.2)
    assert cos_call(m, 100.0, 90.0, 1.0, N=1024, L=12.0) == pytest.approx(19.099355, abs=1e-5)


def test_cos_cgmy_reference_and_monotone_in_Y() -> None:
    """CGMY (C=1,G=5,M=5,Y=0.5) ATM call reference; price increases with the tail index Y."""
    ref = cos_call(CGMY(r=0.1, q=0.0, C=1.0, G=5.0, M=5.0, Y=0.5), 100.0, 100.0, 1.0, N=4096, L=16.0)
    assert ref == pytest.approx(19.812949, abs=1e-4)
    prices = [cos_call(CGMY(r=0.1, q=0.0, C=1.0, G=5.0, M=5.0, Y=Y), 100.0, 100.0, 1.0, N=4096, L=16.0)
              for Y in (0.2, 0.5, 0.9, 1.5)]
    assert prices == sorted(prices)          # monotone increasing in Y


# ── (4) digitals + parity + structural properties ────────────────────────────


def test_cos_digital_matches_analytic() -> None:
    """Cash-or-nothing digital call = e^{-rT} N(d2) (analytic, machine eps)."""
    S0, r, sigma, T = 100.0, 0.05, 0.25, 1.0
    m = GBM(r=r, q=0.0, sigma=sigma)
    for K in (90.0, 100.0, 110.0):
        d2 = (math.log(S0 / K) + (r - 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        analytic = math.exp(-r * T) * float(norm.cdf(d2))
        assert cos_digital(m, S0, K, T, "call", N=512, L=10.0) == pytest.approx(analytic, abs=1e-10)


def test_cos_put_call_parity_exact() -> None:
    """cos_call - cos_put == S0 e^{-qT} - K e^{-rT} (parity, exact by construction)."""
    m = Heston(r=0.03, q=0.01, v0=0.04, kappa=1.5, theta=0.04, sigma=0.5, rho=-0.6)
    S0, K, T = 100.0, 105.0, 0.75
    c = cos_call(m, S0, K, T, N=1024, L=14.0)
    p = cos_put(m, S0, K, T, N=1024, L=14.0)
    parity = S0 * math.exp(-m.q * T) - K * math.exp(-m.r * T)
    assert (c - p) == pytest.approx(parity, abs=1e-10)


def test_cos_put_priced_directly_avoids_cancellation() -> None:
    """The put is priced directly (bounded integrand) and matches BS to machine eps."""
    S0, K, r, sigma, T = 100.0, 100.0, 0.05, 0.25, 1.0
    m = GBM(r=r, q=0.0, sigma=sigma)
    assert cos_put(m, S0, K, T, N=256, L=10.0) == pytest.approx(bs_price(S0, K, r, sigma, T, "put"), abs=1e-11)


def test_cos_prices_positive_and_monotone_in_strike() -> None:
    m = Heston(r=0.02, q=0.0, v0=0.05, kappa=2.0, theta=0.05, sigma=0.4, rho=-0.5)
    strikes = [60.0, 80.0, 100.0, 120.0, 140.0]
    calls = [cos_call(m, 100.0, K, 1.0, N=1024, L=14.0) for K in strikes]
    puts = [cos_put(m, 100.0, K, 1.0, N=1024, L=14.0) for K in strikes]
    assert all(c > 0 for c in calls) and all(p > 0 for p in puts)
    assert calls == sorted(calls, reverse=True)     # call decreasing in K
    assert puts == sorted(puts)                      # put increasing in K
