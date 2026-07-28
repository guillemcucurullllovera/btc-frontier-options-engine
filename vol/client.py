"""Hardened Deribit public API client.

Typed responses, retry with exponential backoff, timeout handling,
classified errors, UTC timestamps, provenance metadata, offline fixture replay.

All live-endpoint methods return typed Pydantic models from engine.data_models.
When a fixture fixture_dir is provided, live network calls are bypassed.
"""

from __future__ import annotations

import json
import pathlib
import random
import time
from datetime import UTC, datetime
from typing import Any

import requests

from config.models import Provenance
from engine.data_models import BookSummary, DvolBar, OptionInstrument, SpotBar
from engine.errors import DataError

BASE: str = "https://www.deribit.com/api/v2/public"
DEFAULT_TIMEOUT_S: float = 15.0
MAX_RETRIES: int = 3
BASE_DELAY_S: float = 0.5
MAX_DELAY_S: float = 10.0


class DeribitClientError(DataError):
    """Base error for Deribit client failures."""


class DeribitTimeoutError(DeribitClientError):
    """Request exceeded timeout."""


class DeribitRateLimitError(DeribitClientError):
    """Rate-limited by Deribit API."""


class DeribitServerError(DeribitClientError):
    """5xx or transient server error."""


class DeribitApiError(DeribitClientError):
    """Deribit API returned an error in the JSON-RPC response."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.api_message = message
        super().__init__(f"Deribit API error {code}: {message}")


class DeribitClient:
    """Public Deribit API client with retries, timeouts, and offline replay."""

    def __init__(
        self,
        base_url: str = BASE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = MAX_RETRIES,
        fixture_dir: pathlib.Path | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._fixture_dir = fixture_dir
        self._session = requests.Session()

    # ── Public endpoints ──────────────────────────────────────────────────

    def spot_index(self, currency_pair: str = "btc_usd") -> SpotBar:
        raw = self._request("get_index_price", index_name=currency_pair)
        result: dict[str, Any] = raw["result"]
        timestamp = datetime.now(UTC)
        price = float(result["index_price"])
        return SpotBar(timestamp=timestamp, price=price, provenance=Provenance.OBSERVED, origin="deribit")

    def dvol_latest(self, currency: str = "BTC", resolution: str = "3600") -> list[DvolBar]:
        now_ms = int(time.time() * 1000)
        raw = self._request(
            "get_volatility_index_data",
            currency=currency,
            start_timestamp=now_ms - 86_400_000,
            end_timestamp=now_ms,
            resolution=resolution,
        )
        result: dict[str, Any] = raw["result"]
        data: list[list[float]] = result.get("data", [])
        bars: list[DvolBar] = []
        for row in data:
            ts = datetime.fromtimestamp(row[0] / 1000, tz=UTC)
            bars.append(DvolBar(
                timestamp=ts,
                open=float(row[1]) / 100.0,
                high=float(row[2]) / 100.0,
                low=float(row[3]) / 100.0,
                close=float(row[4]) / 100.0,
                provenance=Provenance.OBSERVED,
                origin="deribit",
            ))
        return bars

    def option_chain(self, currency: str = "BTC") -> list[OptionInstrument]:
        raw = self._request("get_instruments", currency=currency, kind="option", expired="false")
        instruments: list[dict[str, Any]] = raw.get("result", [])
        result: list[OptionInstrument] = []
        for inst in instruments:
            exp_ms = inst.get("expiration_timestamp", 0)
            exp_ts = datetime.fromtimestamp(exp_ms / 1000, tz=UTC)
            result.append(OptionInstrument(
                instrument_name=inst.get("instrument_name", ""),
                base_currency=inst.get("base_currency", "BTC"),
                quote_currency=inst.get("quote_currency", "USD"),
                settlement_currency=inst.get("settlement_currency", "BTC"),
                instrument_type=inst.get("instrument_type", "reversed"),
                option_type=inst.get("option_type", "call"),
                strike=float(inst.get("strike", 0)),
                expiration_timestamp=exp_ts,
                contract_size=float(inst.get("contract_size", 1.0)),
                min_trade_amount=float(inst.get("min_trade_amount", 0.1)),
                block_trade_min_trade_amount=float(inst.get("block_trade_min_trade_amount", 25.0)),
                tick_size=float(inst.get("tick_size", 0.0001)),
                maker_commission=float(inst.get("maker_commission", 0.0)),
                taker_commission=float(inst.get("taker_commission", 0.0)),
                block_trade_commission=float(inst.get("block_trade_commission", 0.0)),
                timestamp=datetime.now(UTC),
                provenance=Provenance.OBSERVED,
                origin="deribit",
            ))
        return result

    def book_summary(self, currency: str = "BTC") -> list[BookSummary]:
        raw = self._request("get_book_summary_by_currency", currency=currency, kind="option")
        summaries: list[dict[str, Any]] = raw.get("result", [])
        result: list[BookSummary] = []
        for s in summaries:
            ts = datetime.fromtimestamp(s.get("creation_timestamp", 0) / 1000, tz=UTC)
            iv = s.get("mark_iv")
            if iv is not None:
                iv = float(iv) / 100.0
            result.append(BookSummary(
                instrument_name=s.get("instrument_name", ""),
                mark_price=float(s.get("mark_price", 0)),
                mark_iv=iv or 0.0,
                bid_price=_safe_float(s.get("bid_price")),
                bid_iv=_safe_iv(s.get("bid_iv")),
                ask_price=_safe_float(s.get("ask_price")),
                ask_iv=_safe_iv(s.get("ask_iv")),
                open_interest=float(s.get("open_interest", 0)),
                underlying_price=float(s.get("underlying_price", 0)),
                interest_rate=float(s.get("interest_rate", 0)),
                timestamp=ts,
                provenance=Provenance.OBSERVED,
                origin="deribit",
            ))
        return result

    # ── Internal request logic with retries, backoff, fixture replay ─────

    def _request(self, endpoint: str, **params: Any) -> dict[str, Any]:
        slug = _endpoint_slug(endpoint, params)
        fixture = self._try_load_fixture(slug)
        if fixture is not None:
            return fixture

        url = f"{self._base}/{endpoint}"
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout_s)
            except requests.exceptions.Timeout:
                last_exc = DeribitTimeoutError(f"Timeout after {self._timeout_s}s on {endpoint}")
                _sleep_backoff(attempt)
                continue
            except requests.exceptions.ConnectionError as exc:
                last_exc = DeribitClientError(f"Connection error on {endpoint}: {exc}")
                _sleep_backoff(attempt)
                continue
            except requests.exceptions.RequestException as exc:
                last_exc = DeribitClientError(f"Request failed on {endpoint}: {exc}")
                _sleep_backoff(attempt)
                continue

            if resp.status_code == 429:
                last_exc = DeribitRateLimitError(f"Rate limited on {endpoint}")
                _sleep_backoff(attempt, cap=30.0)
                continue
            if resp.status_code >= 500:
                last_exc = DeribitServerError(f"Server error {resp.status_code} on {endpoint}")
                _sleep_backoff(attempt)
                continue

            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                last_exc = DeribitClientError(f"HTTP {resp.status_code} on {endpoint}: {exc}")
                _sleep_backoff(attempt)
                continue

            try:
                body: dict[str, Any] = resp.json()
            except ValueError as exc:
                last_exc = DeribitClientError(f"Invalid JSON from {endpoint}: {exc}")
                _sleep_backoff(attempt)
                continue

            if "error" in body and body["error"] is not None:
                err = body["error"]
                code = err.get("code", -1) if isinstance(err, dict) else -1
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                last_exc = DeribitApiError(code, msg)
                _sleep_backoff(attempt)
                continue

            return body

        raise DeribitClientError(
            f"All {self._max_retries} retries failed for {endpoint}"
        ) from last_exc

    def _try_load_fixture(self, slug: str) -> dict[str, Any] | None:
        if self._fixture_dir is None:
            return None
        path = self._fixture_dir / f"{slug}.json"
        if not path.exists():
            return None
        raw_bytes = path.read_bytes()
        data: Any = json.loads(raw_bytes)
        if isinstance(data, dict):
            return data
        return None

    def close(self) -> None:
        self._session.close()


def _endpoint_slug(endpoint: str, params: dict[str, Any]) -> str:
    mapping: dict[str, str] = {
        "get_index_price": "index_price",
        "get_volatility_index_data": "dvol",
        "get_instruments": "instruments",
        "get_book_summary_by_currency": "book_summary",
    }
    return mapping.get(endpoint, endpoint)


def _sleep_backoff(attempt: int, cap: float = MAX_DELAY_S) -> None:
    delay = min(BASE_DELAY_S * (2 ** (attempt - 1)) + random.uniform(0, 0.5 * BASE_DELAY_S), cap)
    time.sleep(delay)


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


def _safe_iv(v: Any) -> float | None:
    if v is None:
        return None
    return float(v) / 100.0
