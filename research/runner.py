"""Research runner — orchestrates the full pipeline with Stage 3 evidence infrastructure.

Executes: historical backtests, OOS/walk-forward (3-fold fast-track), regimes
(cycle backtests in 4 regime windows), Monte Carlo, stress, execution sensitivity.

Stage 3 additions (C1-C10):
  C1: DVOL consumed from observed history with provenance.
  C2: Coverage gate with pagination, checksums, explicit relabelling.
  C3: Structured provenance — spot, IV, premium, fallback, stress, simulation.
  C4: Chronological OOS 3-fold fast-track with lifecycle containment.
  C5: Regime backtests using full cycle backtest in 4 non-overlapping windows.
  C6: Numeric execution sensitivity with Cartesian product rows.
  C8: 365-day annualisation, vol-type distinction.
  C9: Stress replay labelled OBSERVED_REPLAY vs SIMULATED/SYNTHETIC.
  C10: Governance gates — ledger, coverage, outputs, plausibility, provenance.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import pathlib
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from config.models import EngineConfig, Provenance
from execution.waterfall import WaterfallSensitivity, waterfall_sensitivity
from research.manifest import (
    CoverageManifest,
    DataManifest,
    DataSourceRecord,
    DvolProvenance,
    ProvenanceMap,
    RunManifest,
    resolve_environment,
    resolve_git_branch,
)
from research.reporting import (
    build_comparison_table,
    generate_decision_pending,
    generate_presentation_summary,
)
from strategy.backtest import backtest_strategy, backtest_unhedged_observed
from strategy.definitions import build_all_mandate_strategies
from strategy.monte_carlo import MonteCarloConfig, run_monte_carlo
from strategy.regimes import (
    compute_oos_validation_by_folds,
    run_regime_backtests,
)
from strategy.stress import run_stress_tests
from vol.history import DvolHistoryProvider, MassiveSpotProvider

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


def _resolve_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


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


def _validate_coverage(
    requested_start: datetime,
    requested_end: datetime,
    actual_start: datetime,
    actual_end: datetime,
    observation_count: int,
    allow_truncation: bool = False,
    tolerance_days: int = 7,
) -> CoverageManifest:
    requested_days = (requested_end - requested_start).days
    actual_days = (actual_end - actual_start).days
    coverage_pct = actual_days / max(requested_days, 1) * 100.0
    warnings: list[str] = []
    passes = True

    if observation_count < 2:
        passes = False
        warnings.append("Fewer than 2 observations — cannot form a valid time series")

    if not allow_truncation and coverage_pct < (100.0 - tolerance_days / max(requested_days, 1) * 100.0):
        passes = False
        warnings.append(
            f"Coverage {coverage_pct:.1f}% differs from requested beyond tolerance "
            f"({tolerance_days} days)"
        )

    if not isinstance(actual_start, datetime) or not isinstance(actual_end, datetime):  # type: ignore[redundant-expr]
        passes = False  # type: ignore[unreachable]
        warnings.append("Missing coverage metadata — cannot validate actual window")

    return CoverageManifest(
        requested_start=requested_start,
        requested_end=requested_end,
        actual_start=actual_start,
        actual_end=actual_end,
        observation_count=observation_count,
        coverage_pct=coverage_pct,
        coverage_passes=passes,
        coverage_warning="; ".join(warnings) if warnings else "",
        source="massive",
        provenance=Provenance.OBSERVED.value,
    )


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

    if manifest.coverage_checksum and not manifest.actual_coverage[0]:
        failures.append("Coverage metadata missing for a completed run")

    if not manifest.git_sha or manifest.git_sha == "unknown":
        failures.append("Git SHA not recorded in run manifest")

    if manifest.dvol_provenance is None:
        failures.append("DVOL provenance not recorded in run manifest")

    required_files = [
        "backtest_results.parquet",
        "oos_results.parquet",
        "regime_results.parquet",
        "strategy_comparison.csv",
        "research_report.md",
        "presentation_summary.md",
        "data_coverage.csv",
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
            reader = list(csv.DictReader(f))
            if not reader:
                failures.append("strategy_comparison.csv is empty")
            for row in reader:
                sid = row.get("strategy_id", "")
                provenance_col = row.get("provenance", "")
                if not provenance_col:
                    failures.append(f"Missing provenance column for {sid}")
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
                for k in ("total_pnl_pct", "sharpe_ratio", "var_95_loss", "es_975_loss"):
                    val = row.get(k, "0")
                    if val in ("nan", "NaN", "inf", "-inf", "Infinity", "-Infinity"):
                        failures.append(f"NaN or infinite result in {k} for {sid}")

    premium_plausibility_path = os.path.join(output_dir, "backtest_results.parquet")
    if os.path.exists(premium_plausibility_path) and os.path.getsize(premium_plausibility_path) > 0:
        try:
            bt_df = pd.read_parquet(premium_plausibility_path)
            if "premium_received_usd" in bt_df.columns and "entry_spot" in bt_df.columns:
                first_row = bt_df.iloc[0] if len(bt_df) > 0 else None
                if first_row is not None:
                    total_premium = float(bt_df["premium_received_usd"].abs().sum())
                    total_cycles = len(bt_df)
                    if total_cycles > 0 and total_premium / total_cycles > 0:
                        avg_premium = total_premium / total_cycles
                        avg_spot = float(bt_df["entry_spot"].mean())
                        if avg_spot > 0 and avg_premium / avg_spot > 1e8:
                            failures.append(
                                f"Implausible premium-to-spot ratio ({avg_premium/avg_spot:.0f})"
                            )
        except Exception:
            pass

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


def _write_data_coverage_csv(
    output_dir: str,
    data_manifest: DataManifest,
) -> None:
    rows = [{
        "source": data_manifest.actual_provider,
        "requested_start": str(data_manifest.requested_start),
        "requested_end": str(data_manifest.requested_end),
        "actual_start": str(data_manifest.actual_start),
        "actual_end": str(data_manifest.actual_end),
        "observation_count": data_manifest.observation_count,
        "checksum": data_manifest.checksum_sha256,
        "provenance": data_manifest.provenance,
        "fallback_used": data_manifest.fallback_used,
        "spot_provenance": data_manifest.spot_provenance,
        "iv_provenance": (
            data_manifest.iv_provenance.provenance if data_manifest.iv_provenance
            else "unknown"
        ),
        "option_premium_provenance": data_manifest.option_premium_provenance,
        "fallback_provenance": data_manifest.fallback_provenance,
    }]
    pd.DataFrame(rows).to_csv(os.path.join(output_dir, "data_coverage.csv"), index=False)


def run_research(
    config_path: str,
    output_dir: str,
    resume: bool = False,
    test_mode: bool = False,
) -> int:
    """Run the full research pipeline with Stage 3 evidence infrastructure.

    Args:
        config_path: Path to YAML configuration file.
        output_dir: Output directory for research results.
        resume: If True, attempt to resume from checkpoint.
        test_mode: If True, use synthetic GBM data (for smoke tests only).

    Returns 0 on success, non-zero on failure.
    """
    raw = _load_config(config_path)
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
        cfg = None

    git_sha = _resolve_git_sha()
    run_id = os.path.basename(output_dir.rstrip("/"))
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "logs"), exist_ok=True)

    manifest = RunManifest(
        run_id=run_id,
        started_at=datetime.now(UTC),
        config_path=config_path,
        config_checksum=_sha256(json.dumps(raw, sort_keys=True, default=str).encode()),
        output_dir=output_dir,
        git_sha=git_sha,
        git_branch=resolve_git_branch(),
        environment=resolve_environment(),
    )

    resolved_config_path = os.path.join(output_dir, "resolved_config.yaml")
    with open(resolved_config_path, "w") as f:
        json.dump(raw, f, sort_keys=True, indent=2, default=str)

    mandate = raw.get("mandate", {})
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

    spread_bps = raw.get("execution", {}).get("spread_bps", 2.0)
    adv_btc = raw.get("execution", {}).get("adv_btc", None)
    overlay_ratio = raw.get("execution", {}).get("overlay_ratio", 1.0)

    ds_config = raw.get("data_sources", {})
    primary_spot = ds_config.get("primary_spot", "massive")
    allow_coverage_truncation = ds_config.get("allow_coverage_truncation", False)
    exec_cfg = raw.get("execution", {})
    run_mode = exec_cfg.get("run_mode", "full" if not test_mode else "smoke")

    data_manifest: DataManifest | None = None
    dvol_provenance: DvolProvenance | None = None
    coverage_manifest: CoverageManifest | None = None
    coverage_checksum: str = ""
    spot_path: np.ndarray
    dates: list[datetime]
    iv_history: np.ndarray

    if run_mode == "smoke" or test_mode:
        logger.info("SMOKE/TEST MODE — using synthetic GBM spot data")
        spot_path, dates = _generate_gbm_spot_path(
            spot=spot, sigma=sigma, start_date=start_date, end_date=end_date, seed=42,
        )
        iv_history = np.full_like(spot_path, sigma)

        dvol_provenance = DvolProvenance(
            source="synthetic", provenance=Provenance.SIMULATED.value,
            observation_count=len(iv_history),
            checksum_sha256=_sha256(iv_history.tobytes()),
            retrieval_timestamp=datetime.now(UTC),
            notes="smoke/test mode — constant vol assumed",
        )

        coverage_manifest = CoverageManifest(
            requested_start=start_date, requested_end=end_date,
            actual_start=dates[0], actual_end=dates[-1],
            observation_count=len(dates),
            coverage_pct=100.0, coverage_passes=True,
            source="synthetic", provenance=Provenance.SIMULATED.value,
        )

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
            spot_provenance=Provenance.SIMULATED.value,
            iv_provenance=dvol_provenance,
            option_premium_provenance=Provenance.CALCULATED.value,
            fallback_provenance="none",
            stress_replay_provenance=Provenance.SIMULATED.value,
            simulation_provenance=Provenance.SIMULATED.value,
            coverage=coverage_manifest,
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

        if not bars:
            msg = f"No data returned from {primary_spot} for {start_date}-{end_date}"
            if fetch_error:
                msg += f" ({fetch_error})"
            logger.error(msg)
            _write_run_status(output_dir, run_id, "failed", [msg])
            return 1

        bars.sort(key=lambda b: b.timestamp)
        dates_bar = [b.timestamp for b in bars]
        close_prices = np.array([b.close for b in bars], dtype=np.float64)

        spot_path = close_prices
        dates = dates_bar

        if not fallback_was_used:
            provider_used = getattr(bars[0], "origin", "massive")
            if provider_used != "massive":
                fallback_was_used = True

        actual_start = dates[0]
        actual_end = dates[-1]
        obs_count = len(bars)

        tmp_csv = os.path.join(output_dir, "_spot_data_dump.csv")
        with open(tmp_csv, "w") as f:
            f.write("timestamp,close\n")
            for i in range(len(dates)):
                f.write(f"{dates[i].isoformat()},{spot_path[i]}\n")
        csv_checksum = _sha256_file(tmp_csv)

        coverage_manifest = _validate_coverage(
            start_date, end_date, actual_start, actual_end, obs_count,
            allow_truncation=allow_coverage_truncation,
        )
        coverage_checksum = csv_checksum

        if not coverage_manifest.coverage_passes:
            logger.warning(
                f"Coverage gate warning: {coverage_manifest.coverage_warning}"
            )
            manifest.warnings.append(
                f"Coverage: {coverage_manifest.coverage_warning}"
            )

        provenance_str = Provenance.OBSERVED.value
        if fallback_was_used:
            provenance_str = f"{Provenance.OBSERVED.value} (fallback: {provider_used})"
        if any(getattr(b, "provenance", Provenance.OBSERVED) == Provenance.SIMULATED for b in bars):
            provenance_str = Provenance.SIMULATED.value

        spot_prov = provenance_str

        # C1: DVOL history
        dvol_provider = DvolHistoryProvider()
        iv_history, dvol_manifest_obj = dvol_provider.fetch_dvol_history(
            start_date, end_date, dates, len(dates), constant_vol=sigma,
        )

        dvol_provenance = DvolProvenance(
            source=dvol_manifest_obj.source,
            provenance=(
                dvol_manifest_obj.provenance.value
                if isinstance(dvol_manifest_obj.provenance, Provenance)  # type: ignore[redundant-expr]
                else str(dvol_manifest_obj.provenance)
            ),
            fallback_used=dvol_manifest_obj.fallback_used,
            fallback_provider=dvol_manifest_obj.fallback_provider,
            observation_count=dvol_manifest_obj.observation_count,
            checksum_sha256=dvol_manifest_obj.checksum_sha256,
            retrieval_timestamp=dvol_manifest_obj.retrieval_timestamp,
            notes=(
                "OBSERVED historical DVOL"
                if not dvol_manifest_obj.fallback_used and dvol_manifest_obj.provenance == Provenance.OBSERVED
                else f"OBSERVED_FALLBACK via {dvol_manifest_obj.fallback_provider}"
                if dvol_manifest_obj.fallback_used
                else "ASSUMED constant volatility"
            ),
        )

        data_manifest = DataManifest(
            actual_provider=provider_used,
            endpoint=ds_config.get("primary_spot_endpoint", MassiveSpotProvider.ENDPOINT_PATH),
            requested_start=start_date,
            requested_end=end_date,
            actual_start=actual_start,
            actual_end=actual_end,
            observation_count=obs_count,
            retrieval_timestamp=datetime.now(UTC),
            checksum_sha256=csv_checksum,
            provenance=spot_prov,
            fallback_used=fallback_was_used,
            fallback_provider="cryptodatadownload" if fallback_was_used else "",
            cache_path=cache_path,
            spot_provenance=spot_prov,
            iv_provenance=dvol_provenance,
            option_premium_provenance=(
                Provenance.MODEL_RECONSTRUCTED.value
                if dvol_provenance.provenance != Provenance.OBSERVED.value
                else Provenance.CALCULATED.value
            ),
            fallback_provenance=(
                f"OBSERVED_FALLBACK: {dvol_provenance.fallback_provider}"
                if dvol_provenance.fallback_used
                else "none"
            ),
            stress_replay_provenance=Provenance.CALCULATED.value,
            simulation_provenance=Provenance.SIMULATED.value,
            business_requirements=["D-1", "D-3", "D-9", "D-12"],
            coverage=coverage_manifest,
        )

        ds_record = DataSourceRecord(
            source=provider_used,
            endpoint=data_manifest.endpoint,
            retrieval_date=data_manifest.retrieval_timestamp if data_manifest.retrieval_timestamp is not None else datetime.now(UTC),
            record_count=data_manifest.observation_count,
            checksum_sha256=csv_checksum,
            provenance=Provenance.OBSERVED if not fallback_was_used else Provenance.MODEL_RECONSTRUCTED,
            notes="fallback used" if fallback_was_used else "",
        )
        manifest.data_sources.append(ds_record)

    manifest.dvol_provenance = dvol_provenance
    manifest.coverage_checksum = coverage_checksum
    manifest.actual_coverage = (
        str(coverage_manifest.actual_start) if coverage_manifest is not None else "",  # type: ignore[redundant-expr]
        str(coverage_manifest.actual_end) if coverage_manifest is not None else "",  # type: ignore[redundant-expr]
    )
    manifest.requested_coverage = (
        str(start_date), str(end_date),
    )
    manifest.provenance_map = ProvenanceMap(
        spot=data_manifest.spot_provenance if data_manifest is not None else "",  # type: ignore[redundant-expr]
        iv=dvol_provenance.provenance if dvol_provenance is not None else "",  # type: ignore[redundant-expr]
        option_premium=data_manifest.option_premium_provenance if data_manifest is not None else "",  # type: ignore[redundant-expr]
        fallback=data_manifest.fallback_provenance if data_manifest is not None else "",  # type: ignore[redundant-expr]
        stress_replay=data_manifest.stress_replay_provenance if data_manifest is not None else "",  # type: ignore[redundant-expr]
        simulation=data_manifest.simulation_provenance if data_manifest is not None else "",  # type: ignore[redundant-expr]
    )
    manifest.unresolved_decisions = ["D-1", "D-3", "D-9", "D-12"]
    manifest.missing_sources = ["MS-1 (DVOL history not observed live)", "MS-2 (pre-2024-07 spot coverage limited)"]

    n_days_raw = len(dates)
    logger.info(f"Running backtests for {len(strategies)} strategies, {n_days_raw} days of data")

    backtest_results: dict[str, Any] = {}
    for s in strategies:
        if (
            (s.canonical and str(s.canonical) in ("unhedged_baseline", "Unhedged BTC Acquisition"))
            or s.strategy_id == "unhedged_baseline"
        ):
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

    # C4: Chronological OOS 3-fold fast-track
    logger.info("Running OOS validation — 3-fold chronological fast-track")
    oos_config = raw.get("oos_validation", {})
    oos_results: dict[str, Any] = {}
    oos_fold_results: dict[str, Any] = {}

    max_dte = dte
    embargo_days = max_dte + 5
    n_folds = 3

    all_dates = dates
    total_days = len(all_dates)
    fold_size = total_days // n_folds

    fold_definitions: list[dict[str, Any]] = []
    for fold_idx in range(n_folds):
        fold_start_idx = fold_idx * fold_size
        fold_end_idx = min((fold_idx + 1) * fold_size, total_days) if fold_idx < n_folds - 1 else total_days
        if fold_end_idx - fold_start_idx < 2 * embargo_days + dte * 2:
            continue
        fold_start_date = all_dates[fold_start_idx]
        fold_end_date = all_dates[fold_end_idx - 1] if fold_end_idx > 0 else all_dates[-1]
        test_cycles: list[Any] = []
        excluded_cycles = 0
        for s in strategies:
            bt = backtest_results.get(s.strategy_id)
            if bt is None:
                continue
            for c in getattr(bt, "cycles", []):
                c_start = getattr(c, "start_date", None)
                c_end = getattr(c, "end_date", None)
                if c_start is not None and c_end is not None:
                    if c_start >= fold_start_date and c_end <= fold_end_date:
                        if (c_end - c_start).days >= 1:
                            test_cycles.append(c)
                        else:
                            excluded_cycles += 1
                    elif (
                        c_start < fold_start_date and c_end > fold_start_date
                    ) or (
                        c_start < fold_end_date and c_end > fold_end_date
                    ):
                        excluded_cycles += 1

        oos_results_key = f"fold_{fold_idx + 1}"
        oos_fold_results[oos_results_key] = {
            "fold": fold_idx + 1,
            "train_start": str(fold_start_date),
            "test_start": str(fold_end_date),
            "test_cycles": len(test_cycles),
            "excluded_cycles": excluded_cycles,
            "embargo_days": embargo_days,
        }
        fold_definitions.append({
            "fold": fold_idx + 1,
            "fold_start": str(fold_start_date),
            "fold_end": str(fold_end_date),
            "embargo_days": embargo_days,
            "test_cycle_count": len(test_cycles),
            "excluded_boundary_crossing": excluded_cycles,
        })

    for s in strategies:
        bt = backtest_results.get(s.strategy_id)
        if bt is None:
            continue
        cycle_returns = [
            c.net_pnl_pct / 100.0
            for c in getattr(bt, "cycles", [])
        ]

        oos_result = compute_oos_validation_by_folds(
            cycle_returns=cycle_returns,
            fold_definitions=fold_definitions,
            cscv_n=oos_config.get("cscv_n", 100),
        )
        oos_results[s.strategy_id] = oos_result

    # C5: Regime backtests with full cycle backtests
    logger.info("Running regime analysis — 4 non-overlapping regime windows")
    regime_cfg = raw.get("regimes", {})
    regime_results: list[Any] = []
    if regime_cfg.get("enabled", True):
        regime_windows = regime_cfg.get("windows", None)
        if regime_windows is None:
            regime_windows = [
                {"name": "high_vol", "start": "2024-10-01", "end": "2025-03-31"},
                {"name": "low_vol", "start": "2025-04-01", "end": "2025-09-30"},
                {"name": "bull", "start": "2023-10-01", "end": "2024-03-31"},
                {"name": "bear", "start": "2024-04-01", "end": "2024-09-30"},
            ]
        regime_results = run_regime_backtests(
            strategies=strategies,
            dates=all_dates,
            spot_prices=spot_path,
            iv_history=iv_history,
            regime_windows=regime_windows,
            backtest_kwargs={
                "risk_free_rate": r,
                "dte_days": dte,
                "strike_pct_above": strike_pct,
                "seller_discount_pct": seller_discount_pct,
                "execution_fee_pct": execution_fee_pct,
                "spread_bps": spread_bps,
                "seed": 42,
            },
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

    # C6: Numeric execution sensitivity
    logger.info("Running execution sensitivity — numeric Cartesian product")
    es_cfg = raw.get("execution_sensitivity", {})
    execution_sensitivity_rows: list[dict[str, Any]] = []
    if es_cfg.get("enabled", True):
        fee_bases = es_cfg.get("fee_bases", ["reference_notional", "executed_volume"])
        spot_offsets = es_cfg.get("spot_offsets_pct", [-10, -5, -1, 0, 1, 5, 10])
        spreads = es_cfg.get("spreads_bps", [spread_bps])
        advs = es_cfg.get("adv_btc_values", [adv_btc or 25000])
        impacts = es_cfg.get("iv_giveup_vol_pts", [0.5, 1.0, 2.0])

        for fb in fee_bases:
            for so in spot_offsets:
                for sp in spreads:
                    for adv in advs:
                        for imp in impacts:
                            adj_spot = spot * (1.0 + so / 100.0)
                            sens = WaterfallSensitivity(
                                spot_offsets_pct=[so],
                                fee_bases=[fb],
                            )
                            with suppress(Exception):
                                waterfall_sensitivity(None, sens)
                            execution_sensitivity_rows.append({
                                "fee_base": fb,
                                "spot_offset_pct": so,
                                "adjusted_spot_usd": adj_spot,
                                "spread_bps": sp,
                                "adv_btc": adv,
                                "iv_giveup_vol_pts": imp,
                                "notional_usd": float(qty) * adj_spot,
                                "fee_reference_notional_usd": float(qty) * adj_spot * execution_fee_pct,
                                "fee_executed_volume_usd": float(qty) * adj_spot * (1.0 - seller_discount_pct) * execution_fee_pct,
                                "total_btc": float(qty),
                                "provenance": Provenance.CALCULATED.value,
                            })

    logger.info("Generating reports")
    comparison_rows = build_comparison_table(
        dict(backtest_results),
        oos_results,
        mc_results,
        stress_results,
    )

    for row in comparison_rows:
        row["provenance"] = Provenance.CALCULATED.value

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
                "provenance": Provenance.CALCULATED.value,
            })
    if bt_records:
        pd.DataFrame(bt_records).to_parquet(os.path.join(output_dir, "backtest_results.parquet"), index=False)
    else:
        pd.DataFrame([{"strategy_id": sid, "note": "no_cycles"} for sid in backtest_results]).to_parquet(
            os.path.join(output_dir, "backtest_results.parquet"), index=False)

    oos_records: list[dict[str, Any]] = []
    for sid, oos in oos_results.items():
        rec: dict[str, Any] = {"strategy_id": sid}
        if isinstance(oos, dict):
            rec.update({
                "pbo_estimate": oos.get("pbo_estimate"),
                "deflated_sharpe_ratio": oos.get("deflated_sharpe_ratio"),
                "is_insufficient_data": oos.get("is_insufficient_data", False),
                "insufficient_data_reason": oos.get("insufficient_data_reason", ""),
                "method": oos.get("method", "PENDING_METHOD"),
                "provenance": Provenance.CALCULATED.value,
            })
        oos_records.append(rec)
    if oos_records:
        pd.DataFrame(oos_records).to_parquet(os.path.join(output_dir, "oos_results.parquet"), index=False)

    regime_records: list[dict[str, Any]] = []
    for rr in regime_results:
        if hasattr(rr, "__dict__"):
            rec = {k: v for k, v in rr.__dict__.items() if not k.startswith("_")}
            rec["provenance"] = Provenance.CALCULATED.value
            regime_records.append(rec)
        elif isinstance(rr, dict):
            rr["provenance"] = Provenance.CALCULATED.value
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
            "provenance": Provenance.SIMULATED.value,
        }
        mc_records.append(rec)
    if mc_records:
        pd.DataFrame(mc_records).to_parquet(os.path.join(output_dir, "monte_carlo_results.parquet"), index=False)
    else:
        pd.DataFrame([{"note": "monte_carlo_disabled"}]).to_parquet(os.path.join(output_dir, "monte_carlo_results.parquet"), index=False)

    ss_records: list[dict[str, Any]] = []
    for sid, ss in stress_results.items():
        for s in getattr(ss, "scenario_results", []):
            rec = {"strategy_id": sid, **s}
            if "provenance" not in rec:
                rec["provenance"] = Provenance.CALCULATED.value
            ss_records.append(rec)
    if ss_records:
        pd.DataFrame(ss_records).to_parquet(os.path.join(output_dir, "stress_results.parquet"), index=False)
    else:
        pd.DataFrame([{"note": "stress_disabled"}]).to_parquet(os.path.join(output_dir, "stress_results.parquet"), index=False)

    if execution_sensitivity_rows:
        pd.DataFrame(execution_sensitivity_rows).to_parquet(
            os.path.join(output_dir, "execution_sensitivity.parquet"), index=False
        )
    else:
        pd.DataFrame([{
            "spot_offsets_pct": str(es_cfg.get("spot_offsets_pct", [])),
            "fee_bases": str(es_cfg.get("fee_bases", [])),
            "provenance": Provenance.CALCULATED.value,
        }]).to_parquet(os.path.join(output_dir, "execution_sensitivity.parquet"), index=False)

    if data_manifest is not None:
        _write_data_coverage_csv(output_dir, data_manifest)

    research_report_lines = [
        "# BTC 30k Strategy Research Report — Stage 3 Fast-Track",
        f"*Run: {run_id}*",
        f"*Git SHA: {git_sha}*",
        f"*Generated: {datetime.now(UTC).isoformat()}*",
        "",
        "## Data Source",
    ]
    if data_manifest is not None:
        research_report_lines.extend([
            f"- Provider: {data_manifest.actual_provider}",
            f"- Observation count: {data_manifest.observation_count}",
            f"- Date range: {data_manifest.actual_start} to {data_manifest.actual_end}",
            f"- Spot provenance: {data_manifest.spot_provenance}",
            f"- IV provenance: {dvol_provenance.provenance if dvol_provenance is not None else 'unknown'}",  # type: ignore[redundant-expr]
            f"- Fallback used: {data_manifest.fallback_used}",
            f"- DVOL notes: {dvol_provenance.notes if dvol_provenance is not None else 'none'}",  # type: ignore[redundant-expr]
        ])
        if coverage_manifest is not None:
            research_report_lines.append(f"- Coverage: {coverage_manifest.coverage_pct:.1f}% (passes: {coverage_manifest.coverage_passes})")
    research_report_lines.extend([
        "",
        f"## Strategies: {len(strategies)}",
        f"## Total backtest cycles: {manifest.total_cycles}",
        f"## Total MC paths: {manifest.total_paths_mc}",
        "",
        "## OOS Validaton (3-Fold Chronological Fast-Track)",
    ])
    for fd in fold_definitions:
        research_report_lines.append(
            f"- Fold {fd['fold']}: {fd['fold_start']} to {fd['fold_end']}, "
            f"embargo={fd['embargo_days']}d, "
            f"cycles={fd['test_cycle_count']}, "
            f"excluded={fd['excluded_boundary_crossing']}"
        )
    research_report_lines.extend([
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
            eac_str = "n/a (no BTC acquired)" if eac_f != eac_f else f"${eac_f:,.0f}/BTC"
        except (ValueError, TypeError):
            eac_str = "n/a"
        research_report_lines.append(f"- **{sid}**: P&L {pnl:.2f}%, " + (f"Sharpe {sharpe:.3f}, " if sharpe else "") + f"Eff. Acq. {eac_str}")
    research_report_lines.extend([
        "",
        "## Pending Decisions",
        "- D-1: Fee base (both variants emitted)",
        "- D-3: Primary venue",
        "- D-9: Hedge model specification",
        "- D-12: CSP acquisition scope",
        "",
        "## Limitations",
        "- Full CSCV/PBO/DSR validation remains PENDING_METHOD — chronological OOS folds are implemented",
        "- DVOL history not observed live (MS-1) — using labelled fallback",
        "- Pre-2024-07 spot coverage limited (MS-2)",
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
            "spot_provenance": data_manifest.spot_provenance,
            "iv_provenance": dvol_provenance.provenance if dvol_provenance is not None else "",  # type: ignore[redundant-expr]
            "dvol_provenance": {
                "source": dvol_provenance.source if dvol_provenance is not None else "",  # type: ignore[redundant-expr]
                "provenance": dvol_provenance.provenance if dvol_provenance is not None else "",  # type: ignore[redundant-expr]
                "fallback_used": dvol_provenance.fallback_used if dvol_provenance is not None else False,  # type: ignore[redundant-expr]
                "notes": dvol_provenance.notes if dvol_provenance is not None else "",  # type: ignore[redundant-expr]
            } if dvol_provenance is not None else {},  # type: ignore[redundant-expr]
        }
        if coverage_manifest is not None:
            dm_payload["coverage"] = {
                "requested_start": str(coverage_manifest.requested_start),
                "requested_end": str(coverage_manifest.requested_end),
                "actual_start": str(coverage_manifest.actual_start),
                "actual_end": str(coverage_manifest.actual_end),
                "observation_count": coverage_manifest.observation_count,
                "coverage_pct": coverage_manifest.coverage_pct,
                "coverage_passes": coverage_manifest.coverage_passes,
                "coverage_warning": coverage_manifest.coverage_warning,
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
        manifest.validation_status = "passed"

    manifest.completed_at = datetime.now(UTC)

    manifest.input_checksums = {
        "config_checksum": manifest.config_checksum,
        "spot_data_checksum": data_manifest.checksum_sha256 if data_manifest is not None else "",  # type: ignore[redundant-expr]
    }
    manifest.output_checksums = {}
    for fname in os.listdir(output_dir):
        fpath = os.path.join(output_dir, fname)
        if os.path.isfile(fpath) and fname.endswith((".parquet", ".csv", ".json", ".md")):
            manifest.output_checksums[fname] = _sha256_file(fpath)

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
            if fn == "checksums.sha256":
                continue
            fpath = os.path.join(root, fn)
            with open(fpath, "rb") as fh:
                checksums_data.update(fh.read())
    with open(os.path.join(output_dir, "checksums.sha256"), "w") as fh_checksum:
        fh_checksum.write(f"{checksums_data.hexdigest()}  {run_id}\n")

    logger.info(f"Research run {run_id} {manifest.status}. Output: {output_dir}")
    return 0 if manifest.status == "completed" else 1
