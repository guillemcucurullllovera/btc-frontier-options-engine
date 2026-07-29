"""Offline fixture loader for replaying Deribit API responses in tests.

Fixtures are stored in tests/fixtures/ with a SHA-256 manifest.
Test helper functions return pre-recorded data without ever touching the network.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from engine.errors import DataError

FIXTURE_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
)


def _manifest_sha256(name: str) -> str | None:
    """SHA-256 recorded in the manifest for `{name}.json`, or None if absent."""
    for entry in load_manifest().get("entries", []):
        if entry.get("path") == f"{name}.json":
            sha = entry.get("sha256")
            return str(sha) if sha else None
    return None


def load_fixture(name: str, verify: bool = True) -> dict[str, Any]:
    """Load a single fixture by slug (e.g. 'index_price', 'dvol', 'instruments', 'book_summary').

    Returns the parsed JSON body as a dict.  Raises FileNotFoundError if the
    fixture has not been recorded yet. FRF-023 / AT-023: when `verify` is set and
    the manifest carries a hash for this fixture, the file's SHA-256 is checked
    at load and a mismatch raises `DataError` (no silent tampered/stale replay).
    """
    path: pathlib.Path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Fixture '{name}' not found at {path}. "
            f"Run 'python3 -m vol.fixture_recorder' to record live fixtures."
        )
    raw = path.read_bytes()
    if verify:
        expected = _manifest_sha256(name)
        if expected is not None:
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected:
                raise DataError(
                    f"fixture '{name}' SHA-256 mismatch: manifest {expected} != file {actual}"
                )
    data: Any = json.loads(raw)
    if isinstance(data, dict):
        return data
    return {}


def load_manifest() -> dict[str, Any]:
    """Load the SHA-256 fixture manifest."""
    path: pathlib.Path = FIXTURE_DIR / "manifest.json"
    if not path.exists():
        return {"entries": [], "description": "No fixture manifest"}
    data: Any = json.loads(path.read_bytes())
    if isinstance(data, dict):
        return data
    return {"entries": [], "description": "Invalid manifest"}


def fixture_available(name: str) -> bool:
    """Check whether a fixture is available for offline replay."""
    return (FIXTURE_DIR / f"{name}.json").exists()
