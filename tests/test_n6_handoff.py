"""C10 · N6 — self-contained design hand-off bundle.

SIMULATED / diagnostic; MS-26-gated; deck & canonical main untouched. Validates the committed hand-off
bundle is present and self-contained: the master doc carries the governance disclaimer, the five
corrections, the full inline data grid, and the 7 figure references; the migration manifest lists the SVG
uploads; the results brief carries the snapshot + verification note; and the figures/ directory holds all 7
per-structure figures + the comparison (PNG+SVG). The external design session has no repo access, so every
number/instruction must be inline — only the image files are uploaded.
"""

from __future__ import annotations

import pathlib

_H = pathlib.Path(__file__).resolve().parents[1] / "docs" / "handoff"
_STRUCTS = ("unhedged", "covered_call", "long_btc_plus_short_put", "cash_secured_put",
            "collar", "call_spread", "strike_ladder")


def test_handoff_master_is_self_contained() -> None:
    doc = (_H / "DESIGN_HANDOFF.md").read_text()
    assert "MS-26-gated" in doc and "OPPORTUNITY COST" in doc and "NOT a loss" in doc     # governance
    assert "five corrections" in doc.lower() and "risk-reshaping" in doc.lower()          # the 5 corrections
    assert doc.count("| covered_call ") + doc.count("| collar ") > 10                     # inline data grid
    for n in _STRUCTS:
        assert f"{n}.svg" in doc or f"{n}.png" in doc or n.replace("_", " ") in doc       # figure references
    assert "63,402" in doc                                                                # inline S0 (no repo lookup)


def test_migration_manifest_lists_uploads_and_map() -> None:
    m = (_H / "MIGRATION_MANIFEST.md").read_text()
    for n in _STRUCTS:
        assert f"figures/{n}.svg" in m                                                    # upload each figure
    assert "_comparison_collar_vs_covered.svg" in m
    assert "PASTE" in m and "old-slide" in m.lower() and "piled" in m.lower()             # paste + old->new map


def test_results_brief_has_snapshot_and_verification() -> None:
    b = (_H / "RESULTS_BRIEF.md").read_text()
    assert "Snapshot" in b and "Verification note" in b
    assert "+4.5%" in b and "0.46" in b                                                   # corrected numbers inline


def test_figures_bundled_png_and_svg() -> None:
    figs = _H / "figures"
    for n in (*_STRUCTS, "_comparison_collar_vs_covered"):
        for ext in ("png", "svg"):
            f = figs / f"{n}.{ext}"
            assert f.exists() and f.stat().st_size > 1000
