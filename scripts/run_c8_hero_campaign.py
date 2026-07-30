#!/usr/bin/env python3
"""C8 Phase 3 - rolling-lifecycle hero MC campaign (DIAGNOSTIC / SIMULATED).

Calibrates volatility to the live snapshot (near-tenor ATM IV; DVOL reported) and
r to the observed Deribit rate, then runs the two hero structures through the
rolling-lifecycle MC across seeds x tiers (strike% x model). Validates:
reconciles (all configs completed), cross-seed variance non-zero per group, and
zero non-finite outputs. Emits evidence JSON + a per-hero metric summary.

No ranking / optimality / convergence claim is made (MS-26 pending); every output
is labelled SIMULATED and is not decision evidence.

Usage:
  python scripts/run_c8_hero_campaign.py                 # promoted anchor
  python scripts/run_c8_hero_campaign.py --paths 50000   # override path count
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import pathlib
import sys
from statistics import pstdev
from typing import Any, Literal, cast

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from strategy.definitions import build_covered_call, build_long_btc_plus_short_put
from strategy.hero_lifecycle_mc import HeroMCResult, run_hero_lifecycle_mc
from strategy.multi_cycle_mc import MultiCycleMCConfig
from strategy.strategy_grid import atm_iv_for_expiry
from vol.chain import select_expiries
from vol.snapshot import load_snapshot, promoted_anchor_dir

logger = logging.getLogger("c8.hero_campaign")

REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT: pathlib.Path = REPO_ROOT / "market_snapshots"
FIXTURES_DIR: pathlib.Path = REPO_ROOT / "tests" / "fixtures"
CAMPAIGN_FILE: str = "c8_hero_mc_campaign.json"

# Right-sized diagnostic campaign (this-week timeline; not a full 60M path run).
STRIKE_TIERS: dict[str, tuple[float, ...]] = {
    "covered_call": (0.05, 0.10, 0.15),
    "long_btc_plus_short_put": (0.03, 0.05, 0.10),
}
MODELS: tuple[str, ...] = ("GBM", "Merton")
SEEDS: tuple[int, ...] = (101, 102, 103, 104, 105)
N_CYCLES: int = 12
CADENCE_DAYS: float = 29.0
DRIFT: float = 0.10  # ASSUMED (SIMULATED); not a return forecast.


def _calibrate(snapshot_dir: pathlib.Path) -> dict[str, Any]:
    snap = load_snapshot(snapshot_dir)
    s0 = snap.spot.price
    r = 0.0
    r_source = "assumed (config 4%)"
    sel = select_expiries(snap.instruments, snap.book_summaries, reference=snap.meta.created_at)
    near = min(sel.distinct, key=lambda e: e.days_to_expiry)
    atm_iv = atm_iv_for_expiry(near.expiry.isoformat(), s0, snap.instruments, snap.book_summaries)
    # r from a near-tenor instrument's observed interest_rate (Deribit sets it per currency).
    for b in snap.book_summaries:
        if near.label in b.instrument_name:
            r, r_source = b.interest_rate, "observed (deribit interest_rate)"
            break
    return {
        "s0": s0,
        "r": r,
        "r_source": r_source,
        "near_tenor": near.label,
        "near_dte": near.days_to_expiry,
        "atm_iv": atm_iv,
        "dvol": snap.meta.dvol_latest,
        "as_of": snap.meta.created_at.isoformat(),
        "snapshot_dir": str(snapshot_dir),
    }


def _config(hero: str, strike: float, model: str, seed: int, cal: dict[str, Any], paths: int) -> MultiCycleMCConfig:
    return MultiCycleMCConfig(
        n_paths=paths, n_cycles=N_CYCLES, cycle_length_years=CADENCE_DAYS / 365.0,
        n_steps_per_cycle=int(CADENCE_DAYS), initial_spot=cal["s0"], volatility=cal["atm_iv"],
        risk_free_rate=cal["r"], drift=DRIFT, model=cast(Literal["GBM", "Merton"], model), seed=seed,
        strike_target_pct=strike, d12_interpretation="cash_settled",
        capital_base=cal["s0"] * 30_000.0, store_paths=False,
    )


def run_campaign(snapshot_dir: pathlib.Path, paths: int) -> dict[str, Any]:
    cal = _calibrate(snapshot_dir)
    vol_source = f"calibrated: {cal['near_tenor']} ATM IV (snapshot, {cal['atm_iv']:.4f})"
    logger.info("Calibrated vol=%.4f (%s ATM IV); DVOL=%s; S0=%.2f; r=%.4f",
                cal["atm_iv"], cal["near_tenor"], cal["dvol"], cal["s0"], cal["r"])

    heroes = {"covered_call": build_covered_call(), "long_btc_plus_short_put": build_long_btc_plus_short_put()}
    results: list[dict[str, Any]] = []
    total_configs = sum(len(STRIKE_TIERS[h]) for h in heroes) * len(MODELS) * len(SEEDS)
    done = 0
    for hero, strat in heroes.items():
        for strike in STRIKE_TIERS[hero]:
            for model in MODELS:
                for seed in SEEDS:
                    cfg = _config(hero, strike, model, seed, cal, paths)
                    res: HeroMCResult = run_hero_lifecycle_mc(
                        strat, cfg, volatility_source=vol_source, risk_free_source=cal["r_source"],
                    )
                    row = dataclasses.asdict(res)
                    row["provenance"] = str(res.provenance)
                    row["tier_strike_pct"] = strike * 100.0
                    results.append(row)
                    done += 1
                    logger.info("[%d/%d] %s strike=%.0f%% %s seed=%d -> mean=%.0f prob_loss=%.3f nonfinite=%d",
                                done, total_configs, hero, strike * 100, model, seed,
                                res.mean_outcome_usd, res.probability_of_loss, res.n_non_finite)

    aggregate = _aggregate(results, paths, total_configs)
    return {"calibration": cal, "campaign": {
        "n_paths_per_config": paths, "n_configs": total_configs,
        "total_simulated_paths": total_configs * paths, "n_cycles": N_CYCLES,
        "cadence_days": CADENCE_DAYS, "drift_assumed": DRIFT, "seeds": list(SEEDS),
        "models": list(MODELS), "strike_tiers": {k: list(v) for k, v in STRIKE_TIERS.items()},
    }, "aggregate": aggregate, "results": results,
        "provenance": "SIMULATED", "note": "Diagnostic only; not decision evidence (MS-26 pending)."}


def _aggregate(results: list[dict[str, Any]], paths: int, total_configs: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        key = f"{r['strategy_kind']}|strike{r['tier_strike_pct']:.0f}|{r['model']}"
        groups.setdefault(key, []).append(r)

    key_metrics = ["mean_outcome_usd", "var_95_usd", "expected_shortfall_975_usd",
                   "mean_max_drawdown_usd", "probability_of_loss"]
    group_summ: dict[str, Any] = {}
    variance_ok = True
    zero_var_groups: list[str] = []
    for key, rows in groups.items():
        stats: dict[str, Any] = {}
        for m in key_metrics:
            vals = [row[m] for row in rows]
            stats[m] = {"mean": sum(vals) / len(vals), "cross_seed_std": pstdev(vals)}
        # A genuine campaign has non-zero cross-seed dispersion of the tail metric.
        if stats["var_95_usd"]["cross_seed_std"] <= 0.0:
            variance_ok = False
            zero_var_groups.append(key)
        group_summ[key] = stats

    total_non_finite = sum(int(r["n_non_finite"]) for r in results)
    reconciles = (len(results) == total_configs) and (total_non_finite == 0)
    return {
        "groups": group_summ,
        "reconciles": reconciles,
        "cross_seed_variance_nonzero": variance_ok,
        "zero_variance_groups": zero_var_groups,
        "total_non_finite": total_non_finite,
        "configs_completed": len(results),
        "configs_expected": total_configs,
    }


def _print_summary(campaign: dict[str, Any]) -> None:
    cal = campaign["calibration"]
    camp = campaign["campaign"]
    agg = campaign["aggregate"]
    print("\n" + "=" * 78)
    print("C8 PHASE 3 - HERO ROLLING-LIFECYCLE MC (DIAGNOSTIC / SIMULATED)")
    print("=" * 78)
    print(f"as of {cal['as_of']}  |  S0={cal['s0']:,.2f}")
    print(f"calibrated vol = {cal['atm_iv']:.4f} ({cal['near_tenor']} ATM IV, {cal['near_dte']:.1f}d)  "
          f"| DVOL={cal['dvol']}  | r={cal['r']:.4f} [{cal['r_source']}]  | drift={camp['drift_assumed']} (ASSUMED)")
    print(f"rolling cadence {camp['cadence_days']:.0f}d x {camp['n_cycles']} cycles  |  "
          f"{camp['n_configs']} configs x {camp['n_paths_per_config']:,} paths = "
          f"{camp['total_simulated_paths']:,} simulated paths")
    print(f"\nGATES:  reconciles={agg['reconciles']}  "
          f"cross_seed_variance_nonzero={agg['cross_seed_variance_nonzero']}  "
          f"total_non_finite={agg['total_non_finite']}")
    print(f"        configs {agg['configs_completed']}/{agg['configs_expected']}")

    print("\nPer-hero metric summary (mean across seeds+strikes+models; SIMULATED):")
    by_hero: dict[str, list[dict[str, Any]]] = {}
    for r in campaign["results"]:
        by_hero.setdefault(r["strategy_kind"], []).append(r)
    for hero, rows in by_hero.items():
        def avg(m: str, rows: list[dict[str, Any]] = rows) -> float:
            return float(sum(row[m] for row in rows) / len(rows))
        cap = rows[0]["capital_base"]
        print(f"\n  [{hero}]  (n={len(rows)} configs)")
        print(f"    prob-of-loss     {avg('probability_of_loss'):.3f}")
        print(f"    VaR95            {avg('var_95_usd'):,.0f} ({100*avg('var_95_usd')/cap:.1f}% cap)")
        print(f"    ES97.5           {avg('expected_shortfall_975_usd'):,.0f} "
              f"({100*avg('expected_shortfall_975_usd')/cap:.1f}% cap)")
        print(f"    EAC/BTC          {avg('mean_eac_usd_per_btc'):,.0f}")
        print(f"    max drawdown     {avg('mean_max_drawdown_usd'):,.0f} "
              f"({avg('mean_max_drawdown_pct_capital'):.1f}% cap)  p95 {avg('p95_max_drawdown_usd'):,.0f}")
        print(f"    ITM freq         {avg('mean_itm_frequency'):.3f}   touch freq {avg('mean_touch_frequency'):.3f}")
        print(f"    leg split: holding(BTC-inherent) {avg('mean_holding_pnl_usd'):,.0f}  "
              f"overlay(advised, pre-fee) {avg('mean_overlay_gross_pnl_usd'):,.0f}  "
              f"fee {rows[0]['structuring_fee_usd']:,.0f}")
    print("=" * 78 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="C8 Phase 3 - hero rolling-lifecycle MC campaign")
    parser.add_argument("--snapshot", type=pathlib.Path, default=None)
    parser.add_argument("--paths", type=int, default=50_000, help="paths per config (default 50,000)")
    parser.add_argument("--out", type=pathlib.Path, default=None)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    snapshot_dir = args.snapshot or promoted_anchor_dir(DEFAULT_OUT_ROOT) or FIXTURES_DIR
    campaign = run_campaign(snapshot_dir, args.paths)

    out = args.out or (snapshot_dir / CAMPAIGN_FILE)
    out.write_text(json.dumps(campaign, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote campaign evidence to %s", out)

    _print_summary(campaign)
    ok = campaign["aggregate"]["reconciles"] and campaign["aggregate"]["cross_seed_variance_nonzero"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
