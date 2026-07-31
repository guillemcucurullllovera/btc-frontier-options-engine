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


def test_handoff_covers_all_ten_slides() -> None:  # N6.5a — whole-deck slide-by-slide
    doc = (_H / "DESIGN_HANDOFF.md").read_text()
    for slide in ("Slide 00 ", "Slide 00b ", "Slide 1 ", "Slide 2 ", "Slide 2b ",
                  "Slide 3 ", "Slide 4 ", "Slide 5 ", "Slide 6 ", "Slide 7 "):
        assert f"### {slide}" in doc, slide
    # Slide 3 / 5 rewritten to the current engine
    assert "COS" in doc and "SVJJ" in doc and "SVI/SSVI" in doc and "881" in doc


def test_handoff_standalone_and_dual_objective_framing() -> None:  # N6.5b + N6.5c
    doc = (_H / "DESIGN_HANDOFF.md").read_text()
    assert "STANDALONE-SYSTEM FRAMING" in doc and "no before/after" in doc.lower()
    assert "DUAL-OBJECTIVE" in doc
    assert "Accumulation" in doc and "Long BTC + short put" in doc                        # accumulation path
    assert "Protection" in doc and "collar" in doc and "INVARIANT" in doc                 # protection path
    # objective-conditional, never universal best/optimal
    assert "best/optimal" in doc and "natural" in doc.lower()


def test_handoff_live_reanchor_with_deal_reference() -> None:  # N6.5d
    doc = (_H / "DESIGN_HANDOFF.md").read_text()
    assert "63,402" in doc and "65,000" in doc                                            # both bases shown
    assert "deal reference" in doc.lower() and "live snapshot" in doc.lower()
    assert "2026-07-28" in doc                                                            # stamped as-of date
    # Slide-1 economics recomputed at live (the value decomposition, engine waterfall)
    assert "60,631" in doc and "4.37%" in doc and "1,902" in doc


def test_migration_manifest_lists_uploads_and_map() -> None:
    m = (_H / "MIGRATION_MANIFEST.md").read_text()
    for n in _STRUCTS:
        assert f"figures/{n}.svg" in m                                                    # upload each figure
    assert "_comparison_collar_vs_covered.svg" in m
    assert "PASTE" in m and "old-slide" in m.lower() and "piled" in m.lower()             # paste + old->new map


def test_vrp_framing_positive_and_honest() -> None:  # N6.6a
    for fn in ("DESIGN_HANDOFF.md", "RESULTS_BRIEF.md"):
        t = (_H / fn).read_text().lower()
        assert "fair-valued" not in t and "positive but thin" not in t and "premium edge" not in t
        assert "real, positive, stable premium" in t                     # leads positive
        assert "tail-compensated" in t and "not a risk-free edge" in t   # keeps the honesty


def test_collar_rows_disambiguated_by_put_floor() -> None:  # N6.6b
    doc = (_H / "DESIGN_HANDOFF.md").read_text()
    assert "put floor%" in doc                                           # the new distinguishing column
    # both collar variants appear in the appendix, self-labelled by put floor
    assert "| collar | 28AUG26 (31d) | +2 | -10 |" in doc
    assert "| collar | 28AUG26 (31d) | +2 | -5 |" in doc
    # the featured Slide-2b cell is still the 10%-floor variant (-6,010, 0.62%)
    assert "| collar | +5% / 100% / 28AUG26 | 0.62% (392 $/BTC) | 0.727 | -6,010 " in doc


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
