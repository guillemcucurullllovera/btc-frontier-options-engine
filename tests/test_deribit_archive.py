"""C10 · N2 — Deribit surface archive + cross-temporal Q pipeline (network-free).

SIMULATED / diagnostic; MS-26-gated; OBSERVED surfaces; deck & canonical main untouched. Validates the
seeded day-1 archive (provenance OBSERVED, checksummed, sane size) with checksum INTEGRITY, and that the
cross-temporal Q pipeline calibrates a sensible Heston to the archived live surface. The cross-temporal
STABILITY series is data-gated on the archive accruing (weeks / backfill) — not asserted here.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib

_ARCHIVE = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "deribit_surface_archive"


def _day_dirs() -> list[pathlib.Path]:
    return sorted(d for d in _ARCHIVE.glob("*") if d.is_dir() and (d / "meta.json").exists())


def test_archive_meta_observed_and_checksum_integrity() -> None:
    days = _day_dirs()
    assert days, "no archived Deribit surface day (expected the seeded day 1)"
    d = days[0]
    meta = json.loads((d / "meta.json").read_text())
    assert meta["source"] == "deribit" and meta["provenance"] == "OBSERVED"
    assert meta["n_instruments"] >= 100 and meta["n_book_rows"] >= 100
    # checksum integrity: recompute sha256 of each payload and match the committed digest
    for fname, digest in meta["sha256"].items():
        blob = (d / fname).read_text()
        assert hashlib.sha256(blob.encode()).hexdigest() == digest, f"checksum mismatch {fname}"


def test_q_pipeline_calibrates_archived_surface() -> None:
    from scripts.cross_temporal_q import _calibrate_date
    row = _calibrate_date(_day_dirs()[0])
    assert row is not None                                   # >=2 usable weekly+ slices on the live surface
    assert math.isfinite(row["arpe"]) and 0.0 < row["arpe"] < 0.30
    assert 0.2 < row["atm_vol"] < 1.5                        # a sane BTC ATM vol from the calibration
    assert row["n_options"] >= 20 and row["kappa"] > 0.0
