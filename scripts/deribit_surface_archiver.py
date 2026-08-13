#!/usr/bin/env python3
"""Daily Deribit option-surface archiver (C10 · N2) — start the historical-Q clock.

SIMULATED / diagnostic; MS-26-gated; OBSERVED data; deck & canonical main untouched. Snapshots the full
live Deribit BTC option surface (instruments + book-summary marks/IVs + index + DVOL) once per day into a
checksummed, provenance-labelled archive under market_snapshots/deribit_surface_archive/<YYYY-MM-DD>/, so
the historical option-surface archive begins accruing immediately. Idempotent (skips a date already
snapshotted). Reuses the public DeribitClient (no auth). Cross-temporal Q-calibration + residual-tracking
(see cross_temporal_q.py) is DATA-GATED on this archive maturing (weeks of accrual, or a paid backfill).

Schedule (daily, e.g. 00:10 UTC) via cron:
    10 0 * * *  cd <repo> && <venv>/python scripts/deribit_surface_archiver.py >> logs/deribit_archiver.log 2>&1

Usage:  python scripts/deribit_surface_archiver.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

# Durable imports: prefer the local tree, but also expose the CANONICAL repo so a copy deployed OUTSIDE
# the ephemeral worktree (N3.0) can still import vol.client after the worktree is removed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.append("/home/francisco/btc/btc_engine_frontier")

from vol.client import DeribitClient

# Accruing archive lives at a STABLE canonical path outside the ephemeral worktree (N3.0), overridable
# via DERIBIT_ARCHIVE_DIR (tests point it at the committed in-repo fixture).
_ARCHIVE = pathlib.Path(os.environ.get("DERIBIT_ARCHIVE_DIR", "/home/francisco/btc/deribit_surface_archive"))


def _dump(models: list[Any]) -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") for m in models]


def snapshot(date: str, now: datetime) -> dict[str, Any]:
    out_dir = _ARCHIVE / date
    if (out_dir / "meta.json").exists():
        return {"date": date, "status": "already_exists", "dir": str(out_dir)}

    client = DeribitClient()
    try:
        instruments = _dump(client.option_chain("BTC"))
        book = _dump(client.book_summary("BTC"))
        index = client.spot_index("btc_usd").model_dump(mode="json")
        try:
            dvol = _dump(client.dvol_latest("BTC"))
        except Exception:                                       # DVOL is best-effort
            dvol = []
    finally:
        client.close()

    if not instruments or not book:
        raise RuntimeError(f"empty Deribit surface for {date} (instruments={len(instruments)} book={len(book)})")

    payloads = {"instruments.json": instruments, "book_summary.json": book,
                "index.json": index, "dvol.json": dvol}
    out_dir.mkdir(parents=True, exist_ok=True)
    digests = {}
    for fname, payload in payloads.items():
        blob = json.dumps(payload, sort_keys=True, default=str)
        (out_dir / fname).write_text(blob)
        digests[fname] = hashlib.sha256(blob.encode()).hexdigest()

    meta = {
        "date": date, "source": "deribit", "provenance": "OBSERVED", "currency": "BTC",
        "n_instruments": len(instruments), "n_book_rows": len(book),
        "index_price": index.get("price"), "n_dvol_rows": len(dvol),
        "sha256": digests, "fetched_at_utc": now.isoformat(),
        "endpoint": "www.deribit.com/api/v2/public (get_instruments/get_book_summary_by_currency)",
        "note": ("Daily live-surface snapshot for the historical-Q archive (C10 N2). Levels/IVs are the "
                 "Deribit marks at fetch time; the surface accrues one snapshot/day toward cross-temporal "
                 "Q-calibration (data-gated on maturity)."),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return {"date": date, "status": "written", "dir": str(out_dir),
            "n_instruments": len(instruments), "n_book_rows": len(book), "index_price": index.get("price")}


def main() -> int:
    now = datetime.now(UTC)
    date = now.date().isoformat()
    if len(sys.argv) > 2 and sys.argv[1] == "--date":
        date = sys.argv[2]
    res = snapshot(date, now)
    print(json.dumps(res, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
