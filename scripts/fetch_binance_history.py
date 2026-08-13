#!/usr/bin/env python3
"""Fetch Binance BTCUSDT klines history into checksummed snapshots (C9 · overnight Phase B).

Builds three frozen snapshots under ``market_snapshots/binance_history/{1d,1h,1m}/``:
  * 1d  — full daily history from 2017-08 to now (~2900 bars),
  * 1h  — hourly from 2019-01 to now (~66k bars),
  * 1m  — last ~90 days (~130k bars).

Each snapshot is ``bars.json`` (list of HistoricalSpotBar) + ``meta.json`` (source, provenance, basis
caveat, date range, n_bars, sha256 over the canonical bars payload). Bulk history comes from the public
``data.binance.vision`` archive; the recent tail (current month / day) from the public REST endpoint.
No API key. The incomplete current bar is excluded. Provenance OBSERVED, origin ``binance``.

Usage:  python scripts/fetch_binance_history.py [--only 1d,1h,1m]
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.data_models import HistoricalSpotBar
from vol.binance import BinanceKlinesProvider

_OUT = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history"
_INTERVAL_SECONDS = {"1d": 86_400, "1h": 3_600, "1m": 60}
_BULK_START = {"1d": (2017, 8), "1h": (2019, 1), "1m": None}   # 1m uses lookback, not full bulk


def _month_iter(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    y, m = start
    out = []
    while (y, m) <= end:
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _build(
    interval: str, now: datetime, lookback_days: int | None = None,
) -> tuple[list[HistoricalSpotBar], dict[str, object]]:
    prov = BinanceKlinesProvider(interval=interval)
    bars: list[HistoricalSpotBar] = []

    if lookback_days is not None:                       # 1m: bulk months covering the lookback window
        start_dt = now - timedelta(days=lookback_days)
        months = _month_iter((start_dt.year, start_dt.month), (now.year, now.month))
    else:
        bulk_start = _BULK_START[interval]
        assert bulk_start is not None                   # non-1m intervals have a full-bulk start month
        months = _month_iter(bulk_start, (now.year, now.month))

    # complete months from the bulk archive (skip the current month -> REST fills it)
    for (y, m) in months:
        if (y, m) == (now.year, now.month):
            continue
        try:
            bars.extend(prov.fetch_bulk_month(y, m))
        except Exception as exc:                        # tolerate a missing month, keep going
            print(f"  [warn] bulk {interval} {y}-{m:02d}: {type(exc).__name__}", flush=True)

    # recent tail via REST (from the last bulk bar, or the lookback start)
    rest_start = (bars[-1].timestamp + timedelta(seconds=1)) if bars else (
        now - timedelta(days=lookback_days or 3))
    try:
        bars.extend(prov.fetch_rest(rest_start, now))
    except Exception as exc:
        print(f"  [warn] REST {interval} tail: {type(exc).__name__}", flush=True)
    prov.close()

    # dedup + sort, exclude the incomplete current bar (bar must be fully closed)
    step = _INTERVAL_SECONDS[interval]
    now_s = now.timestamp()
    uniq = {b.timestamp: b for b in bars}
    complete = [b for b in sorted(uniq.values(), key=lambda x: x.timestamp)
                if b.timestamp.timestamp() + step <= now_s]
    if lookback_days is not None:                       # trim 1m to exactly the lookback window
        cutoff = now - timedelta(days=lookback_days)
        complete = [b for b in complete if b.timestamp >= cutoff]

    payload = [b.model_dump(mode="json") for b in complete]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    meta = {
        "source": "binance", "symbol": "BTCUSDT", "interval": interval, "provenance": "OBSERVED",
        "n_bars": len(complete),
        "start": complete[0].timestamp.isoformat() if complete else None,
        "end": complete[-1].timestamp.isoformat() if complete else None,
        "sha256": digest, "fetched_at": now.date().isoformat(),
        "bulk_source": "data.binance.vision", "rest_source": "api.binance.com/api/v3/klines",
        "basis_caveat": (
            "BTCUSDT (USDT-quoted Binance spot) vs the Deribit USD index: price LEVELS differ by the "
            "small/stationary USDT basis + exchange composition; LOG-RETURNS (the input to all physical "
            "dynamics estimation) are an excellent BTC/USD proxy. Frozen option/DVOL anchor untouched."
        ),
        "note": "incomplete current bar excluded; timestamps normalised (ms/µs->s).",
    }
    return complete, meta


def main() -> int:
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--only":
        only = set(sys.argv[2].split(","))
    now = datetime.now(UTC)
    specs = [("1d", None), ("1h", None), ("1m", 90)]
    for interval, lookback in specs:
        if only and interval not in only:
            continue
        print(f"[fetch] {interval} ...", flush=True)
        bars, meta = _build(interval, now, lookback_days=lookback)
        out_dir = _OUT / interval
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "bars.json").write_text(json.dumps([b.model_dump(mode="json") for b in bars]))
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        print(f"  {interval}: {meta['n_bars']} bars {meta['start']} -> {meta['end']} "
              f"sha={str(meta['sha256'])[:12]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
