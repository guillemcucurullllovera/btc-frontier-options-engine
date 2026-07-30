"""C9 · M0.1 — inverse-layer correctness (B2 exchange delta, B3 forward marking, B4 carry).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched.

Independent oracle: QuantLib. The premium-adjusted exchange delta Δ_BTC = Δ_USD - V_USD/S
is reconstructed independently from a QuantLib BlackScholesMerton engine
(dividend-yield q) as ``option.delta() - option.NPV()/S`` and compared to our
``greeks_inverse_btc`` / ``inverse_greeks_report``. The carry sensitivity (B4) is
cross-checked against the QuantLib div-yield NPV shift.

Conventions verified against: Deribit inverse-option spec (r=q=0 off the observed
forward, Black-76 on F) and Lucic-Sepp "Applied Bitcoin Options" Cor.1.
"""

from __future__ import annotations

import math

import pytest

# U8 (SR 11-7): QuantLib is a DECLARED, pinned validation dependency — the external
# pricing anchor must ALWAYS run in CI, never silently skip. A missing QuantLib is a
# hard collection error (loud), not a skip.
import QuantLib as ql

from pricing.black76 import price_black76
from pricing.inverse import (
    InverseGreeksReport,
    carry_sensitivity,
    greeks_inverse_btc,
    inverse_greeks_report,
    price_inverse_btc,
    price_inverse_btc_forward,
)

# Representative BTC-scale parameter grid (spot, strike, r, sigma, days, kind, q).
_CASES: tuple[tuple[float, float, float, float, int, str, float], ...] = (
    (64_508.0, 64_508.0, 0.0, 0.49, 30, "call", 0.0),
    (64_508.0, 72_000.0, 0.0, 0.49, 30, "call", 0.0),
    (64_508.0, 58_000.0, 0.0, 0.52, 45, "put", 0.0),
    (64_508.0, 64_508.0, 0.04, 0.45, 45, "call", 0.0),
    (64_508.0, 70_000.0, 0.04, 0.60, 60, "call", 0.02),
    (64_508.0, 55_000.0, 0.04, 0.65, 60, "put", 0.05),
    (30_000.0, 30_000.0, 0.0, 0.80, 90, "call", 0.0),
    (120_000.0, 100_000.0, 0.03, 0.55, 30, "put", 0.10),
)


def _ql_setup(
    S: float, K: float, r: float, sigma: float, days: int, kind: str, q: float,
) -> tuple[ql.VanillaOption, float]:
    """Build a QuantLib European option; return (option, exact_T)."""
    today = ql.Date(15, 7, 2026)
    ql.Settings.instance().evaluationDate = today
    dc = ql.Actual365Fixed()
    cal = ql.NullCalendar()
    expiry = today + int(days)
    T = dc.yearFraction(today, expiry)

    ql_kind = ql.Option.Call if kind == "call" else ql.Option.Put
    payoff = ql.PlainVanillaPayoff(ql_kind, K)
    exercise = ql.EuropeanExercise(expiry)
    spot_h = ql.QuoteHandle(ql.SimpleQuote(S))
    rf = ql.YieldTermStructureHandle(ql.FlatForward(today, r, dc))
    div = ql.YieldTermStructureHandle(ql.FlatForward(today, q, dc))
    vol = ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today, cal, sigma, dc))
    process = ql.BlackScholesMertonProcess(spot_h, div, rf, vol)
    option = ql.VanillaOption(payoff, exercise)
    option.setPricingEngine(ql.AnalyticEuropeanEngine(process))
    return option, T


# ── B2 — premium-adjusted exchange delta ──────────────────────────────────────


def test_b2_exchange_delta_matches_quantlib_oracle() -> None:
    """Δ_BTC (our) == option.delta() - option.NPV()/S (independent QuantLib)."""
    max_err = 0.0
    for S, K, r, sigma, days, kind, q in _CASES:
        option, T = _ql_setup(S, K, r, sigma, days, kind, q)
        # Δ_BTC = Δ_USD - V_USD/S, both from QuantLib (div-yield q process).
        oracle = float(option.delta() - option.NPV() / S)
        ours = greeks_inverse_btc(S, K, r, sigma, T, kind, q).delta
        max_err = max(max_err, abs(ours - oracle))
    assert max_err < 1e-6, f"max Δ_BTC vs QuantLib oracle: {max_err:.2e}"


def test_b2_value_usd_matches_quantlib() -> None:
    """V_USD = price_inverse_btc·S reconciles to the QuantLib NPV (no-arb anchor)."""
    for S, K, r, sigma, days, kind, q in _CASES:
        option, T = _ql_setup(S, K, r, sigma, days, kind, q)
        v_usd = price_inverse_btc(S, K, r, sigma, T, kind, q) * S
        assert v_usd == pytest.approx(option.NPV(), abs=1e-5, rel=1e-8)


def test_b2_delta_usd_matches_quantlib() -> None:
    """Δ_USD (from the Black-76 forward greek) matches the QuantLib spot delta."""
    for S, K, r, sigma, days, kind, q in _CASES:
        option, T = _ql_setup(S, K, r, sigma, days, kind, q)
        rep = inverse_greeks_report(S, K, r, sigma, T, kind, q)
        assert rep.delta_usd == pytest.approx(option.delta(), abs=1e-6)


def test_b2_reconciliation_identity() -> None:
    """Δ_BTC == Δ_USD - V_USD/S == S·d(price_BTC)/dS (internal identity, residual ~0)."""
    for S, K, r, sigma, days, kind, q in _CASES:
        _, T = _ql_setup(S, K, r, sigma, days, kind, q)
        rep = inverse_greeks_report(S, K, r, sigma, T, kind, q)
        assert rep.reconciliation_residual < 1e-12
        # Δ_BTC = S · d(price_BTC)/dS  (the pre-B2 return was Δ_BTC/S).
        assert rep.delta_exchange_btc == pytest.approx(S * rep.dprice_btc_dS, rel=1e-5, abs=1e-8)
        # greeks_inverse_btc surfaces the exchange delta, not the raw price greek.
        q_quote = greeks_inverse_btc(S, K, r, sigma, T, kind, q)
        assert q_quote.delta == pytest.approx(rep.delta_exchange_btc, abs=1e-12)


def test_b2_raw_price_greek_still_fd_consistent() -> None:
    """The retained d(price_BTC)/dS matches a coarse central difference (pre-B2 quantity)."""
    for S, K, r, sigma, days, kind, q in _CASES:
        _, T = _ql_setup(S, K, r, sigma, days, kind, q)
        rep = inverse_greeks_report(S, K, r, sigma, T, kind, q)
        h = 10.0
        fd = (price_inverse_btc(S + h, K, r, sigma, T, kind, q)
              - price_inverse_btc(S - h, K, r, sigma, T, kind, q)) / (2.0 * h)
        assert rep.dprice_btc_dS == pytest.approx(fd, rel=1e-5, abs=1e-10)


def test_b2_exchange_delta_put_call_parity() -> None:
    """Δ_BTC_call - Δ_BTC_put == (K/S)·exp(-rT)  (independent parity identity)."""
    for S, K, r, sigma, days, _kind, q in _CASES:
        _, T = _ql_setup(S, K, r, sigma, days, "call", q)
        dc = greeks_inverse_btc(S, K, r, sigma, T, "call", q).delta
        dp = greeks_inverse_btc(S, K, r, sigma, T, "put", q).delta
        assert dc - dp == pytest.approx((K / S) * math.exp(-r * T), rel=1e-6, abs=1e-9)


def test_b2_report_is_frozen_labelled() -> None:
    """The report keeps exchange delta and raw price greek as distinct named fields."""
    rep = inverse_greeks_report(64_508.0, 64_508.0, 0.0, 0.49, 30 / 365.0, "call")
    assert isinstance(rep, InverseGreeksReport)
    # Distinct: exchange delta is O(1); the raw price greek is O(1/S) (~1e-5 scale).
    assert abs(rep.delta_exchange_btc) > 100.0 * abs(rep.dprice_btc_dS)


# ── B3 — marking convention (r=q=0 off the observed forward) ───────────────────


def test_b3_forward_marking_no_arb_identity() -> None:
    """price_inverse_btc_forward(F,...)·F == Black-76 USD price on F with r=0 (undiscounted)."""
    for F, K, sigma, T in ((64_508.0, 64_508.0, 0.49, 30 / 365.0),
                           (64_508.0, 72_000.0, 0.49, 45 / 365.0),
                           (64_508.0, 58_000.0, 0.52, 60 / 365.0)):
        for kind in ("call", "put"):
            pif = price_inverse_btc_forward(F, K, sigma, T, kind)
            b76_r0 = price_black76(F, K, 0.0, sigma, T, kind)
            assert pif * F == pytest.approx(b76_r0, rel=1e-10, abs=1e-10)


def test_b3_observed_forward_matches_spot_route_when_consistent() -> None:
    """Forward marking equals the spot route when F is the same forward (consistency)."""
    S, r, sigma, T = 64_508.0, 0.04, 0.49, 45 / 365.0
    K = 66_000.0
    F = S * math.exp(r * T)  # forward implied by the spot route
    for kind in ("call", "put"):
        spot_route = price_inverse_btc(S, K, r, sigma, T, kind)
        fwd_route = price_inverse_btc_forward(F, K, sigma, T, kind)
        assert fwd_route == pytest.approx(spot_route, rel=1e-12, abs=1e-14)


def test_b3_correction_changes_price_vs_r004_off_spot() -> None:
    """r=0.04-off-spot injects a drift the exchange never applies — a material difference.

    With an OBSERVED forward at/near spot (Deribit r=0), the correct mark differs from
    the r=0.04-off-spot mark; the gap grows with T (documents the B3 correction).
    """
    S, sigma = 64_508.0, 0.49
    F_obs = 64_490.0  # observed forward ≈ spot (Deribit marks r=q=0)
    for T in (30 / 365.0, 180 / 365.0):
        correct = price_inverse_btc_forward(F_obs, S, sigma, T, "call")
        wrong = price_inverse_btc(S, S, 0.04, sigma, T, "call")  # F = S·e^{0.04T}
        assert wrong != pytest.approx(correct, rel=1e-4)
    # Longer T ⇒ larger injected-drift gap.
    gap_30 = abs(price_inverse_btc(S, S, 0.04, sigma, 30 / 365.0, "call")
                 - price_inverse_btc_forward(F_obs, S, sigma, 30 / 365.0, "call"))
    gap_180 = abs(price_inverse_btc(S, S, 0.04, sigma, 180 / 365.0, "call")
                  - price_inverse_btc_forward(F_obs, S, sigma, 180 / 365.0, "call"))
    assert gap_180 > gap_30


# ── B4 — carry q sensitivity (CALCULATED, MS-11 ASSUMED input) ─────────────────


def test_b4_carry_sensitivity_sign_and_monotonicity() -> None:
    """Positive carry lowers the USD-equivalent price; magnitude grows with q and T."""
    S, K, r, sigma = 64_508.0, 64_508.0, 0.0, 0.49
    prev_by_T: dict[str, float] = {}
    for days in (30, 60, 180):
        sens = carry_sensitivity(S, K, r, sigma, days / 365.0, "call")
        vals = [sens["q_2pct"], sens["q_5pct"], sens["q_10pct"]]
        assert all(v < 0.0 for v in vals)                    # carry ⇒ price down
        assert vals[0] > vals[1] > vals[2]                   # |shift| increases with q
        if prev_by_T:
            # |shift| increases with T at each q.
            assert sens["q_5pct"] < prev_by_T["q_5pct"]
        prev_by_T = sens


def test_b4_carry_sensitivity_matches_quantlib() -> None:
    """CALCULATED carry sensitivity matches the QuantLib div-yield NPV shift (oracle)."""
    S, K, sigma, days, kind = 64_508.0, 64_508.0, 0.49, 45, "call"
    option0, T = _ql_setup(S, K, 0.0, sigma, days, kind, 0.0)
    base = option0.NPV()
    sens = carry_sensitivity(S, K, 0.0, sigma, T, kind)
    for q, key in ((0.02, "q_2pct"), (0.05, "q_5pct"), (0.10, "q_10pct")):
        opt_q, _ = _ql_setup(S, K, 0.0, sigma, days, kind, q)
        oracle_pct = 100.0 * (opt_q.NPV() - base) / base
        assert sens[key] == pytest.approx(oracle_pct, abs=0.02)


def test_b4_carry_sensitivity_reports_true_values_not_stale_constant() -> None:
    """The prior hard-coded {-1.4,-3.4,-6.7} does NOT reproduce; report the true numbers.

    Documents that the constant was a tenor/strike-specific approximation. For a 30d ATM
    call the CALCULATED shift is ≈ -1.5/-3.8/-7.6%, materially different from -1.4/-3.4/-6.7.
    """
    sens = carry_sensitivity(64_508.0, 64_508.0, 0.0, 0.49, 30 / 365.0, "call")
    assert sens["q_2pct"] == pytest.approx(-1.54, abs=0.15)
    assert sens["q_5pct"] == pytest.approx(-3.82, abs=0.20)
    assert sens["q_10pct"] == pytest.approx(-7.55, abs=0.30)
