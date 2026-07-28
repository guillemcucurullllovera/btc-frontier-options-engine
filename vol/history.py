"""Historical BTC spot ingestion.

Massive is the primary provider; CryptoDataDownload is the explicitly-labelled
fallback (AC-5, per authoritative_corrections.md §5 and mandate_sanitized.md §Data rules).

Providers return typed HistoricalSpotBar models with provenance and origin labels.
Caching is managed by SpotCache with configurable staleness thresholds.
No live network dependency in tests — use fixture-based providers.
"""

from __future__ import annotations

import csv
import io
import pathlib
from abc import ABC, abstractmethod
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from config.models import Provenance
from engine.data_models import HistoricalSpotBar
from engine.errors import DataError


class HistoricalSpotError(DataError):
    """Base error for historical spot data operations."""


class HistoricalSpotNotFound(HistoricalSpotError):
    """No data available for the requested period."""


class StaleDataError(HistoricalSpotError):
    """Cached data exceeds the staleness threshold."""


# ── Data provider abstractions ────────────────────────────────────────────


class SpotProvider(ABC):
    """Abstract base for historical BTC spot data providers."""

    @abstractmethod
    def fetch_bars(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[HistoricalSpotBar]:
        """Fetch historical spot bars within the optional time range."""


class MassiveSpotProvider(SpotProvider):
    """Massive primary historical BTC spot provider.

    Reads from CSV files or an API interface.  When *fixture_path* is provided,
    data is read from a local file for offline testing.
    """

    ORIGIN: ClassVar[str] = "massive"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.massive.com/v1",
        fixture_path: pathlib.Path | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._fixture_path = fixture_path

    def fetch_bars(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[HistoricalSpotBar]:
        if self._fixture_path is not None:
            return self._parse_csv(self._fixture_path)
        if self._api_key is None:
            msg = "MassiveSpotProvider requires api_key or fixture_path"
            raise HistoricalSpotError(msg)
        raise NotImplementedError("Live Massive API not yet connected")

    @staticmethod
    def _parse_csv(path: pathlib.Path) -> list[HistoricalSpotBar]:
        """Parse a Massive-format CSV into HistoricalSpotBar list."""
        text = path.read_text()
        reader = csv.DictReader(io.StringIO(text))
        bars: list[HistoricalSpotBar] = []
        for row in reader:
            ts = _parse_timestamp(row.get("timestamp", row.get("t", "")))
            bars.append(HistoricalSpotBar(
                symbol=row.get("symbol", "btc_usd"),
                timestamp=ts,
                open=float(row.get("open", row.get("o", 0))),
                high=float(row.get("high", row.get("h", 0))),
                low=float(row.get("low", row.get("l", 0))),
                close=float(row.get("close", row.get("c", 0))),
                volume=float(row.get("volume", row.get("v", 0))),
                vwap=_safe_parse_float(row.get("vwap", row.get("vw"))),
                transactions=_safe_parse_int(row.get("transactions", row.get("n"))),
                provenance=Provenance.OBSERVED,
                origin="massive",
            ))
        return bars


class CryptoDataDownloadProvider(SpotProvider):
    """CryptoDataDownload fallback historical BTC spot provider.

    Explicitly labelled as fallback origin.  Used only when Massive
    data is unavailable.
    """

    ORIGIN: ClassVar[str] = "cryptodatadownload"

    def __init__(
        self,
        fixture_path: pathlib.Path | None = None,
    ) -> None:
        self._fixture_path = fixture_path

    def fetch_bars(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[HistoricalSpotBar]:
        if self._fixture_path is not None:
            return self._parse_csv(self._fixture_path)
        msg = "CryptoDataDownloadProvider requires fixture_path; no live API configured"
        raise HistoricalSpotError(msg)

    @staticmethod
    def _parse_csv(path: pathlib.Path) -> list[HistoricalSpotBar]:
        """Parse a CDD-format CSV into HistoricalSpotBar list."""
        text = path.read_text()
        reader = csv.DictReader(io.StringIO(text))
        bars: list[HistoricalSpotBar] = []
        for row in reader:
            ts = _parse_timestamp(row.get("date", row.get("timestamp", row.get("t", ""))))
            bars.append(HistoricalSpotBar(
                symbol=row.get("symbol", row.get("Symbol", "btc_usd")),
                timestamp=ts,
                open=float(row.get("open", row.get("Open", 0))),
                high=float(row.get("high", row.get("High", 0))),
                low=float(row.get("low", row.get("Low", 0))),
                close=float(row.get("close", row.get("Close", 0))),
                volume=float(row.get("volume", row.get("Volume BTC", row.get("Volume", 0)))),
                vwap=None,
                transactions=None,
                provenance=Provenance.OBSERVED,
                origin="cryptodatadownload",
            ))
        return bars


# ── Composite provider (Massive primary, CDD fallback) ────────────────────


class CompositeSpotProvider(SpotProvider):
    """Tries Massive first, falls back to CryptoDataDownload.

    Primary provider: MassiveSpotProvider.
    Fallback provider: CryptoDataDownloadProvider.
    """

    def __init__(
        self,
        primary: SpotProvider,
        fallback: SpotProvider,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def fetch_bars(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[HistoricalSpotBar]:
        try:
            bars = self._primary.fetch_bars(start=start, end=end, limit=limit)
            if bars:
                return bars
        except (HistoricalSpotError, NotImplementedError):
            pass
        return self._fallback.fetch_bars(start=start, end=end, limit=limit)


# ── Cache with staleness handling ─────────────────────────────────────────


class SpotCache:
    """In-memory cache for historical spot bars with staleness detection.

    Stores bars keyed by (start_timestamp, end_timestamp) for the query range.
    """

    def __init__(self, max_age: timedelta = timedelta(hours=1)) -> None:
        self._max_age = max_age
        self._cache: OrderedDict[tuple[float, float], tuple[datetime, list[HistoricalSpotBar]]] = (
            OrderedDict()
        )

    def get(
        self, start: datetime | None, end: datetime | None
    ) -> list[HistoricalSpotBar] | None:
        key = _cache_key(start, end)
        entry = self._cache.get(key)
        if entry is None:
            return None
        cached_at, bars = entry
        if datetime.now(UTC) - cached_at > self._max_age:
            del self._cache[key]
            return None
        return bars

    def put(
        self, start: datetime | None, end: datetime | None, bars: list[HistoricalSpotBar]
    ) -> None:
        key = _cache_key(start, end)
        self._cache[key] = (datetime.now(UTC), bars)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def is_stale(self) -> bool:
        if not self._cache:
            return False
        latest_ts = max(ts for ts, _ in self._cache.values())
        return datetime.now(UTC) - latest_ts > self._max_age

    @property
    def entry_count(self) -> int:
        return len(self._cache)


# ── Helpers ───────────────────────────────────────────────────────────────


def _parse_timestamp(raw: str) -> datetime:
    """Parse various timestamp formats to UTC datetime."""
    raw = raw.strip()
    if not raw:
        return datetime.now(UTC)
    try:
        ts = float(raw)
        if ts > 1e12:
            return datetime.fromtimestamp(ts / 1000, tz=UTC)
        return datetime.fromtimestamp(ts, tz=UTC)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return datetime.now(UTC)


def _safe_parse_float(v: str | None) -> float | None:
    if v is None or v.strip() == "":
        return None
    return float(v)


def _safe_parse_int(v: str | None) -> int | None:
    if v is None or v.strip() == "":
        return None
    return int(float(v))


def _cache_key(start: datetime | None, end: datetime | None) -> tuple[float, float]:
    s = start.timestamp() if start else 0.0
    e = end.timestamp() if end else float("inf")
    return (s, e)
