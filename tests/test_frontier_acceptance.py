"""Frontier Stage-2 deterministic acceptance tests (AT-xxx).

Each test encodes a real numeric invariant from
`docs/reports/frontier_acceptance_tests.md`. They are written red-green: each
must fail on the unrepaired module and pass after the corresponding repair.
Golden/preservation suites (FRF-034) must stay green throughout.

Fixtures are deterministic and offline; no test requires live network or a
large simulation.
"""

from __future__ import annotations

import math
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Literal

import numpy as np
import pytest
from scipy.stats import norm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import anonymisation_scan as ascan  # type: ignore[import-not-found]

from engine.errors import ClassificationError, PricingError
from engine.settlement import Venue
from engine.strategy import Leg, Strategy, StrategyKind, classify
from pricing.black76 import greeks_black76, price_black76
from pricing.black_scholes import price as bs_price
from pricing.inverse import price_inverse_btc
from strategy.backtest import BacktestResult, backtest_no_lookahead, backtest_strategy
from strategy.definitions import (
    build_call_spread,
    build_cash_secured_put,
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_partial_overlay,
    build_strike_ladder,
    build_unhedged_baseline,
)
from strategy.payoffs import (
    long_btc_plus_short_put_pnl,
    loss_quantities,
    strategy_pnl,
    structural_max_loss,
)


def _bsm_usd(S: float, K: float, r: float, q: float, sigma: float, T: float, kind: str) -> float:
    """Independent Black-Scholes-Merton USD price on an underlying with a
    continuous dividend/convenience yield q. Coded from scratch (NOT derived
    from pricing.inverse) so it is a genuine cross-check for AT-015."""
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "call":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)

_CONTRACTS = (pathlib.Path(__file__).resolve().parents[1] / "contracts.md").read_text(
    encoding="utf-8"
)

# ── deterministic fixtures ────────────────────────────────────────────────


def _dates(n: int, start: datetime | None = None) -> list[datetime]:
    start = start or datetime(2024, 8, 1, tzinfo=UTC)
    return [start + timedelta(days=i) for i in range(n)]


def _deterministic_spot(n: int, base: float = 65_000.0) -> np.ndarray:
    """A smooth, non-monotone, strictly-positive path (no RNG)."""
    idx = np.arange(n, dtype=float)
    # trend + two deterministic oscillations; amplitude well below `base`.
    path = base * (1.0 + 0.25 * np.sin(idx / 17.0) + 0.0009 * idx
                   + 0.05 * np.cos(idx / 5.0))
    return path.astype(float)


def _flat_iv(n: int, sigma: float = 0.45) -> np.ndarray:
    return np.full(n, sigma, dtype=float)


# ── AT-031 — no-look-ahead mutation integrity (FRF-036) ───────────────────


class TestAT031NoLookAhead:
    """For every cycle entirely before a future-only mutation, is_itm, strike,
    net_pnl_usd, premium_received_usd and entry_spot must be identical."""

    def test_no_lookahead_mutation_integrity(self) -> None:
        n = 200
        dates = _dates(n)
        spot = _deterministic_spot(n)
        iv = _flat_iv(n)
        strat = build_long_btc_plus_short_put(quantity=1.0, entry_spot=float(spot[0]))

        # The engine performs the mutation internally and asserts integrity.
        # It must complete without raising a look-ahead AssertionError.
        backtest_no_lookahead(strat, dates, spot, iv, dte_days=30)

    def test_no_lookahead_is_independently_verifiable(self) -> None:
        # Independent replication of the invariant (does not rely on the
        # engine's internal asserts): mutate future-only, compare pre-split
        # cycles field-by-field.
        n = 200
        dates = _dates(n)
        spot = _deterministic_spot(n)
        iv = _flat_iv(n)
        split = n // 2
        spot_mut = spot.copy()
        spot_mut[split:] += 50_000.0
        iv_mut = iv.copy()
        iv_mut[split:] += 0.20

        strat = build_covered_call(quantity=1.0, entry_spot=float(spot[0]))
        orig = backtest_strategy(strat, dates, spot, iv, dte_days=30)
        mut = backtest_strategy(strat, dates, spot_mut, iv_mut, dte_days=30)

        date_to_idx = {d: i for i, d in enumerate(dates)}
        checked = 0
        for a, b in zip(orig.cycles, mut.cycles, strict=False):
            if date_to_idx[a.end_date] >= split:
                continue
            checked += 1
            assert a.entry_spot == b.entry_spot
            assert a.strike == b.strike
            assert a.is_itm == b.is_itm
            assert a.premium_received_usd == b.premium_received_usd
            assert a.net_pnl_usd == b.net_pnl_usd
        assert checked >= 2, "fixture must exercise ≥2 fully-pre-split cycles"


# ── AT-033 — anonymisation scan hardened (FRF-038) ────────────────────────


class TestAT033AnonymisationScan:
    """The scan must flag a firm-identifying token in a comment AND in a line
    containing 'exclude'; it must scan prompts/ and binary content."""

    TOKEN = "ACMECAPITALPARTNERS"

    def test_flags_token_in_comment_and_exclude_line(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "note.md"
        f.write_text(
            f"# internal comment mentioning {self.TOKEN}\n"
            f"we must exclude {self.TOKEN} from the public deck\n"
            "an unrelated line with no sensitive content\n"
        )
        terms = ascan.load_deal_terms(frozenset({self.TOKEN}))
        findings = ascan.scan_file(f, terms)
        flagged_lines = {ln for rid, _, ln, _ in findings if rid == "DEAL_IDENTIFIER"}
        assert 1 in flagged_lines, "token in a COMMENT must be flagged"
        assert 2 in flagged_lines, "token in an 'exclude' line must be flagged"
        assert 3 not in flagged_lines

    def test_scans_binary_content(self, tmp_path: pathlib.Path) -> None:
        b = tmp_path / "artifact.bin"
        b.write_bytes(b"\x00\x01\x02" + self.TOKEN.encode() + b"\xff\xfe\x00")
        terms = ascan.load_deal_terms(frozenset({self.TOKEN}))
        findings = ascan.scan_file(b, terms)
        assert any(rid == "DEAL_IDENTIFIER" for rid, *_ in findings), \
            "token in BINARY content must be flagged"

    def test_prompts_dir_no_longer_excluded(self) -> None:
        p = ascan.ROOT / "prompts" / "10_fix_phase0_review_findings.md"
        assert ascan.should_consider(p), "prompts/ must be in scan scope"

    def test_no_deal_terms_leaves_generic_scan_green(self) -> None:
        # With no configured terms the generic behaviour is unchanged (a clean
        # source tree stays clean) — the deal pass is strictly additive.
        clean = ascan.ROOT / "README.md"
        assert ascan.scan_file(clean, frozenset()) == []


# ── AT-032 — contract-amendment consistency (FRF-018, FRF-037) ────────────


class TestAT032ContractAmendment:
    """(a) the resolved premium-entry convention yields P&L identical to the
    independent analytic identity; (b) §7.3/§13.1 inverse text states the BTC
    numeraire and has no 'TBD' golden rows; (c) corrected citations present."""

    def test_premium_convention_matches_analytic_identity(self) -> None:
        # Two independently-coded computation paths for the SAME strategy: the
        # engine's leg-formula (strategy_pnl) and the closed-form LBSP identity.
        # Under the resolved unsigned-with-side convention they must be equal.
        S0, K, P, qty = 65_000.0, 58_500.0, 1_500.0, 1.0
        strat = build_long_btc_plus_short_put(
            quantity=qty, entry_spot=S0, strike=K, premium_received=P
        )
        for st in [0.0, 30_000.0, K - 1.0, K, K + 1.0, 90_000.0, 200_000.0]:
            formula = strategy_pnl(strat, st)
            identity = qty * long_btc_plus_short_put_pnl(S0, K, P, st)
            assert abs(formula - identity) < 1e-9, f"P&L mismatch at S_T={st}"

    def test_max_loss_floor_is_negative_S0_plus_K_minus_P(self) -> None:
        S0, K, P = 65_000.0, 58_500.0, 1_500.0
        strat = build_long_btc_plus_short_put(
            quantity=1.0, entry_spot=S0, strike=K, premium_received=P
        )
        # signed floor at S_T = 0 is -(S0 + K - P)
        assert abs(strategy_pnl(strat, 0.0) - (-(S0 + K - P))) < 1e-9

    def test_contract_states_btc_numeraire_and_no_tbd(self) -> None:
        assert "(BTC) numeraire" in _CONTRACTS
        assert "no-arbitrage" in _CONTRACTS.lower()
        # the two inverse pricing golden rows must no longer be TBD
        assert "TBD from test derivation" not in _CONTRACTS

    def test_contract_citation_corrections_present(self) -> None:
        assert "Hull §11.4" in _CONTRACTS  # parity re-cited (was §15.8)
        assert "Hull §15.8" not in _CONTRACTS
        assert "business_requirement" in _CONTRACTS  # Bailey N≥100 relabelled


# ── AT-015 — inverse pricing numeraire & no-arbitrage (FRF-015) ───────────

_R = 0.04
_GRID_S = (30_000.0, 65_000.0, 125_000.0)
_GRID_K = (40_000.0, 65_000.0, 100_000.0)
_GRID_T = (7 / 365.0, 30 / 365.0, 180 / 365.0)
_GRID_SIG = (0.35, 0.65, 1.0)


class TestAT015InversePricing:
    """price_inverse_btc x S == BS/BSM USD over a parameter grid, calls AND
    puts, q=0 and q!=0; deep-ITM -> exp(-qT); invalid inputs raise."""

    def test_no_arbitrage_identity_q_zero(self) -> None:
        for S in _GRID_S:
            for K in _GRID_K:
                for T in _GRID_T:
                    for sig in _GRID_SIG:
                        for kind in ("call", "put"):
                            btc = price_inverse_btc(S, K, _R, sig, T, kind, q=0.0)
                            usd = bs_price(S, K, _R, sig, T, kind)
                            assert abs(btc * S - usd) < 1e-6 * max(usd, 1.0), (
                                f"q=0 parity fail {kind} S={S} K={K} T={T} sig={sig}"
                            )

    def test_no_arbitrage_identity_q_nonzero(self) -> None:
        for q in (0.02, 0.06, -0.03):
            for S in _GRID_S:
                for K in _GRID_K:
                    for kind in ("call", "put"):
                        T, sig = 30 / 365.0, 0.65
                        btc = price_inverse_btc(S, K, _R, sig, T, kind, q=q)
                        usd = _bsm_usd(S, K, _R, q, sig, T, kind)
                        assert abs(btc * S - usd) < 1e-6 * max(abs(usd), 1.0), (
                            f"q={q} parity fail {kind} S={S} K={K}"
                        )

    def test_deep_itm_call_limit(self) -> None:
        # K -> 0 : inverse call -> exp(-qT); at q=0 -> 1.0 BTC.
        p0 = price_inverse_btc(100_000.0, 1.0, _R, 0.45, 30 / 365.0, "call", q=0.0)
        assert abs(p0 - 1.0) < 1e-4
        q = 0.05
        pq = price_inverse_btc(100_000.0, 1.0, _R, 0.45, 30 / 365.0, "call", q=q)
        assert abs(pq - math.exp(-q * 30 / 365.0)) < 1e-4

    def test_invalid_inputs_raise(self) -> None:
        for s, k, sig, t in (
            (-1.0, 100.0, 0.5, 0.5),
            (100.0, 0.0, 0.5, 0.5),
            (100.0, 100.0, 0.0, 0.5),
            (100.0, 100.0, 0.5, 0.0),
        ):
            with pytest.raises(PricingError):
                price_inverse_btc(s, k, _R, sig, t, "call")
        with pytest.raises(PricingError):
            price_inverse_btc(100.0, 100.0, _R, 0.5, 0.5, "straddle")


# ── AT-016 — Black-76 put theta (FRF-016) ─────────────────────────────────


class TestAT016Black76PutTheta:
    """greeks_black76 put theta == central FD of price_black76, and satisfies
    the parity relation to the call theta."""

    def _fd_theta(self, F: float, X: float, r: float, sig: float, T: float, kind: str) -> float:
        h = 1e-5
        up = price_black76(F, X, r, sig, T + h, kind)
        dn = price_black76(F, X, r, sig, T - h, kind)
        return -(up - dn) / (2.0 * h)  # theta = -dP/dT

    def test_put_theta_matches_fd_haug_point(self) -> None:
        F, X, r, sig, T = 19.0, 19.0, 0.10, 0.28, 0.75
        analytic = greeks_black76(F, X, r, sig, T, "put").theta
        assert abs(analytic - self._fd_theta(F, X, r, sig, T, "put")) < 1e-4

    def test_put_theta_matches_fd_grid(self) -> None:
        for F in (50.0, 100.0, 150.0):
            for X in (80.0, 100.0, 120.0):
                for sig in (0.2, 0.6):
                    T, r = 0.5, 0.05
                    analytic = greeks_black76(F, X, r, sig, T, "put").theta
                    fd = self._fd_theta(F, X, r, sig, T, "put")
                    assert abs(analytic - fd) < 1e-3, f"put theta FD mismatch F={F} X={X} sig={sig}"

    def test_theta_parity_call_vs_put(self) -> None:
        # Θ_put - Θ_call == -r·e^{-rT}(F-X)
        F, X, r, sig, T = 105.0, 100.0, 0.05, 0.4, 0.5
        tc = greeks_black76(F, X, r, sig, T, "call").theta
        tp = greeks_black76(F, X, r, sig, T, "put").theta
        expected = -r * math.exp(-r * T) * (F - X)
        assert abs((tp - tc) - expected) < 1e-9


# ── AT-026 — loss quantities (FRF-026) ────────────────────────────────────


def _rel_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1.0)


class TestAT026LossQuantities:
    """structural_max_loss == analytic identity == payoff minimum; and the
    stored builder field equals the payoff-derived value."""

    def _payoff_min_magnitude(self, strat: Strategy) -> float:
        strikes = sorted({leg.strike for leg in strat.legs if leg.strike is not None})
        spots = [leg.entry_spot for leg in strat.legs if leg.entry_spot is not None]
        hi = strikes[-1] if strikes else (max(spots) if spots else 1.0)
        pts = [0.0, *strikes, hi + 1.0]
        return max(0.0, -min(strategy_pnl(strat, float(s)) for s in pts))

    def test_lbsp_equals_analytic_identity(self) -> None:
        S0, K, P = 65_000.0, 58_500.0, 1_500.0
        strat = build_long_btc_plus_short_put(
            quantity=1.0, entry_spot=S0, strike=K, premium_received=P
        )
        analytic = S0 + K - P
        assert _rel_close(structural_max_loss(strat), analytic)
        assert _rel_close(structural_max_loss(strat), self._payoff_min_magnitude(strat))

    def test_field_matches_payoff_derived_for_mandate_strategies(self) -> None:
        strategies = [
            build_unhedged_baseline(),
            build_covered_call(),
            build_cash_secured_put(),
            build_long_btc_plus_short_put(),
            build_collar(),
            build_call_spread(),
            build_partial_overlay(),
            build_strike_ladder(),
        ]
        for s in strategies:
            derived = structural_max_loss(s)
            assert _rel_close(derived, self._payoff_min_magnitude(s)), s.strategy_id
            # the stored builder field must equal the payoff-derived structural loss
            assert _rel_close(derived, s.structural_max_loss), (
                f"{s.strategy_id}: field {s.structural_max_loss} != payoff {derived}"
            )

    def test_loss_block_components(self) -> None:
        S0, K, P, qty = 65_000.0, 58_500.0, 1_500.0, 30_000.0
        strat = build_long_btc_plus_short_put(
            quantity=qty, entry_spot=S0, strike=K, premium_received=P
        )
        notional = qty * S0
        capital = qty * S0
        lq = loss_quantities(strat, reference_btc=qty, notional_usd=notional, capital_usd=capital)
        assert _rel_close(lq.max_loss_usd, qty * (S0 + K - P))
        assert _rel_close(lq.max_loss_per_btc, S0 + K - P)
        assert _rel_close(lq.max_loss_pct_notional, (S0 + K - P) / S0)


# ── AT-030 — premium-percentage metric (FRF-030) ──────────────────────────


class TestAT030PremiumPct:
    """premium_received_pct == net USD premium / (entry spot x reference qty),
    with NO division by leg count (collar/spread not halved)."""

    def _run(self, strat: Strategy) -> BacktestResult:
        n = 120
        dates = _dates(n)
        spot = _deterministic_spot(n)
        iv = _flat_iv(n)
        return backtest_strategy(strat, dates, spot, iv, dte_days=30)

    def test_single_leg_identity(self) -> None:
        res = self._run(build_covered_call(quantity=1.0, entry_spot=65_000.0))
        for c in res.cycles:
            expected = 100.0 * c.premium_received_usd / (c.entry_spot * 1.0)  # stored as %
            assert abs(c.premium_received_pct - expected) < 1e-9

    def test_multi_leg_not_halved(self) -> None:
        res = self._run(build_collar(quantity=1.0, entry_spot=65_000.0))
        for c in res.cycles:
            # Full net premium over spot x qty — NOT divided by the 2 option legs.
            expected = 100.0 * c.premium_received_usd / (c.entry_spot * 1.0)
            assert abs(c.premium_received_pct - expected) < 1e-9


# ── AT-019 — classification integrity (FRF-019) ───────────────────────────


def _opt(
    kind: Literal["call", "put"], side: Literal["LONG", "SHORT"],
    strike: float, qty: float = 1.0,
) -> Leg:
    return Leg(
        instrument=f"BTC-{kind}-{int(strike)}", venue=Venue.OTC,
        product=f"{kind}_option", side=side, quantity=qty,
        option_type=kind, strike=strike,
    )


def _spot(side: Literal["LONG", "SHORT"], qty: float = 1.0) -> Leg:
    return Leg(instrument="BTC-spot", venue=Venue.OTC, product="spot",
               side=side, quantity=qty, entry_spot=65_000.0)


class TestAT019Classification:
    def test_partial_overlay_reachable(self) -> None:
        legs = [_spot("LONG", 1.0), _opt("call", "SHORT", 75_000.0, 0.5)]
        assert classify(legs) == StrategyKind.PARTIAL_OVERLAY

    def test_full_overlay_is_covered_call(self) -> None:
        legs = [_spot("LONG", 1.0), _opt("call", "SHORT", 75_000.0, 1.0)]
        assert classify(legs) == StrategyKind.COVERED_CALL

    def test_long_btc_short_put_never_covered_put(self) -> None:
        legs = [_spot("LONG", 1.0), _opt("put", "SHORT", 58_500.0, 1.0)]
        c = classify(legs)
        assert str(c) == "long_btc_plus_short_put"
        assert str(c) != "covered_put"

    def test_two_same_direction_calls_not_call_spread(self) -> None:
        legs = [_opt("call", "SHORT", 75_000.0), _opt("call", "SHORT", 85_000.0)]
        assert classify(legs) != StrategyKind.CALL_SPREAD

    def test_opposite_calls_distinct_strikes_is_call_spread(self) -> None:
        legs = [_opt("call", "SHORT", 75_000.0), _opt("call", "LONG", 85_000.0)]
        assert classify(legs) == StrategyKind.CALL_SPREAD

    def test_unknown_combo_is_bespoke(self) -> None:
        # a lone long call is a valid leg but an unrecognised strategy combo
        assert classify([_opt("call", "LONG", 75_000.0)]) == StrategyKind.BESPOKE

    def test_invalid_component_raises(self) -> None:
        weird = Leg(instrument="XYZ", venue=Venue.OTC, product="unknown",
                    side="LONG", quantity=1.0)
        with pytest.raises(ClassificationError):
            classify([weird])
        with pytest.raises(ClassificationError):
            classify([])

    def test_label_mismatch_warning_emitted(self) -> None:
        s = build_long_btc_plus_short_put(business_label="Covered Put Strategy")
        assert s.classification_warning is not None
        assert "W-CLASSIFY-MISMATCH" in s.classification_warning
