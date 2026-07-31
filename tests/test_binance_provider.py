"""C9 · overnight Phase B — Binance klines provider (network-free fixture tests).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Locks the ms/µs/s timestamp
normalisation (Binance switched data.binance.vision kline timestamps from milliseconds to
microseconds in 2025) and the fixture-CSV parse path. Live fetching is exercised by the
scripts/fetch_binance_history.py snapshot builder, not the test suite.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime

import pytest

from config.models import Provenance
from vol.binance import BinanceError, BinanceKlinesProvider, _ts_seconds

_FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "binance_btcusdt_1d_sample.csv"


def test_ts_seconds_handles_all_precisions() -> None:
    """The critical gotcha: normalise microseconds (2025+ dumps), milliseconds (REST/pre-2025), seconds."""
    # 2020-01-01T00:00:00Z is 1577836800 s = 1_577_836_800_000 ms = 1_577_836_800_000_000 µs.
    assert _ts_seconds(1_577_836_800) == pytest.approx(1_577_836_800.0)          # seconds
    assert _ts_seconds(1_577_836_800_000) == pytest.approx(1_577_836_800.0)      # milliseconds
    assert _ts_seconds(1_577_836_800_000_000) == pytest.approx(1_577_836_800.0)  # microseconds
    # A 2026 microsecond stamp must NOT land 1000x in the future.
    assert datetime.fromtimestamp(_ts_seconds(1_780_272_000_000_000), tz=UTC).year == 2026


def test_fixture_parses_to_observed_binance_bars() -> None:
    prov = BinanceKlinesProvider(interval="1d", fixture_path=_FIX)
    bars = prov.fetch_bars()
    assert len(bars) == 5
    assert [b.timestamp.date().isoformat() for b in bars] == [
        "2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"]
    b0 = bars[0]
    assert b0.symbol == "BTCUSDT" and b0.origin == "binance"
    assert b0.provenance == Provenance.OBSERVED
    assert b0.open == pytest.approx(7195.24) and b0.close == pytest.approx(7200.85)
    assert b0.low <= (b0.vwap or 0.0) <= b0.high          # VWAP proxy = quote_vol / base_vol, within range


def test_bars_sorted_and_monotonic() -> None:
    bars = BinanceKlinesProvider(interval="1d", fixture_path=_FIX).fetch_bars()
    ts = [b.timestamp for b in bars]
    assert ts == sorted(ts)
    assert len(set(ts)) == len(ts)                        # deduplicated


def test_unsupported_interval_raises() -> None:
    with pytest.raises(BinanceError):
        BinanceKlinesProvider(interval="7d")
