"""Fixture recorder for Deribit public API responses.

Records byte-level copies of live API responses with SHA-256 manifest metadata.
Fixtures stored under tests/fixtures/ so tests replay offline without network.

Usage:
    python3 -m vol.fixture_recorder                          # records all endpoints
    python3 -m vol.fixture_recorder --dry-run                # preview without network
    python3 -m vol.fixture_recorder --output-dir /tmp/fx    # custom output dir
    python3 -m vol.fixture_recorder --endpoints index_price # specific endpoints only

Phase 0 — frozen per contracts.md §6.4.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import time
from datetime import UTC, datetime
from typing import Any

import requests

BASE: str = "https://www.deribit.com/api/v2/public"
FIXTURE_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
)
MANIFEST_PATH: pathlib.Path = FIXTURE_DIR / "manifest.json"


ENDPOINTS: list[tuple[str, str, dict[str, Any]]] = [
    ("get_index_price", "index_price", {"index_name": "btc_usd"}),
    (
        "get_volatility_index_data",
        "dvol",
        {
            "currency": "BTC",
            "start_timestamp": 0,
            "end_timestamp": 0,
            "resolution": "3600",
        },
    ),
    (
        "get_instruments",
        "instruments",
        {"currency": "BTC", "kind": "option", "expired": "false"},
    ),
    (
        "get_book_summary_by_currency",
        "book_summary",
        {"currency": "BTC", "kind": "option"},
    ),
]


def _get_raw(endpoint: str, params: dict[str, Any], timeout: int = 30) -> tuple[bytes, int]:
    """Fetch raw response bytes and status code."""
    url: str = f"{BASE}/{endpoint}"
    resp: requests.Response = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.content, resp.status_code


def record_fixtures(
    output_dir: pathlib.Path | None = None,
    endpoints: list[str] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Fetch Deribit endpoints and write responses to output_dir.

    When *dry_run* is True, prints what would be recorded without making
    network requests.  *endpoints* filters by slug name; None means all.

    Returns list of manifest entries (dicts) for inspection.
    """
    fixture_dir = output_dir or FIXTURE_DIR
    fixture_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = fixture_dir / "manifest.json"

    if endpoints is not None:
        filtered = [(ep, slug, params) for ep, slug, params in ENDPOINTS if slug in endpoints]
    else:
        filtered = list(ENDPOINTS)
    now: datetime = datetime.now(UTC)
    retrieval_ts: int = int(time.time() * 1000)
    entries: list[dict[str, Any]] = []

    for endpoint, slug, params_template in filtered:
        params: dict[str, Any] = dict(params_template)
        # Set timestamps for DVOL endpoint
        if endpoint == "get_volatility_index_data":
            params["end_timestamp"] = retrieval_ts
            params["start_timestamp"] = retrieval_ts - 86_400_000

        url: str = f"{BASE}/{endpoint}"
        file_name: str = f"{slug}.json"
        file_path: pathlib.Path = fixture_dir / file_name

        if dry_run:
            print(f"  ~ {slug}: would fetch {url} (dry-run)")
            entries.append({
                "path": file_name,
                "sha256": "",
                "retrieval_date": now.isoformat(),
                "venue": "deribit",
                "endpoint": endpoint,
                "record_count": 0,
                "status_code": 0,
                "byte_count": 0,
                "url": url,
            })
            continue

        try:
            content, status = _get_raw(endpoint, params)
        except Exception as exc:
            entries.append({
                "path": file_name,
                "sha256": "",
                "retrieval_date": now.isoformat(),
                "venue": "deribit",
                "endpoint": endpoint,
                "record_count": 0,
                "status_code": 0,
                "byte_count": 0,
                "url": url,
                "error": str(exc),
            })
            continue

        sha256: str = hashlib.sha256(content).hexdigest()
        file_path.write_bytes(content)

        # Count records for the manifest
        data: dict[str, Any] = json.loads(content.decode("utf-8"))
        result: object = data.get("result", [])
        if isinstance(result, list):
            record_count: int = len(result)
        elif isinstance(result, dict):
            record_count = 1
        else:
            record_count = 1 if result else 0

        entries.append({
            "path": file_name,
            "sha256": sha256,
            "retrieval_date": now.isoformat(),
            "venue": "deribit",
            "endpoint": endpoint,
            "record_count": record_count,
            "status_code": status,
            "byte_count": len(content),
            "url": url,
        })

        print(
            f"  ✓ {slug}: {record_count} records, {len(content)} bytes, "
            f"sha256={sha256[:16]}..."
        )

    # Write manifest
    manifest: dict[str, Any] = {
        "created_at": now.isoformat(),
        "description": "Replayable Deribit public API fixtures",
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Record Deribit public API responses as offline test fixtures.",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=None,
        help="Output directory (default: tests/fixtures/)",
    )
    parser.add_argument(
        "--endpoints",
        nargs="+",
        default=None,
        help="Endpoint slug(s) to record (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be recorded without making network requests",
    )
    args = parser.parse_args()

    if args.dry_run:
        print(f"Dry-run: would record to {args.output_dir or FIXTURE_DIR}/")
    else:
        print("Recording Deribit fixtures...")

    result_entries: list[dict[str, Any]] = record_fixtures(
        output_dir=args.output_dir,
        endpoints=args.endpoints,
        dry_run=args.dry_run,
    )
    if result_entries:
        out = args.output_dir or FIXTURE_DIR
        print(f"\n{'Would record' if args.dry_run else 'Recorded'} "
              f"{len(result_entries)} fixture(s) to {out}/")
        print(f"Manifest {'would be' if args.dry_run else ''} written to {out / 'manifest.json'}")
    else:
        print("No fixtures recorded.")
