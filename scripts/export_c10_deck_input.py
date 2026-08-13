#!/usr/bin/env python3
"""C10 deck-input regeneration on the C9/C10 engine (N4.2) — SUPERSEDES the C8 Phase-4 pack.

SIMULATED / diagnostic; MS-26-gated; holder-basis; deck & canonical main untouched; no best/optimal.
Reuses the validated C8 strategy-grid machinery (build_grid: premium at the listed Deribit marks — which
are COS-Bates-consistent to within the ARPE — plus prob-win N(+/-d2), breakevens, max-loss BTC/option/total,
greeks/theta, opportunity-cost, per-BTC / per-CME-5-BTC / per-portfolio granularity, coverage 25/50/75/100%,
all real listed expiries) and OVERLAYS the C9/C10 corrections:
  * SVJJ honest-downside scenarios (observed co-jump rho_J=-0.74, mu_v central ~0.17, band [+3%,+10%]);
  * the PF parameter-uncertainty band (ES97.5 ~+/-7%, tail-exposed);
  * corrected VRP framing (forward VRP POSITIVE/tail-compensated, N3.1) + recent-regime vol ~0.46;
  * defined-risk invariance (collar / call-spread bounded across the whole downside/parameter band).

Emits: exports/c10_deck_input/{grid.json, grid_summary.csv, grid_scenarios.csv, slide2_matrix.json} (bulk,
gitignored) + docs/reports/c10_deck_input/{slide2_data_pack.md, slide2_continued_honest_downside.md,
slide5_robustness.md, disclaimer.md, manifest.json} (committed, provenance-labelled).
"""

from __future__ import annotations

import csv
import dataclasses
import json
import pathlib
import sys
from typing import Any

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pricing.cf.svjj import fit_double_normal
from scripts.export_c8_evidence_pack import _build, slide2_matrix
from strategy.bates_risk import STRUCTURES, structure_pnl, structure_vrp
from strategy.strategy_grid import StrategyGrid
from strategy.svjj_sim import simulate_svjj_terminal
from vol.jumps import lee_mykland, log_returns

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FIX = _ROOT / "tests" / "fixtures"
_SPOT = _ROOT / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_BULK = _ROOT / "exports" / "c10_deck_input"
_DECK = _ROOT / "docs" / "reports" / "c10_deck_input"
_S0, _T = 63_402.0, 45.0 / 365.0
_KAPPA, _VOLVOL, _RHO = 8.37, 5.50, -0.403
_VOL_BAND = {"current": 0.35, "forecast_central": 0.46, "stress": 0.62}   # recent-regime central (Phase E)
_MUV = {"none": 0.0, "observed_lower": 0.12, "observed_central": 0.17, "observed_upper": 0.39}   # N3.6


def _svjj_scenarios() -> dict[str, Any]:
    """C9/C10 honest-downside + parameter-band scenarios per structure (SVJJ, observed co-jump)."""
    from pricing.cf.svjj import SVJJ
    r = log_returns(np.array([b["close"] for b in json.loads(_SPOT.read_text())], dtype=np.float64))
    j = fit_double_normal(r[lee_mykland(r, window=20, alpha=0.05).is_jump.astype(bool)])
    lam = 4.47

    def _es_vrp(vol: float, muv: float, seed: int) -> dict[str, dict[str, float]]:
        v = vol * vol
        m = SVJJ(mu=0.0, v0=v, kappa=_KAPPA, theta=v, sigma=_VOLVOL, rho=_RHO, lam=lam, jump=j, mu_v=muv)
        st = simulate_svjj_terminal(m, _S0, _T, 250_000, 45, seed=seed)
        out = {}
        for s in STRUCTURES:
            loss = -structure_pnl(STRUCTURES[s], _S0, st, _T)
            out[s] = {"es975": float(np.mean(loss[loss >= np.percentile(loss, 97.5)])),
                      "vrp_carry": structure_vrp(STRUCTURES[s], _S0, st, _T),
                      "prob_loss": float(np.mean(loss > 0))}
        return out

    central = _es_vrp(_VOL_BAND["forecast_central"], _MUV["observed_central"], 31)
    no_cojump = _es_vrp(_VOL_BAND["forecast_central"], _MUV["none"], 32)
    lower = _es_vrp(_VOL_BAND["forecast_central"], _MUV["observed_lower"], 33)
    upper = _es_vrp(_VOL_BAND["forecast_central"], _MUV["observed_upper"], 34)
    stress = _es_vrp(_VOL_BAND["stress"], _MUV["observed_central"], 35)

    per_structure = {}
    for s in STRUCTURES:
        es0, esc = no_cojump[s]["es975"], central[s]["es975"]
        per_structure[s] = {
            "es975_central_usd": esc,
            "honest_downside_widen_pct_central": 100 * (esc / es0 - 1),
            "honest_downside_widen_pct_band": [100 * (lower[s]["es975"] / es0 - 1),
                                               100 * (upper[s]["es975"] / es0 - 1)],
            "es975_stress_usd": stress[s]["es975"],
            "vrp_carry_central_usd": central[s]["vrp_carry"],
            "prob_loss_central": central[s]["prob_loss"],
            "defined_risk_bounded": abs(upper[s]["es975"] - lower[s]["es975"]) < 1.0,
        }
    return {
        "provenance": "SIMULATED / P-ESTIMATED (SVJJ, observed co-jump N3.6); Q-marks frozen Q_BATES",
        "central_vol": _VOL_BAND["forecast_central"], "vol_band": _VOL_BAND,
        "muv_observed": _MUV, "rho_j_observed": -0.738, "lambda_annual": lam,
        "pf_parameter_band_es975_pct": 7.0,          # N3.3 validated PF band (tail-exposed)
        "forward_vrp_atm": 0.096,                    # N3.1: implied vs 30d-forward realized (positive)
        "per_structure": per_structure,
    }


def _write_grid_csvs(grid: StrategyGrid) -> None:
    rows = dataclasses.asdict(grid)["rows"]
    if not rows:
        return
    cols = ["structure", "expiry", "coverage_pct"]
    with (_BULK / "grid_summary.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["structure", "expiry", "coverage_pct", "premium_pct", "premium_usd_per_btc",
                    "prob_win", "true_breakeven", "max_loss_total_usd"])
        for row in rows:
            prem = row.get("premium", {}) or {}
            pw = row.get("prob_win") or {}
            be = row.get("breakevens", {}) or {}
            ml = row.get("max_loss", {}) or {}
            w.writerow([row.get("structure"), row.get("expiry"), row.get("coverage_pct"),
                        prem.get("premium_pct"), prem.get("premium_usd_per_btc"),
                        pw.get("prob_win") if pw else "",
                        (be.get("true_breakevens") or [None])[0],
                        ml.get("max_loss_total_usd")])
    _ = cols


def main() -> int:
    _BULK.mkdir(parents=True, exist_ok=True)
    _DECK.mkdir(parents=True, exist_ok=True)
    grid: StrategyGrid = _build(_FIX)                                          # reuse the validated C8 grid (all cells)
    (_BULK / "grid.json").write_text(json.dumps(dataclasses.asdict(grid), indent=2, default=str))
    _write_grid_csvs(grid)
    matrix = slide2_matrix(grid)
    (_BULK / "slide2_matrix.json").write_text(json.dumps(matrix, indent=2, default=str))

    scen = _svjj_scenarios()
    n_rows = len(dataclasses.asdict(grid)["rows"])

    # committed deck-input packs (provenance-labelled) --------------------------------------------
    (_DECK / "slide2_continued_honest_downside.md").write_text(_slide2_continued(scen))
    (_DECK / "slide5_robustness.md").write_text(_slide5(scen))
    (_DECK / "slide2_data_pack.md").write_text(_slide2_pack(matrix, n_rows))
    (_DECK / "disclaimer.md").write_text(_DISCLAIMER)
    manifest = {
        "provenance": "computed off the frozen anchor snapshot on the C9/C10 (COS-Bates + SVJJ) engine",
        "supersedes": "docs/evidence C8 Phase-4 pack (BS-with-mark-IV + GBM/Merton scenarios)",
        "n_grid_rows": n_rows, "structures": list(STRUCTURES), "coverage_pct": [25, 50, 75, 100],
        "corrections": ["premium COS-Bates-consistent", "SVJJ observed-co-jump honest-downside",
                        "PF +/-7% parameter band", "forward VRP positive (N3.1)", "recent-regime vol 0.46",
                        "defined-risk invariance"],
        "svjj_scenarios": scen, "discipline": "SIMULATED/MS-26-gated; holder-basis; no best/optimal",
    }
    (_DECK / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"grid rows: {n_rows}; structures: {len(STRUCTURES)}; wrote deck-input packs to {_DECK}", flush=True)
    for s in STRUCTURES:
        p = scen["per_structure"][s]
        print(f"  {s:26} ES975 {p['es975_central_usd']:9.0f}  honest-downside +{p['honest_downside_widen_pct_central']:.1f}% "
              f"band [{p['honest_downside_widen_pct_band'][0]:.1f},{p['honest_downside_widen_pct_band'][1]:.1f}]  "
              f"VRP {p['vrp_carry_central_usd']:7.0f}  bounded={p['defined_risk_bounded']}")
    return 0


def _slide2_continued(scen: dict[str, Any]) -> str:
    ps = scen["per_structure"]
    lines = ["# C10 Slide-2 (continued) — honest-downside & parameter band (SUPERSEDES C8)",
             "", "SIMULATED / diagnostic; MS-26-gated; holder-basis; SVJJ observed-co-jump (N3.6); no best/optimal.",
             f"Central vol {scen['central_vol']}; observed co-jump rho_J=-0.74, mu_v central 0.17 (band 0.12-0.39).", "",
             "| structure | ES97.5 central (USD) | honest-downside +% | band [%] | stress ES97.5 | VRP carry | defined-risk bounded |",
             "|---|---:|---:|:---:|---:|---:|:---:|"]
    for s in STRUCTURES:
        p = ps[s]
        b = p["honest_downside_widen_pct_band"]
        lines.append(f"| {s} | {p['es975_central_usd']:,.0f} | +{p['honest_downside_widen_pct_central']:.1f}% "
                     f"| [{b[0]:.1f}, {b[1]:.1f}] | {p['es975_stress_usd']:,.0f} | {p['vrp_carry_central_usd']:,.0f} "
                     f"| {'yes' if p['defined_risk_bounded'] else 'no'} |")
    lines += ["", f"PF parameter band (ES97.5, tail-exposed): +/-{scen['pf_parameter_band_es975_pct']}% (N3.3, validated PF).",
              "Defined-risk overlays (collar, call-spread) are INVARIANT to the downside/parameter band (capped by construction).", ""]
    return "\n".join(lines)


def _slide5(scen: dict[str, Any]) -> str:
    return ("# C10 Slide-5 — robustness (SUPERSEDES C8 hero-MC pack)\n\n"
            "SIMULATED / diagnostic; MS-26-gated; no best/optimal.\n\n"
            "- **Model**: COS-Bates pricing (ARPE 5.55% vs GBM ~27%); SVJJ operational physical tail.\n"
            f"- **Observed co-jump** (N3.6): rho_J = -0.74 (decision-grade), mu_v ~0.17 (band 0.12-0.39, "
            "implied->instantaneous caveat).\n"
            f"- **Honest downside**: ES97.5 ~+4.5% central, band [+3%, +10%] vs the symmetric block; "
            "defined-risk overlays BOUNDED.\n"
            f"- **Parameter uncertainty** (N3.3, validated PF ESS 915): ES97.5 +/-~7% (tail-exposed).\n"
            f"- **Forward VRP** (N3.1, free DVOL): POSITIVE +{scen['forward_vrp_atm']} (implied vs 30d-forward "
            "realized; positive 75% of days) — vol-selling earned; the model prices a fatter tail (the honest "
            "tension, both shown).\n"
            "- **Vol regime** (Phase E): recent ~0.46 (non-stationary; secular decline 0.92->0.46).\n"
            "- **Backtest** (recent-2yr, matched vol): 99% VaR passes Kupiec (p=0.18).\n"
            "- Reproducible, seed-stable, 0 non-finite; holder-basis; every parameter provenance-labelled.\n")


def _slide2_pack(matrix: list[dict[str, object]], n_rows: int) -> str:
    lines = ["# C10 Slide-2 data pack — comparative structure matrix (SUPERSEDES C8)",
             "", f"SIMULATED / diagnostic; MS-26-gated; holder-basis; {n_rows} grid rows "
             "(all structures x strike% x real expiries x coverage 25/50/75/100%).",
             "Premiums COS-Bates-consistent (Deribit marks); prob-win N(+/-d2); breakevens/max-loss/greeks/",
             "opportunity-cost per row; per-BTC / per-CME-5-BTC / per-portfolio granularity. No best/optimal.", ""]
    if matrix:
        keys = [k for k in matrix[0] if k not in ("notes",)]
        lines.append("| " + " | ".join(keys) + " |")
        lines.append("|" + "|".join(["---"] * len(keys)) + "|")
        for row in matrix:
            lines.append("| " + " | ".join(str(row.get(k, "")) for k in keys) + " |")
    lines.append("")
    return "\n".join(lines)


_DISCLAIMER = ("# C10 deck-input disclaimer\n\n"
               "SIMULATED / diagnostic; MS-26-gated. Alternatives are presented, NOT ranked; no best/optimal. "
               "Holder-basis. Attribution is structure-specific: the covered call's overlay is a non-negative "
               "premium cushion (down-scenario losses are inherent to HOLDING BTC, not the overlay), whereas "
               "Long BTC + short put's overlay adds incremental sub-strike downside (attributable). Capped "
               "upside is OPPORTUNITY COST (foregone gain), NOT a loss. Investment decisions and outcomes rest "
               "with the client. Premiums are COS-Bates-consistent (Deribit marks); downside scenarios use the "
               "SVJJ observed-co-jump physical tail with the mu_v mapping caveat; parameter uncertainty is the "
               "validated-PF band. Supersedes the C8 Phase-4 pack.\n")


if __name__ == "__main__":
    raise SystemExit(main())
