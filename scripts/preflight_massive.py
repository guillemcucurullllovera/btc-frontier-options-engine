#!/usr/bin/env python3
"""Massive live preflight — performs a short live request and prints diagnostics.

Exits non-zero if the data is missing, synthetic, malformed or empty.

Usage:
  python scripts/preflight_massive.py [--days 30]
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from config.models import Provenance
from vol.history import (
    HistoricalSpotError,
    HistoricalSpotNotFound,
    MassiveSpotProvider,
)

_MASSIVE_ENDPOINT = MassiveSpotProvider.ENDPOINT_PATH


def main() -> int:
    days = 30
    if len(sys.argv) > 2 and sys.argv[1] == "--days":
        days = int(sys.argv[2])

    api_key = os.environ.get("MASSIVE_API_KEY", "")
    if not api_key:
        print("ERROR: MASSIVE_API_KEY not set in environment")
        return 1

    end_date = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    start_date = end_date - timedelta(days=days)

    cache_dir = pathlib.Path(tempfile.mkdtemp(prefix="massive_preflight_"))
    provider = MassiveSpotProvider(api_key=api_key, cache_dir=cache_dir)

    fallback_used = False
    used_provider = "massive"
    provenance = Provenance.OBSERVED.value
    bars: list[Any] = []
    fetch_error: str | None = None
    endpoint = "/v2/aggs/ticker/{ticker}/range/1/day/{from_}/{to}".format(
        ticker=MassiveSpotProvider.TICKER,
        from_=start_date.strftime("%Y-%m-%d"),
        to=end_date.strftime("%Y-%m-%d"),
    )

    try:
        bars = provider.fetch_bars(start=start_date, end=end_date)
    except HistoricalSpotNotFound:
        print("ERROR: Massive returned no results for the requested period")
        return 1
    except HistoricalSpotError as exc:
        fetch_error = str(exc)

    if not bars and fetch_error:
        print(f"ERROR: Massive fetch failed: {fetch_error}")
        return 1

    if not bars:
        print("ERROR: Massive returned empty data")
        return 1

    for b in bars:
        if b.provenance == Provenance.SIMULATED:
            print("ERROR: Bars have SIMULATED provenance — rejecting synthetic data")
            return 1

    if any(b.provenance != Provenance.OBSERVED for b in bars):
        print("ERROR: Bars have non-OBSERVED provenance")
        return 1

    if any(b.origin != "massive" for b in bars):
        fallback_used = True
        used_provider = bars[0].origin

    actual_start = bars[0].timestamp
    actual_end = bars[-1].timestamp

    for i in range(1, len(bars)):
        if bars[i].timestamp <= bars[i - 1].timestamp:
            print(f"ERROR: Non-monotonic timestamps at index {i}")
            return 1

    csv_lines = [f"{b.timestamp.isoformat()},{b.close}" for b in bars]
    checksum = hashlib.sha256("\n".join(csv_lines).encode()).hexdigest()

    cache_files = sorted(cache_dir.glob("massive_*.json"))
    cache_path = str(cache_files[-1]) if cache_files else ""

    print("provider:", used_provider)
    print("endpoint:", endpoint)
    print("requested_start:", start_date.isoformat())
    print("requested_end:", end_date.isoformat())
    print("actual_start:", actual_start.isoformat())
    print("actual_end:", actual_end.isoformat())
    print("observation_count:", len(bars))
    print("provenance:", provenance)
    print("fallback_used:", fallback_used)
    print("checksum:", checksum)
    print("cache_path:", cache_path)

    raw_json = json.dumps({
        "provider": used_provider,
        "endpoint": endpoint,
        "requested_start": start_date.isoformat(),
        "requested_end": end_date.isoformat(),
        "actual_start": actual_start.isoformat(),
        "actual_end": actual_end.isoformat(),
        "observation_count": len(bars),
        "provenance": provenance,
        "fallback_used": fallback_used,
        "checksum": checksum,
        "cache_path": cache_path,
    }, indent=2)
    print("\n--- JSON ---")
    print(raw_json)

    provider.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
