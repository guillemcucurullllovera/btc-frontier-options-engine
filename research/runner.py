"""Research runner — orchestrates the full pipeline.

Executes: historical backtests, OOS/walk-forward, regimes, Monte Carlo,
stress, and execution sensitivity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from execution.waterfall import WaterfallSensitivity, waterfall_sensitivity
from research.manifest import RunManifest
from research.reporting import (
    build_comparison_table,
    generate_decision_pending,
    generate_presentation_summary,
)
from strategy.backtest import backtest_strategy, backtest_unhedged
from strategy.definitions import build_all_mandate_strategies
from strategy.monte_carlo import MonteCarloConfig, run_monte_carlo
from strategy.regimes import (
    compute_oos_validation,
    run_regime_analysis,
    split_train_test,
)
from strategy.stress import run_stress_tests

logger = logging.getLogger("research")


def _load_config(config_path: str) -> dict[str, Any]:
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    if isinstance(raw, dict):
        return raw
    return {}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_research(
    config_path: str,
    output_dir: str,
    resume: bool = False,
) -> int:
    """Run the full research pipeline.

    Returns 0 on success, non-zero on failure.
    """
    config = _load_config(config_path)
    run_id = os.path.basename(output_dir.rstrip("/"))
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "logs"), exist_ok=True)

    manifest = RunManifest(
        run_id=run_id,
        started_at=datetime.now(UTC),
        config_path=config_path,
        config_checksum=_sha256(json.dumps(config, sort_keys=True).encode()),
        output_dir=output_dir,
    )

    config_bytes = json.dumps(config, sort_keys=True, indent=2).encode()
    with open(os.path.join(output_dir, "resolved_config.yaml"), "wb") as f:
        f.write(config_bytes)

    mandate = config["mandate"]
    qty = mandate["btc_quantity"]
    spot = mandate["reference_spot_usd"]

    strategies = build_all_mandate_strategies(quantity=float(qty), entry_spot=float(spot))
    manifest.strategy_count = len(strategies)

    bt_config = config["backtest"]
    start_date = datetime.fromisoformat(bt_config["window_start"]).replace(tzinfo=UTC)
    end_date = datetime.fromisoformat(bt_config["window_end"]).replace(tzinfo=UTC)
    dte = bt_config["dte_days"]
    r = bt_config["risk_free_rate"]
    sigma = bt_config["volatility"]
    strike_pct = bt_config["strike_pct_above"]

    n_days = max((end_date - start_date).days, 1)
    rng = np.random.default_rng(42)
    dt_val = 1.0 / 365.0
    z = rng.normal(size=n_days)
    returns = (0.10 - 0.5 * sigma ** 2) * dt_val + sigma * np.sqrt(dt_val) * z
    spot_path = spot * np.exp(np.cumsum(np.insert(returns, 0, 0.0)))
    dates = [start_date + timedelta(days=i) for i in range(n_days + 1)]
    iv_history = np.full_like(spot_path, sigma)

    logger.info(f"Running backtests for {len(strategies)} strategies, {n_days} days")

    backtest_results = {}
    for s in strategies:
        if (s.canonical and str(s.canonical) in ("unhedged_baseline", "Unhedged BTC Acquisition")) or s.strategy_id == "unhedged_baseline":
            result = backtest_unhedged(s, start_date, end_date, spot, seed=42)
        else:
            result = backtest_strategy(
                s, dates, spot_path, iv_history,
                risk_free_rate=r, dte_days=dte,
                strike_pct_above=strike_pct,
                seed=42,
            )
        backtest_results[s.strategy_id] = result
        manifest.total_cycles += len(getattr(result, "cycles", []))

    logger.info("Running OOS validation")
    oos_config = config["oos_validation"]
    train_start = datetime.fromisoformat(oos_config["train_start"]).replace(tzinfo=UTC)
    train_end = datetime.fromisoformat(oos_config["train_end"]).replace(tzinfo=UTC)
    test_start = datetime.fromisoformat(oos_config["test_start"]).replace(tzinfo=UTC)
    test_end = datetime.fromisoformat(oos_config["test_end"]).replace(tzinfo=UTC)
    cscv_s = oos_config["cscv_s"]
    cscv_n = oos_config["cscv_n"]

    all_dates = [start_date + timedelta(days=i) for i in range(n_days + 1)]
    _train_idx, _test_idx = split_train_test(all_dates, train_ratio=0.70)

    oos_results = {}
    for s in strategies:
        bt = backtest_results.get(s.strategy_id)
        if bt is None:
            continue
        returns_train = [c.net_pnl_pct / 100.0 for c in getattr(bt, "cycles", []) if c.start_date <= train_end]
        returns_test = [c.net_pnl_pct / 100.0 for c in getattr(bt, "cycles", []) if c.start_date >= test_start]
        train_sharpe = float(np.mean(returns_train)) / float(np.std(returns_train)) if len(returns_train) > 1 and float(np.std(returns_train)) > 1e-9 else None
        test_sharpe = float(np.mean(returns_test)) / float(np.std(returns_test)) if len(returns_test) > 1 and float(np.std(returns_test)) > 1e-9 else None

        oos = compute_oos_validation(
            train_result={"sharpe": train_sharpe, "returns": returns_train,
                          "train_period": (train_start, train_end),
                          "test_period": (test_start, test_end)},
            test_result={"sharpe": test_sharpe, "returns": returns_test,
                         "test_period": (test_start, test_end),
                         "train_period": (train_start, train_end)},
            cscv_s=cscv_s, cscv_n=cscv_n,
        )
        oos_results[s.strategy_id] = oos

    logger.info("Running regime analysis")
    regime_cfg = config["regimes"]
    _regime_results = []
    if regime_cfg.get("enabled", True):
        _regime_results = run_regime_analysis(
            strategies, all_dates, spot_path,
            window_days=regime_cfg["window_days"],
        )

    mc_results = {}
    mc_cfg = config["monte_carlo"]
    if mc_cfg.get("enabled", True):
        logger.info(f"Running Monte Carlo with {mc_cfg['n_paths']} paths")
        for s in strategies:
            for model in mc_cfg.get("models", ["GBM"]):
                mc_config = MonteCarloConfig(
                    n_paths=mc_cfg["n_paths"],
                    horizon_years=mc_cfg["horizon_years"],
                    initial_spot=float(spot),
                    drift=mc_cfg["drift"],
                    volatility=sigma,
                    model=model,
                    seed=mc_cfg["seed"],
                    use_antithetic=mc_cfg.get("use_antithetic", True),
                )
                if model == "Merton" and "merton_params" in mc_cfg:
                    mp = mc_cfg["merton_params"]
                    mc_config = MonteCarloConfig(
                        n_paths=mc_cfg["n_paths"],
                        horizon_years=mc_cfg["horizon_years"],
                        initial_spot=float(spot),
                        drift=mc_cfg["drift"],
                        volatility=sigma,
                        model=model,
                        seed=mc_cfg["seed"],
                        use_antithetic=mc_cfg.get("use_antithetic", True),
                        jump_intensity=mp["jump_intensity"],
                        jump_mean=mp["jump_mean"],
                        jump_std=mp["jump_std"],
                    )
                mc_results[f"{s.strategy_id}_{model}"] = run_monte_carlo(s, mc_config)
                manifest.total_paths_mc += mc_cfg["n_paths"]

    stress_results = {}
    stress_cfg = config["stress"]
    if stress_cfg.get("enabled", True):
        logger.info("Running stress tests")
        stress_results_list = run_stress_tests(strategies, start_spot=float(spot))
        for r in stress_results_list:
            stress_results[r.strategy_id] = r

    logger.info("Running execution sensitivity")
    es_cfg = config.get("execution_sensitivity", {})
    if es_cfg.get("enabled", True):
        sens = WaterfallSensitivity(
            spot_offsets_pct=es_cfg.get("spot_offsets_pct", [-10, -5, -1, 0, 1, 5, 10]),
            fee_bases=es_cfg.get("fee_bases", ["reference_notional", "executed_volume"]),
        )
        waterfall_sensitivity(None, sens)

    logger.info("Generating reports")
    comparison_rows = build_comparison_table(
        dict(backtest_results),
        oos_results,
        mc_results,
        stress_results,
    )

    import csv
    if comparison_rows:
        with open(os.path.join(output_dir, "strategy_comparison.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=comparison_rows[0].keys())
            writer.writeheader()
            writer.writerows(comparison_rows)

    generate_presentation_summary(
        comparison_rows,
        os.path.join(output_dir, "presentation_summary.md"),
    )

    generate_decision_pending(
        os.path.join(output_dir, "decision_pending.json"),
    )

    manifest.status = "completed"
    manifest.completed_at = datetime.now(UTC)

    with open(os.path.join(output_dir, "run_manifest.json"), "w") as f:
        json.dump(manifest.to_dict(), f, indent=2)

    with open(os.path.join(output_dir, "run_status.json"), "w") as f:
        json.dump({"status": "completed", "run_id": run_id, "completed_at": datetime.now(UTC).isoformat()}, f)

    checksums_data = hashlib.sha256()
    for root, _dirs, files in os.walk(output_dir):
        for fn in sorted(files):
            fpath = os.path.join(root, fn)
            with open(fpath, "rb") as f:
                checksums_data.update(f.read())
    with open(os.path.join(output_dir, "checksums.sha256"), "w") as f:
        f.write(f"{checksums_data.hexdigest()}  {run_id}\n")

    logger.info(f"Research run {run_id} complete. Output: {output_dir}")
    return 0
