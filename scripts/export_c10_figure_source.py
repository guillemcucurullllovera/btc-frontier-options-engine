#!/usr/bin/env python3
"""Per-structure figure-source data (C10 · N4.5, N6.5e-aligned) — ONE clean figure per structure.

SIMULATED / diagnostic; MS-26-gated; holder-basis; deck & canonical main untouched; no best/optimal. Emits
the figure-READY series for a STANDALONE figure per structure (resolving the CEO's "all-piled-in-1 ->
separate" complaint): the expiry payoff curve (P&L vs spot), the sigma-scenario bars, and the
max-loss / opportunity-cost decomposition. Companion spec: docs/reports/c10_figure_spec.md.

N6.5e — figure <-> grid consistency. The figures and the deck's highlighted table cells now share ONE
reference configuration: the committed N4.2 deck-input grid cell at spot S0=63,402, the near expiry
(28AUG26, ~30.7 DTE), 100% coverage, and the featured strike per structure. The headline max-loss,
premium and breakeven are sourced FROM that grid cell (one max-loss definition across figures + tables).
The payoff curve is reconstructed from the structure legs offset by the grid net premium and drawn down
toward spot -> 0, so the curve honestly reaches the true max-loss: for the defined-risk structures
(collar, call spread) it FLATTENS at a bounded floor; for the others (unhedged / covered call / LBSP /
CSP / ladder) it slides to a max-loss-to-zero (e.g. covered call ~= -$62,228/BTC). The word "floor" is
therefore reserved for the defined-risk structures only. Builds NO slides/figures — that is N5. Writes one
JSON per structure under docs/reports/c10_figure_source/.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from typing import Any

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from strategy.bates_risk import STRUCTURES, StructureDef

_R = pathlib.Path(__file__).resolve().parents[1]
_OUT = _R / "docs" / "reports" / "c10_figure_source"
_GRID = _R / "exports" / "c10_deck_input" / "grid.json"
_S0, _VOL = 63_402.0, 0.46                             # recent-regime central vol (Phase E) for sigma bars
_DEFINED = ("collar", "call_spread")                   # the ONLY structures with a bounded floor

# figure name -> (grid structure_id, featured strike_pct) : the ONE shared reference cell (100% coverage,
# near expiry). These are exactly the cells the deck Slide-2 grid highlights.
_CANON: dict[str, tuple[str, float | None]] = {
    "unhedged": ("unhedged_baseline", None),
    "covered_call": ("covered_call", 5.0),
    "long_btc_plus_short_put": ("long_btc_plus_short_put", -5.0),
    "cash_secured_put": ("cash_secured_put", -5.0),
    "collar": ("collar", 5.0),
    "call_spread": ("call_spread", 5.0),
    "strike_ladder": ("strike_ladder", 5.0),
}


def _canon_cell(rows: list[dict[str, Any]], sid: str, strike: float | None) -> dict[str, Any]:
    """The near-expiry, 100%-coverage, featured-strike grid row for this structure (the shared cell)."""
    cand = [r for r in rows if r["structure_id"] == sid and r["coverage_pct"] == 100.0]
    if strike is not None:
        cand = [r for r in cand if r.get("strike_pct") == strike] or cand
    return min(cand, key=lambda x: x["dte_days"])


def _grid_scalar(x: Any) -> float:
    return float(x.get("per_btc", 0.0) if isinstance(x, dict) else x)


def _effective_legs(name: str, sdef: StructureDef, cell: dict[str, Any]) -> list[tuple[str, str, float, float]]:
    """(kind, side, strike_pct, weight) legs for the FIGURE geometry, reconciled to the grid cell.

    call_spread is a pure credit spread whose max-loss is the strike WIDTH minus the premium; the grid
    cell's width differs from the toolkit's illustrative +3/+5, so derive the long strike from the grid
    economics (short at the featured strike; width = premium - max_loss) to keep floor == grid.
    """
    if name == "call_spread":
        short_pct = float(cell.get("strike_pct") or 5.0)
        prem = float(cell["premium"].get("net_per_btc") or 0.0)
        width_pct = 100.0 * (prem - _grid_scalar(cell["max_loss"]["total"])) / _S0
        return [("call", "SHORT", short_pct, 1.0), ("call", "LONG", short_pct + width_pct, 1.0)]
    return [(leg.kind, leg.side, leg.strike_pct, leg.weight) for leg in sdef.legs]


def _payoff_ex_premium(legs: list[tuple[str, str, float, float]], s_t: np.ndarray, has_holding: bool) -> np.ndarray:
    """Structure P&L excluding option premium (holding + option intrinsic payoffs) — holder-basis."""
    pnl = (s_t - _S0) if has_holding else np.zeros_like(s_t)
    for kind, side, strike_pct, weight in legs:
        k = _S0 * (1.0 + strike_pct / 100.0)
        payoff = np.maximum(s_t - k, 0.0) if kind == "call" else np.maximum(k - s_t, 0.0)
        sign = 1.0 if side == "SHORT" else -1.0
        pnl = pnl - sign * weight * payoff
    return pnl


def _payoff_series(name: str, sdef: StructureDef, cell: dict[str, Any]) -> dict[str, Any]:
    dte = float(cell["dte_days"])
    t_years = dte / 365.0
    sigma_h = _VOL * math.sqrt(t_years)
    net_prem = float(cell["premium"].get("net_per_btc") or 0.0)          # grid net premium ($/BTC)
    max_loss = _grid_scalar(cell["max_loss"]["total"])                   # grid max-loss (the one definition)
    is_defined = name in _DEFINED
    legs = _effective_legs(name, sdef, cell)
    # curve runs from spot = 0 so the true max-loss is ON the curve (not a plotted-range minimum): the
    # long-BTC structures slide to a max-loss-to-zero; the defined-risk ones flatten at a bounded floor.
    st = np.linspace(0.0, 1.75 * _S0, 261)
    pnl = _payoff_ex_premium(legs, st, sdef.has_holding) + net_prem      # grid-consistent offset
    unhedged = st - _S0                                                  # holder-basis reference (hold BTC)
    cap = float(np.max(pnl))
    # breakevens from the grid cell (authoritative), else the curve's sign changes
    grid_be = (cell.get("breakeven", {}) or {}).get("true_breakevens") or []
    bes = [float(b) for b in grid_be] or \
          [float(0.5 * (st[i] + st[i + 1])) for i in range(len(st) - 1) if pnl[i] * pnl[i + 1] < 0]
    # strike guides come from the EFFECTIVE legs (the ones the payoff curve uses) so the guide lines
    # align with the curve kinks (matters for call_spread, whose long strike is grid-derived).
    strikes = [{"strike": _S0 * (1 + spct / 100.0), "kind": kind, "side": side}
               for kind, side, spct, _w in legs]
    bars = []
    for k in (-2, -1, 0, 1, 2):
        s = _S0 * (1.0 + k * sigma_h)
        bars.append({"sigma": k, "spot": float(s),
                     "pnl_usd_per_btc": float(_payoff_ex_premium(legs, np.array([s]), sdef.has_holding)[0] + net_prem)})
    # opportunity cost = FOREGONE UPSIDE GAIN only (structure below holding, ABOVE spot); the below-spot
    # gap is amplified downside, not opportunity cost, so it is excluded here.
    opp = unhedged - pnl
    up = st > _S0
    opp_up = opp[up]
    opp_region = st[up][opp_up > 1.0]
    max_opp_cost = float(np.max(opp_up)) if opp_up.size and float(np.max(opp_up)) > 0 else 0.0
    return {
        "structure": sdef.name, "has_holding": sdef.has_holding, "is_defined_risk": is_defined,
        "spot0": _S0, "horizon_days": round(dte), "vol_central": _VOL, "sigma_h": sigma_h,
        "ref_config": {"grid_structure_id": cell["structure_id"], "expiry_label": cell["expiry_label"],
                       "dte_days": dte, "strike_pct": cell.get("strike_pct"),
                       "coverage_pct": cell["coverage_pct"], "atm_iv": cell.get("atm_iv"),
                       "premium_pct_of_spot": cell["premium"].get("pct_of_spot")},
        "payoff_curve": {"spot": [float(x) for x in st], "pnl_usd_per_btc": [float(x) for x in pnl],
                         "unhedged_reference": [float(x) for x in unhedged]},
        "annotations": {"strikes": strikes, "breakevens_usd": bes, "cap_usd_per_btc": cap,
                        "max_loss_usd_per_btc": max_loss, "premium_usd_per_btc": net_prem,
                        "opportunity_cost_starts_usd": float(opp_region.min()) if opp_region.size else None,
                        "max_opportunity_cost_usd_per_btc": max_opp_cost},
        "sigma_scenario_bars": bars,
        "max_loss_opportunity_decomp": {
            "max_loss_usd_per_btc": max_loss,
            "max_opportunity_cost_usd_per_btc": max_opp_cost,
            "max_loss_kind": "floor (bounded, defined-risk)" if is_defined else "max loss to spot -> 0",
            "note": ("Capped upside is OPPORTUNITY COST (foregone gain vs holding), NOT a loss. The "
                     "defined-risk structures (collar, call spread) cap the downside at a bounded FLOOR; "
                     "the others slide to a max-loss-to-zero. Max-loss/premium/breakeven are the shared "
                     "deck-input grid cell (spot 63,402, near expiry, 100% coverage, featured strike)."),
        },
        "provenance": "SIMULATED / holder-basis; max-loss/premium/breakeven sourced from the N4.2 grid cell.",
    }


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    rows = list(json.loads(_GRID.read_text())["rows"])
    for name, sdef in STRUCTURES.items():
        sid, strike = _CANON[name]
        cell = _canon_cell(rows, sid, strike)
        (_OUT / f"{name}.json").write_text(json.dumps(_payoff_series(name, sdef, cell), indent=2))
    print(f"wrote {len(STRUCTURES)} per-structure figure-source files to {_OUT}")
    for name, sdef in STRUCTURES.items():
        sid, strike = _CANON[name]
        a = _payoff_series(name, sdef, _canon_cell(rows, sid, strike))["annotations"]
        kind = "floor" if name in _DEFINED else "maxloss->0"
        print(f"  {name:26} {kind:11} {a['max_loss_usd_per_btc']:10,.0f}  cap {a['cap_usd_per_btc']:9,.0f}  "
              f"prem {a['premium_usd_per_btc']:7,.0f}  breakevens {[round(b) for b in a['breakevens_usd']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
