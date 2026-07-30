#!/usr/bin/env python3
"""C7 post-remediation 60,000,000-path robustness campaign (resumable, idempotent).

Authoritative structure (docs/reports/final_empirical_research_synthesis_deepseek.md
§7.1-7.2; evidence_packages/stage3_fasttrack/legacy_60m_campaign_verification.txt):
  - 12 seeds x 3 tiers (500k / 1.5M / 3M) = 36 path-generation configurations.
  - single Merton model (the baseline model); strategies are evaluated on the SAME
    paths per (seed, tier), so neither the model nor the strategy dimension multiplies
    the aggregate path count.
  - aggregate = 12 x (0.5M + 1.5M + 3M) = 60,000,000 simulated paths.

All outputs are SIMULATED diagnostics. Per FRONTIER_ORCHESTRATION.md §8 no ranking /
optimality / convergence claim is authorised (MS-25 objective function and MS-26
simulation methodology are unresolved); volatility / drift / jump params are ASSUMED.
D-1 fee base and D-12 interpretation are UNRESOLVED business decisions — the campaign
runs the reference_notional / cash_settled pair and labels it as such; the
alternative variants are emitted by run_c7_fasttrack_suite.

Design: one process, bounded chunks, nice; no wall-clock timeout. Each (seed, tier)
config is idempotent — a completed config with a valid output checksum is skipped on
resume. Interrupt-safe: an incomplete config is simply re-run.

Usage:
  python scripts/run_c7_campaign.py --dry-run     # validate plan + 60M reconciliation
  python scripts/run_c7_campaign.py               # run / resume the campaign
  python scripts/run_c7_campaign.py --status      # print completion inventory
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import resource
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.strategy import Strategy
from strategy.definitions import (
    build_cash_secured_put,
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_partial_overlay,
    build_unhedged_baseline,
)
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    run_multi_cycle_monte_carlo_multi,
)

# ── authoritative campaign structure ──────────────────────────────────────────
SEEDS = [101, 211, 307, 401, 503, 601, 701, 809, 907, 1009, 1103, 1201]
TIERS = [500_000, 1_500_000, 3_000_000]
MODEL: Literal["GBM", "Merton"] = "Merton"
N_CYCLES = 12
CHUNK_SIZE = 50_000
EXPECTED_AGGREGATE = len(SEEDS) * sum(TIERS)  # 60,000,000

# Documented reference transaction configuration (all ASSUMED where uncalibrated).
REF: dict[str, Any] = {
    "cycle_length_years": 30.0 / 365.0,
    "initial_spot": 65_000.0,
    "drift": 0.10,
    "volatility": 0.45,
    "risk_free_rate": 0.04,
    "jump_intensity": 2.0,
    "jump_mean": -0.05,
    "jump_std": 0.10,
    "n_steps_per_cycle": 30,
    "strike_target_pct": 0.15,
    "btc_quantity": 30_000.0,
    "execution_fee_pct": 0.005,
    "seller_discount_pct": 0.025,
    "capital_base": 1_950_000_000.0,
    "d1_fee_base": "reference_notional",   # D-1 UNRESOLVED — labelled; alt = executed_volume
    "d12_interpretation": "cash_settled",  # D-12 UNRESOLVED — labelled; alt = post_purchase
}

# C7 multi-cycle-modelled strategies ONLY. call_spread / strike_ladder / protective_put
# are NOT modelled by _run_cycles_vectorized (they would evaluate as hold-only) and are
# deliberately EXCLUDED pending dedicated multi-cycle economics (methodology gap, logged).
STRATEGIES: list[tuple[str, Callable[[], Strategy]]] = [
    ("unhedged", lambda: build_unhedged_baseline(quantity=30_000.0, entry_spot=65_000.0)),
    ("covered_call", lambda: build_covered_call(quantity=30_000.0, entry_spot=65_000.0, strike=74_750.0, premium_received=1500.0)),
    ("lbsp", lambda: build_long_btc_plus_short_put(quantity=30_000.0, entry_spot=65_000.0, strike=55_250.0, premium_received=1500.0)),
    ("collar", lambda: build_collar(quantity=30_000.0, entry_spot=65_000.0, call_strike=74_750.0, put_strike=55_250.0, call_premium=1500.0, put_premium=1200.0)),
    ("partial_50", lambda: build_partial_overlay(total_quantity=30_000.0, overlay_ratio=0.5, entry_spot=65_000.0, strike=74_750.0, premium_received=1500.0)),
    ("cash_secured_put", lambda: build_cash_secured_put(quantity=30_000.0, entry_spot=65_000.0, strike=55_250.0, premium_received=1500.0)),
]

CAMPAIGN_DIR = pathlib.Path("/home/francisco/btc/post_remediation_60m_campaign")
SUBDIRS = ["config", "checkpoints", "logs", "raw_results", "aggregate_results",
           "manifests", "checksums", "evidence", "reports"]


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=str(pathlib.Path(__file__).resolve().parents[1]), timeout=5).stdout.strip()
    except Exception:
        return "unknown"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _config_for(seed: int, tier: int) -> MultiCycleMCConfig:
    return MultiCycleMCConfig(
        n_paths=tier, n_cycles=N_CYCLES, model=MODEL, seed=seed,
        chunk_size=CHUNK_SIZE, store_paths=False, use_antithetic=True, **REF)


def _config_id(seed: int, tier: int) -> str:
    return f"mc-{MODEL}-{tier}-seed-{seed}"


def _setup_dirs() -> None:
    for d in SUBDIRS:
        (CAMPAIGN_DIR / d).mkdir(parents=True, exist_ok=True)


def _log(msg: str) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    with open(CAMPAIGN_DIR / "logs" / "campaign.log", "a") as f:
        f.write(line + "\n")


def _manifest_path() -> pathlib.Path:
    return CAMPAIGN_DIR / "manifests" / "campaign_manifest.json"


def _load_manifest() -> dict[str, Any]:
    p = _manifest_path()
    if p.exists():
        with open(p) as f:
            data: dict[str, Any] = json.load(f)
            return data
    return {"git_sha": _git_sha(), "created_at": _now(), "expected_aggregate_paths": EXPECTED_AGGREGATE,
            "seeds": SEEDS, "tiers": TIERS, "model": MODEL, "n_cycles": N_CYCLES,
            "strategies": [s for s, _ in STRATEGIES], "completed": {}}


def _save_manifest(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    with open(_manifest_path(), "w") as f:
        json.dump(manifest, f, indent=2, default=str)


def _config_complete(manifest: dict[str, Any], cid: str) -> bool:
    entry = manifest.get("completed", {}).get(cid)
    if not entry:
        return False
    out = CAMPAIGN_DIR / "raw_results" / f"{cid}.csv"
    return out.exists() and _sha256_file(out) == entry.get("checksum")


def build_plan() -> list[tuple[int, int]]:
    return [(seed, tier) for tier in TIERS for seed in SEEDS]


def reconcile_aggregate() -> tuple[int, bool]:
    total = sum(tier for _seed, tier in build_plan())
    return total, total == EXPECTED_AGGREGATE


def dry_run() -> int:
    _setup_dirs()
    plan = build_plan()
    total, ok = reconcile_aggregate()
    inv = []
    for seed, tier in plan:
        inv.append({"config_id": _config_id(seed, tier), "seed": seed, "tier": tier,
                    "model": MODEL, "n_cycles": N_CYCLES,
                    "strategies": ",".join(s for s, _ in STRATEGIES)})
    with open(CAMPAIGN_DIR / "config" / "planned_configurations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(inv[0].keys()))
        w.writeheader()
        w.writerows(inv)
    print(f"Planned configurations: {len(plan)}  (= {len(SEEDS)} seeds x {len(TIERS)} tiers)")
    print(f"Strategies per config (shared paths): {len(STRATEGIES)} -> {[s for s,_ in STRATEGIES]}")
    print(f"Aggregate simulated paths: {total:,}  expected {EXPECTED_AGGREGATE:,}  "
          f"reconciles={'YES' if ok else 'NO'}")
    print(f"Model: {MODEL} (single). Path count NOT multiplied by model or strategy count.")
    print("Excluded (not multi-cycle-modelled): call_spread, strike_ladder, protective_put.")
    print("D-1=reference_notional, D-12=cash_settled (both UNRESOLVED; alt variants via fast-track suite).")
    print(f"Config inventory written: {CAMPAIGN_DIR / 'config' / 'planned_configurations.csv'}")
    return 0 if ok else 1


def _resource_snapshot() -> dict[str, Any]:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return {"peak_rss_mb": round(ru.ru_maxrss / 1024.0, 1), "utime_s": round(ru.ru_utime, 1),
            "stime_s": round(ru.ru_stime, 1)}


def _run_config(seed: int, tier: int) -> dict[str, Any]:
    cid = _config_id(seed, tier)
    cfg = _config_for(seed, tier)
    strategies = [factory() for _label, factory in STRATEGIES]
    labels = {factory().strategy_id: label for label, factory in STRATEGIES}
    t0 = time.perf_counter()
    results = run_multi_cycle_monte_carlo_multi(strategies, cfg)
    wall = time.perf_counter() - t0

    rows = []
    for sid, r in results.items():
        rows.append({
            "config_id": cid, "seed": seed, "tier": tier, "model": MODEL,
            "strategy": labels.get(sid, sid), "strategy_kind": r.strategy_kind,
            "n_paths": r.n_paths, "n_cycles": r.n_cycles,
            "d1_fee_base": r.d1_fee_base, "d12_interpretation": r.d12_interpretation,
            "mean_outcome_usd": round(r.mean_outcome_usd, 2),
            "median_outcome_usd": round(r.median_outcome_usd, 2),
            "std_outcome_usd": round(r.std_outcome_usd, 2),
            "percentile_5_usd": round(r.percentile_5_usd, 2),
            "percentile_1_usd": round(r.percentile_1_usd, 2),
            "expected_shortfall_95": round(r.expected_shortfall_95, 2),
            "expected_shortfall_99": round(r.expected_shortfall_99, 2),
            "probability_of_loss": round(r.probability_of_loss, 6),
            "max_loss_usd": round(r.max_loss_usd, 2),
            "mc_standard_error": round(r.mc_standard_error, 2),
            "mean_final_btc": round(r.mean_final_btc, 4),
            "mean_total_premium_pct": round(r.mean_total_premium_pct, 6),
            "total_asym_fee_usd": round(r.total_asym_fee_usd, 2),
            "provenance": "SIMULATED",
        })
    out = CAMPAIGN_DIR / "raw_results" / f"{cid}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    checksum = _sha256_file(out)
    (CAMPAIGN_DIR / "checksums" / f"{cid}.sha256").write_text(f"{checksum}  {out.name}\n")
    return {"config_id": cid, "seed": seed, "tier": tier, "paths": tier,
            "wall_seconds": round(wall, 1), "checksum": checksum,
            "n_rows": len(rows), "resources": _resource_snapshot(), "completed_at": _now()}


def run_campaign() -> int:
    _setup_dirs()
    total, ok = reconcile_aggregate()
    if not ok:
        _log(f"ABORT: aggregate {total} != expected {EXPECTED_AGGREGATE}")
        return 1
    (CAMPAIGN_DIR / "logs" / "campaign.pid").write_text(str(os.getpid()))
    manifest = _load_manifest()
    manifest.setdefault("completed", {})
    plan = build_plan()
    _log(f"Campaign start pid={os.getpid()} git={_git_sha()} "
         f"configs={len(plan)} aggregate={total:,}")
    for i, (seed, tier) in enumerate(plan, 1):
        cid = _config_id(seed, tier)
        if _config_complete(manifest, cid):
            _log(f"[{i}/{len(plan)}] SKIP {cid} (complete, checksum valid)")
            continue
        _log(f"[{i}/{len(plan)}] RUN  {cid} ({tier:,} paths)")
        entry = _run_config(seed, tier)
        manifest["completed"][cid] = entry
        _save_manifest(manifest)
        _log(f"[{i}/{len(plan)}] DONE {cid} {entry['wall_seconds']}s "
             f"peakRSS={entry['resources']['peak_rss_mb']}MB")

    # Final reconciliation
    completed = manifest["completed"]
    done_paths = sum(e["paths"] for e in completed.values())
    manifest["final"] = {
        "completed_configs": len(completed),
        "expected_configs": len(plan),
        "aggregate_paths_completed": done_paths,
        "expected_aggregate_paths": EXPECTED_AGGREGATE,
        "reconciles": done_paths == EXPECTED_AGGREGATE and len(completed) == len(plan),
        "finished_at": _now(),
    }
    _save_manifest(manifest)
    _log(f"Campaign complete: {len(completed)}/{len(plan)} configs, "
         f"{done_paths:,}/{EXPECTED_AGGREGATE:,} paths, "
         f"reconciles={manifest['final']['reconciles']}")
    return 0 if manifest["final"]["reconciles"] else 1


def status() -> int:
    manifest = _load_manifest()
    completed = manifest.get("completed", {})
    plan = build_plan()
    done_paths = sum(e["paths"] for e in completed.values())
    print(f"Completed configs: {len(completed)}/{len(plan)}")
    print(f"Completed paths:   {done_paths:,}/{EXPECTED_AGGREGATE:,}")
    pending = [(_config_id(s, t)) for s, t in plan if _config_id(s, t) not in completed]
    print(f"Pending configs:   {len(pending)}")
    if pending[:5]:
        print("  next:", ", ".join(pending[:5]))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="C7 60M-path robustness campaign")
    p.add_argument("--dry-run", action="store_true", help="validate plan + reconciliation, do not run")
    p.add_argument("--status", action="store_true", help="print completion inventory")
    args = p.parse_args()
    if args.dry_run:
        return dry_run()
    if args.status:
        return status()
    return run_campaign()


if __name__ == "__main__":
    raise SystemExit(main())
