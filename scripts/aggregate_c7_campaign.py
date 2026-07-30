#!/usr/bin/env python3
"""Aggregate the C7 60M campaign raw results into the post-remediation evidence
package. Reads the per-config CSVs written by run_c7_campaign.py and produces
seed-level + aggregate metrics, a configuration summary, a run inventory, checksums,
a source-to-number map and a committee-facing report.

Crucially it reports the **cross-seed dispersion** of each metric per (strategy, tier).
The prior 60M campaign's fatal defect was zero variance across seeds (the aggregates
came from a deterministic backtest, not the MC); here the metrics are MC-derived, so a
non-zero cross-seed std is the validation that the campaign is genuine.

All outputs are SIMULATED diagnostics. No ranking / optimality / convergence claim.

Usage: python scripts/aggregate_c7_campaign.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import statistics
import sys
from datetime import UTC, datetime
from typing import Any

CAMPAIGN_DIR = pathlib.Path("/home/francisco/btc/post_remediation_60m_campaign")
RAW = CAMPAIGN_DIR / "raw_results"
AGG = CAMPAIGN_DIR / "aggregate_results"
EVID = CAMPAIGN_DIR / "evidence"
REPORTS = CAMPAIGN_DIR / "reports"
CHECKSUMS = CAMPAIGN_DIR / "checksums"

METRICS = [
    "mean_outcome_usd", "median_outcome_usd", "std_outcome_usd",
    "percentile_5_usd", "percentile_1_usd", "expected_shortfall_95",
    "expected_shortfall_99", "probability_of_loss", "max_loss_usd",
    "mc_standard_error", "mean_final_btc", "mean_total_premium_pct",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for p in sorted(RAW.glob("mc-*.csv")):
        with open(p) as f:
            rows.extend(csv.DictReader(f))
    return rows


def main() -> int:
    for d in (AGG, EVID, REPORTS, CHECKSUMS):
        d.mkdir(parents=True, exist_ok=True)
    rows = _load_rows()
    if not rows:
        print("No raw results found; run the campaign first.", file=sys.stderr)
        return 1

    # group by (strategy, tier) across seeds
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    seeds_seen: set[str] = set()
    for r in rows:
        groups.setdefault((r["strategy"], r["tier"]), []).append(r)
        seeds_seen.add(r["seed"])

    agg_rows: list[dict[str, Any]] = []
    for (strat, tier), grp in sorted(groups.items()):
        entry: dict[str, Any] = {
            "strategy": strat, "tier": int(tier), "model": grp[0]["model"],
            "n_seeds": len(grp), "n_cycles": grp[0]["n_cycles"],
            "d1_fee_base": grp[0]["d1_fee_base"], "d12_interpretation": grp[0]["d12_interpretation"],
            "provenance": "SIMULATED",
        }
        for m in METRICS:
            vals = [float(r[m]) for r in grp]
            entry[f"{m}__seed_mean"] = round(statistics.fmean(vals), 6)
            entry[f"{m}__seed_std"] = round(statistics.pstdev(vals), 6) if len(vals) > 1 else 0.0
            entry[f"{m}__seed_min"] = round(min(vals), 6)
            entry[f"{m}__seed_max"] = round(max(vals), 6)
        agg_rows.append(entry)

    agg_path = AGG / "aggregate_by_strategy_tier.csv"
    with open(agg_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(agg_rows[0].keys()))
        w.writeheader()
        w.writerows(agg_rows)

    # Seed-level file (verbatim raw, sorted)
    seed_path = AGG / "seed_level_metrics.csv"
    with open(seed_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["strategy"], int(r["tier"]), int(r["seed"]))))

    # Genuine-variance validation: for the key tail metric, is cross-seed std > 0?
    variance_ok = True
    zero_var = []
    for e in agg_rows:
        key = "expected_shortfall_95__seed_std"
        if e["n_seeds"] > 1 and e[key] == 0.0 and e["strategy"] != "unhedged":
            variance_ok = False
            zero_var.append((e["strategy"], e["tier"]))

    # Distinct simulated paths = sum of tiers over distinct (seed, tier) configs;
    # strategies share paths, so the strategy dimension does NOT multiply the count.
    distinct_configs = {(r["seed"], r["tier"]) for r in rows}
    aggregate_paths = sum(int(t) for _s, t in distinct_configs)

    summary = {
        "generated_at": _now(),
        "provenance": "SIMULATED — diagnostic only (MS-25/MS-26 unresolved; no ranking/optimality/convergence claim)",
        "seeds": sorted(int(s) for s in seeds_seen),
        "tiers": sorted({int(r["tier"]) for r in rows}),
        "strategies": sorted({r["strategy"] for r in rows}),
        "model": rows[0]["model"],
        "distinct_configs": len(distinct_configs),
        "aggregate_simulated_paths": aggregate_paths,
        "expected_aggregate_paths": 60_000_000,
        "aggregate_reconciles": aggregate_paths == 60_000_000,
        "cross_seed_variance_nonzero": variance_ok,
        "zero_variance_groups": zero_var,
        "d1_fee_base": rows[0]["d1_fee_base"],
        "d12_interpretation": rows[0]["d12_interpretation"],
    }
    (EVID / "configuration_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # source-to-number map
    trace_path = EVID / "source_to_number_traceability.csv"
    with open(trace_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["output_file", "row_key", "metric", "method", "provenance"])
        w.writeheader()
        for e in agg_rows:
            for m in METRICS:
                w.writerow({"output_file": agg_path.name,
                            "row_key": f"{e['strategy']}_{e['tier']}",
                            "metric": f"{m}__seed_mean",
                            "method": "multi_cycle_monte_carlo (Merton, shared paths)",
                            "provenance": "SIMULATED"})

    # committee-facing report
    report = [
        "# C7 Post-Remediation 60M Campaign — Evidence Summary (SIMULATED / DIAGNOSTIC)",
        "",
        f"Generated: {_now()}",
        "",
        "> **Provenance & governance.** Every number here is SIMULATED (Monte Carlo).",
        "> Volatility, drift and jump parameters are ASSUMED/uncalibrated. Per",
        "> FRONTIER_ORCHESTRATION.md §8 this is a diagnostic run only: **no strategy is",
        "> ranked, preferred or called optimal**, and no convergence is claimed from the",
        "> path-count tiers. MS-25 (objective function) and MS-26 (simulation methodology)",
        "> remain unresolved. D-1=reference_notional and D-12=cash_settled are UNRESOLVED",
        "> business decisions (alternative variants emitted by run_c7_fasttrack_suite).",
        "",
        "## Campaign structure",
        f"- Model: {summary['model']} (single). Seeds: {summary['seeds']}.",
        f"- Tiers (paths/seed): {summary['tiers']}.",
        f"- Strategies (shared paths): {summary['strategies']}.",
        f"- Distinct configs: {summary['distinct_configs']}  |  "
        f"Aggregate simulated paths: {summary['aggregate_simulated_paths']:,} "
        f"(expected 60,000,000, reconciles={summary['aggregate_reconciles']}).",
        "",
        "## Cross-seed variance validation",
        f"- Cross-seed dispersion of ES95 is non-zero for hedged strategies: "
        f"**{summary['cross_seed_variance_nonzero']}** "
        f"(the prior campaign's fatal defect was zero cross-seed variance).",
    ]
    if zero_var:
        report.append(f"- Zero-variance groups (investigate): {zero_var}")
    report += [
        "",
        "## Seed-mean outcome (USD) and tail risk by strategy x tier",
        "",
        "| strategy | tier | mean_outcome_usd (seed-mean ± seed-std) | ES95 (seed-mean ± std) | P(loss) seed-mean |",
        "|---|---|---|---|---|",
    ]
    for e in sorted(agg_rows, key=lambda x: (x["strategy"], x["tier"])):
        report.append(
            f"| {e['strategy']} | {e['tier']:,} | "
            f"{e['mean_outcome_usd__seed_mean']:,.0f} ± {e['mean_outcome_usd__seed_std']:,.0f} | "
            f"{e['expected_shortfall_95__seed_mean']:,.0f} ± {e['expected_shortfall_95__seed_std']:,.0f} | "
            f"{e['probability_of_loss__seed_mean']:.4f} |")
    report += [
        "",
        "## Files",
        f"- Aggregate: `aggregate_results/{agg_path.name}`",
        f"- Seed-level: `aggregate_results/{seed_path.name}`",
        "- Configuration summary: `evidence/configuration_summary.json`",
        "- Source-to-number: `evidence/source_to_number_traceability.csv`",
        "",
        "*Not decision evidence. For internal diagnostic review only.*",
    ]
    report_path = REPORTS / "campaign_evidence_summary.md"
    report_path.write_text("\n".join(report))

    # checksums of the evidence outputs
    checks = {}
    for p in (agg_path, seed_path, EVID / "configuration_summary.json", trace_path, report_path):
        checks[p.name] = _sha256(p)
    (CHECKSUMS / "evidence_checksums.json").write_text(json.dumps(checks, indent=2))

    print(f"Aggregated {len(rows)} rows -> {len(agg_rows)} (strategy,tier) groups.")
    print(f"Aggregate paths: {summary['aggregate_simulated_paths']:,} "
          f"reconciles={summary['aggregate_reconciles']}  "
          f"cross_seed_variance_ok={summary['cross_seed_variance_nonzero']}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
