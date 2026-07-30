#!/usr/bin/env python3
"""C8 Phase 4 - evidence & deck-input pack (NOT the deck).

Emits, all provenance-labelled and snapshot-cited:
  * the full 210-row strategy grid as CSV + JSON (all structures at parity, both
    standalone and total-portfolio scenario views);
  * a Slide-2 / Slide-2-continued data pack - the computed quantitative comparative
    matrix across every structure plus the hero highlights;
  * a Slide-5 MC diagnostic pack - the drift-band metrics over the archetypes
    (SIMULATED), read from the frozen campaign;
  * a small, properly-worded disclaimer;
  * a file manifest (checksums + snapshot cite + pending decision refs).

Bulk artefacts (grid CSV/JSON) go to exports/ (git-ignored, regenerable); the
human-readable deck-input packs + manifest are written under docs/evidence/
(committed). Builds no slides and touches no HTML/Marp.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import logging
import math
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from strategy.strategy_grid import (
    DISCLAIMER,
    PENDING_DECISION_REFS,
    GridExpiry,
    GridRow,
    StrategyGrid,
    atm_iv_for_expiry,
    build_grid,
)
from vol.chain import select_expiries
from vol.snapshot import load_snapshot, promoted_anchor_dir

logger = logging.getLogger("c8.evidence")

REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT: pathlib.Path = REPO_ROOT / "market_snapshots"
FIXTURES_DIR: pathlib.Path = REPO_ROOT / "tests" / "fixtures"
EXPORT_DIR: pathlib.Path = REPO_ROOT / "exports" / "c8_evidence_pack"   # git-ignored bulk
EVIDENCE_DIR: pathlib.Path = REPO_ROOT / "docs" / "evidence"           # committed deck input
CAMPAIGN_FILE: str = "c8_hero_mc_campaign.json"
RISK_FREE_FALLBACK: float = 0.04

# Representative cell per structure for the Slide-2 comparative matrix (near expiry, 100% cov).
REPRESENTATIVE: dict[str, float | None] = {
    "unhedged_baseline": None,
    "covered_call": 5.0,
    "long_btc_plus_short_put": -5.0,
    "cash_secured_put": -5.0,
    "collar": 5.0,          # 10%-floor variant selected below
    "call_spread": 5.0,
    "strike_ladder": 5.0,
}


def _build(snapshot_dir: pathlib.Path) -> StrategyGrid:
    snap = load_snapshot(snapshot_dir)
    s0, ref = snap.spot.price, snap.meta.created_at
    sel = select_expiries(snap.instruments, snap.book_summaries, reference=ref)
    expiries: list[GridExpiry] = []
    for e in sel.distinct:
        aiv = atm_iv_for_expiry(e.expiry.isoformat(), s0, snap.instruments, snap.book_summaries)
        expiries.append(GridExpiry(
            label=e.label, expiry_utc=e.expiry.isoformat(), dte_days=e.days_to_expiry,
            t_years=e.days_to_expiry / 365.0, atm_iv=aiv,
            sigma_horizon=aiv * math.sqrt(e.days_to_expiry / 365.0),
        ))
    return build_grid(ref.isoformat(), str(snapshot_dir), s0, RISK_FREE_FALLBACK, expiries,
                      snap.instruments, snap.book_summaries)


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── CSV writers ──────────────────────────────────────────────────────────────


def _term(row: GridRow, portfolio: bool) -> dict[float, float]:
    cells = row.scenarios_terminal_portfolio if portfolio else row.scenarios_terminal
    return {c.k_sigma: c.total.per_btc for c in cells}


def write_grid_csvs(grid: StrategyGrid) -> tuple[pathlib.Path, pathlib.Path]:
    summary = EXPORT_DIR / "grid_summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "structure_id", "canonical_kind", "is_hero", "benchmark_only", "expiry", "dte_days",
            "coverage_pct", "strike_pct", "atm_iv", "sigma_horizon",
            "net_premium_per_btc", "premium_pct_spot", "premium_per_portfolio",
            "prob_win", "prob_win_measure",
            "maxloss_total_per_btc", "maxloss_holding_per_btc", "maxloss_option_per_btc",
            "maxloss_total_pct_capital", "capital_basis", "true_breakevens",
            "opt_delta_per_btc", "theta_per_day_per_btc", "total_pos_delta",
            "opp_cost_p1sigma_per_btc", "opp_cost_p2sigma_per_btc",
            "fee_reference_notional", "fee_executed_volume",
            "term_std_m2", "term_std_m1", "term_std_0", "term_std_p1", "term_std_p2",
            "term_pf_m2", "term_pf_m1", "term_pf_0", "term_pf_p1", "term_pf_p2",
            "attractive_when", "pending_decision_refs",
        ])
        for r in grid.rows:
            std, pf = _term(r, False), _term(r, True)
            oc = {c.k_sigma: c.foregone.per_btc for c in r.opportunity_cost}
            w.writerow([
                r.structure_id, r.canonical_kind, r.is_hero, r.benchmark_only, r.expiry_label,
                round(r.dte_days, 2), r.coverage_pct, r.strike_pct, round(r.atm_iv, 6),
                round(r.sigma_horizon, 6), round(r.premium.net_per_btc, 2),
                round(r.premium.pct_of_spot, 4), round(r.premium.per_portfolio, 2),
                round(r.prob_win.value, 4) if r.prob_win else "", r.prob_win.measure if r.prob_win else "",
                round(r.max_loss.total.per_btc, 2), round(r.max_loss.holding.per_btc, 2),
                round(r.max_loss.option.per_btc, 2), round(r.max_loss.total_pct_of_capital, 4),
                r.max_loss.capital_basis, ";".join(f"{b:.2f}" for b in r.breakeven.true_breakevens),
                round(r.greeks.option_delta_per_btc, 4), round(r.greeks.theta_per_day_per_btc, 2),
                round(r.greeks.total_position_delta_per_block_btc, 4),
                round(oc.get(1.0, 0.0), 2), round(oc.get(2.0, 0.0), 2),
                round(r.structuring_fee.on_reference_notional_usd, 2),
                round(r.structuring_fee.on_executed_volume_usd, 2),
                *[round(std.get(k, 0.0), 2) for k in (-2, -1, 0, 1, 2)],
                *[round(pf.get(k, 0.0), 2) for k in (-2, -1, 0, 1, 2)],
                r.attractive_when, "|".join(r.pending_decision_refs),
            ])

    scenarios = EXPORT_DIR / "grid_scenarios.csv"
    with scenarios.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["structure_id", "expiry", "coverage_pct", "strike_pct", "view", "mode",
                    "k_sigma", "pct_move", "scenario_spot",
                    "holding_per_btc", "option_per_btc", "total_per_btc", "pct_of_portfolio"])
        for r in grid.rows:
            views = [
                ("standalone", "instantaneous", r.scenarios_instantaneous),
                ("standalone", "terminal", r.scenarios_terminal),
                ("total_portfolio", "instantaneous", r.scenarios_instantaneous_portfolio),
                ("total_portfolio", "terminal", r.scenarios_terminal_portfolio),
            ]
            for view, mode, cells in views:
                for c in cells:
                    w.writerow([r.structure_id, r.expiry_label, r.coverage_pct, r.strike_pct,
                                view, mode, c.k_sigma, round(c.pct_move, 4), round(c.scenario_spot, 2),
                                round(c.holding.per_btc, 2), round(c.option.per_btc, 2),
                                round(c.total.per_btc, 2), round(c.pct_of_portfolio, 4)])
    return summary, scenarios


# ── Slide-2 comparative matrix ───────────────────────────────────────────────


def _pick(grid: StrategyGrid, structure_id: str, strike_pct: float | None) -> GridRow | None:
    for r in grid.rows:
        if r.structure_id != structure_id or r.expiry_label != grid.expiries[0].label:
            continue
        if r.coverage_pct != 100.0 or r.strike_pct != strike_pct:
            continue
        if structure_id == "collar":  # choose the 10%-floor variant
            put = next((leg for leg in r.option_legs if leg.kind == "put"), None)
            if put is None or abs(put.requested_pct + 10.0) > 1e-6:
                continue
        return r
    return None


def slide2_matrix(grid: StrategyGrid) -> list[dict[str, object]]:
    exp = grid.expiries[0].label
    rows: list[dict[str, object]] = []
    for sid, strike in REPRESENTATIVE.items():
        r = _pick(grid, sid, strike)
        if r is None:
            continue
        term = {c.k_sigma: c.total.per_btc for c in r.scenarios_terminal}
        rows.append({
            "structure": sid, "canonical_kind": r.canonical_kind, "is_hero": r.is_hero,
            "benchmark_only": r.benchmark_only, "business_label": r.business_label,
            "expiry": exp, "coverage_pct": r.coverage_pct, "strike_pct": r.strike_pct,
            "premium_pct_spot": round(r.premium.pct_of_spot, 3) if r.option_legs else None,
            "premium_per_portfolio": round(r.premium.per_portfolio, 0) if r.option_legs else None,
            "prob_win": round(r.prob_win.value, 3) if r.prob_win else None,
            "maxloss_total_per_btc": round(r.max_loss.total.per_btc, 0),
            "maxloss_holding_per_btc": round(r.max_loss.holding.per_btc, 0),
            "maxloss_option_per_btc": round(r.max_loss.option.per_btc, 0),
            "maxloss_pct_capital": round(100 * r.max_loss.total_pct_of_capital, 1),
            "true_breakevens": [round(b, 0) for b in r.breakeven.true_breakevens],
            "opt_delta_per_btc": round(r.greeks.option_delta_per_btc, 3),
            "theta_per_day_per_btc": round(r.greeks.theta_per_day_per_btc, 1),
            "opp_cost_p2sigma_per_btc": round(
                next((c.foregone.per_btc for c in r.opportunity_cost if c.k_sigma == 2.0), 0.0), 0),
            "term_total_per_btc_by_sigma": {str(int(k)): round(term.get(k, 0.0), 0)
                                            for k in (-2, -1, 0, 1, 2)},
            "attractive_when": r.attractive_when,
        })
    return rows


# ── main ─────────────────────────────────────────────────────────────────────


def _fmt(x: object) -> str:
    if isinstance(x, float):
        return f"{x:,.0f}" if abs(x) >= 1000 else f"{x:,.3f}"
    return str(x)


def write_slide2_md(matrix: list[dict[str, object]], grid: StrategyGrid) -> pathlib.Path:
    lines = [
        "# C8 Slide-2 / Slide-2-continued Data Pack (computed comparative matrix)",
        "",
        f"Snapshot as of **{grid.as_of_utc}**; S0 **{grid.s0:,.2f}**; expiry **{grid.expiries[0].label}** "
        f"(~{grid.expiries[0].dte_days:.0f}d); 100% coverage; representative strike per structure. Every "
        "number computed off the frozen snapshot. No best/optimal/preferred language.",
        "",
        "The computed successor to the qualitative choice matrix. Full 210-row grid (all strikes x both "
        "expiries x coverage {25/50/75/100}%, standalone + total-portfolio views) in the CSV/JSON.",
        "",
        "| Structure | prem %spot | prob-win | max-loss/BTC (hold+opt=total) | %cap | breakeven | delta/BTC | theta/day/BTC | opp-cost +2sig/BTC | attractive when |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in matrix:
        hold = m["maxloss_holding_per_btc"]
        opt = m["maxloss_option_per_btc"]
        tot = m["maxloss_total_per_btc"]
        prem = m["premium_pct_spot"]
        lines.append(
            f"| {m['business_label']}{' *(benchmark)*' if m['benchmark_only'] else ''}"
            f"{' **[HERO]**' if m['is_hero'] else ''} "
            f"| {prem if prem is not None else 'n/a'} "
            f"| {m['prob_win'] if m['prob_win'] is not None else 'n/a'} "
            f"| {_fmt(hold)}+{_fmt(opt)}={_fmt(tot)} "
            f"| {m['maxloss_pct_capital']} "
            f"| {m['true_breakevens']} "
            f"| {m['opt_delta_per_btc']} | {m['theta_per_day_per_btc']} "
            f"| {_fmt(m['opp_cost_p2sigma_per_btc'])} "
            f"| {m['attractive_when']} |"
        )
    lines += [
        "",
        "**Hero highlights (28AUG26, 100% coverage, strike sweep):**",
        "",
        "| Hero | strike% | prem %spot | prob-win | max-loss/BTC | +2sigma terminal/BTC (capped) |",
        "|---|---|---|---|---|---|",
    ]
    for sid in ("covered_call", "long_btc_plus_short_put"):
        for r in grid.rows:
            if (r.structure_id == sid and r.expiry_label == grid.expiries[0].label
                    and r.coverage_pct == 100.0 and r.prob_win is not None):
                term = {c.k_sigma: c.total.per_btc for c in r.scenarios_terminal}
                lines.append(
                    f"| {r.business_label} | {r.strike_pct} | {r.premium.pct_of_spot:.3f} "
                    f"| {r.prob_win.value:.3f} | {r.max_loss.total.per_btc:,.0f} "
                    f"| {term.get(2.0, 0.0):,.0f} |"
                )
    lines += ["", f"Pending decisions carried: {', '.join(PENDING_DECISION_REFS)}.", ""]
    path = EVIDENCE_DIR / "c8_slide2_data_pack.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_slide5_md(campaign: dict[str, Any] | None) -> pathlib.Path:
    path = EVIDENCE_DIR / "c8_slide5_mc_pack.md"
    if campaign is None:
        path.write_text("# C8 Slide-5 MC pack\n\nCampaign JSON not found; run "
                        "scripts/run_c8_hero_campaign.py to regenerate.\n", encoding="utf-8")
        return path
    cal = campaign["calibration"]
    band = campaign["drift_band"]
    camp = campaign["campaign"]
    roles = camp["archetype_roles"]
    lines = [
        "# C8 Slide-5 MC Diagnostic Pack (SIMULATED / diagnostic — not decision evidence)",
        "",
        f"Snapshot as of **{cal['as_of']}**; calibrated vol **{cal['atm_iv']:.4f}** "
        f"({cal['near_tenor']} ATM IV; DVOL {cal['dvol']}); r **{cal['r']}** ({cal['r_source']}); "
        f"drift band **{camp['drift_band']}** (ASSUMED; neutral 0 = no-view anchor). "
        f"{camp['total_simulated_paths']:,} simulated paths; MS-26 pending.",
        "",
        "prob-of-loss is BTC-inherent (near-identical across archetypes at drift 0); the collar's value "
        "is the collapsed tail. No ranking / optimality / convergence claim.",
        "",
        "| Archetype (role) | drift | P&L mean | P&L p5 | P&L p95 | prob-loss | VaR95%cap | ES97.5%cap | maxDD%cap | ITM | touch |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for kind in ("covered_call", "long_btc_plus_short_put", "collar", "partial_overlay"):
        if kind not in band:
            continue
        cap = next(iter(band[kind].values()))["capital_base"]
        for dkey in sorted(band[kind], key=float):
            b = band[kind][dkey]
            role = roles.get(kind, "")
            lines.append(
                f"| {kind} ({role}) | {dkey} | {b['total_pnl_mean_usd']:,.0f} "
                f"| {b['total_pnl_p5_usd']:,.0f} | {b['total_pnl_p95_usd']:,.0f} "
                f"| {b['probability_of_loss']:.3f} | {100*b['var_95_usd']/cap:.1f} "
                f"| {100*b['expected_shortfall_975_usd']/cap:.1f} "
                f"| {100*b['mean_max_drawdown_usd']/cap:.1f} "
                f"| {b['mean_itm_frequency']:.2f} | {b['mean_touch_frequency']:.2f} |"
            )
    lines += ["", "Holding-vs-overlay decomposition (drift 0, USD):", ""]
    for kind in band:
        d0 = band[kind].get("+0.00")
        if d0:
            lines.append(f"- **{kind}**: holding (BTC-inherent) {d0['mean_holding_pnl_usd']:,.0f}; "
                         f"overlay (advised, pre-fee) {d0['mean_overlay_gross_pnl_usd']:,.0f}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


DISCLAIMER_TEXT = (
    DISCLAIMER + "\n\n"
    "Attribution is structure-specific: the covered call's overlay is a non-negative premium cushion "
    "(down-scenario losses are inherent to holding BTC, not attributable to the overlay), whereas "
    "Long BTC + short put's overlay adds incremental downside below the strike (that sub-strike loss "
    "IS attributable to the advised structure). Capped upside is opportunity cost (foregone gain), "
    "not a loss. Alternatives are presented, not ranked; investment decisions and their outcomes rest "
    "with the client."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="C8 Phase 4 - evidence & deck-input pack")
    parser.add_argument("--snapshot", type=pathlib.Path, default=None)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    snapshot_dir = args.snapshot or promoted_anchor_dir(DEFAULT_OUT_ROOT) or FIXTURES_DIR
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    grid = _build(snapshot_dir)
    grid_json = EXPORT_DIR / "grid.json"
    grid_json.write_text(json.dumps(dataclasses.asdict(grid), indent=2, default=str), encoding="utf-8")
    summary_csv, scenarios_csv = write_grid_csvs(grid)

    matrix = slide2_matrix(grid)
    (EXPORT_DIR / "slide2_matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    slide2_md = write_slide2_md(matrix, grid)

    campaign_path = snapshot_dir / CAMPAIGN_FILE
    campaign = json.loads(campaign_path.read_text()) if campaign_path.exists() else None
    slide5_md = write_slide5_md(campaign)

    disclaimer_md = EVIDENCE_DIR / "c8_disclaimer.md"
    disclaimer_md.write_text("# C8 Disclaimer\n\n" + DISCLAIMER_TEXT + "\n", encoding="utf-8")

    committed = [slide2_md, slide5_md, disclaimer_md]
    bulk = [grid_json, summary_csv, scenarios_csv]
    manifest = {
        "provenance": "computed off frozen snapshot",
        "snapshot_dir": str(snapshot_dir),
        "as_of_utc": grid.as_of_utc,
        "s0": grid.s0,
        "grid_rows": len(grid.rows),
        "pending_decision_refs": list(PENDING_DECISION_REFS),
        "mc_diagnostic": "SIMULATED (MS-26 pending); see c8_hero_mc_manifest.json for MC provenance",
        "files": {
            p.name: {"path": str(p.relative_to(REPO_ROOT)), "sha256": _sha256(p),
                     "committed": p in committed}
            for p in [*committed, *bulk]
        },
        "note": "Bulk grid CSV/JSON are git-ignored under exports/ (regenerable); deck-input packs "
                "are committed under docs/evidence/.",
    }
    manifest_path = EVIDENCE_DIR / "c8_evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info("Evidence pack: %d grid rows; %d committed packs, %d bulk artefacts.",
                len(grid.rows), len(committed), len(bulk))
    print(f"\nWrote evidence pack for snapshot {grid.as_of_utc}:")
    for p in [*committed, manifest_path]:
        print(f"  committed: {p.relative_to(REPO_ROOT)}")
    for p in bulk:
        print(f"  bulk (git-ignored): {p.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
