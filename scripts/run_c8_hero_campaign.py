#!/usr/bin/env python3
"""C8 Phase 3 - rolling-lifecycle archetype MC campaign (DIAGNOSTIC / SIMULATED).

Runs the three mandate archetypes - covered call (premium), Long BTC + short put
(accumulation) and the collar (protection) - plus a coverage-varied partial
overlay, through the rolling-lifecycle MC. Volatility is calibrated to the live
snapshot (near-tenor ATM IV; DVOL reported), r to the observed Deribit rate, and
drift is a LABELLED sensitivity band {-0.10, 0, +0.10} (ASSUMED; neutral 0 is the
no-view anchor - a single drift would implicitly rank the structures, MS-25).

Validates: reconciles (all configs completed), cross-seed variance non-zero per
group, zero non-finite. Freezes a manifest (seeds, config, vol calibration,
results checksum) so the deck numbers are reproducible even though raw paths stay
git-ignored. No ranking/optimality/convergence claim (MS-26 pending).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import pathlib
import subprocess
import sys
from collections.abc import Callable
from statistics import pstdev
from typing import Any, Literal, cast

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.strategy import Strategy
from strategy.definitions import (
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_partial_overlay,
)
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
MANIFEST_FILE: pathlib.Path = REPO_ROOT / "docs" / "reports" / "c8_hero_mc_manifest.json"

BUILDERS: dict[str, Callable[..., Strategy]] = {
    "covered_call": build_covered_call,
    "long_btc_plus_short_put": build_long_btc_plus_short_put,
    "collar": build_collar,
    "partial_overlay": build_partial_overlay,
}
ARCHETYPE_ROLE = {
    "covered_call": "premium", "long_btc_plus_short_put": "accumulation",
    "collar": "protection", "partial_overlay": "coverage-varied premium",
}
STRIKE_TIERS: dict[str, tuple[float, ...]] = {
    "covered_call": (0.05, 0.10, 0.15),
    "long_btc_plus_short_put": (0.03, 0.05, 0.10),
    "collar": (0.05, 0.10, 0.15),
    "partial_overlay": (0.05, 0.10, 0.15),
}
MODELS: tuple[str, ...] = ("GBM", "Merton")
SEEDS: tuple[int, ...] = (101, 102, 103, 104, 105)
DRIFTS: tuple[float, ...] = (-0.10, 0.0, 0.10)  # LABELLED sensitivity band (ASSUMED)
N_CYCLES: int = 12
CADENCE_DAYS: float = 29.0

BAND_METRICS = [
    "total_pnl_mean_usd", "total_pnl_median_usd", "total_pnl_p5_usd", "total_pnl_p95_usd",
    "probability_of_loss", "var_95_usd", "expected_shortfall_975_usd",
    "mean_rolling_programme_eac_usd_per_btc", "mean_max_drawdown_usd",
    "mean_itm_frequency", "mean_touch_frequency",
    "mean_holding_pnl_usd", "mean_overlay_gross_pnl_usd",
]


def _git_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                           cwd=str(REPO_ROOT), check=False)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _calibrate(snapshot_dir: pathlib.Path) -> dict[str, Any]:
    snap = load_snapshot(snapshot_dir)
    s0 = snap.spot.price
    r, r_source = 0.0, "assumed (config 4%)"
    sel = select_expiries(snap.instruments, snap.book_summaries, reference=snap.meta.created_at)
    near = min(sel.distinct, key=lambda e: e.days_to_expiry)
    atm_iv = atm_iv_for_expiry(near.expiry.isoformat(), s0, snap.instruments, snap.book_summaries)
    for b in snap.book_summaries:
        if near.label in b.instrument_name:
            r, r_source = b.interest_rate, "observed (deribit interest_rate)"
            break
    return {
        "s0": s0, "r": r, "r_source": r_source, "near_tenor": near.label,
        "near_dte": near.days_to_expiry, "atm_iv": atm_iv, "dvol": snap.meta.dvol_latest,
        "as_of": snap.meta.created_at.isoformat(), "snapshot_dir": str(snapshot_dir),
        "checksums": snap.meta.checksums,
    }


def _config(strike: float, model: str, seed: int, drift: float, cal: dict[str, Any], paths: int) -> MultiCycleMCConfig:
    return MultiCycleMCConfig(
        n_paths=paths, n_cycles=N_CYCLES, cycle_length_years=CADENCE_DAYS / 365.0,
        n_steps_per_cycle=int(CADENCE_DAYS), initial_spot=cal["s0"], volatility=cal["atm_iv"],
        risk_free_rate=cal["r"], drift=drift, model=cast(Literal["GBM", "Merton"], model),
        seed=seed, strike_target_pct=strike, d12_interpretation="cash_settled",
        capital_base=cal["s0"] * 30_000.0, store_paths=False,
    )


def run_campaign(snapshot_dir: pathlib.Path, paths: int) -> dict[str, Any]:
    cal = _calibrate(snapshot_dir)
    vol_source = f"calibrated: {cal['near_tenor']} ATM IV (snapshot, {cal['atm_iv']:.4f})"
    logger.info("Calibrated vol=%.4f (%s ATM IV); DVOL=%s; S0=%.2f; r=%.4f",
                cal["atm_iv"], cal["near_tenor"], cal["dvol"], cal["s0"], cal["r"])

    results: list[dict[str, Any]] = []
    total = sum(len(STRIKE_TIERS[k]) for k in BUILDERS) * len(MODELS) * len(SEEDS) * len(DRIFTS)
    done = 0
    for kind, builder in BUILDERS.items():
        strat = builder()
        for strike in STRIKE_TIERS[kind]:
            for model in MODELS:
                for drift in DRIFTS:
                    for seed in SEEDS:
                        cfg = _config(strike, model, seed, drift, cal, paths)
                        res: HeroMCResult = run_hero_lifecycle_mc(
                            strat, cfg, volatility_source=vol_source, risk_free_source=cal["r_source"],
                        )
                        row = dataclasses.asdict(res)
                        row["provenance"] = str(res.provenance)
                        row["tier_strike_pct"] = strike * 100.0
                        row["drift"] = drift
                        results.append(row)
                        done += 1
            logger.info("[%d/%d] %s done", done, total, kind)

    aggregate = _aggregate(results, total)
    drift_band = _drift_band(results)
    campaign = {
        "calibration": cal,
        "campaign": {
            "n_paths_per_config": paths, "n_configs": total, "total_simulated_paths": total * paths,
            "n_cycles": N_CYCLES, "cadence_days": CADENCE_DAYS, "drift_band": list(DRIFTS),
            "seeds": list(SEEDS), "models": list(MODELS),
            "strike_tiers": {k: list(v) for k, v in STRIKE_TIERS.items()},
            "archetype_roles": ARCHETYPE_ROLE,
        },
        "aggregate": aggregate, "drift_band": drift_band, "results": results,
        "provenance": "SIMULATED",
        "note": "Diagnostic only; not decision evidence (MS-26 pending). Drift is an ASSUMED band, "
                "neutral 0 is the no-view anchor; no single drift is presented.",
    }
    return campaign


def _aggregate(results: list[dict[str, Any]], total: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        key = f"{r['strategy_kind']}|k{r['tier_strike_pct']:.0f}|{r['model']}|d{r['drift']:+.2f}"
        groups.setdefault(key, []).append(r)
    variance_ok = True
    zero_var: list[str] = []
    for key, rows in groups.items():
        if pstdev([row["var_95_usd"] for row in rows]) <= 0.0:
            variance_ok = False
            zero_var.append(key)
    total_non_finite = sum(int(r["n_non_finite"]) for r in results)
    return {
        "reconciles": (len(results) == total) and (total_non_finite == 0),
        "cross_seed_variance_nonzero": variance_ok, "zero_variance_groups": zero_var,
        "total_non_finite": total_non_finite,
        "configs_completed": len(results), "configs_expected": total,
    }


def _drift_band(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Per (archetype, drift): mean of each band metric across strikes/models/seeds."""
    band: dict[str, dict[str, dict[str, float]]] = {}
    for r in results:
        kind, drift = r["strategy_kind"], r["drift"]
        band.setdefault(kind, {}).setdefault(f"{drift:+.2f}", {})
    for kind, drifts in band.items():
        for dkey in drifts:
            rows = [r for r in results if r["strategy_kind"] == kind and f"{r['drift']:+.2f}" == dkey]
            drifts[dkey] = {m: sum(r[m] for r in rows) / len(rows) for m in BAND_METRICS}
            drifts[dkey]["capital_base"] = rows[0]["capital_base"]
            drifts[dkey]["n_configs"] = float(len(rows))
    return band


def _write_manifest(campaign: dict[str, Any]) -> str:
    """Freeze a small committed manifest: config + vol calibration + results checksum."""
    checksum = hashlib.sha256(
        json.dumps(campaign["drift_band"], sort_keys=True, default=str).encode()
    ).hexdigest()
    cal = campaign["calibration"]
    manifest = {
        "provenance": "SIMULATED",
        "as_of_utc": cal["as_of"],
        "git_sha": _git_sha(),
        "snapshot_dir": cal["snapshot_dir"],
        "snapshot_checksums": cal["checksums"],
        "vol_calibration": {
            "volatility": cal["atm_iv"], "source": f"{cal['near_tenor']} ATM IV",
            "dvol": cal["dvol"], "r": cal["r"], "r_source": cal["r_source"], "s0": cal["s0"],
        },
        "campaign": campaign["campaign"],
        "drift_band_sha256": checksum,
        "note": "Deck numbers reproduce from (snapshot, seeds, config); raw paths git-ignored.",
    }
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return checksum


def _print_summary(campaign: dict[str, Any], checksum: str) -> None:
    cal, camp, agg = campaign["calibration"], campaign["campaign"], campaign["aggregate"]
    print("\n" + "=" * 92)
    print("C8 PHASE 3 - ARCHETYPE ROLLING-LIFECYCLE MC (DIAGNOSTIC / SIMULATED)")
    print("=" * 92)
    print(f"as of {cal['as_of']}  |  S0={cal['s0']:,.2f}")
    print(f"calibrated vol={cal['atm_iv']:.4f} ({cal['near_tenor']} ATM IV, {cal['near_dte']:.1f}d) | "
          f"DVOL={cal['dvol']} | r={cal['r']:.4f} [{cal['r_source']}] | drift band {camp['drift_band']} (ASSUMED)")
    print(f"{camp['n_configs']} configs x {camp['n_paths_per_config']:,} paths = "
          f"{camp['total_simulated_paths']:,} simulated paths  |  cadence {camp['cadence_days']:.0f}d x {camp['n_cycles']}")
    print(f"GATES: reconciles={agg['reconciles']}  cross_seed_variance_nonzero={agg['cross_seed_variance_nonzero']}  "
          f"non_finite={agg['total_non_finite']}  configs={agg['configs_completed']}/{agg['configs_expected']}")
    print(f"drift_band_sha256={checksum[:32]}...")

    band = campaign["drift_band"]
    for kind in BUILDERS:
        if kind not in band:
            continue
        cap = next(iter(band[kind].values()))["capital_base"]
        print(f"\n[{kind}]  role={ARCHETYPE_ROLE[kind]}  (SIMULATED; capital {cap:,.0f})")
        print(f"  {'drift':>6} {'P&L mean':>14} {'P&L p5':>14} {'P&L p95':>14} "
              f"{'prob_loss':>9} {'VaR95%cap':>10} {'ES97.5%cap':>11} {'maxDD%cap':>10} {'ITM':>5} {'touch':>6}")
        for dkey in sorted(band[kind], key=float):
            b = band[kind][dkey]
            print(f"  {dkey:>6} {b['total_pnl_mean_usd']:>14,.0f} {b['total_pnl_p5_usd']:>14,.0f} "
                  f"{b['total_pnl_p95_usd']:>14,.0f} {b['probability_of_loss']:>9.3f} "
                  f"{100*b['var_95_usd']/cap:>10.1f} {100*b['expected_shortfall_975_usd']/cap:>11.1f} "
                  f"{100*b['mean_max_drawdown_usd']/cap:>10.1f} {b['mean_itm_frequency']:>5.2f} {b['mean_touch_frequency']:>6.2f}")
        d0 = band[kind].get("+0.00")
        if d0:
            print(f"  @drift 0 (no-view): holding(BTC-inherent) {d0['mean_holding_pnl_usd']:,.0f}  "
                  f"overlay(advised,pre-fee) {d0['mean_overlay_gross_pnl_usd']:,.0f}")
    print("=" * 92 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="C8 Phase 3 - archetype rolling-lifecycle MC campaign")
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
    checksum = _write_manifest(campaign)
    logger.info("Wrote campaign evidence to %s and manifest to %s", out, MANIFEST_FILE)

    _print_summary(campaign, checksum)
    agg = campaign["aggregate"]
    return 0 if (agg["reconciles"] and agg["cross_seed_variance_nonzero"]) else 1


if __name__ == "__main__":
    sys.exit(main())
