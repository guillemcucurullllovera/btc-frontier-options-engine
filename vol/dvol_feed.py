"""Deribit public market-data feed (no authentication required for these endpoints).
Docs: https://docs.deribit.com  — verify current spec on first Hetzner run (Agent A2).

Endpoints used:
  /public/get_index_price            currency index (btc_usd)
  /public/get_volatility_index_data  DVOL history (resolution seconds: 3600, 43200, 86400)
  /public/get_instruments            live option chain metadata
  /public/get_book_summary_by_currency  mark/bid/ask/IV per instrument

NOTE: this sandbox has no route to deribit.com — run from the Hetzner box.
Offline fixtures for tests live in tests/fixtures/.
"""

from __future__ import annotations

import time
from typing import Any

import requests

BASE: str = "https://www.deribit.com/api/v2/public"


def _get_raw(endpoint: str, **params: Any) -> dict[str, Any]:
    """Call Deribit public API and return parsed JSON body."""
    r: requests.Response = requests.get(f"{BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    body: dict[str, Any] = r.json()
    if "error" in body:
        raise RuntimeError(body["error"])
    return body


def spot_index(currency_pair: str = "btc_usd") -> float:
    body: dict[str, Any] = _get_raw("get_index_price", index_name=currency_pair)
    result: dict[str, Any] = body["result"]
    return float(result["index_price"])


def dvol_latest(currency: str = "BTC") -> float:
    now: int = int(time.time() * 1000)
    body: dict[str, Any] = _get_raw(
        "get_volatility_index_data",
        currency=currency,
        start_timestamp=now - 86_400_000,
        end_timestamp=now,
        resolution="3600",
    )
    result: dict[str, Any] = body["result"]
    data: list[list[float]] = result["data"]
    return float(data[-1][4])


def option_chain(currency: str = "BTC") -> list[dict[str, Any]]:
    body: dict[str, Any] = _get_raw(
        "get_instruments", currency=currency, kind="option", expired="false"
    )
    instruments: Any = body["result"]
    if isinstance(instruments, list):
        return instruments
    return []


def book_summary(currency: str = "BTC") -> list[dict[str, Any]]:
    """Per-instrument mark_price, mark_iv, bid/ask, open_interest — the calibration input."""
    body: dict[str, Any] = _get_raw(
        "get_book_summary_by_currency", currency=currency, kind="option"
    )
    summaries: Any = body["result"]
    if isinstance(summaries, list):
        return summaries
    return []


if __name__ == "__main__":
    print("BTC index:", spot_index())
    print("DVOL:", dvol_latest())
    chain: list[dict[str, Any]] = option_chain()
    print(f"Live option instruments: {len(chain)}")
