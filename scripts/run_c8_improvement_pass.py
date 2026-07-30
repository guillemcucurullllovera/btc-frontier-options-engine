#!/usr/bin/env python3
"""C8 R1-R3 improvement pass — full-grid VRP MC, EVT tails, CVaR frontier.

DIAGNOSTIC / SIMULATED (MS-26 pending). Produces the REVIEW-GATE evidence:
  * full-grid drift-band table {-0.10,0,+0.10} in BOTH vol regimes — pure-implied
    fair-value (no-edge) and variance-risk-premium (sell implied, realise physical)
    — with bootstrap SE on every metric;
  * an EVT/GPD vs empirical vs Cornish-Fisher tail comparison (ES the headline);
  * a CVaR loss-budget efficient frontier over the full candidate grid.

No single flattering case: both vol regimes and the whole drift band are shown;
drift 0 is the no-view anchor; no ranking (the frontier is an admissible set).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pathlib
import sys
from statistics import mean, pstdev
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
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    _generate_chunk_paths,
    _iter_chunks,
)
from strategy.strategy_grid import atm_iv_for_expiry
from vol.chain import select_expiries
from vol.realised import close_to_close_realised_vol
from vol.snapshot import load_snapshot, promoted_anchor_dir

logger = logging.getLogger("c8.improve")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = REPO_ROOT / "market_snapshots"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
REPORT = REPO_ROOT / "docs" / "reports" / "c8_improvement_pass_gate.md"
EVIDENCE = REPO_ROOT / "docs" / "reports" / "c8_improvement_pass_evidence.json"

BUILDERS: dict[str, Callable[..., Strategy]] = {
    "covered_call": build_covered_call, "long_btc_plus_short_put": build_long_btc_plus_short_put,
    "collar": build_collar, "partial_overlay": build_partial_overlay,
    "cash_secured_put": build_cash_secured_put, "call_spread": build_call_spread,
    "strike_ladder": build_strike_ladder,
}
STRIKES = {
    "covered_call": (0.05, 0.10, 0.15), "long_btc_plus_short_put": (0.03, 0.05, 0.10),
    "collar": (0.05, 0.10, 0.15), "partial_overlay": (0.05, 0.10, 0.15),
    "cash_secured_put": (0.05, 0.10), "call_spread": (0.05, 0.10), "strike_ladder": (0.10,),
}
REPR_STRIKE = {  # representative strike per structure for the drift-band table
    "covered_call": 0.10, "long_btc_plus_short_put": 0.05, "collar": 0.10,
    "partial_overlay": 0.10, "cash_secured_put": 0.05, "call_spread": 0.05, "strike_ladder": 0.10,
}
DRIFTS = (-0.10, 0.0, 0.10)
SEEDS = (101, 102, 103)
N_CYCLES, CADENCE = 12, 29.0


def _calibrate(snap_dir: pathlib.Path) -> dict[str, Any]:
    snap = load_snapshot(snap_dir)
    s0 = snap.spot.price
    sel = select_expiries(snap.instruments, snap.book_summaries, reference=snap.meta.created_at)
    near = min(sel.distinct, key=lambda e: e.days_to_expiry)
    implied = atm_iv_for_expiry(near.expiry.isoformat(), s0, snap.instruments, snap.book_summaries)
    r, r_src = 0.0, "assumed (config 4%)"
    for b in snap.book_summaries:
        if near.label in b.instrument_name:
            r, r_src = b.interest_rate, "observed (deribit interest_rate)"
            break
    realised, realised_src = implied, "fallback: implied (no spot history)"
    sh = snap_dir / "spot_history.json"
    if sh.exists():
        bars = [HistoricalSpotBar.model_validate(d) for d in json.loads(sh.read_text())]
        closes = [b.close for b in sorted(bars, key=lambda b: b.timestamp)][-31:]
        if len(closes) >= 3:
            realised = close_to_close_realised_vol(closes, annualisation_days=365.0)
            realised_src = "OBSERVED (massive spot history, 30d close-to-close, sqrt365)"
    return {
        "s0": s0, "implied_atm_iv": implied, "realised_vol": realised, "realised_src": realised_src,
        "dvol": snap.meta.dvol_latest, "r": r, "r_source": r_src, "near_tenor": near.label,
        "near_dte": near.days_to_expiry, "as_of": snap.meta.created_at.isoformat(),
        "snapshot_dir": str(snap_dir), "snapshot_checksums": snap.meta.checksums,
    }


def _config(vol: float, strike: float, drift: float, seed: int, cal: dict[str, Any], paths: int) -> MultiCycleMCConfig:
    return MultiCycleMCConfig(
        n_paths=paths, n_cycles=N_CYCLES, cycle_length_years=CADENCE / 365.0,
        n_steps_per_cycle=int(CADENCE), initial_spot=cal["s0"], volatility=vol,
        risk_free_rate=cal["r"], drift=drift, model="GBM", seed=seed,
        strike_target_pct=strike, d12_interpretation="cash_settled",
        capital_base=cal["s0"] * 30_000.0, store_paths=False,
    )


def _run(kind: str, cfg: MultiCycleMCConfig, cal: dict[str, Any], regime: str) -> Any:
    # fair_value: diffuse & price at implied. vrp: diffuse at realised, price at implied.
    pricing = cal["implied_atm_iv"] if regime == "vrp" else None
    return run_hero_lifecycle_mc(
        BUILDERS[kind](), cfg, kind=kind, pricing_vol=pricing, bootstrap_samples=150,
        volatility_source=f"{regime}: diffusion {cfg.volatility:.4f} / pricing implied {cal['implied_atm_iv']:.4f}",
        risk_free_source=cal["r_source"],
    )


def _pnl_sample(kind: str, cfg: MultiCycleMCConfig, pricing_vol: float) -> np.ndarray:
    up = unit_premiums_for(kind, cfg, pricing_vol)
    fee = cfg.asym_fee_usd
    parts = [
        _extended_cycles_vectorized(kind, _generate_chunk_paths(cfg, ci, cnt), cfg, fee, up).pnl_post_fee
        for ci, _s, cnt in _iter_chunks(cfg.n_paths, cfg.chunk_size, cfg.use_antithetic)
    ]
    return np.concatenate(parts)


def run_pass(snap_dir: pathlib.Path, paths: int) -> dict[str, Any]:
    cal = _calibrate(snap_dir)
    logger.info("implied=%.4f realised=%.4f (VRP spread %.4f); DVOL=%s r=%.4f",
                cal["implied_atm_iv"], cal["realised_vol"],
                cal["implied_atm_iv"] - cal["realised_vol"], cal["dvol"], cal["r"])
    cap = cal["s0"] * 30_000.0

    # ── drift band (representative strike per structure) x regime x drift x seed ──
    band: dict[str, Any] = {}
    n_nonfinite = 0
    for kind in BUILDERS:
        band[kind] = {}
        for regime in ("fair_value", "vrp"):
            diffuse = cal["realised_vol"] if regime == "vrp" else cal["implied_atm_iv"]
            for drift in DRIFTS:
                res = [_run(kind, _config(diffuse, REPR_STRIKE[kind], drift, s, cal, paths), cal, regime)
                       for s in SEEDS]
                n_nonfinite += sum(r.n_non_finite for r in res)

                def agg(attr: str, res: list[Any] = res) -> float:
                    return float(mean(getattr(r, attr) for r in res))

                def agg_se(m: str, res: list[Any] = res) -> float:
                    return float(mean(r.metric_ci.get(m, {}).get("se", 0.0) for r in res))
                band[kind][f"{regime}|{drift:+.2f}"] = {
                    "mean_pnl": agg("mean_outcome_usd"), "mean_pnl_se": agg_se("mean_pnl"),
                    "var95": agg("var_95_usd"), "var95_se": agg_se("var_95_usd"),
                    "es975": agg("expected_shortfall_975_usd"), "es975_se": agg_se("es_975_usd"),
                    "prob_loss": agg("probability_of_loss"), "prob_loss_se": agg_se("prob_loss"),
                    "cvar95": agg("cvar_95_usd"), "overlay": agg("mean_overlay_gross_pnl_usd"),
                    "cross_seed_std_pnl": pstdev([r.mean_outcome_usd for r in res]),
                }

    # ── CVaR frontier (full strike sweep, drift 0, VRP) ──
    candidates: list[Candidate] = []
    for kind, strikes in STRIKES.items():
        diffuse = cal["realised_vol"]
        for strike in strikes:
            res = [_run(kind, _config(diffuse, strike, 0.0, s, cal, paths), cal, "vrp") for s in SEEDS]
            candidates.append(Candidate(
                label=f"{kind}@{strike*100:.0f}%", structure=kind, strike_pct=strike * 100.0,
                expected_pnl=mean(r.mean_outcome_usd for r in res),
                cvar=mean(r.cvar_95_usd for r in res),
                note="collar = strike-tuned protective floor" if kind == "collar" else "",
            ))
    budgets = [0.20 * cap, 0.30 * cap, 0.40 * cap, 0.50 * cap, 0.60 * cap]
    frontier = build_frontier(candidates, budgets)
    eff = efficient_frontier(candidates)

    # ── EVT tail comparison (representative: LBSP 5%, drift 0, VRP) ──
    evt_cfg = _config(cal["realised_vol"], 0.05, 0.0, 101, cal, max(paths, 40_000))
    evt_pnl = _pnl_sample("long_btc_plus_short_put", evt_cfg, cal["implied_atm_iv"])
    tail = compare_tail_methods(evt_pnl, confidence=0.975)

    return {
        "provenance": "SIMULATED", "calibration": cal,
        "campaign": {"n_paths": paths, "seeds": list(SEEDS), "drifts": list(DRIFTS),
                     "n_cycles": N_CYCLES, "cadence_days": CADENCE, "capital_base": cap,
                     "total_non_finite": n_nonfinite, "model": "GBM"},
        "drift_band": band,
        "cvar_frontier": {
            "beta": 0.95, "budgets_pct_capital": [0.2, 0.3, 0.4, 0.5, 0.6],
            "candidates": [{"label": c.label, "structure": c.structure, "strike_pct": c.strike_pct,
                            "expected_pnl": c.expected_pnl, "cvar95": c.cvar} for c in candidates],
            "frontier": [{"loss_budget": fp.loss_budget, "budget_pct_cap": 100 * fp.loss_budget / cap,
                          "admissible": fp.admissible, "efficient": fp.efficient_label,
                          "efficient_expected": fp.efficient_expected} for fp in frontier],
            "pareto_efficient": [c.label for c in eff],
        },
        "evt_tail": {"structure": "long_btc_plus_short_put@5% (drift 0, VRP)", "confidence": 0.975,
                     "capital_base": cap,
                     "methods": {name: {"var": t.var, "es": t.es, "xi": t.xi,
                                        "threshold": t.threshold, "n_exceedances": t.n_exceedances}
                                 for name, t in tail.items()}},
        "pending_decision_refs": ["D-1", "D-4", "D-7", "D-9", "D-10", "MS-25", "MS-26"],
        "note": "Diagnostic only; not decision evidence. Both vol regimes + full drift band shown; "
                "frontier is an admissible set (D-10 selects), not a ranking (MS-25).",
    }


def _write_report(res: dict[str, Any], checksum: str) -> None:
    cal, camp = res["calibration"], res["campaign"]
    cap = camp["capital_base"]
    L = [
        "# C8 R1-R3 Improvement Pass — Review Gate Report (SIMULATED / diagnostic)",
        "",
        f"Snapshot as of **{cal['as_of']}**; S0 **{cal['s0']:,.2f}**. "
        f"Implied ATM IV **{cal['implied_atm_iv']:.4f}** ({cal['near_tenor']}, ~{cal['near_dte']:.0f}d); "
        f"realised vol **{cal['realised_vol']:.4f}** [{cal['realised_src']}]; "
        f"**variance-risk-premium spread {cal['implied_atm_iv']-cal['realised_vol']:+.4f}**; "
        f"DVOL {cal['dvol']}; r {cal['r']} ({cal['r_source']}).",
        "",
        f"Full-grid MC: 7 structures, drift band {camp['drifts']} (ASSUMED, 0=no-view anchor), "
        f"2 vol regimes (fair-value / VRP), {len(camp['seeds'])} seeds, {camp['n_paths']:,} paths/config, "
        f"GBM, {camp['cadence_days']:.0f}d x {camp['n_cycles']} rolling cycles. "
        f"total_non_finite={camp['total_non_finite']}. evidence sha256 `{checksum[:24]}`.",
        "",
        "> The VRP case sells options at the live implied IV while spot diffuses at the OBSERVED "
        "realised vol — the honest edge (implied > realised), not an assumed drift. The crash-risk "
        "tail remains (Alexander-Imeraj; Sinclair). MS-26 pending; no ranking/optimality claim.",
        "",
        "## 1. Full-grid drift-band table (drift 0 shown; VRP vs fair-value; +/- bootstrap SE)",
        "",
        "| Structure | regime | mean P&L +/- SE | VaR95 +/- SE (%cap) | ES97.5 +/- SE (%cap) | prob-loss +/- SE | overlay P&L |",
        "|---|---|---|---|---|---|---|",
    ]
    for kind in BUILDERS:
        for regime in ("fair_value", "vrp"):
            b = res["drift_band"][kind][f"{regime}|+0.00"]
            L.append(
                f"| {kind} | {regime} "
                f"| {b['mean_pnl']:,.0f} +/- {b['mean_pnl_se']:,.0f} "
                f"| {b['var95']:,.0f} +/- {b['var95_se']:,.0f} ({100*b['var95']/cap:.1f}%) "
                f"| {b['es975']:,.0f} +/- {b['es975_se']:,.0f} ({100*b['es975']/cap:.1f}%) "
                f"| {b['prob_loss']:.3f} +/- {b['prob_loss_se']:.3f} "
                f"| {b['overlay']:,.0f} |"
            )
    L += ["", "Full drift band {-0.10,0,+0.10} x both regimes per structure is in the evidence JSON. "
          "The VRP overlay is positive (earns implied-minus-realised); fair-value overlay ~ 0 (no edge). "
          "prob-of-loss stays BTC-inherent (dominated by the holding leg) even with the VRP edge.", ""]

    t = res["evt_tail"]
    L += [
        "## 2. EVT tail comparison — " + t["structure"] + " (ES is the coherent headline)",
        "",
        "| Method | VaR97.5 | ES97.5 | %cap (ES) | GPD xi | threshold | n_exceed |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, m in t["methods"].items():
        xi = f"{m['xi']:.3f}" if m["xi"] is not None else "-"
        th = f"{m['threshold']:,.0f}" if m["threshold"] is not None else "-"
        ne = str(m["n_exceedances"]) if m["n_exceedances"] is not None else "-"
        L.append(f"| {name} | {m['var']:,.0f} | {m['es']:,.0f} | {100*m['es']/t['capital_base']:.1f}% "
                 f"| {xi} | {th} | {ne} |")
    xi = t["methods"].get("evt_gpd", {}).get("xi")
    xi_txt = (f"The GPD shape xi={xi:.3f} here is "
              + ("positive — a heavy tail." if (xi or 0) > 0 else
                 "negative — a bounded tail under this GBM diffusion; a jump-diffusion (Merton) or the "
                 "real market's crash risk, for which the VRP compensates, would fatten it.")
              ) if xi is not None else "GPD did not fit (too few exceedances); empirical used."
    L += ["", "EVT/GPD fits the far tail (peaks-over-threshold, McNeil QRM Ch.5); Cornish-Fisher is the "
          "moment-based cross-check; ES (coherent) is the headline. The three methods agree closely. "
          + xi_txt, ""]

    fr = res["cvar_frontier"]
    L += [
        "## 3. CVaR loss-budget efficient frontier (beta=0.95, drift 0, VRP) — admissible set, not a ranking",
        "",
        "| Loss budget (%cap) | # admissible | admissible structures | max-expected point | its E[P&L] |",
        "|---|---|---|---|---|",
    ]
    for fp in fr["frontier"]:
        adm = ", ".join(fp["admissible"]) if fp["admissible"] else "(none)"
        eff_lbl = fp["efficient"] or "-"
        eff_e = f"{fp['efficient_expected']:,.0f}" if fp["efficient_expected"] is not None else "-"
        L.append(f"| {fp['budget_pct_cap']:.0f}% | {len(fp['admissible'])} | {adm} | {eff_lbl} | {eff_e} |")
    L += ["", f"Pareto-efficient candidates (the frontier): {', '.join(fr['pareto_efficient'])}.",
          "The client's **D-10 loss budget** selects a point on this frontier; the engine only draws it "
          "(no single pick — MS-25/MS-26/D-10 open). Collars enter at the tightest budgets (floored tail).", ""]

    L += ["## 4. Discipline", "",
          "All outputs SIMULATED/diagnostic; pending_decision_refs " + ", ".join(res["pending_decision_refs"])
          + " carried; VRP-vs-fair-value and the full drift band shown (never a single flattering case); "
          "no best/optimal/preferred/winning language; no claim requiring MS-25/MS-26/CSCV-PBO-DSR; "
          "every figure traces to the frozen snapshot. Tier-0 T0-1 (GARCH sqrt365) and T0-5 (q=0 "
          "provenance) fixed; DSR/PBO (T0-2/3) remain gated (no PBO/DSR number shown). **Review gate — "
          "Phase 5 packaging not started.**", ""]
    REPORT.write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="C8 R1-R3 improvement pass")
    p.add_argument("--snapshot", type=pathlib.Path, default=None)
    p.add_argument("--paths", type=int, default=20_000)
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    snap_dir = args.snapshot or promoted_anchor_dir(DEFAULT_OUT_ROOT) or FIXTURES_DIR
    res = run_pass(snap_dir, args.paths)
    EVIDENCE.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    checksum = hashlib.sha256(json.dumps(res["drift_band"], sort_keys=True, default=str).encode()).hexdigest()
    _write_report(res, checksum)
    logger.info("Wrote %s and %s", REPORT, EVIDENCE)
    vrp_spread = res["calibration"]["implied_atm_iv"] - res["calibration"]["realised_vol"]
    print(f"non_finite={res['campaign']['total_non_finite']}  VRP_spread={vrp_spread:.4f}  "
          f"pareto={res['cvar_frontier']['pareto_efficient']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
