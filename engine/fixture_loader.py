"""Offline fixture loader for replaying Deribit API responses in tests.

Fixtures are stored in tests/fixtures/ with a SHA-256 manifest.
Test helper functions return pre-recorded data without ever touching the network.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

FIXTURE_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
)


def load_fixture(name: str) -> dict[str, Any]:
    """Load a single fixture by slug (e.g. 'index_price', 'dvol', 'instruments', 'book_summary').

    Returns the parsed JSON body as a dict.  Raises FileNotFoundError if
    the fixture has not been recorded yet.
    """
    path: pathlib.Path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Fixture '{name}' not found at {path}. "
            f"Run 'python3 -m vol.fixture_recorder' to record live fixtures."
        )
    data: Any = json.loads(path.read_bytes())
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
