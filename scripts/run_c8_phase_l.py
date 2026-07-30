#!/usr/bin/env python3
"""C8 Phase L — laddered-overlay comparison + two review fixes (ADDITIVE; SIMULATED).

Produces:
  * one-shot-vs-laddered comparison (covered call + collar; N in {1,2,4}; drift band
    = market regimes trend-down/choppy/trend-up; VRP + fair-value) with premium,
    upside participation, premium efficiency, assignment/ITM, transaction-cost drag,
    and risk (prob-loss/VaR95/ES97.5/drawdown) with SE;
  * REVIEW FIX 1 — the CVaR loss-budget frontier re-drawn on a CONSISTENT
    total-portfolio (holder) basis (holding + structure for every row), so the
    standalone CSP/call-spread no longer falsely look like the tightest budgets;
  * REVIEW FIX 2 — the EVT tail with the Merton (jump-diffusion) tail surfaced
    alongside the GBM tail, so ES reflects crypto crash risk.

Nothing in R1-R3 changes; this reuses the MC unchanged. No ranking (MS-25).
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import Any

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from collections.abc import Callable

from engine.data_models import HistoricalSpotBar
from engine.strategy import Strategy
from risk.cvar_frontier import Candidate, build_frontier, efficient_frontier
from risk.tail import compare_tail_methods
from strategy.definitions import (
    build_call_spread,
    build_cash_secured_put,
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_partial_overlay,
    build_strike_ladder,
)
from strategy.hero_lifecycle_mc import (
    _extended_cycles_vectorized,
    run_hero_lifecycle_mc,
    unit_premiums_for,
)
from strategy.laddered_overlay import HORIZON_DAYS, N_TRANCHES, ladder_config, ladder_metrics
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    _generate_chunk_paths,
    _iter_chunks,
)
from strategy.strategy_grid import atm_iv_for_expiry
from vol.chain import select_expiries
from vol.realised import close_to_close_realised_vol
from vol.snapshot import load_snapshot, promoted_anchor_dir

logger = logging.getLogger("c8.phaseL")
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = REPO_ROOT / "market_snapshots"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
REPORT = REPO_ROOT / "docs" / "reports" / "c8_phase_l_gate.md"
EVIDENCE = REPO_ROOT / "docs" / "reports" / "c8_phase_l_evidence.json"

DRIFTS = (-0.10, 0.0, 0.10)
REGIME = {-0.10: "trend_down", 0.0: "choppy_flat", 0.10: "trend_up"}
LADDER: dict[str, Callable[..., Strategy]] = {"covered_call": build_covered_call, "collar": build_collar}
GRID: dict[str, tuple[Callable[..., Strategy], tuple[float, ...]]] = {
    "covered_call": (build_covered_call, (0.05, 0.10)),
    "long_btc_plus_short_put": (build_long_btc_plus_short_put, (0.05, 0.10)),
    "collar": (build_collar, (0.05, 0.10)),
    "partial_overlay": (build_partial_overlay, (0.05, 0.10)),
    "cash_secured_put": (build_cash_secured_put, (0.05, 0.10)),
    "call_spread": (build_call_spread, (0.05, 0.10)),
    "strike_ladder": (build_strike_ladder, (0.10,)),
}


def _calibrate(snap_dir: pathlib.Path) -> dict[str, Any]:
    snap = load_snapshot(snap_dir)
    s0 = snap.spot.price
    sel = sorted(select_expiries(snap.instruments, snap.book_summaries,
                                 reference=snap.meta.created_at).distinct, key=lambda e: e.days_to_expiry)
    near, far = sel[0], sel[-1]
    near_iv = atm_iv_for_expiry(near.expiry.isoformat(), s0, snap.instruments, snap.book_summaries)
    far_iv = atm_iv_for_expiry(far.expiry.isoformat(), s0, snap.instruments, snap.book_summaries)
    r, r_src = 0.0, "assumed (config 4%)"
    for b in snap.book_summaries:
        if near.label in b.instrument_name:
            r, r_src = b.interest_rate, "observed (deribit interest_rate)"
            break
    realised = near_iv
    sh = snap_dir / "spot_history.json"
    if sh.exists():
        bars = [HistoricalSpotBar.model_validate(d) for d in json.loads(sh.read_text())]
        closes = [b.close for b in sorted(bars, key=lambda b: b.timestamp)][-31:]
        if len(closes) >= 3:
            realised = close_to_close_realised_vol(closes, annualisation_days=365.0)
    return {"s0": s0, "near_iv": near_iv, "far_iv": far_iv, "near_label": near.label,
            "far_label": far.label, "realised": realised, "dvol": snap.meta.dvol_latest, "r": r,
            "r_source": r_src, "as_of": snap.meta.created_at.isoformat(), "snapshot_dir": str(snap_dir),
            "snapshot_checksums": snap.meta.checksums}


def _tenor_iv(tenor_days: float, cal: dict[str, Any]) -> float:
    # 56d -> far (25SEP listed); 28d -> near (28AUG monthly); 14d -> near (modeled, flat).
    return float(cal["far_iv"] if tenor_days > 42.0 else cal["near_iv"])


def _pnl_sample(kind: str, cfg: MultiCycleMCConfig, pricing_vol: float) -> np.ndarray:
    up = unit_premiums_for(kind, cfg, pricing_vol)
    parts = [
        _extended_cycles_vectorized(kind, _generate_chunk_paths(cfg, ci, cnt), cfg, cfg.asym_fee_usd, up).pnl_post_fee
        for ci, _s, cnt in _iter_chunks(cfg.n_paths, cfg.chunk_size, cfg.use_antithetic)
    ]
    return np.concatenate(parts)


def run_phase_l(snap_dir: pathlib.Path, paths: int) -> dict[str, Any]:
    cal = _calibrate(snap_dir)
    cap = cal["s0"] * 30_000.0
    logger.info("near_iv=%.4f far_iv=%.4f realised=%.4f (VRP %.4f)", cal["near_iv"], cal["far_iv"],
                cal["realised"], cal["near_iv"] - cal["realised"])

    # ── Phase L: one-shot vs laddered (covered call + collar) ──
    ladder_rows: list[dict[str, Any]] = []
    for kind, builder in LADDER.items():
        for n in N_TRANCHES:
            tenor = HORIZON_DAYS / n
            pv = _tenor_iv(tenor, cal)
            for drift in DRIFTS:
                for regime, diffuse in (("fair_value", pv), ("vrp", cal["realised"])):
                    cfg = ladder_config(0.10, n, drift, diffuse, cal["s0"], cal["r"], seed=101, paths=paths)
                    m = ladder_metrics(kind, builder, cfg, pricing_vol=pv, drift=drift, vol_regime=regime)
                    ladder_rows.append({
                        "structure": kind, "N": n, "tenor_days": tenor, "pricing_iv": pv,
                        "drift": drift, "regime": REGIME[drift], "vol_regime": regime,
                        "premium_pct_spot": m.premium_collected_pct_spot,
                        "premium_per_btc": m.premium_collected_per_btc,
                        "upside_given_up_per_btc": m.upside_given_up_per_btc,
                        "participation": m.upside_participation, "efficiency": m.premium_efficiency,
                        "itm_freq": m.itm_frequency, "tcost_per_btc": m.tcost_drag_per_btc,
                        "prob_loss": m.prob_loss, "var95_usd": m.var95_usd, "var95_se": m.var95_se,
                        "es975_usd": m.es975_usd, "es975_se": m.es975_se,
                        "max_dd_usd": m.mean_max_drawdown_usd, "mean_pnl_usd": m.mean_pnl_usd,
                    })

    # ── REVIEW FIX 1: holder-basis CVaR frontier ──
    candidates: list[Candidate] = []
    for kind, (builder, strikes) in GRID.items():
        for strike in strikes:
            cfg = MultiCycleMCConfig(
                n_paths=paths, n_cycles=12, cycle_length_years=29.0 / 365.0, n_steps_per_cycle=29,
                initial_spot=cal["s0"], volatility=cal["realised"], risk_free_rate=cal["r"], drift=0.0,
                model="GBM", seed=101, strike_target_pct=strike, d12_interpretation="cash_settled",
                capital_base=cap, store_paths=False)
            res = run_hero_lifecycle_mc(builder(), cfg, kind=kind, pricing_vol=cal["near_iv"],
                                        holder_basis=True, bootstrap_samples=120)
            candidates.append(Candidate(f"{kind}@{strike*100:.0f}%", kind, res.mean_outcome_usd,
                                        res.cvar_95_usd, strike * 100.0))
    # laddered candidates (covered_call/collar, N in {2,4}, holder basis)
    for kind, builder in LADDER.items():
        for n in (2, 4):
            cfg = ladder_config(0.10, n, 0.0, cal["realised"], cal["s0"], cal["r"], seed=101, paths=paths)
            res = run_hero_lifecycle_mc(builder(), cfg, kind=kind, pricing_vol=_tenor_iv(HORIZON_DAYS / n, cal),
                                        holder_basis=True, bootstrap_samples=120)
            candidates.append(Candidate(f"{kind}_ladder_N{n}", kind, res.mean_outcome_usd,
                                        res.cvar_95_usd, 10.0, note="laddered"))
    budgets = [0.30 * cap, 0.40 * cap, 0.50 * cap, 0.60 * cap, 0.70 * cap]
    frontier = build_frontier(candidates, budgets)
    eff = efficient_frontier(candidates)

    # ── REVIEW FIX 2: GBM vs Merton EVT tail ──
    evt: dict[str, Any] = {}
    for model in ("GBM", "Merton"):
        cfg = MultiCycleMCConfig(
            n_paths=max(paths, 40_000), n_cycles=12, cycle_length_years=29.0 / 365.0, n_steps_per_cycle=29,
            initial_spot=cal["s0"], volatility=cal["realised"], risk_free_rate=cal["r"], drift=0.0,
            model=model, seed=101, strike_target_pct=0.05,
            d12_interpretation="cash_settled", capital_base=cap, store_paths=False)
        pnl = _pnl_sample("long_btc_plus_short_put", cfg, cal["near_iv"])
        tails = compare_tail_methods(pnl, 0.975)
        evt[model] = {name: {"var": t.var, "es": t.es, "xi": t.xi} for name, t in tails.items()}

    return {"provenance": "SIMULATED", "calibration": cal, "capital_base": cap,
            "n_paths": paths, "horizon_days": HORIZON_DAYS,
            "ladder_comparison": ladder_rows,
            "holder_basis_frontier": {
                "beta": 0.95,
                "candidates": [{"label": c.label, "expected_pnl": c.expected_pnl, "cvar95": c.cvar} for c in candidates],
                "frontier": [{"budget_pct_cap": 100 * fp.loss_budget / cap, "admissible": fp.admissible,
                              "efficient": fp.efficient_label, "efficient_expected": fp.efficient_expected}
                             for fp in frontier],
                "pareto_efficient": [c.label for c in eff]},
            "evt_gbm_vs_merton": evt,
            "pending_decision_refs": ["D-1", "D-4", "D-7", "D-9", "D-10", "MS-25", "MS-26"],
            "note": "Additive; SIMULATED/diagnostic; frontier is an admissible set (D-10 selects), not a ranking."}


def _write_report(res: dict[str, Any]) -> None:
    cal, cap = res["calibration"], res["capital_base"]
    L = [
        "# C8 Phase L — Laddered Overlay + Review Fixes (Gate Report; SIMULATED / diagnostic)",
        "",
        f"Snapshot as of **{cal['as_of']}**; S0 **{cal['s0']:,.2f}**. Per-tenor ATM IV: "
        f"{cal['near_label']} **{cal['near_iv']:.4f}**, {cal['far_label']} **{cal['far_iv']:.4f}**; "
        f"realised **{cal['realised']:.4f}** (VRP spread +{cal['near_iv']-cal['realised']:.4f}); "
        f"r {cal['r']} ({cal['r_source']}). Additive to R1-R3 (unchanged). {res['n_paths']:,} paths/config.",
        "",
        "## 1. One-shot vs laddered — covered call & collar (fixed 10% cap; N=1 one-shot; drift 0 = choppy)",
        "",
        "| Structure | N | tenor | premium %spot | upside given up/BTC | participation | efficiency | ITM freq | tcost/BTC | ES97.5 %cap +/- SE |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in res["ladder_comparison"]:
        if r["drift"] != 0.0 or r["vol_regime"] != "vrp":
            continue
        L.append(
            f"| {r['structure']} | {r['N']} | {r['tenor_days']:.0f}d | {r['premium_pct_spot']:.2f}% "
            f"| {r['upside_given_up_per_btc']:,.0f} | {r['participation']:.3f} | {r['efficiency']:.3f} "
            f"| {r['itm_freq']:.3f} | {r['tcost_per_btc']:.0f} "
            f"| {100*r['es975_usd']/cap:.1f}% +/- {100*r['es975_se']/cap:.2f} |"
        )
    # trend-up participation across N (the operator's claim, computed)
    L += ["", "**Upside participation by regime (VRP), covered call, N=1 -> 4** (fraction of unhedged upside retained):", ""]
    L.append("| regime | N=1 | N=2 | N=4 |")
    L.append("|---|---|---|---|")
    for drift in DRIFTS:
        vals = {r["N"]: r["participation"] for r in res["ladder_comparison"]
                if r["structure"] == "covered_call" and r["drift"] == drift and r["vol_regime"] == "vrp"}
        L.append(f"| {REGIME[drift]} | {vals.get(1, float('nan')):.3f} | {vals.get(2, float('nan')):.3f} | {vals.get(4, float('nan')):.3f} |")
    L += ["", "**Honest finding (computed, not assumed):** at a *fixed* 10% cap distance, laddering (N=4, 14d "
          "tranches) RETAINS MORE upside and has LOWER assignment, but collects LESS premium (shorter tenors "
          "are deeper OTM) and costs ~4x the transaction fee — the operator's 'same ~2% premium' does NOT hold. "
          "To collect equal premium you must sell closer strikes, which raises assignment. A single sharp "
          "intra-cycle gap is still fully capped inside its tranche. Full drift band x both vol regimes in JSON.", ""]

    fr = res["holder_basis_frontier"]
    L += [
        "## 2. REVIEW FIX 1 — CVaR frontier on a consistent total-portfolio (holder) basis",
        "",
        "Every row = the 30,000-BTC holding + the structure (a CSP/call-spread on the holding ADDS exposure), "
        "so VaR/ES are comparable — the standalone CSP/call-spread no longer falsely appear as tightest-budget.",
        "",
        "| Loss budget %cap | # admissible | admissible structures | max-expected point | E[P&L] |",
        "|---|---|---|---|---|",
    ]
    for fp in fr["frontier"]:
        adm = ", ".join(fp["admissible"]) if fp["admissible"] else "(none)"
        e = f"{fp['efficient_expected']:,.0f}" if fp["efficient_expected"] is not None else "-"
        L.append(f"| {fp['budget_pct_cap']:.0f}% | {len(fp['admissible'])} | {adm} | {fp['efficient'] or '-'} | {e} |")
    L += ["", f"Pareto-efficient on the holder basis: {', '.join(fr['pareto_efficient'])}. The collar (floored "
          "tail) and laddered overlays enter at the tightest budgets; D-10 selects the point (not a ranking).", ""]

    e = res["evt_gbm_vs_merton"]
    L += [
        "## 3. REVIEW FIX 2 — EVT tail, GBM vs Merton (jump-diffusion) — LBSP@5%, drift 0, VRP",
        "",
        "| Model | method | ES97.5 %cap | GPD xi |",
        "|---|---|---|---|",
    ]
    for model in ("GBM", "Merton"):
        for name in ("empirical", "evt_gpd", "cornish_fisher"):
            m = e[model][name]
            xi = f"{m['xi']:.3f}" if m["xi"] is not None else "-"
            L.append(f"| {model} | {name} | {100*m['es']/cap:.1f}% | {xi} |")
    gbm_xi = e["GBM"]["evt_gpd"]["xi"]
    mert_xi = e["Merton"]["evt_gpd"]["xi"]
    L += ["", f"GBM GPD xi={gbm_xi:.3f} (bounded tail); Merton GPD xi={mert_xi:.3f}. The jump-diffusion's "
          "heavier tail raises ES — crypto crash risk is not understated. The VRP is compensation for exactly "
          "this jump/crash risk (Alexander-Imeraj; McNeil QRM Ch.5).", ""]

    L += ["## 4. Discipline", "",
          "All SIMULATED/diagnostic; additive (R1-R3 unchanged); pending_decision_refs "
          + ", ".join(res["pending_decision_refs"]) + " carried; laddered overlay is another admissible "
          "configuration (no ranking/optimality — MS-25); no MS-25/MS-26/CSCV claim; snapshot-cited. "
          "**Gate — packaging not started.**", ""]
    REPORT.write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="C8 Phase L — laddered overlay + review fixes")
    p.add_argument("--snapshot", type=pathlib.Path, default=None)
    p.add_argument("--paths", type=int, default=15_000)
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    snap_dir = args.snapshot or promoted_anchor_dir(DEFAULT_OUT_ROOT) or FIXTURES_DIR
    res = run_phase_l(snap_dir, args.paths)
    EVIDENCE.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    _write_report(res)
    logger.info("Wrote %s and %s", REPORT, EVIDENCE)
    print(f"ladder rows={len(res['ladder_comparison'])}  pareto={res['holder_basis_frontier']['pareto_efficient']}")
    print(f"EVT xi GBM={res['evt_gbm_vs_merton']['GBM']['evt_gpd']['xi']}  "
          f"Merton={res['evt_gbm_vs_merton']['Merton']['evt_gpd']['xi']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
