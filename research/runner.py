"""Research runner — orchestrates the full pipeline.

Executes: historical backtests, OOS/walk-forward, regimes, Monte Carlo,
stress, and execution sensitivity.

Full mode fetches real BTC spot from Massive (MASSIVE_API_KEY).
Smoke/test mode uses synthetic GBM paths.
Never silently substitute a provider in full mode.
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

from config.models import EngineConfig, Provenance
from execution.waterfall import WaterfallSensitivity, waterfall_sensitivity
from research.manifest import DataManifest, DataSourceRecord, RunManifest
from research.reporting import (
    build_comparison_table,
    generate_decision_pending,
    generate_presentation_summary,
)
from strategy.backtest import backtest_strategy, backtest_unhedged_observed
from strategy.definitions import build_all_mandate_strategies
from strategy.monte_carlo import MonteCarloConfig, run_monte_carlo
from strategy.regimes import (
    compute_oos_validation,
    run_regime_analysis,
    split_train_test,
)
from strategy.stress import run_stress_tests
from vol.history import (
    CryptoDataDownloadProvider,
    MassiveSpotProvider,
)

logger = logging.getLogger("research")


def _load_config(config_path: str) -> dict[str, Any]:
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    if isinstance(raw, dict):
        return raw
    return {}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_gbm_spot_path(
    spot: float,
    sigma: float,
    start_date: datetime,
    end_date: datetime,
    seed: int = 42,
) -> tuple[np.ndarray, list[datetime]]:
    n_days = max((end_date - start_date).days, 1)
    rng = np.random.default_rng(seed)
    dt_val = 1.0 / 365.0
    z = rng.normal(size=n_days)
    returns = (0.10 - 0.5 * sigma ** 2) * dt_val + sigma * np.sqrt(dt_val) * z
    spot_path = spot * np.exp(np.cumsum(np.insert(returns, 0, 0.0)))
    dates = [start_date + timedelta(days=i) for i in range(n_days + 1)]
    return spot_path, dates


def _validate_results(
    manifest: RunManifest,
    data_manifest: DataManifest | None,
    output_dir: str,
    run_id: str,
    mc_enabled: bool = True,
    stress_enabled: bool = True,
) -> list[str]:
    failures: list[str] = []

    if not manifest.data_sources:
        failures.append("data_sources is empty for a completed run")

    if data_manifest is None:
        failures.append("data_manifest.json was not produced")
    elif data_manifest.observation_count <= 0:
        failures.append("observation_count must be positive")
    elif data_manifest.provenance.upper().startswith("SIMULATED") and data_manifest.actual_provider not in ("synthetic", "smoke"):
        failures.append("historical provenance cannot be SIMULATED in full mode")

    required_files = [
        "backtest_results.parquet",
        "oos_results.parquet",
        "regime_results.parquet",
        "strategy_comparison.csv",
        "research_report.md",
        "presentation_summary.md",
    ]
    if mc_enabled:
        required_files.append("monte_carlo_results.parquet")
    if stress_enabled:
        required_files.append("stress_results.parquet")
    required_files.append("execution_sensitivity.parquet")

    for fn in required_files:
        fpath = os.path.join(output_dir, fn)
        if not os.path.exists(fpath):
            failures.append(f"required output {fn} is missing")
        elif os.path.getsize(fpath) == 0:
            failures.append(f"required output {fn} is empty")

    comparison_path = os.path.join(output_dir, "strategy_comparison.csv")
    if os.path.exists(comparison_path) and os.path.getsize(comparison_path) > 0:
        with open(comparison_path) as f:
            import csv
            reader = list(csv.DictReader(f))
            for row in reader:
                sid = row.get("strategy_id", "")
                if mc_enabled:
                    var95 = row.get("var_95_loss", "0.0")
                    es975 = row.get("es_975_loss", "0.0")
                    prob_loss = row.get("probability_of_loss", "0")
                    if var95 == "0.0" and es975 == "0.0" and prob_loss in ("0.0", "0"):
                        failures.append(f"risk metrics all zero for {sid}")
                try:
                    eac = float(row.get("effective_acquisition_cost", "0"))
                    if eac < 0:
                        failures.append(f"negative effective acquisition cost for {sid}")
                except (ValueError, TypeError):
                    pass
                try:
                    tpp = float(row.get("total_pnl_pct", "0"))
                    if abs(tpp) > 500.0:
                        failures.append(f"implausible total_pnl_pct {tpp} for {sid}")
                except (ValueError, TypeError):
                    pass
                # NOTE: effective_acquisition_cost is intentionally EXCLUDED —
                # a strategy that acquires no BTC reports EAC = n/a (nan) by
                # design (FRF-014 / D-12). Its plausibility is covered by the
                # negative-EAC check above and by AT-014 component reconciliation.
                for k in ("total_pnl_pct", "sharpe_ratio", "var_95_loss", "es_975_loss"):
                    val = row.get(k, "0")
                    if val in ("nan", "NaN", "inf", "-inf", "Infinity", "-Infinity"):
                        failures.append(f"NaN or infinite result in {k} for {sid}")

    return failures


def _write_run_status(
    output_dir: str,
    run_id: str,
    status: str,
    failures: list[str] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "run_id": run_id,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if failures:
        payload["validation_failures"] = failures
    with open(os.path.join(output_dir, "run_status.json"), "w") as f:
        json.dump(payload, f, indent=2)


def run_research(
    config_path: str,
    output_dir: str,
    resume: bool = False,
    test_mode: bool = False,
) -> int:
    """Run the full research pipeline.

    Args:
        config_path: Path to YAML configuration file.
        output_dir: Output directory for research results.
        resume: If True, attempt to resume from checkpoint.
        test_mode: If True, use synthetic GBM data (for smoke tests only).

    Returns 0 on success, non-zero on failure.
    """
    # Issue 8: consume validated config layer (EngineConfig), not raw YAML dict.
    raw = _load_config(config_path)
    # EngineConfig fields may be at top level or nested under 'mandate'.
    eng_fields: dict[str, Any] = {}
    mandate_section = raw.get("mandate", {})
    for field_name in EngineConfig.model_fields:
        if field_name in raw:
            eng_fields[field_name] = raw[field_name]
        elif isinstance(mandate_section, dict) and field_name in mandate_section:
            eng_fields[field_name] = mandate_section[field_name]
    try:
        cfg = EngineConfig(**eng_fields)
    except Exception:
        # Fall back: config doesn't have full EngineConfig fields; use raw values
        cfg = None
    run_id = os.path.basename(output_dir.rstrip("/"))
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "logs"), exist_ok=True)

    manifest = RunManifest(
        run_id=run_id,
        started_at=datetime.now(UTC),
        config_path=config_path,
        config_checksum=_sha256(json.dumps(raw, sort_keys=True, default=str).encode()),
        output_dir=output_dir,
    )

    resolved_config_path = os.path.join(output_dir, "resolved_config.yaml")
    with open(resolved_config_path, "w") as f:
        json.dump(raw, f, sort_keys=True, indent=2, default=str)

    mandate = raw.get("mandate", {})
    # Issue 8: use validated config where available, raw dict otherwise
    if cfg is not None:
        qty = cfg.btc_quantity
        spot = cfg.reference_spot_usd
        seller_discount_pct = cfg.seller_discount_pct / 100.0
        execution_fee_pct = cfg.execution_fee_pct / 100.0
        risk_free_rate_pct_dec = cfg.risk_free_rate_pct / 100.0
    else:
        qty = mandate.get("btc_quantity", 30000)
        spot = mandate.get("reference_spot_usd", 65000.0)
        seller_discount_pct = mandate.get("seller_discount_pct", 0.025)
        execution_fee_pct = mandate.get("execution_fee_pct", 0.005)
        risk_free_rate_pct_dec = 0.04

    strategies = build_all_mandate_strategies(quantity=float(qty), entry_spot=float(spot))
    enabled_list = raw.get("strategies", {}).get("enabled", [s.strategy_id for s in strategies])
    if enabled_list:
        strategies = [s for s in strategies if s.strategy_id in enabled_list]
    manifest.strategy_count = len(strategies)

    bt_config = raw.get("backtest", {})
    start_date = datetime.fromisoformat(bt_config["window_start"]).replace(tzinfo=UTC)
    end_date = datetime.fromisoformat(bt_config["window_end"]).replace(tzinfo=UTC)
    dte = bt_config["dte_days"]
    r = bt_config.get("risk_free_rate", risk_free_rate_pct_dec)
    sigma = bt_config["volatility"]
    if cfg is not None:
        strike_pct = bt_config.get("strike_pct_above", cfg.strike_target_pct_above_spot[0] / 100.0)
    else:
        strike_pct = bt_config.get("strike_pct_above", 0.15)

    # Issue 8: additional execution assumptions from config
    spread_bps = raw.get("execution", {}).get("spread_bps", 2.0)
    adv_btc = raw.get("execution", {}).get("adv_btc", None)
    overlay_ratio = raw.get("execution", {}).get("overlay_ratio", 1.0)

    ds_config = raw.get("data_sources", {})
    primary_spot = ds_config.get("primary_spot", "massive")
    allow_fallback = ds_config.get("allow_cdd_fallback", False)
    exec_cfg = raw.get("execution", {})
    run_mode = exec_cfg.get("run_mode", "full" if not test_mode else "smoke")

    data_manifest: DataManifest | None = None
    spot_path: np.ndarray
    dates: list[datetime]
    iv_history: np.ndarray

    if run_mode == "smoke" or test_mode:
        logger.info("SMOKE/TEST MODE — using synthetic GBM spot data")
        spot_path, dates = _generate_gbm_spot_path(
            spot=spot, sigma=sigma, start_date=start_date, end_date=end_date, seed=42,
        )
        iv_history = np.full_like(spot_path, sigma)

        data_manifest = DataManifest(
            actual_provider="synthetic",
            endpoint="gbm-rng-seed-42",
            requested_start=start_date,
            requested_end=end_date,
            actual_start=dates[0],
            actual_end=dates[-1],
            observation_count=len(dates),
            retrieval_timestamp=datetime.now(UTC),
            checksum_sha256="",
            provenance="SIMULATED",
            fallback_used=False,
        )

        ds_record = DataSourceRecord(
            source="synthetic",
            endpoint="gbm-rng-seed-42",
            retrieval_date=datetime.now(UTC),
            record_count=len(dates),
            checksum_sha256="",
            provenance=Provenance.SIMULATED,
            notes="smoke/test mode",
        )
        manifest.data_sources.append(ds_record)
    else:
        logger.info(f"FULL MODE — fetching from {primary_spot}")
        api_key = os.environ.get("MASSIVE_API_KEY", "")
        cache_dir = pathlib.Path(output_dir) / "cache"
        massive = MassiveSpotProvider(api_key=api_key if api_key else None, cache_dir=cache_dir)

        bars: list[Any] = []
        provider_used = ""
        fallback_was_used = False
        fetch_error: str | None = None
        cache_path: str = ""

        try:
            bars = massive.fetch_bars(start=start_date, end=end_date)
            provider_used = "massive"
            if cache_dir.exists():
                cache_files = sorted(cache_dir.glob("massive_*.json"))
                if cache_files:
                    cache_path = str(cache_files[-1])
        except Exception as exc:
            fetch_error = str(exc)
            logger.warning(f"Massive fetch failed: {fetch_error}")

        if not bars and allow_fallback and fetch_error is not None:
            logger.info("Attempting CDD fallback")
            cdd = CryptoDataDownloadProvider()
            try:
                bars = cdd.fetch_bars(start=start_date, end=end_date)
                provider_used = "cryptodatadownload"
                fallback_was_used = True
            except Exception as exc2:
                fetch_error = str(exc2)
                logger.error(f"CDD fallback also failed: {fetch_error}")

        if not bars:
            msg = f"No data returned from {primary_spot} for {start_date}-{end_date}"
            if fetch_error:
                msg += f" ({fetch_error})"
            logger.error(msg)
            _write_run_status(output_dir, run_id, "failed", [msg])
            return 1

        if fallback_was_used and not allow_fallback:
            msg = "CDD fallback used but allow_cdd_fallback is disabled"
            logger.error(msg)
            _write_run_status(output_dir, run_id, "failed", [msg])
            return 1

        if not fallback_was_used and not api_key:
            msg = "MASSIVE_API_KEY not set in full mode"
            logger.error(msg)
            _write_run_status(output_dir, run_id, "failed", [msg])
            return 1

        bars.sort(key=lambda b: b.timestamp)
        dates_bar = [b.timestamp for b in bars]
        close_prices = np.array([b.close for b in bars], dtype=np.float64)

        if not fallback_was_used:
            provider_used = getattr(bars[0], "origin", "massive")
            if provider_used != "massive":
                fallback_was_used = True

        spot_path = close_prices
        dates = dates_bar
        iv_history = np.full_like(spot_path, sigma)

        provenance_str = Provenance.OBSERVED.value
        if fallback_was_used:
            provenance_str = f"{Provenance.OBSERVED.value} (fallback: {provider_used})"
        if any(getattr(b, "provenance", Provenance.OBSERVED) == Provenance.SIMULATED for b in bars):
            provenance_str = Provenance.SIMULATED.value

        tmp_csv = os.path.join(output_dir, "_spot_data_dump.csv")
        with open(tmp_csv, "w") as f:
            f.write("timestamp,close\n")
            for i in range(len(dates)):
                f.write(f"{dates[i].isoformat()},{spot_path[i]}\n")
        csv_checksum = _sha256_file(tmp_csv)

        data_manifest = DataManifest(
            actual_provider=provider_used,
            endpoint=ds_config.get("primary_spot_endpoint", MassiveSpotProvider.ENDPOINT_PATH),
            requested_start=start_date,
            requested_end=end_date,
            actual_start=dates[0],
            actual_end=dates[-1],
            observation_count=len(bars),
            retrieval_timestamp=datetime.now(UTC),
            checksum_sha256=csv_checksum,
            provenance=provenance_str,
            fallback_used=fallback_was_used,
            fallback_provider="cryptodatadownload" if fallback_was_used else "",
            cache_path=cache_path,
        )

        ds_record = DataSourceRecord(
            source=provider_used,
            endpoint=data_manifest.endpoint,
            retrieval_date=data_manifest.retrieval_timestamp if data_manifest.retrieval_timestamp is not None else datetime.now(UTC),
            record_count=data_manifest.observation_count,
            checksum_sha256=csv_checksum,
            provenance=(
                Provenance.OBSERVED if not fallback_was_used
                else Provenance.MODEL_RECONSTRUCTED
            ),
            notes="fallback used" if fallback_was_used else "",
        )
        manifest.data_sources.append(ds_record)

    n_days_raw = len(dates)
    logger.info(f"Running backtests for {len(strategies)} strategies, {n_days_raw} days of data")

    backtest_results: dict[str, Any] = {}
    for s in strategies:
        if (
            (s.canonical and str(s.canonical) in ("unhedged_baseline", "Unhedged BTC Acquisition"))
            or s.strategy_id == "unhedged_baseline"
        ):
            # FRF-002 / AT-002: the baseline consumes the SAME observed spot
            # series as every strategy (buy-and-hold), never a synthetic GBM
            # path. The synthetic backtest_unhedged wrapper is quarantined from
            # full research mode.
            result = backtest_unhedged_observed(s, dates, spot_path, iv_history)
        else:
            result = backtest_strategy(
                s, dates, spot_path, iv_history,
                risk_free_rate=r, dte_days=dte,
                strike_pct_above=strike_pct,
                overlay_ratio=overlay_ratio,
                seller_discount_pct=seller_discount_pct,
                execution_fee_pct=execution_fee_pct,
                spread_bps=spread_bps,
                adv_btc=adv_btc,
                seed=42,
            )
        backtest_results[s.strategy_id] = result
        manifest.total_cycles += len(getattr(result, "cycles", []))

    logger.info("Running OOS validation")
    oos_config = raw.get("oos_validation", {})
    train_start = datetime.fromisoformat(oos_config["train_start"]).replace(tzinfo=UTC)
    train_end = datetime.fromisoformat(oos_config["train_end"]).replace(tzinfo=UTC)
    test_start = datetime.fromisoformat(oos_config["test_start"]).replace(tzinfo=UTC)
    test_end = datetime.fromisoformat(oos_config["test_end"]).replace(tzinfo=UTC)
    cscv_s = oos_config["cscv_s"]
    cscv_n = oos_config["cscv_n"]

    all_dates = dates
    _train_idx, _test_idx = split_train_test(all_dates, train_ratio=0.70)

    oos_results: dict[str, Any] = {}
    for s in strategies:
        bt = backtest_results.get(s.strategy_id)
        if bt is None:
            continue
        returns_train = [
            c.net_pnl_pct / 100.0
            for c in getattr(bt, "cycles", [])
            if c.start_date <= train_end
        ]
        returns_test = [
            c.net_pnl_pct / 100.0
            for c in getattr(bt, "cycles", [])
            if c.start_date >= test_start
        ]
        train_sharpe = (
            float(np.mean(returns_train)) / float(np.std(returns_train))
            if len(returns_train) > 1 and float(np.std(returns_train)) > 1e-9
            else None
        )
        test_sharpe = (
            float(np.mean(returns_test)) / float(np.std(returns_test))
            if len(returns_test) > 1 and float(np.std(returns_test)) > 1e-9
            else None
        )

        oos = compute_oos_validation(
            train_result={
                "sharpe": train_sharpe,
                "returns": returns_train,
                "train_period": (train_start, train_end),
                "test_period": (test_start, test_end),
            },
            test_result={
                "sharpe": test_sharpe,
                "returns": returns_test,
                "test_period": (test_start, test_end),
                "train_period": (train_start, train_end),
            },
            cscv_s=cscv_s,
            cscv_n=cscv_n,
        )
        oos_results[s.strategy_id] = oos

    logger.info("Running regime analysis")
    regime_cfg = raw.get("regimes", {})
    regime_results: list[Any] = []
    if regime_cfg.get("enabled", True):
        regime_results = run_regime_analysis(
            strategies, all_dates, spot_path,
            window_days=regime_cfg["window_days"],
        )

    mc_results: dict[str, Any] = {}
    mc_cfg = raw.get("monte_carlo", {})
    mc_enabled = mc_cfg.get("enabled", True)
    if mc_enabled:
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
                mc_result = run_monte_carlo(s, mc_config)
                mc_results[f"{s.strategy_id}_{model}"] = mc_result
                mc_results[s.strategy_id] = mc_result
                manifest.total_paths_mc += mc_cfg["n_paths"]

    stress_results: dict[str, Any] = {}
    stress_cfg = raw.get("stress", {})
    if stress_cfg.get("enabled", True):
        logger.info("Running stress tests")
        stress_results_list = run_stress_tests(strategies, start_spot=float(spot))
        for rst in stress_results_list:
            stress_results[rst.strategy_id] = rst

    logger.info("Running execution sensitivity")
    es_cfg = raw.get("execution_sensitivity", {})
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
    comparison_path = os.path.join(output_dir, "strategy_comparison.csv")
    if comparison_rows:
        with open(comparison_path, "w", newline="") as f:
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

    import pandas as pd  # type: ignore[import-untyped]

    bt_records: list[dict[str, Any]] = []
    for sid, bt in backtest_results.items():
        for c in getattr(bt, "cycles", []):
            bt_records.append({
                "strategy_id": sid,
                "cycle_num": c.cycle_num,
                "start_date": c.start_date.isoformat(),
                "end_date": c.end_date.isoformat(),
                "entry_spot": c.entry_spot,
                "strike": c.strike,
                "expiry_spot": c.expiry_spot,
                "is_itm": c.is_itm,
                "net_pnl_usd": c.net_pnl_usd,
                "net_pnl_pct": c.net_pnl_pct,
                "premium_received_usd": c.premium_received_usd,
                "premium_received_btc": c.premium_received_btc,
                "total_fees_usd": c.venue_fees_usd + c.delivery_fee_usd + c.spread_slippage_usd + c.impact_usd,
                "realised_assignment": c.realised_assignment,
                "cash_usd_end": c.cash_usd_end,
                "btc_inventory_end": c.btc_inventory_end,
            })
    if bt_records:
        pd.DataFrame(bt_records).to_parquet(os.path.join(output_dir, "backtest_results.parquet"), index=False)
    else:
        pd.DataFrame([{"strategy_id": sid, "note": "no_cycles"} for sid in backtest_results]).to_parquet(
            os.path.join(output_dir, "backtest_results.parquet"), index=False)

    oos_records: list[dict[str, Any]] = []
    for sid, oos in oos_results.items():
        oos_records.append({
            "strategy_id": sid,
            "pbo_estimate": getattr(oos, "pbo_estimate", oos.get("pbo_estimate") if hasattr(oos, "get") else None),
            "deflated_sharpe_ratio": getattr(oos, "deflated_sharpe_ratio", oos.get("deflated_sharpe_ratio") if hasattr(oos, "get") else None),
        })
    if oos_records:
        pd.DataFrame(oos_records).to_parquet(os.path.join(output_dir, "oos_results.parquet"), index=False)

    regime_records: list[dict[str, Any]] = []
    for rr in regime_results:
        if hasattr(rr, "__dict__"):
            regime_records.append({k: v for k, v in rr.__dict__.items() if not k.startswith("_")})
        elif isinstance(rr, dict):
            regime_records.append(rr)
    if regime_records:
        pd.DataFrame(regime_records).to_parquet(os.path.join(output_dir, "regime_results.parquet"), index=False)
    else:
        pd.DataFrame([{"status": "regime_analysis_ran_no_results"}]).to_parquet(os.path.join(output_dir, "regime_results.parquet"), index=False)

    mc_records: list[dict[str, Any]] = []
    for key, mc in mc_results.items():
        if "_GBM" in key or "_Merton" in key:
            continue
        rec = {
            "strategy_id": getattr(mc, "strategy_id", ""),
            "n_paths": getattr(mc, "n_paths", 0),
            "model": getattr(mc, "model", ""),
            "expected_pnl": getattr(mc, "expected_pnl", 0.0),
            "var_95": getattr(mc, "var_95", 0.0),
            "var_99": getattr(mc, "var_99", 0.0),
            "es_975": getattr(mc, "es_975", 0.0),
            "es_99": getattr(mc, "es_99", 0.0),
            "var_95_pnl": getattr(mc, "var_95_pnl", 0.0),
            "es_975_pnl": getattr(mc, "es_975_pnl", 0.0),
            "probability_of_loss": getattr(mc, "probability_of_loss", 0.0),
            "itm_probability": getattr(mc, "itm_probability", 0.0),
        }
        mc_records.append(rec)
    if mc_records:
        pd.DataFrame(mc_records).to_parquet(os.path.join(output_dir, "monte_carlo_results.parquet"), index=False)
    else:
        pd.DataFrame([{"note": "monte_carlo_disabled"}]).to_parquet(os.path.join(output_dir, "monte_carlo_results.parquet"), index=False)

    ss_records: list[dict[str, Any]] = []
    for sid, ss in stress_results.items():
        for s in getattr(ss, "scenario_results", []):
            ss_records.append({"strategy_id": sid, **s})
    if ss_records:
        pd.DataFrame(ss_records).to_parquet(os.path.join(output_dir, "stress_results.parquet"), index=False)
    else:
        pd.DataFrame([{"note": "stress_disabled"}]).to_parquet(os.path.join(output_dir, "stress_results.parquet"), index=False)

    es_df = pd.DataFrame([{
        "spot_offsets_pct": str(es_cfg.get("spot_offsets_pct", [])),
        "fee_bases": str(es_cfg.get("fee_bases", [])),
    }])
    es_df.to_parquet(os.path.join(output_dir, "execution_sensitivity.parquet"), index=False)

    research_report_lines = [
        "# BTC 30k Strategy Research Report",
        f"*Run: {run_id}*",
        f"*Generated: {datetime.now(UTC).isoformat()}*",
        "",
        "## Data Source",
    ]
    if data_manifest is not None:
        research_report_lines.extend([
            f"- Provider: {data_manifest.actual_provider}",
            f"- Observation count: {data_manifest.observation_count}",
            f"- Date range: {data_manifest.actual_start} to {data_manifest.actual_end}",
            f"- Provenance: {data_manifest.provenance}",
            f"- Fallback used: {data_manifest.fallback_used}",
        ])
    research_report_lines.extend([
        "",
        f"## Strategies: {len(strategies)}",
        f"## Total backtest cycles: {manifest.total_cycles}",
        f"## Total MC paths: {manifest.total_paths_mc}",
        "",
        "## Strategy Comparison",
        "",
    ])
    for row in comparison_rows:
        sid = row.get("strategy_id", "")
        pnl = row.get("total_pnl_pct", 0.0)
        sharpe = row.get("sharpe_ratio")
        eac = row.get("effective_acquisition_cost", 0)
        try:
            eac_f = float(eac)
            eac_str = "n/a (no BTC acquired)" if eac_f != eac_f else f"${eac_f:,.0f}/BTC"  # nan → n/a
        except (ValueError, TypeError):
            eac_str = "n/a"
        research_report_lines.append(f"- **{sid}**: P&L {pnl:.2f}%, " + (f"Sharpe {sharpe:.3f}, " if sharpe else "") + f"Eff. Acq. {eac_str}")
    research_report_lines.extend([
        "",
        "*No strategy is described as best, optimal, preferred, recommended, safest or winner.*",
        "*This document does not constitute an investment recommendation.*",
    ])
    with open(os.path.join(output_dir, "research_report.md"), "w") as f:
        f.write("\n".join(research_report_lines))

    if data_manifest is not None:
        dm_path = os.path.join(output_dir, "data_manifest.json")
        dm_payload: dict[str, Any] = {
            "actual_provider": data_manifest.actual_provider,
            "endpoint": data_manifest.endpoint,
            "requested_start": data_manifest.requested_start.isoformat() if data_manifest.requested_start else None,
            "requested_end": data_manifest.requested_end.isoformat() if data_manifest.requested_end else None,
            "actual_start": data_manifest.actual_start.isoformat() if data_manifest.actual_start else None,
            "actual_end": data_manifest.actual_end.isoformat() if data_manifest.actual_end else None,
            "observation_count": data_manifest.observation_count,
            "retrieval_timestamp": data_manifest.retrieval_timestamp.isoformat() if data_manifest.retrieval_timestamp else None,
            "checksum": data_manifest.checksum_sha256,
            "provenance": data_manifest.provenance,
            "fallback_used": data_manifest.fallback_used,
            "fallback_provider": data_manifest.fallback_provider,
            "cache_path": data_manifest.cache_path,
            "notes": data_manifest.notes,
        }
        with open(dm_path, "w") as f:
            json.dump(dm_payload, f, indent=2)

    mc_cfg_enabled = raw.get("monte_carlo", {}).get("enabled", True)
    stress_cfg_enabled = raw.get("stress", {}).get("enabled", True)
    validation_failures = _validate_results(
        manifest, data_manifest, output_dir, run_id,
        mc_enabled=mc_cfg_enabled,
        stress_enabled=stress_cfg_enabled,
    )

    if validation_failures:
        manifest.status = "failed"
        manifest.errors = [{"code": "VALIDATION_GATE", "detail": f} for f in validation_failures]
        logger.error(f"Validation gates failed: {validation_failures}")
    else:
        manifest.status = "completed"

    manifest.completed_at = datetime.now(UTC)

    with open(os.path.join(output_dir, "run_manifest.json"), "w") as f:
        json.dump(manifest.to_dict(), f, indent=2, default=str)

    _write_run_status(
        output_dir,
        run_id,
        manifest.status,
        validation_failures if validation_failures else None,
    )

    checksums_data = hashlib.sha256()
    for root, _dirs, files in os.walk(output_dir):
        for fn in sorted(files):
            fpath = os.path.join(root, fn)
            with open(fpath, "rb") as fh:
                checksums_data.update(fh.read())
    with open(os.path.join(output_dir, "checksums.sha256"), "w") as fh_checksum:
        fh_checksum.write(f"{checksums_data.hexdigest()}  {run_id}\n")

    logger.info(f"Research run {run_id} {manifest.status}. Output: {output_dir}")
    return 0 if manifest.status == "completed" else 1
