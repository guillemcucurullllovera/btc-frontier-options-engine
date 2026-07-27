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
import requests

BASE = "https://www.deribit.com/api/v2/public"


def _get(method: str, **params) -> dict:
    r = requests.get(f"{BASE}/{method}", params=params, timeout=15)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def spot_index(currency_pair: str = "btc_usd") -> float:
    return _get("get_index_price", index_name=currency_pair)["index_price"]


def dvol_latest(currency: str = "BTC") -> float:
    now = int(time.time() * 1000)
    res = _get("get_volatility_index_data", currency=currency,
               start_timestamp=now - 86_400_000, end_timestamp=now, resolution="3600")
    # candles: [ts, open, high, low, close]
    return res["data"][-1][4]


def option_chain(currency: str = "BTC") -> list[dict]:
    return _get("get_instruments", currency=currency, kind="option", expired="false")


def book_summary(currency: str = "BTC") -> list[dict]:
    """Per-instrument mark_price, mark_iv, bid/ask, open_interest — the calibration input."""
    return _get("get_book_summary_by_currency", currency=currency, kind="option")


if __name__ == "__main__":
    print("BTC index:", spot_index())
    print("DVOL:", dvol_latest())
    chain = option_chain()
    print(f"Live option instruments: {len(chain)}")
