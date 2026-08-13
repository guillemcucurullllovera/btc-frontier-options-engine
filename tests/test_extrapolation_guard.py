"""C9 · M5.3 — extrapolation model-risk guard.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched.

Oracle: the frozen anchor's listed strikes/expiries define the observed grid — an exact listed
strike is OBSERVED, a within-range strike is INTERPOLATED, a deep-wing strike is EXTRAPOLATED, and a
non-listed expiry (rolled tenor) is flagged extrapolated-in-time.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime

from risk.extrapolation_guard import classify_iv_cell, guard_strike_grid
from vol.chain import select_expiries, snap_to_listed_strike
from vol.snapshot import load_snapshot

_SNAP = load_snapshot(pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures")
_REF = datetime(2026, 7, 30, tzinfo=UTC)
_EXP = select_expiries(_SNAP.instruments, _SNAP.book_summaries, reference=_REF).distinct[0].expiry
_S0 = _SNAP.spot.price


def test_exact_listed_strike_is_observed() -> None:
    K, _ = snap_to_listed_strike(_SNAP.instruments, _EXP, "put", _S0 * 0.95)
    f = classify_iv_cell(K, _EXP, "put", _SNAP.instruments, _SNAP.book_summaries)
    assert f.status == "OBSERVED" and not f.is_extrapolated and f.expiry_listed


def test_within_range_strike_is_interpolated() -> None:
    # An off-grid strike inside the listed range (unlikely to be exactly listed).
    f = classify_iv_cell(_S0 * 0.933, _EXP, "put", _SNAP.instruments, _SNAP.book_summaries)
    assert f.status in ("INTERPOLATED", "OBSERVED") and not f.is_extrapolated
    assert f.listed_min is not None and f.listed_max is not None
    assert f.listed_min <= _S0 * 0.933 <= f.listed_max


def test_deep_wing_strike_is_extrapolated() -> None:
    f = classify_iv_cell(_S0 * 0.55, _EXP, "put", _SNAP.instruments, _SNAP.book_summaries)
    assert f.status == "EXTRAPOLATED" and f.is_extrapolated       # below the listed floor
    assert f.listed_min is not None and f.listed_min > _S0 * 0.55


def test_rolled_tenor_flagged_extrapolated_in_time() -> None:
    rolled = datetime(2027, 12, 31, 8, 0, tzinfo=UTC)             # not a listed expiry
    f = classify_iv_cell(_S0, rolled, "put", _SNAP.instruments, _SNAP.book_summaries)
    assert not f.expiry_listed and f.is_extrapolated


def test_grid_guard_counts_extrapolated_wings() -> None:
    rep = guard_strike_grid(_S0, _EXP, "put", (-3.0, -5.0, -10.0, -15.0, -40.0, -60.0),
                            _SNAP.instruments, _SNAP.book_summaries)
    assert rep.n_cells == 6
    assert rep.any_extrapolated and rep.n_extrapolated >= 2       # the -40%/-60% wings
    assert rep.n_observed + rep.n_interpolated + rep.n_extrapolated == rep.n_cells
    assert 0.0 < rep.extrapolated_fraction < 1.0
