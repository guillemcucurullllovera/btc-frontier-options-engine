"""C8 Phase 1 tests — live market snapshot, expiry selection, per-(strike,expiry)
IV lookup, and realised-vol comparison.

All tests are offline and derive from the frozen Deribit fixtures under
tests/fixtures/ (which are themselves a loadable market snapshot).  No live
network.  A fixed reference date is used so expiry-selection assertions are
deterministic and independent of wall-clock time.
"""

from __future__ import annotations

import json
import math
import pathlib
import shutil
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from config.models import Provenance
from engine.data_models import HistoricalSpotBar
from vol.chain import (
    iv_for,
    parse_instrument_name,
    select_expiries,
    snap_to_listed_strike,
)
from vol.realised import (
    close_to_close_realised_vol,
    realised_vol_windows,
)
from vol.snapshot import MarketSnapshot, load_snapshot

FIXTURE_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
)

# The frozen fixtures were retrieved 2026-07-28; pin a deterministic reference
# two days later so the 29Jul/30Jul weeklies fall in the past and the liquid
# monthlies 28Aug26 (~29d) and 25Sep26 (~57d) are the near-30/45/60d candidates.
REFERENCE: datetime = datetime(2026, 7, 30, tzinfo=UTC)


# ══════════════════════════════════════════════════════════════════════════
# 1. Snapshot load (fixtures dir doubles as a frozen snapshot)
# ══════════════════════════════════════════════════════════════════════════


def test_load_snapshot_from_fixtures() -> None:
    snap = load_snapshot(FIXTURE_DIR)
    assert isinstance(snap, MarketSnapshot)
    assert snap.spot.price > 0
    assert snap.spot.provenance == Provenance.OBSERVED
    assert len(snap.dvol) > 0
    assert len(snap.instruments) == 836
    assert len(snap.book_summaries) == 836
    # Meta reconstructed from manifest.json (no snapshot_meta.json in fixtures).
    assert snap.meta.spot_usd == pytest.approx(snap.spot.price)
    assert set(snap.meta.checksums) >= {
        "index_price.json",
        "dvol.json",
        "instruments.json",
        "book_summary.json",
    }
    # Checksums in the reconstructed meta must equal the fixture manifest digests.
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text())
    by_path = {e["path"]: e["sha256"] for e in manifest["entries"]}
    for name, digest in snap.meta.checksums.items():
        assert digest == by_path[name]


def test_load_snapshot_prefers_snapshot_meta(tmp_path: pathlib.Path) -> None:
    # Copy the fixture snapshot and drop in an explicit snapshot_meta.json.
    for name in (
        "index_price.json",
        "dvol.json",
        "instruments.json",
        "book_summary.json",
        "manifest.json",
    ):
        shutil.copy(FIXTURE_DIR / name, tmp_path / name)
    meta = {
        "created_at": "2026-07-28T14:54:47.619273+00:00",
        "git_sha": "deadbeefcafe",
        "git_branch": "sprint/c8-strategy-grid",
        "endpoints": ["get_index_price"],
        "checksums": {"index_price.json": "abc"},
        "spot_usd": 63401.86,
        "dvol_latest": 0.3795,
        "provenance": {"spot": "observed"},
        "origin": "deribit",
    }
    (tmp_path / "snapshot_meta.json").write_text(json.dumps(meta))
    snap = load_snapshot(tmp_path)
    assert snap.meta.git_sha == "deadbeefcafe"
    assert snap.meta.git_branch == "sprint/c8-strategy-grid"


# ══════════════════════════════════════════════════════════════════════════
# 2. Instrument-name parsing
# ══════════════════════════════════════════════════════════════════════════


def test_parse_instrument_name_call() -> None:
    p = parse_instrument_name("BTC-29JUL26-57000-C")
    assert p is not None
    assert p.base == "BTC"
    assert p.strike == 57000.0
    assert p.kind == "call"
    assert p.expiry.year == 2026
    assert p.expiry.month == 7
    assert p.expiry.day == 29


def test_parse_instrument_name_put() -> None:
    p = parse_instrument_name("BTC-28AUG26-59000-P")
    assert p is not None
    assert p.strike == 59000.0
    assert p.kind == "put"


def test_parse_instrument_name_rejects_perpetual() -> None:
    assert parse_instrument_name("BTC-PERPETUAL") is None
    assert parse_instrument_name("garbage") is None


# ══════════════════════════════════════════════════════════════════════════
# 3. Liquid-expiry selection around 30/45/60d — and the documented collapse
# ══════════════════════════════════════════════════════════════════════════


def test_select_expiries_collapses_45_and_60() -> None:
    snap = load_snapshot(FIXTURE_DIR)
    sel = select_expiries(
        snap.instruments,
        snap.book_summaries,
        reference=REFERENCE,
        targets_days=(30.0, 45.0, 60.0),
    )
    # Three nominal targets, but only two distinct liquid listed expiries exist.
    assert len(sel.targets) == 3
    assert len(sel.distinct) == 2
    assert sel.collapsed is True

    by_target = {t.target_days: t.selected.label for t in sel.targets}
    assert by_target[30.0] == "28AUG26"
    assert by_target[45.0] == "25SEP26"
    assert by_target[60.0] == "25SEP26"

    labels = {e.label for e in sel.distinct}
    assert labels == {"28AUG26", "25SEP26"}

    # Selected expiries must be liquid, future, and carry days-left + liquidity.
    for e in sel.distinct:
        assert e.is_liquid
        assert e.days_to_expiry > 0
        assert e.n_liquid > 0
        assert e.total_open_interest > 0

    aug = next(e for e in sel.distinct if e.label == "28AUG26")
    sep = next(e for e in sel.distinct if e.label == "25SEP26")
    assert aug.days_to_expiry == pytest.approx((
        datetime(2026, 8, 28, 8, tzinfo=UTC) - REFERENCE
    ).total_seconds() / 86400.0)
    assert sep.days_to_expiry > aug.days_to_expiry
    # The collapse must be explicitly surfaced, not silently deduped.
    assert any("45" in n or "60" in n for n in sel.notes)


def test_select_expiries_excludes_past_expiries() -> None:
    snap = load_snapshot(FIXTURE_DIR)
    sel = select_expiries(
        snap.instruments,
        snap.book_summaries,
        reference=REFERENCE,
        targets_days=(30.0, 45.0, 60.0),
    )
    for e in sel.distinct:
        assert e.expiry > REFERENCE


# ══════════════════════════════════════════════════════════════════════════
# 4. Strike snapping to the listed Deribit grid
# ══════════════════════════════════════════════════════════════════════════


def test_snap_to_listed_strike_picks_nearest() -> None:
    snap = load_snapshot(FIXTURE_DIR)
    aug = datetime(2026, 8, 28, 8, tzinfo=UTC)
    requested = 66000.0
    listed, name = snap_to_listed_strike(snap.instruments, aug, "call", requested)
    # The result is genuinely a listed instrument at that expiry/kind...
    listed_strikes = [
        i.strike
        for i in snap.instruments
        if i.expiration_timestamp == aug and i.option_type == "call"
    ]
    assert listed in listed_strikes
    # ...and no other listed strike is closer to the request.
    best = min(abs(s - requested) for s in listed_strikes)
    assert abs(listed - requested) == pytest.approx(best)
    assert name.startswith("BTC-28AUG26-")
    assert name.endswith("-C")


# ══════════════════════════════════════════════════════════════════════════
# 5. Per-(strike,expiry) IV lookup: direct listed mark_iv, smile fallback
# ══════════════════════════════════════════════════════════════════════════


def test_iv_for_direct_listed_is_observed() -> None:
    snap = load_snapshot(FIXTURE_DIR)
    aug = datetime(2026, 8, 28, 8, tzinfo=UTC)
    # Pick a real 28AUG26 call that has a populated mark_iv.
    book = {b.instrument_name: b for b in snap.book_summaries}
    inst = next(
        i
        for i in snap.instruments
        if i.expiration_timestamp == aug
        and i.option_type == "call"
        and book.get(i.instrument_name) is not None
        and book[i.instrument_name].mark_iv > 0
    )
    lk = iv_for(inst.strike, aug, "call", snap.instruments, snap.book_summaries)
    assert lk.provenance == Provenance.OBSERVED
    assert lk.source == inst.instrument_name
    assert lk.iv == pytest.approx(book[inst.instrument_name].mark_iv)
    assert 0.0 < lk.iv < 3.0  # decimal, annualised


def test_iv_for_unlisted_strike_falls_back_to_smile() -> None:
    snap = load_snapshot(FIXTURE_DIR)
    aug = datetime(2026, 8, 28, 8, tzinfo=UTC)
    listed_strikes = sorted(
        i.strike
        for i in snap.instruments
        if i.expiration_timestamp == aug and i.option_type == "call"
    )
    # A strike one dollar above a mid-chain listed strike is not itself listed.
    mid = listed_strikes[len(listed_strikes) // 2]
    requested = mid + 1.0
    assert requested not in set(listed_strikes)
    lk = iv_for(requested, aug, "call", snap.instruments, snap.book_summaries)
    assert lk.provenance == Provenance.MODEL_RECONSTRUCTED
    assert lk.source == "smile_interpolation_strike_space"
    assert math.isfinite(lk.iv)
    assert lk.iv > 0.0


# ══════════════════════════════════════════════════════════════════════════
# 6. Realised vol (comparison only) — close-to-close, 365-day annualisation
# ══════════════════════════════════════════════════════════════════════════


def _closes_from_returns(first: float, returns: list[float]) -> list[float]:
    closes = [first]
    for r in returns:
        closes.append(closes[-1] * math.exp(r))
    return closes


def test_close_to_close_matches_sample_std() -> None:
    returns = [0.01, -0.02, 0.015, -0.005, 0.02, -0.011]
    closes = _closes_from_returns(100.0, returns)
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)  # ddof=1
    expected = math.sqrt(var) * math.sqrt(365.0)
    got = close_to_close_realised_vol(closes, annualisation_days=365.0)
    assert got == pytest.approx(expected, rel=1e-12)


def test_close_to_close_annualisation_scales() -> None:
    closes = _closes_from_returns(100.0, [0.01, -0.02, 0.015, -0.005, 0.02])
    a365 = close_to_close_realised_vol(closes, annualisation_days=365.0)
    a252 = close_to_close_realised_vol(closes, annualisation_days=252.0)
    assert a252 / a365 == pytest.approx(math.sqrt(252.0 / 365.0), rel=1e-12)


def test_close_to_close_requires_two_points() -> None:
    with pytest.raises(ValueError):
        close_to_close_realised_vol([100.0])
    with pytest.raises(ValueError):
        close_to_close_realised_vol([100.0, -1.0])  # non-positive price


def test_realised_vol_windows_labels_and_computes() -> None:
    # 61 daily bars ending at REFERENCE, deterministic alternating returns.
    returns = [0.012 if i % 2 == 0 else -0.008 for i in range(60)]
    closes = _closes_from_returns(50000.0, returns)
    bars = [
        HistoricalSpotBar(
            symbol="btc_usd",
            timestamp=REFERENCE - timedelta(days=(len(closes) - 1 - i)),
            open=c,
            high=c,
            low=c,
            close=c,
            volume=1.0,
            provenance=Provenance.OBSERVED,
            origin="massive",
        )
        for i, c in enumerate(closes)
    ]
    results = realised_vol_windows(
        bars,
        windows_days=[30],
        reference=REFERENCE,
        annualisation_days=365.0,
        provenance=Provenance.OBSERVED,
        origin="massive",
    )
    assert len(results) == 1
    rv = results[0]
    assert rv.window_days == 30
    assert rv.available is True
    assert rv.provenance == Provenance.OBSERVED
    assert rv.origin == "massive"
    # Reconcile against the pure estimator over the same window of closes.
    window_closes = [
        b.close for b in bars if b.timestamp > REFERENCE - timedelta(days=30)
    ]
    expected = close_to_close_realised_vol(window_closes, annualisation_days=365.0)
    assert rv.sigma_annual == pytest.approx(expected, rel=1e-12)
    assert rv.n_returns == len(window_closes) - 1
