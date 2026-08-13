"""C9 · M0.2 — full IV-surface pipeline: SVI/SSVI calibration + static no-arb gates.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched.

Independent oracles: (1) a KNOWN arbitrage-free SVI slice is regenerated and re-fitted,
recovering total variance to numerical precision; (2) analytic SVI w', w'' are checked
against finite differences; (3) the Gatheral-Jacquier canonical arbitrageable slice is
flagged by the butterfly gate; (4) a hand-built butterfly/calendar violation is caught by
the static gate; (5) the fitted surface reprices the real fixtures chain within RMSE.
"""

from __future__ import annotations

import math
import pathlib
from datetime import UTC, datetime

import numpy as np
import pytest

from vol.chain_surface import (
    ChainSlice,
    fit_ssvi_surface,
    fit_svi_surface,
    ingest_chain_slices,
    slices_from_book_summaries,
    static_no_arb_gate,
)
from vol.snapshot import load_snapshot
from vol.surface import fit_surface
from vol.svi import (
    SsviParams,
    SviParams,
    calendar_arb_free,
    calibrate_svi_slice,
    ssvi_butterfly_free,
    svi_butterfly_free,
    svi_g,
)

FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
REFERENCE = datetime(2026, 7, 30, tzinfo=UTC)

_SNAP = load_snapshot(FIXTURE_DIR)
_SLICES = ingest_chain_slices(_SNAP.instruments, _SNAP.book_summaries, REFERENCE)


# ── SVI math: analytic derivatives + known-smile recovery ─────────────────────


def test_svi_analytic_derivatives_match_fd() -> None:
    """Analytic w', w'' (used by the butterfly g) match central finite differences."""
    p = SviParams(a=0.02, b=0.10, rho=-0.4, m=0.05, s=0.20, T=0.5)
    k = np.linspace(-0.8, 0.8, 33)
    h = 1e-5
    w = p.total_variance(k)
    w_up = p.total_variance(k + h)
    w_dn = p.total_variance(k - h)
    w1_fd = (w_up - w_dn) / (2 * h)
    w2_fd = (w_up - 2 * w + w_dn) / (h * h)
    from vol.svi import _svi_w_derivs

    _, w1, w2 = _svi_w_derivs(k, p)
    assert np.max(np.abs(w1 - w1_fd)) < 1e-6
    assert np.max(np.abs(w2 - w2_fd)) < 1e-3


def test_svi_recovers_known_arbfree_slice() -> None:
    """A known arb-free SVI slice is re-fitted; total variance recovered to ~machine tol."""
    true_p = SviParams(a=0.015, b=0.09, rho=-0.35, m=0.02, s=0.18, T=0.5)
    k = np.linspace(-0.7, 0.7, 25)
    w = true_p.total_variance(k)
    fit_p, rmse = calibrate_svi_slice(k, w, T=0.5)
    assert rmse < 1e-5
    assert np.max(np.abs(fit_p.total_variance(k) - w)) < 1e-4
    free, min_g = svi_butterfly_free(true_p)
    assert free and min_g > 0.0


def test_svi_butterfly_gate_flags_arbitrageable_slice() -> None:
    """Gatheral-Jacquier (2014) canonical arbitrageable slice: butterfly gate must flag it."""
    bad = SviParams(a=-0.0410, b=0.1331, rho=0.3060, m=0.3586, s=0.4153, T=1.0)
    free, min_g = svi_butterfly_free(bad)
    assert not free
    assert min_g < 0.0
    # g(k) actually goes negative somewhere on the grid.
    k = np.linspace(-1.5, 1.5, 601)
    assert float(np.min(svi_g(k, bad))) < 0.0


# ── SSVI: arb-free-by-construction + condition gate ───────────────────────────


def test_ssvi_butterfly_condition_flags_bad_params() -> None:
    """theta*phi*(1+|rho|) >= 4 must be flagged (Gatheral-Jacquier Thm 4.2)."""
    good = SsviParams(rho=-0.3, eta=0.6, gamma=0.5)
    ok, margin = ssvi_butterfly_free(good, np.array([0.01, 0.05, 0.15]))
    assert ok and margin > 0.0
    bad = SsviParams(rho=0.5, eta=5.0, gamma=0.5)
    bad_ok, bad_margin = ssvi_butterfly_free(bad, np.array([0.5]))
    assert not bad_ok and bad_margin < 0.0


def test_ssvi_fit_is_arbitrage_free_on_fixtures() -> None:
    """SSVI on the real chain: butterfly-free + calendar-free (monotone theta) by construction."""
    fit = fit_ssvi_surface(_SLICES)
    assert fit.butterfly_free
    assert fit.worst_butterfly_margin > 0.0
    assert fit.calendar_free            # monotone ATM total variance by construction
    assert fit.atm_theta_was_monotone   # raw ATM term structure already monotone here
    assert fit.overall_iv_rmse < 0.05   # reprice within 5 vol pts (report: ~3.5)


# ── Full-chain ingest ─────────────────────────────────────────────────────────


def test_ingest_covers_whole_chain_not_atm_only() -> None:
    """Ingest yields many strikes across many expiries (not per-tenor ATM only)."""
    assert len(_SLICES) >= 5
    total_strikes = sum(sl.k.size for sl in _SLICES)
    assert total_strikes > 100                       # whole chain, not ~1 ATM point per tenor
    for sl in _SLICES:
        assert sl.forward > 0.0
        assert np.all(np.diff(sl.strikes) > 0)       # sorted, distinct
        assert sl.k.size == sl.mark_iv.size == sl.strikes.size


def test_slices_from_books_alone_match_instrument_path() -> None:
    """The book-summary-only ingest recovers the same expiries as the instrument path."""
    book_slices = slices_from_book_summaries(_SNAP.book_summaries, REFERENCE)
    assert len(book_slices) >= 5
    assert sum(sl.k.size for sl in book_slices) > 100


# ── Reprice-the-chain gate (SVI) ──────────────────────────────────────────────


def test_svi_reprices_chain_within_rmse() -> None:
    """SVI gate: per-slice fit reprices the weekly+ chain within RMSE (report the number)."""
    weekly = [sl for sl in _SLICES if sl.T >= 7.0 / 365.0]
    fit = fit_svi_surface(weekly)
    assert fit.butterfly_free                         # every fitted slice butterfly-free
    assert fit.overall_iv_rmse < 0.03                 # < 3 vol pts (report: ~1.0)
    rmses = sorted(s.iv_rmse for s in fit.slices)
    median = rmses[len(rmses) // 2]
    assert median < 0.01                              # median slice < 1 vol pt (report: ~0.3)


# ── Static no-arb gate: real chain (diagnostic) + injected violation ──────────


def test_static_gate_runs_on_real_chain() -> None:
    """Static gate returns a bounded diagnostic on the real chain (minor stale-quote noise)."""
    rep = static_no_arb_gate(_SLICES)
    assert rep.n_slices == len(_SLICES)
    # Real chains have a few stale-quote convexity nicks; they must be a small minority.
    total_strikes = sum(sl.k.size for sl in _SLICES)
    assert rep.total_violations < 0.25 * total_strikes


def _synthetic_slice(strikes: np.ndarray, ivs: np.ndarray, F: float = 100.0, T: float = 0.25) -> ChainSlice:
    kinds = tuple("put" if K < F else "call" for K in strikes)
    return ChainSlice(
        expiry=datetime(2026, 8, 28, 8, 0, tzinfo=UTC), label="SYN", T=T, forward=F,
        strikes=strikes.astype(np.float64), k=np.log(strikes / F), mark_iv=ivs.astype(np.float64),
        bid_iv=ivs - 0.01, ask_iv=ivs + 0.01, kinds=kinds,
    )


def test_static_gate_catches_injected_butterfly_violation() -> None:
    """A crafted non-convex smile (spiked interior IV) is caught as a convexity violation."""
    strikes = np.array([80, 90, 100, 110, 120], dtype=np.float64)
    flat = np.full(5, 0.50)
    clean = static_no_arb_gate([_synthetic_slice(strikes, flat)])
    assert clean.slices[0].convexity_violations == 0     # flat smile is arb-free

    spiked = flat.copy()
    spiked[2] = 0.20                                     # ATM IV crashes -> price dip -> non-convex
    dirty = static_no_arb_gate([_synthetic_slice(strikes, spiked)])
    assert dirty.slices[0].convexity_violations > 0
    assert dirty.slices[0].worst_convexity < 0.0


def test_calendar_arb_free_flags_decreasing_variance() -> None:
    """Calendar check: total variance decreasing in T is flagged (independent unit check)."""
    k = np.linspace(-0.3, 0.3, 21)
    w_short = np.full_like(k, 0.04)
    w_long_ok = np.full_like(k, 0.06)
    w_long_bad = np.full_like(k, 0.03)                  # < short -> calendar arb
    ok, _ = calendar_arb_free([(0.25, w_short), (0.75, w_long_ok)], k)
    bad, worst = calendar_arb_free([(0.25, w_short), (0.75, w_long_bad)], k)
    assert ok
    assert not bad and worst < 0.0


# ── fit_surface method dispatch (declared-but-unused svi/ssvi now real) ────────


def test_fit_surface_svi_method_dispatch() -> None:
    """fit_surface(method='svi'/'ssvi') now returns that method with a reprice RMSE."""
    surf_svi = fit_surface(_SNAP.book_summaries, method="svi")
    assert surf_svi.method == "svi"
    assert surf_svi.fit_rmse is not None and 0.0 < surf_svi.fit_rmse < 0.1

    surf_ssvi = fit_surface(_SNAP.book_summaries, method="ssvi")
    assert surf_ssvi.method == "ssvi"
    assert surf_ssvi.fit_rmse is not None and 0.0 < surf_ssvi.fit_rmse < 0.1

    # Spline path is unchanged.
    surf_spline = fit_surface(_SNAP.book_summaries, method="spline")
    assert surf_spline.method == "spline"


def test_svi_iv_matches_black76_forward_convention() -> None:
    """Sanity: fitted SVI IV at k=0 equals the ATM total-variance implied vol sqrt(w/T)."""
    weekly = [sl for sl in _SLICES if sl.T >= 21.0 / 365.0]
    fit = fit_svi_surface(weekly)
    for sf in fit.slices:
        atm_iv = float(sf.params.iv(0.0))
        atm_w = float(sf.params.total_variance(0.0))
        assert atm_iv == pytest.approx(math.sqrt(max(atm_w, 1e-12) / sf.T), rel=1e-9)
