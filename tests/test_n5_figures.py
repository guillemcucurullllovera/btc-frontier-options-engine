"""C10 · N5 — figure-pack render smoke-test.

SIMULATED / diagnostic; MS-26-gated; deck & canonical main untouched. Verifies the per-structure figure
render produces all 7 standalone figures (PNG+SVG) + a manifest, DETERMINISTICALLY (byte-identical across
runs — no wall-clock/random baked in). matplotlib is a render-time dependency; the test importorskips it so
a minimal environment skips gracefully (the committed PNG/SVG are the deliverable).
"""

from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("matplotlib")   # render-time dep; skip smoke-test if absent (committed figures stand)


def test_figure_pack_renders_all_seven_deterministically() -> None:
    from scripts.render_c10_figures import _OUT, _TITLE, main

    assert main() == 0
    for name in _TITLE:                                        # the 7 structures
        for ext in ("png", "svg"):
            f = _OUT / f"{name}.{ext}"
            assert f.exists() and f.stat().st_size > 1000      # a real figure, not an empty stub
    man = json.loads((_OUT / "manifest.json").read_text())
    assert len(man["figures"]) == 7                            # one figure per structure
    assert "comparison_figure" in man                         # the single illustrative comparison (N5.2)

    # deterministic render: re-render and confirm byte-identical output (no wall-clock/random)
    h1 = hashlib.sha256((_OUT / "collar.svg").read_bytes()).hexdigest()
    assert main() == 0
    h2 = hashlib.sha256((_OUT / "collar.svg").read_bytes()).hexdigest()
    assert h1 == h2
