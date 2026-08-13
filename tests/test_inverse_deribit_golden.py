"""Inverse-pricer certification: PR-DISC / PR-THETA guards + Deribit OBSERVED-mark goldens.

A2 Track 1/2/3. This module CERTIFIES already-correct code (FRF-015 discount split,
FRF-016 put-theta); it locks the fixes, it does not require a code change.

Register hygiene (A2 §0.4 / item 4): the old "F17/F18" labels collided across the workspace.
Renamed here to remove the collision:
  * PR-DISC  = inverse discount-factor split  (was "F17"; the coin/Phi(d1) leg carries e^{-qT},
               the strike/Phi(d2) leg carries e^{-rT} — never a single e^{-rT} on the whole price).
  * PR-THETA = Black-76 put-theta sign        (was "F18"; a CME / USD-leg item, NOT inverse-specific).
At Deribit's own r=q=0 marking PR-DISC is economically inert on the inverse leg — it is a latent
correctness guard whose real bite is the CME USD-settled Black-76 leg and any r>0 scenario/greek run.

Track 3 correction (IMPORTANT, from the live capture): Deribit's ticker ``greeks.delta`` matches the
Black-76 FORWARD delta N(d1) ( = the USD-value delta Delta_USD at r=q=0 ), NOT the premium-adjusted
exchange delta Delta_BTC = Delta_USD - premium that A2 §4 assumed. Measured on the OBSERVED snapshot the
plain forward delta matches Deribit to < 5e-4 across all tenors, while the premium-adjusted delta is off
by up to ~0.09 on longer-dated ATM strikes. The certification below therefore anchors Deribit's reported
delta to the forward delta and separately re-derives the premium-adjusted Delta_BTC as Delta_USD - premium
(Lucic-Sepp Cor.1) — a distinct coin-hedge quantity, not what the ticker prints.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest
from scipy.stats import norm

from pricing import black_scholes
from pricing.black76 import greeks_black76, price_black76
from pricing.inverse import (
    price_inverse_btc,
    price_inverse_btc_forward,
    settlement_inverse_call_holder,
    settlement_inverse_put_holder,
)

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "deribit_ticker_goldens.json"


# ── PR-DISC — inverse discount-factor split (was F17) ─────────────────────────
# The coin / Phi(d1) leg carries e^{-qT}; the strike / Phi(d2) leg carries e^{-rT}. The bug is
# discounting the WHOLE inverse price by a single e^{-rT}. At r=q=0 every DF=1 and the bug is
# invisible — every discriminator below uses r != 0.


class TestPRDiscInverseDiscountSplit:
    def test_prdisc_a_strike_only_df_and_bug_rejected(self) -> None:
        """PR-DISC.a: code == strike-only-DF analytic; the whole-price-DF bug is rejected."""
        S, sig, T = 64_508.0, 0.49, 45 / 365.0
        for r in (0.04, 0.10):
            K = S
            F = S * math.exp(r * T)
            d1 = (math.log(F / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
            d2 = d1 - sig * math.sqrt(T)
            analytic = norm.cdf(d1) - (K / S) * math.exp(-r * T) * norm.cdf(d2)  # strike-only DF
            bug = math.exp(-r * T) * (norm.cdf(d1) - (K / F) * norm.cdf(d2))     # whole-price DF
            code = price_inverse_btc(S, K, r, sig, T, "call", q=0.0)
            assert code == pytest.approx(analytic, abs=1e-12)
            assert abs(code - bug) > 1e-4                                        # bug is rejected

    def test_prdisc_b_deep_itm_scalar(self) -> None:
        """PR-DISC.b: deep-ITM (K->0) inverse call -> ~1 coin; the e^{-rT}-bug would give 0.98775."""
        v = price_inverse_btc(64_508.0, 1.0, 0.10, 0.49, 45 / 365.0, "call", q=0.0)
        assert v > 0.999
        assert math.exp(-0.10 * 45 / 365.0) == pytest.approx(0.98775, abs=1e-4)  # what the bug gives

    def test_prdisc_c_no_arb_at_r_gt_0(self) -> None:
        """PR-DISC.c: price_inverse_btc(...,r>0)*S == Black-Scholes USD price to 1e-9."""
        for S, K, r, sig, T, kind in (
            (64_508.0, 64_508.0, 0.04, 0.45, 45 / 365.0, "call"),
            (64_508.0, 58_000.0, 0.10, 0.52, 30 / 365.0, "put"),
        ):
            lhs = price_inverse_btc(S, K, r, sig, T, kind, q=0.0) * S
            rhs = black_scholes.price(S, K, r, sig, T, kind)
            assert lhs == pytest.approx(rhs, abs=1e-9)


# ── PR-THETA — Black-76 put-theta sign (was F18; a CME/USD-leg item) ──────────
# Correct put theta (FRF-016): Theta_put = -term1 + r*e^{-rT}*X*N(-d2) - r*e^{-rT}*F*N(-d1).
# The old bug flipped the two r-terms -> error = +2rP. At r=0 both collapse to -term1 -> goldens
# MUST use r != 0.


def _b76_put_theta_fd(F: float, X: float, r: float, sig: float, T: float) -> float:
    h = 1e-6
    return -(price_black76(F, X, r, sig, T + h, "put") - price_black76(F, X, r, sig, T - h, "put")) / (2 * h)


class TestPRThetaBlack76PutTheta:
    _CASES = ((64_508.0, 64_508.0, 0.05), (64_508.0, 60_000.0, 0.03), (70_000.0, 66_000.0, 0.08))

    def test_prtheta_a_finite_difference(self) -> None:
        """PR-THETA.a: analytic put theta == central-difference -dP/dT to rel 1e-3, r != 0."""
        sig, T = 0.49, 45 / 365.0
        for F, X, r in self._CASES:
            analytic = greeks_black76(F, X, r, sig, T, "put").theta
            assert analytic == pytest.approx(_b76_put_theta_fd(F, X, r, sig, T), rel=1e-3)

    def test_prtheta_b_parity(self) -> None:
        """PR-THETA.b: Theta_put - Theta_call == -r*e^{-rT}(F-X) to 1e-4."""
        sig, T = 0.49, 45 / 365.0
        for F, X, r in self._CASES:
            tp = greeks_black76(F, X, r, sig, T, "put").theta
            tc = greeks_black76(F, X, r, sig, T, "call").theta
            assert tp - tc == pytest.approx(-r * math.exp(-r * T) * (F - X), abs=1e-4)

    def test_prtheta_c_regression_golden(self) -> None:
        """PR-THETA.c: frozen ATM golden; the sign-flipped bug gives -17121.31 (Delta ~2.5%)."""
        th = greeks_black76(64_508.0, 64_508.0, 0.05, 0.49, 45 / 365.0, "put").theta
        assert th == pytest.approx(-17_560.82, abs=0.05)
        assert abs(th - (-17_121.31)) > 400.0  # the sign-flipped bug is far from the golden

    def test_prtheta_spot_mirror_black_scholes(self) -> None:
        """Spot put theta (black_scholes) uses + r*K*e^{-rT}*N(-d2); assert FD-consistent, r != 0."""
        S, K, sig, T = 64_508.0, 60_000.0, 0.49, 45 / 365.0
        for r in (0.03, 0.05, 0.08):
            analytic = black_scholes.greeks(S, K, r, sig, T, "put").theta
            h = 1e-6
            fd = -(black_scholes.price(S, K, r, sig, T + h, "put")
                   - black_scholes.price(S, K, r, sig, T - h, "put")) / (2 * h)
            assert analytic == pytest.approx(fd, rel=1e-3)


# ── Track 1 — PAYOFF/SETTLEMENT goldens (OBSERVED-from-paper, ACI Table 1, K=$25,000) ──


class TestTrack1PayoffGoldens:
    # (S_T, inv_call BTC, inv_put BTC) — ACI Table 1, strike 25,000.
    _TABLE = (
        (10_000.0, 0.000000, 1.500000),
        (20_000.0, 0.000000, 0.250000),
        (30_000.0, 0.166667, 0.000000),
        (40_000.0, 0.375000, 0.000000),
        (50_000.0, 0.500000, 0.000000),
    )

    def test_track1_settlement_matches_aci_table1(self) -> None:
        K = 25_000.0
        for s_t, call_btc, put_btc in self._TABLE:
            assert settlement_inverse_call_holder(s_t, K) == pytest.approx(call_btc, abs=1e-6)
            assert settlement_inverse_put_holder(s_t, K) == pytest.approx(put_btc, abs=1e-6)


# ── Track 2 — ANALYTIC-ORACLE price goldens (no-arb identity V_BTC*S == BS_USD) ──


class TestTrack2AnalyticOracleGoldens:
    # (S, K, r, sigma, days, kind, V_BTC) — A2 §4 Track 2, frozen regression anchor.
    _TABLE = (
        (64_508.0, 64_508.0, 0.00, 0.49, 30, "call", 0.0559968188),
        (64_508.0, 72_000.0, 0.00, 0.49, 30, "call", 0.0183814280),
        (64_508.0, 58_000.0, 0.00, 0.52, 45, "put", 0.0299776486),
        (64_508.0, 64_508.0, 0.04, 0.45, 45, "call", 0.0653049104),
        (30_000.0, 30_000.0, 0.00, 0.80, 90, "call", 0.1574442272),
        (120_000.0, 100_000.0, 0.03, 0.55, 30, "put", 0.0085235789),
    )

    def test_track2_frozen_vbtc(self) -> None:
        for S, K, r, sig, days, kind, v_btc in self._TABLE:
            T = days / 365.0
            assert price_inverse_btc(S, K, r, sig, T, kind, q=0.0) == pytest.approx(v_btc, abs=1e-9)

    def test_track2_no_arb_identity(self) -> None:
        """V_BTC * S == Black-Scholes USD price (the numeraire identity, machine-eps)."""
        for S, K, r, sig, days, kind, _v in self._TABLE:
            T = days / 365.0
            lhs = price_inverse_btc(S, K, r, sig, T, kind, q=0.0) * S
            assert lhs == pytest.approx(black_scholes.price(S, K, r, sig, T, kind), rel=1e-9, abs=1e-6)


# ── Track 3 — OBSERVED Deribit mark goldens (external certification) ──────────


def _load_goldens() -> dict:
    if not FIXTURE.exists():
        pytest.skip(f"Deribit golden fixture absent ({FIXTURE.name}); "
                    "run scripts/fetch_deribit_ticker_goldens.py to capture (free public REST)")
    return json.loads(FIXTURE.read_text())


def _tradeable(goldens: list[dict]) -> list[dict]:
    """Drop worthless deep-OTM marks (mark <= 1e-6 BTC / delta 0) — nothing to certify there."""
    return [g for g in goldens if g["mark_price_btc"] > 1e-6]


class TestDeribitObservedMarks:
    def test_t3_price_matches_mark(self) -> None:
        """T3.price: price_inverse_btc_forward(F,K,mark_iv,T,kind) == mark_price to tol_px."""
        snap = _load_goldens()
        assert snap["provenance"] == "OBSERVED"
        rows = _tradeable(snap["goldens"])
        assert len(rows) >= 6, "need >=6 non-worthless goldens for a meaningful certification"
        worst = 0.0
        for g in rows:
            ours = price_inverse_btc_forward(
                g["F_underlying"], g["K_strike"], g["mark_iv_pct"] / 100.0, g["T_years"], g["kind"])
            tol_px = max(1e-3, 0.005 * g["mark_price_btc"])
            assert abs(ours - g["mark_price_btc"]) <= tol_px, g["instrument_name"]
            worst = max(worst, abs(ours - g["mark_price_btc"]))
        assert worst < 1e-3  # observed: ~5e-5 BTC

    def test_t3_delta_matches_forward_delta(self) -> None:
        """T3.delta (CORRECTED): Deribit ticker delta == Black-76 FORWARD delta N(d1) = Delta_USD.

        The live snapshot certifies that Deribit reports the plain forward delta, NOT the
        premium-adjusted Delta_BTC (which A2 §4 assumed). Anchoring to the forward delta matches
        the exchange to < 5e-4; the residual is dominated by Deribit's 2-dp mark_iv rounding.
        """
        snap = _load_goldens()
        worst = 0.0
        for g in _tradeable(snap["goldens"]):
            mkt = g["greeks"].get("delta")
            if mkt is None:
                continue
            fwd_delta = greeks_black76(
                g["F_underlying"], g["K_strike"], 0.0, g["mark_iv_pct"] / 100.0,
                g["T_years"], g["kind"]).delta
            assert fwd_delta == pytest.approx(mkt, abs=2e-3), g["instrument_name"]
            worst = max(worst, abs(fwd_delta - mkt))
        assert worst < 2e-3

    def test_t3_premium_adjusted_delta_is_distinct(self) -> None:
        """The premium-adjusted exchange Delta_BTC = Delta_USD - premium (Lucic-Sepp Cor.1) is a
        DIFFERENT quantity from the ticker delta: it differs from the reported forward delta by
        exactly the option premium (in BTC). Documents the correction so no one re-conflates them.
        """
        snap = _load_goldens()
        for g in _tradeable(snap["goldens"]):
            mkt = g["greeks"].get("delta")
            if mkt is None:
                continue
            premium = g["mark_price_btc"]
            # Delta_USD via the forward greek == ticker delta; Delta_BTC = Delta_USD - premium.
            delta_usd = greeks_black76(
                g["F_underlying"], g["K_strike"], 0.0, g["mark_iv_pct"] / 100.0,
                g["T_years"], g["kind"]).delta
            delta_btc = delta_usd - premium
            assert abs((delta_usd - delta_btc) - premium) < 1e-12
            # For a non-trivial premium the two conventions are materially apart.
            if premium > 0.01:
                assert abs(delta_btc - mkt) > 0.5 * premium

    def test_t3_iv_roundtrip(self) -> None:
        """T3.iv-roundtrip: invert mark_price -> Black vol via V_BTC*F == BS_USD(F); == mark_iv.

        Tolerance is price-GRANULARITY aware: Deribit rounds the coin mark to a 1e-4 BTC tick, so
        near-expiry / low-vega instruments carry an irreducible IV uncertainty ~ half_tick/vega_BTC.
        (e.g. the ~2.5h-to-expiry ATM contract: a 5e-5 BTC half-tick moves IV by ~0.6 vol-pt.) We
        assert against max(1.5e-3, half_tick/vega_BTC) so the guard tracks the observable, not noise.
        """
        snap = _load_goldens()
        tick_btc = 1e-4
        for g in _tradeable(snap["goldens"]):
            F, K, T, kind = g["F_underlying"], g["K_strike"], g["T_years"], g["kind"]
            iv_mkt = g["mark_iv_pct"] / 100.0
            target_usd = g["mark_price_btc"] * F                # V_BTC * F == Black-76 USD price (r=0)
            iv = black_scholes.implied_vol(target_usd, F, K, 0.0, T, kind)  # BS on S=F, r=0 == Black-76
            vega_btc = greeks_black76(F, K, 0.0, iv_mkt, T, kind).vega / F   # d(V_BTC)/dsigma
            tol_iv = max(1.5e-3, 0.5 * tick_btc / max(vega_btc, 1e-9))
            assert iv == pytest.approx(iv_mkt, abs=tol_iv), g["instrument_name"]
