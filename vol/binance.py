"""Binance BTCUSDT klines provider — bulk history + recent REST (C9 · overnight Phase B).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Mirrors ``MassiveSpotProvider`` (vol/history.py):
bulk history from the public ``data.binance.vision`` archive (no auth) and recent bars from the public REST
klines endpoint (no key). Symbol ``BTCUSDT``.

Provenance / BASIS CAVEAT: BTCUSDT is a USDT-quoted Binance spot price; the option chain's Deribit index is a
multi-exchange USD index. Price LEVELS differ by the (small, stationary) USDT basis + exchange composition;
LOG-RETURNS — the input to all physical-dynamics estimation (jumps, GARCH, latent vol) — are an excellent
proxy for BTC/USD returns. Bars are labelled OBSERVED with origin ``binance``; the basis caveat is recorded in
the snapshot meta.

Binance kline row layout (both REST JSON arrays and bulk CSV, no header):
    [0] open_time  [1] open  [2] high  [3] low  [4] close  [5] volume(base)  [6] close_time
    [7] quote_volume  [8] num_trades  [9] taker_buy_base  [10] taker_buy_quote  [11] ignore

TIMESTAMP PRECISION: Binance switched the ``data.binance.vision`` kline timestamps from MILLISECONDS
(13 digits, pre-2025) to MICROSECONDS (16 digits, 2025+); the REST endpoint still returns milliseconds.
``_ts_seconds`` normalises by magnitude so both dumps parse correctly.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import requests

from config.models import Provenance
from engine.data_models import HistoricalSpotBar
from vol.history import HistoricalSpotError, HistoricalSpotNotFound, SpotProvider


class BinanceError(HistoricalSpotError):
    """Binance provider error."""


def _ts_seconds(t: int) -> float:
    """Normalise a Binance kline timestamp to POSIX seconds (handles µs / ms / s)."""
    if t >= 1_000_000_000_000_000:      # >= 1e15 -> microseconds (data.binance.vision, 2025+)
        return t / 1_000_000.0
    if t >= 1_000_000_000_000:          # >= 1e12 -> milliseconds (REST + pre-2025 dumps)
        return t / 1_000.0
    return float(t)                     # already seconds


class BinanceKlinesProvider(SpotProvider):
    """Historical BTC klines from Binance (bulk archive + recent REST)."""

    ORIGIN: ClassVar[str] = "binance"
    SYMBOL: ClassVar[str] = "BTCUSDT"
    REST_URL: ClassVar[str] = "https://api.binance.com/api/v3/klines"
    BULK_BASE: ClassVar[str] = "https://data.binance.vision/data/spot"
    REST_LIMIT: ClassVar[int] = 1000
    DEFAULT_TIMEOUT_S: ClassVar[float] = 30.0
    INTERVAL_MS: ClassVar[dict[str, int]] = {"1d": 86_400_000, "1h": 3_600_000,
                                             "5m": 300_000, "1m": 60_000}

    def __init__(
        self,
        symbol: str | None = None,
        interval: str = "1d",
        fixture_path: Any | None = None,
        timeout_s: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._symbol = symbol or self.SYMBOL
        if interval not in self.INTERVAL_MS:
            raise BinanceError(f"unsupported interval {interval!r}; expected {list(self.INTERVAL_MS)}")
        self._interval = interval
        self._fixture_path = fixture_path
        self._timeout_s = timeout_s or self.DEFAULT_TIMEOUT_S
        self._session = session

    # ── SpotProvider interface (recent bars via REST) ────────────────────────
    def fetch_bars(
        self, start: datetime | None = None, end: datetime | None = None, limit: int = 1000,
    ) -> list[HistoricalSpotBar]:
        if self._fixture_path is not None:
            return self._parse_csv(self._fixture_path)
        end = end or datetime.now(UTC)
        start = start or (end - timedelta(days=limit))
        return self.fetch_rest(start, end)

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
        return self._session

    # ── REST (recent, paginated) ─────────────────────────────────────────────
    def fetch_rest(self, start: datetime, end: datetime) -> list[HistoricalSpotBar]:
        """Paginated REST klines over [start, end]. Public endpoint, no API key."""
        step = self.INTERVAL_MS[self._interval]
        cur = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        out: list[HistoricalSpotBar] = []
        session = self._get_session()
        while cur < end_ms:
            params = {"symbol": self._symbol, "interval": self._interval,
                      "startTime": str(cur), "endTime": str(end_ms), "limit": str(self.REST_LIMIT)}
            try:
                resp = session.get(self.REST_URL, params=params, timeout=self._timeout_s)
                resp.raise_for_status()
                rows = resp.json()
            except (requests.RequestException, ValueError) as exc:
                raise BinanceError(f"Binance REST error: {type(exc).__name__}") from exc
            if not rows:
                break
            for row in rows:
                bar = self._parse_row(row)
                if bar is not None:
                    out.append(bar)
            last_open = int(rows[-1][0])
            nxt = int(_ts_seconds(last_open) * 1000) + step
            if nxt <= cur:
                break
            cur = nxt
        return self._dedup_sorted(out)

    # ── Bulk archive (data.binance.vision monthly zips) ──────────────────────
    def fetch_bulk_month(self, year: int, month: int) -> list[HistoricalSpotBar]:
        """Download+parse one monthly kline zip. Raises HistoricalSpotNotFound on 404."""
        fname = f"{self._symbol}-{self._interval}-{year:04d}-{month:02d}.zip"
        url = f"{self.BULK_BASE}/monthly/klines/{self._symbol}/{self._interval}/{fname}"
        session = self._get_session()
        try:
            resp = session.get(url, timeout=self._timeout_s)
        except requests.RequestException as exc:
            raise BinanceError(f"Binance bulk error: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise HistoricalSpotNotFound(f"no bulk file {fname}")
        resp.raise_for_status()
        return self._parse_zip(resp.content)

    def _parse_zip(self, content: bytes) -> list[HistoricalSpotBar]:
        out: list[HistoricalSpotBar] = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            name = zf.namelist()[0]
            text = zf.read(name).decode("utf-8")
        for row in csv.reader(io.StringIO(text)):
            if not row or not row[0] or row[0].lower().startswith("open"):   # skip any header
                continue
            bar = self._parse_row(row)
            if bar is not None:
                out.append(bar)
        return out

    # ── row / csv parsing ────────────────────────────────────────────────────
    def _parse_row(self, row: list[Any]) -> HistoricalSpotBar | None:
        try:
            ts = datetime.fromtimestamp(_ts_seconds(int(row[0])), tz=UTC)
            o, h, lo, c, v = (float(row[i]) for i in (1, 2, 3, 4, 5))
            if o <= 0 and h <= 0 and lo <= 0 and c <= 0:
                return None
            quote_v = float(row[7]) if len(row) > 7 and row[7] else 0.0
            n = int(float(row[8])) if len(row) > 8 and row[8] not in (None, "") else None
            vwap = (quote_v / v) if v > 0 else None            # VWAP proxy = quote_volume / base_volume
            return HistoricalSpotBar(
                symbol=self._symbol, timestamp=ts, open=o, high=h, low=lo, close=c, volume=v,
                vwap=vwap, transactions=n, provenance=Provenance.OBSERVED, origin=self.ORIGIN,
            )
        except (ValueError, OverflowError, OSError, IndexError):
            return None

    def _parse_csv(self, path: Any) -> list[HistoricalSpotBar]:
        out: list[HistoricalSpotBar] = []
        for row in csv.reader(io.StringIO(path.read_text())):
            if not row or not row[0] or row[0].lower().startswith("open"):
                continue
            bar = self._parse_row(row)
            if bar is not None:
                out.append(bar)
        return self._dedup_sorted(out)

    @staticmethod
    def _dedup_sorted(bars: list[HistoricalSpotBar]) -> list[HistoricalSpotBar]:
        seen: dict[datetime, HistoricalSpotBar] = {b.timestamp: b for b in bars}
        return sorted(seen.values(), key=lambda b: b.timestamp)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
