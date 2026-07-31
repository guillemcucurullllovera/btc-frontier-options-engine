#!/usr/bin/env python3
"""Per-structure figure-source data (C10 · N4.5) — ONE clean figure per structure (not piled).

SIMULATED / diagnostic; MS-26-gated; holder-basis; deck & canonical main untouched; no best/optimal. Emits
the figure-READY series for a STANDALONE figure per structure (resolving the CEO's "all-piled-in-1 ->
separate" complaint): the expiry payoff curve (P&L vs spot, with strike/breakeven/cap/floor annotations),
the sigma-scenario bars, and the max-loss / opportunity-cost decomposition. Companion spec:
docs/reports/c10_figure_spec.md. Builds NO slides/figures — that is N5. Writes one JSON per structure under
docs/reports/c10_figure_source/.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from typing import Any

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from strategy.bates_risk import STRUCTURES, StructureDef, structure_pnl

_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c10_figure_source"
_S0, _T, _VOL = 63_402.0, 45.0 / 365.0, 0.46          # recent-regime central vol (Phase E)
_SIGMA_H = _VOL * math.sqrt(_T)                        # horizon sigma ~ 0.161


def _payoff_series(sdef: StructureDef) -> dict[str, Any]:
    st = np.linspace(0.45 * _S0, 1.75 * _S0, 261)
    pnl = structure_pnl(sdef, _S0, st, _T)
    unhedged = st - _S0                                # holder-basis reference (hold BTC)
    # breakevens: sign changes of pnl
    bes = [float(0.5 * (st[i] + st[i + 1])) for i in range(len(st) - 1) if pnl[i] * pnl[i + 1] < 0]
    cap = float(np.max(pnl))
    floor = float(np.min(pnl))
    # strikes (annotations)
    strikes = [{"strike": _S0 * (1 + leg.strike_pct / 100.0), "kind": leg.kind, "side": leg.side}
               for leg in sdef.legs]
    # sigma-scenario bars
    bars = []
    for k in (-2, -1, 0, 1, 2):
        s = _S0 * (1.0 + k * _SIGMA_H)
        bars.append({"sigma": k, "spot": float(s),
                     "pnl_usd_per_btc": float(structure_pnl(sdef, _S0, np.array([s]), _T)[0])})
    # opportunity cost: where the structure caps upside vs holding (pnl < unhedged above spot)
    opp = unhedged - pnl
    opp_region = st[(opp > 1.0) & (st > _S0)]
    max_opp_cost = float(np.max(opp)) if opp.size else 0.0
    return {
        "structure": sdef.name, "has_holding": sdef.has_holding,
        "spot0": _S0, "horizon_days": round(_T * 365), "vol_central": _VOL, "sigma_h": _SIGMA_H,
        "payoff_curve": {"spot": [float(x) for x in st], "pnl_usd_per_btc": [float(x) for x in pnl],
                         "unhedged_reference": [float(x) for x in unhedged]},
        "annotations": {"strikes": strikes, "breakevens_usd": bes, "cap_usd_per_btc": cap,
                        "floor_max_loss_usd_per_btc": floor,
                        "opportunity_cost_starts_usd": float(opp_region.min()) if opp_region.size else None,
                        "max_opportunity_cost_usd_per_btc": max_opp_cost},
        "sigma_scenario_bars": bars,
        "max_loss_opportunity_decomp": {
            "max_loss_usd_per_btc": floor,
            "max_opportunity_cost_usd_per_btc": max_opp_cost,
            "note": ("Capped upside is OPPORTUNITY COST (foregone gain vs holding), NOT a loss. Sub-floor "
                     "loss is the true max loss (defined-risk structures cap it)."),
        },
        "provenance": "SIMULATED / holder-basis; premiums Q_BATES-marked (COS-Bates-consistent).",
    }


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    for name, sdef in STRUCTURES.items():
        (_OUT / f"{name}.json").write_text(json.dumps(_payoff_series(sdef), indent=2))
    print(f"wrote {len(STRUCTURES)} per-structure figure-source files to {_OUT}")
    for name, sdef in STRUCTURES.items():
        d = _payoff_series(sdef)
        a = d["annotations"]
        print(f"  {name:26} floor(maxloss) {a['floor_max_loss_usd_per_btc']:9.0f}  cap {a['cap_usd_per_btc']:9.0f}  "
              f"breakevens {[round(b) for b in a['breakevens_usd']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
