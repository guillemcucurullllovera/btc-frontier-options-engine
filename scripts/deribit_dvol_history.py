#!/usr/bin/env python3
"""Fetch the FREE Deribit DVOL daily history (C10 · N3.1) — the ATM Q-vol level back years, now.

SIMULATED / diagnostic; MS-26-gated; OBSERVED (Deribit DVOL index); deck & canonical main untouched.
DVOL is Deribit's 30-day ATM implied-volatility index — a FREE, immediately-available historical ATM
Q-vol level (no paid backfill needed). Paginates get_volatility_index_data (1000 rows/call) back to the
DVOL launch (~2021-03) and writes a checksummed, provenance-labelled snapshot to
market_snapshots/deribit_dvol_history/dvol_daily.json (+ meta.json).

Usage:  python scripts/deribit_dvol_history.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import time
import urllib.request
from datetime import UTC, datetime

_OUT = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "deribit_dvol_history"
_URL = ("https://www.deribit.com/api/v2/public/get_volatility_index_data"
        "?currency=BTC&start_timestamp={s}&end_timestamp={e}&resolution=86400")
_LAUNCH_MS = int(datetime(2021, 3, 24, tzinfo=UTC).timestamp() * 1000)   # DVOL inception


def _fetch(start_ms: int, end_ms: int) -> list[list[float]]:
    with urllib.request.urlopen(_URL.format(s=start_ms, e=end_ms), timeout=30) as r:
        return list(json.load(r)["result"].get("data", []))


def main() -> int:
    now = datetime.now(UTC)
    end_ms = int(now.timestamp() * 1000)
    rows: dict[int, list[float]] = {}
    day = 86_400_000
    cursor = end_ms
    for _ in range(12):                                     # paginate back to launch (<= 12 calls)
        batch = _fetch(_LAUNCH_MS, cursor)
        if not batch:
            break
        for row in batch:
            rows[int(row[0])] = row
        oldest = min(int(row[0]) for row in batch)
        if oldest <= _LAUNCH_MS + day:
            break
        cursor = oldest - day                              # step the window back
        time.sleep(0.3)

    daily = [{"date": datetime.fromtimestamp(t / 1000, UTC).date().isoformat(),
              "dvol": float(rows[t][4]) / 100.0}                          # close, decimal
             for t in sorted(rows) if t <= end_ms - day]                  # exclude the incomplete current day
    _OUT.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(daily, sort_keys=True)
    (_OUT / "dvol_daily.json").write_text(blob)
    meta = {"source": "deribit", "index": "DVOL (30d ATM IV)", "provenance": "OBSERVED",
            "n_days": len(daily), "start": daily[0]["date"] if daily else None,
            "end": daily[-1]["date"] if daily else None,
            "sha256": hashlib.sha256(blob.encode()).hexdigest(), "fetched_at_utc": now.isoformat(),
            "endpoint": "get_volatility_index_data (resolution=86400)",
            "note": "FREE ATM Q-vol level history (no paid backfill); decimal (DVOL%/100)."}
    (_OUT / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"DVOL daily: {len(daily)} days {meta['start']} -> {meta['end']} "
          f"sha={str(meta['sha256'])[:12]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
