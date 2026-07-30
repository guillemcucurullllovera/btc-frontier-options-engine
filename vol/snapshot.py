"""Frozen live-market snapshots for reproducible, timestamped C8 evidence.

A snapshot is one atomic pull of the Deribit public endpoints (spot index,
DVOL, option instruments, per-instrument book summary), persisted byte-for-byte
under ``market_snapshots/<UTC>/`` together with SHA-256 checksums, the git SHA,
and a UTC timestamp.  Every downstream number cites this snapshot's "as of"
instant and checksums.

The persisted layout is deliberately identical to ``tests/fixtures/`` (the same
``<slug>.json`` files plus ``manifest.json``), so a frozen snapshot replays
through ``DeribitClient(fixture_dir=...)`` with no network — and the existing
fixtures directory is itself a loadable snapshot.

  * ``freeze_live_snapshot`` — pull live, freeze, checksum (requires egress).
  * ``load_snapshot``        — load a frozen snapshot offline.
  * ``latest_snapshot_dir``  — resolve the most-recent frozen snapshot.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from engine.data_models import BookSummary, DvolBar, OptionInstrument, SpotBar
from engine.errors import DataError
from vol.client import DeribitClient
from vol.fixture_recorder import record_fixtures

SNAPSHOT_META_FILE: str = "snapshot_meta.json"
MANIFEST_FILE: str = "manifest.json"
LATEST_POINTER: str = "latest.txt"
ENDPOINT_FILES: tuple[str, ...] = (
    "index_price.json",
    "dvol.json",
    "instruments.json",
    "book_summary.json",
)
_REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]


class SnapshotError(DataError):
    """Snapshot freeze or load error."""


@dataclass(frozen=True)
class SnapshotMeta:
    created_at: datetime
    git_sha: str
    git_branch: str
    endpoints: list[str]
    checksums: dict[str, str]
    spot_usd: float
    dvol_latest: float | None
    provenance: dict[str, str]
    origin: str = "deribit"


@dataclass(frozen=True)
class MarketSnapshot:
    directory: pathlib.Path
    meta: SnapshotMeta
    spot: SpotBar
    dvol: list[DvolBar]
    instruments: list[OptionInstrument]
    book_summaries: list[BookSummary]

    @property
    def created_at(self) -> datetime:
        return self.meta.created_at


# ── Load ───────────────────────────────────────────────────────────────────


def load_snapshot(directory: pathlib.Path) -> MarketSnapshot:
    """Load a frozen snapshot (offline replay via DeribitClient fixtures).

    Metadata is read from ``snapshot_meta.json`` when present; otherwise it is
    reconstructed from ``manifest.json`` (git SHA marked "unknown").
    """
    directory = pathlib.Path(directory)
    if not directory.is_dir():
        raise SnapshotError(f"Snapshot directory does not exist: {directory}")
    for name in ENDPOINT_FILES:
        if not (directory / name).exists():
            raise SnapshotError(f"Snapshot missing endpoint file: {name}")

    client = DeribitClient(fixture_dir=directory)
    try:
        spot = client.spot_index()
        dvol = client.dvol_latest()
        instruments = client.option_chain()
        book_summaries = client.book_summary()
    finally:
        client.close()

    meta = _load_meta(directory, spot, dvol)
    return MarketSnapshot(
        directory=directory,
        meta=meta,
        spot=spot,
        dvol=dvol,
        instruments=instruments,
        book_summaries=book_summaries,
    )


def _load_meta(
    directory: pathlib.Path, spot: SpotBar, dvol: list[DvolBar]
) -> SnapshotMeta:
    meta_path = directory / SNAPSHOT_META_FILE
    if meta_path.exists():
        raw: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
        return SnapshotMeta(
            created_at=datetime.fromisoformat(raw["created_at"]),
            git_sha=str(raw.get("git_sha", "unknown")),
            git_branch=str(raw.get("git_branch", "unknown")),
            endpoints=list(raw.get("endpoints", [])),
            checksums=dict(raw.get("checksums", {})),
            spot_usd=float(raw.get("spot_usd", spot.price)),
            dvol_latest=(
                None if raw.get("dvol_latest") is None else float(raw["dvol_latest"])
            ),
            provenance=dict(raw.get("provenance", {})),
            origin=str(raw.get("origin", "deribit")),
        )
    return _reconstruct_meta(directory, spot, dvol)


def _reconstruct_meta(
    directory: pathlib.Path, spot: SpotBar, dvol: list[DvolBar]
) -> SnapshotMeta:
    manifest_path = directory / MANIFEST_FILE
    checksums: dict[str, str] = {}
    endpoints: list[str] = []
    created_at = spot.timestamp
    if manifest_path.exists():
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest.get("entries", []):
            path = str(entry.get("path", ""))
            if path:
                checksums[path] = str(entry.get("sha256", ""))
            endpoint = str(entry.get("endpoint", ""))
            if endpoint:
                endpoints.append(endpoint)
        created_raw = manifest.get("created_at")
        if isinstance(created_raw, str):
            created_at = datetime.fromisoformat(created_raw)
    return SnapshotMeta(
        created_at=created_at,
        git_sha="unknown",
        git_branch="unknown",
        endpoints=endpoints,
        checksums=checksums,
        spot_usd=spot.price,
        dvol_latest=dvol[-1].close if dvol else None,
        provenance=_observed_provenance(),
        origin="deribit",
    )


# ── Freeze ─────────────────────────────────────────────────────────────────


def freeze_live_snapshot(
    out_root: pathlib.Path,
    reference: datetime | None = None,
) -> MarketSnapshot:
    """Pull the live Deribit endpoints once and freeze them under out_root.

    Requires network egress.  Raises SnapshotError if any endpoint fails so a
    partial snapshot is never persisted as authoritative.
    """
    out_root = pathlib.Path(out_root)
    ts = reference or datetime.now(UTC)
    snap_dir = out_root / _dirname(ts)
    snap_dir.mkdir(parents=True, exist_ok=True)

    entries = record_fixtures(output_dir=snap_dir)
    _validate_entries(entries, snap_dir)

    checksums = {str(e["path"]): str(e["sha256"]) for e in entries}
    endpoints = [str(e["endpoint"]) for e in entries]

    client = DeribitClient(fixture_dir=snap_dir)
    try:
        spot = client.spot_index()
        dvol = client.dvol_latest()
        instruments = client.option_chain()
        book_summaries = client.book_summary()
    finally:
        client.close()

    meta = SnapshotMeta(
        created_at=ts,
        git_sha=_git("rev-parse", "HEAD"),
        git_branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
        endpoints=endpoints,
        checksums=checksums,
        spot_usd=spot.price,
        dvol_latest=dvol[-1].close if dvol else None,
        provenance=_observed_provenance(),
        origin="deribit",
    )
    _write_meta(snap_dir, meta)
    (out_root / LATEST_POINTER).write_text(_dirname(ts), encoding="utf-8")

    return MarketSnapshot(
        directory=snap_dir,
        meta=meta,
        spot=spot,
        dvol=dvol,
        instruments=instruments,
        book_summaries=book_summaries,
    )


def latest_snapshot_dir(out_root: pathlib.Path) -> pathlib.Path | None:
    """Resolve the most-recent frozen snapshot directory, or None."""
    out_root = pathlib.Path(out_root)
    pointer = out_root / LATEST_POINTER
    if pointer.exists():
        name = pointer.read_text(encoding="utf-8").strip()
        candidate = out_root / name
        if candidate.is_dir():
            return candidate
    if not out_root.is_dir():
        return None
    dirs = sorted(
        (p for p in out_root.iterdir() if p.is_dir() and (p / MANIFEST_FILE).exists()),
        key=lambda p: p.name,
    )
    return dirs[-1] if dirs else None


# ── Helpers ────────────────────────────────────────────────────────────────


def _observed_provenance() -> dict[str, str]:
    return {
        "spot": "observed",
        "dvol": "observed",
        "instruments": "observed",
        "book_summary": "observed",
    }


def _validate_entries(entries: list[dict[str, Any]], snap_dir: pathlib.Path) -> None:
    by_endpoint = {str(e.get("endpoint", "")): e for e in entries}
    required = {
        "get_index_price",
        "get_volatility_index_data",
        "get_instruments",
        "get_book_summary_by_currency",
    }
    missing = required - set(by_endpoint)
    if missing:
        raise SnapshotError(f"Snapshot {snap_dir} missing endpoints: {sorted(missing)}")
    for endpoint, entry in by_endpoint.items():
        if entry.get("status_code") != 200 or not entry.get("sha256"):
            raise SnapshotError(
                f"Snapshot {snap_dir} endpoint {endpoint} failed: {entry.get('error', entry)}"
            )


def _write_meta(directory: pathlib.Path, meta: SnapshotMeta) -> None:
    payload = asdict(meta)
    payload["created_at"] = meta.created_at.isoformat()
    (directory / SNAPSHOT_META_FILE).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _dirname(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"
