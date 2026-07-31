"""C10 · N4 — deck-input regeneration + per-structure figure-source (readiness pack).

SIMULATED / diagnostic; MS-26-gated; holder-basis; deck & canonical main untouched. Validates the
regenerated deck-input manifest (full grid; SVJJ observed-co-jump honest-downside; defined-risk invariance;
positive forward VRP) and the per-structure figure-source (one clean figure per structure — annotated
payoff curve + sigma bars + max-loss/opportunity decomposition; defined-risk structures have a tight
capped floor).
"""

from __future__ import annotations

import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "docs" / "reports" / "c10_deck_input" / "manifest.json"
_FIGSRC = _ROOT / "docs" / "reports" / "c10_figure_source"
_STRUCTURES = ("unhedged", "covered_call", "long_btc_plus_short_put", "cash_secured_put",
               "collar", "call_spread", "strike_ladder")


def test_deck_input_manifest_corrected_and_complete() -> None:
    m = json.loads(_MANIFEST.read_text())
    assert m["n_grid_rows"] >= 200                             # full grid (structures x strike x expiry x cov)
    assert set(m["structures"]) == set(_STRUCTURES)
    assert m["coverage_pct"] == [25, 50, 75, 100]
    assert "SUPERSEDES" in m["supersedes"].upper() or "c8" in m["supersedes"].lower()
    scen = m["svjj_scenarios"]
    assert scen["rho_j_observed"] < -0.5                       # observed co-jump carried (N3.6)
    assert scen["forward_vrp_atm"] > 0.0                       # corrected: forward VRP POSITIVE (N3.1)
    ps = scen["per_structure"]
    # tail-exposed structures fatten under the observed co-jump; defined-risk overlays are bounded
    assert ps["long_btc_plus_short_put"]["honest_downside_widen_pct_central"] > 2.0
    assert ps["collar"]["defined_risk_bounded"] is True
    assert ps["call_spread"]["defined_risk_bounded"] is True


def test_figure_source_one_clean_series_per_structure() -> None:
    files = {p.stem for p in _FIGSRC.glob("*.json")}
    assert set(_STRUCTURES) <= files                           # one figure-source per structure
    for name in _STRUCTURES:
        d = json.loads((_FIGSRC / f"{name}.json").read_text())
        pc = d["payoff_curve"]
        assert len(pc["spot"]) == len(pc["pnl_usd_per_btc"]) >= 100    # a real payoff curve
        assert len(d["sigma_scenario_bars"]) == 5                      # -2..+2 sigma companion
        a = d["annotations"]
        assert a["floor_max_loss_usd_per_btc"] <= 0.0                  # a max loss (<=0)
        assert a["cap_usd_per_btc"] >= a["floor_max_loss_usd_per_btc"]
    # defined-risk structures have a TIGHT capped floor (their decision-relevant feature)
    collar = json.loads((_FIGSRC / "collar.json").read_text())
    cspread = json.loads((_FIGSRC / "call_spread.json").read_text())
    assert abs(collar["annotations"]["floor_max_loss_usd_per_btc"]) < 10_000
    assert abs(cspread["annotations"]["floor_max_loss_usd_per_btc"]) < 2_000
