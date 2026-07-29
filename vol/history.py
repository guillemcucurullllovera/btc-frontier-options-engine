"""Historical BTC spot ingestion.

Massive is the primary provider; CryptoDataDownload is the explicitly-labelled
fallback (AC-5, per authoritative_corrections.md §5 and mandate_sanitized.md §Data rules).

Providers return typed HistoricalSpotBar models with provenance and origin labels.
Caching is managed by SpotCache with configurable staleness thresholds.
No live network dependency in tests — use fixture-based providers.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import pathlib
import random
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import requests

from config.models import Provenance
from engine.data_models import HistoricalSpotBar
from engine.errors import DataError


class HistoricalSpotError(DataError):
    """Base error for historical spot data operations."""


class HistoricalSpotNotFound(HistoricalSpotError):
    """No data available for the requested period."""


class StaleDataError(HistoricalSpotError):
    """Cached data exceeds the staleness threshold."""


class MassiveTimeoutError(HistoricalSpotError):
    """Request to Massive API exceeded timeout."""


class MassiveRateLimitError(HistoricalSpotError):
    """Rate-limited by Massive API."""


class MassiveServerError(HistoricalSpotError):
    """5xx or transient server error from Massive."""


class MassiveResponseError(HistoricalSpotError):
    """Malformed or unexpected Massive response."""


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

    Supports live API calls (with MASSIVE_API_KEY env var) and fixture-based
    CSV replay for offline testing.
    """

    ORIGIN: ClassVar[str] = "massive"
    BASE_URL: ClassVar[str] = "https://api.massive.com"
    TICKER: ClassVar[str] = "X:BTCUSD"
    ENDPOINT_PATH: ClassVar[str] = "/v2/aggs/ticker/{ticker}/range/1/day/{from_}/{to}"

    MAX_RETRIES: ClassVar[int] = 3
    BASE_DELAY_S: ClassVar[float] = 1.0
    MAX_DELAY_S: ClassVar[float] = 30.0
    DEFAULT_TIMEOUT_S: ClassVar[float] = 30.0
    PAGE_LIMIT: ClassVar[int] = 5000

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        fixture_path: pathlib.Path | None = None,
        cache_dir: pathlib.Path | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("MASSIVE_API_KEY", "")
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        self._fixture_path = fixture_path
        self._cache_dir = cache_dir
        self._timeout_s = timeout_s or self.DEFAULT_TIMEOUT_S
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def fetch_bars(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[HistoricalSpotBar]:
        if self._fixture_path is not None:
            return self._parse_csv(self._fixture_path)

        if not self._api_key:
            raise HistoricalSpotError("MassiveSpotProvider requires api_key or fixture_path")

        all_bars: list[HistoricalSpotBar] = []
        from_str = self._format_date_param(start)
        to_str = self._format_date_param(end)

        url = f"{self._base_url}{self.ENDPOINT_PATH.format(ticker=self.TICKER, from_=from_str, to=to_str)}"

        raw_response: dict[str, Any] | None = None
        attempt = 0
        while attempt < self.MAX_RETRIES:
            attempt += 1
            try:
                session = self._get_session()
                resp = session.get(
                    url,
                    params={"apiKey": self._api_key, "limit": str(self.PAGE_LIMIT), "sort": "asc"},
                    timeout=self._timeout_s,
                )
            except requests.exceptions.Timeout:
                if attempt >= self.MAX_RETRIES:
                    raise MassiveTimeoutError(f"Timeout after {self._timeout_s}s on Massive API") from None
                self._sleep_backoff(attempt)
                continue
            except requests.exceptions.ConnectionError as exc:
                if attempt >= self.MAX_RETRIES:
                    raise HistoricalSpotError(f"Connection error on Massive API: {exc}") from exc
                self._sleep_backoff(attempt)
                continue
            except requests.exceptions.RequestException as exc:
                if attempt >= self.MAX_RETRIES:
                    raise HistoricalSpotError(f"Request failed on Massive API: {exc}") from exc
                self._sleep_backoff(attempt)
                continue

            if resp.status_code == 429:
                if attempt >= self.MAX_RETRIES:
                    raise MassiveRateLimitError("Rate limited by Massive API after max retries")
                retry_after = resp.headers.get("Retry-After")
                wait_s = float(retry_after) if retry_after else min(self.BASE_DELAY_S * (2 ** (attempt - 1)), self.MAX_DELAY_S)
                time.sleep(wait_s + random.uniform(0, 1.0))
                continue
            if resp.status_code >= 500:
                if attempt >= self.MAX_RETRIES:
                    raise MassiveServerError(f"Massive server error {resp.status_code} after max retries")
                self._sleep_backoff(attempt)
                continue

            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                if attempt >= self.MAX_RETRIES:
                    raise HistoricalSpotError(f"Massive HTTP {resp.status_code}: {exc}") from exc
                self._sleep_backoff(attempt)
                continue

            try:
                raw_response = resp.json()
            except ValueError as exc:
                if attempt >= self.MAX_RETRIES:
                    raise MassiveResponseError(f"Invalid JSON from Massive API: {exc}") from exc
                self._sleep_backoff(attempt)
                continue

            break

        if raw_response is None:
            raise HistoricalSpotError("All retries exhausted for Massive API")

        status = raw_response.get("status", "")
        if status != "OK":
            raise MassiveResponseError(f"Massive API returned status '{status}': {raw_response}")

        if self._cache_dir is not None:
            self._cache_raw(raw_response, from_str, to_str)

        results = raw_response.get("results")
        if not results or not isinstance(results, list):
            raise HistoricalSpotNotFound(f"Massive returned no results for {from_str}-{to_str}")

        for row in results:
            bar = self._parse_result_row(row, raw_response.get("ticker", self.TICKER))
            if bar is not None:
                all_bars.append(bar)

        if not all_bars:
            raise HistoricalSpotNotFound(f"No valid bars parsed from Massive response for {from_str}-{to_str}")

        all_bars = self._deduplicate_and_sort(all_bars)
        self._validate_monotonic(all_bars)
        return all_bars

    def _parse_result_row(self, row: dict[str, Any], ticker: str) -> HistoricalSpotBar | None:
        try:
            t_ms = int(row.get("t", 0))
            if t_ms <= 0:
                return None
            ts = datetime.fromtimestamp(t_ms / 1000.0, tz=UTC)

            o = float(row.get("o", 0))
            h = float(row.get("h", 0))
            lo = float(row.get("l", 0))
            c = float(row.get("c", 0))
            v = float(row.get("v", 0))
            vw = self._safe_float(row.get("vw"))
            n = self._safe_int(row.get("n"))

            # Reject zero-price bars (likely malformed or weekend/NY holidays with no trading)
            if o <= 0 and h <= 0 and lo <= 0 and c <= 0:
                return None

            return HistoricalSpotBar(
                symbol=ticker,
                timestamp=ts,
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=v,
                vwap=vw,
                transactions=n,
                provenance=Provenance.OBSERVED,
                origin="massive",
            )
        except (ValueError, OverflowError, OSError):
            return None

    @staticmethod
    def _deduplicate_and_sort(bars: list[HistoricalSpotBar]) -> list[HistoricalSpotBar]:
        seen: dict[datetime, HistoricalSpotBar] = {}
        for bar in bars:
            seen[bar.timestamp] = bar
        return sorted(seen.values(), key=lambda b: b.timestamp)

    @staticmethod
    def _validate_monotonic(bars: list[HistoricalSpotBar]) -> None:
        if len(bars) < 2:
            return
        for i in range(1, len(bars)):
            if bars[i].timestamp <= bars[i - 1].timestamp:
                raise HistoricalSpotError(
                    f"Non-monotonic timestamps at index {i}: "
                    f"{bars[i-1].timestamp} >= {bars[i].timestamp}"
                )

    def _cache_raw(self, data: dict[str, Any], from_str: str, to_str: str) -> str:
        raw_json = json.dumps(data, sort_keys=True, default=str)
        checksum = hashlib.sha256(raw_json.encode()).hexdigest()
        if self._cache_dir is None:
            return ""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self._cache_dir / f"massive_{from_str}_{to_str}_{checksum[:12]}.json"
        cache_path.write_text(raw_json)
        return str(cache_path)

    @staticmethod
    def _format_date_param(dt: datetime | None) -> str:
        if dt is None:
            return datetime.now(UTC).strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        delay = min(
            MassiveSpotProvider.BASE_DELAY_S * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
            MassiveSpotProvider.MAX_DELAY_S,
        )
        time.sleep(delay)

    @staticmethod
    def _safe_float(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_int(v: Any) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None

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

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


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
    """Parse various timestamp formats to UTC datetime.

    FRF-029 / AT-029: an empty or unparseable timestamp RAISES rather than
    silently substituting the current time (which would turn corrupt rows into
    plausible observed data).
    """
    raw = raw.strip()
    if not raw:
        raise MassiveResponseError("empty timestamp in historical bar (cannot substitute now())")
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
    raise MassiveResponseError(f"unparseable timestamp {raw!r} in historical bar")


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
