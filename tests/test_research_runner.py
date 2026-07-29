"""Research runner tests — smoke test and full-mode validation."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from datetime import UTC, datetime

from config.models import Provenance
from engine.data_models import HistoricalSpotBar
from research.runner import run_research
from vol.history import MassiveSpotProvider


def _massive_bars(n: int = 180, start: str = "2024-01-01", spot: float = 65000.0) -> list[HistoricalSpotBar]:
    import numpy as np
    rng = np.random.default_rng(42)
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    bars: list[HistoricalSpotBar] = []
    for i in range(n):
        dt = start_dt.replace(hour=0) + __import__("datetime").timedelta(days=i)
        o = spot + rng.normal() * 500
        h = o + abs(rng.normal()) * 300
        lo = o - abs(rng.normal()) * 300
        c = o + rng.normal() * 200
        bars.append(HistoricalSpotBar(
            symbol="btc_usd",
            timestamp=dt,
            open=float(o),
            high=float(h),
            low=float(lo),
            close=float(c),
            volume=float(abs(rng.normal() * 100 + 1000)),
            vwap=float(c),
            provenance=Provenance.OBSERVED,
            origin="massive",
        ))
    return bars


class TestResearchRunnerSmoke:
    def test_smoke_research_run(self) -> None:
        import yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.yaml")
            output_dir = os.path.join(tmpdir, "results")

            config = {
                "mandate": {
                    "btc_quantity": 100,
                    "reference_spot_usd": 65000,
                    "seller_discount_pct": 0.025,
                    "target_option_yield_pct": 0.025,
                    "execution_fee_pct": 0.005,
                },
                "strategies": {
                    "enabled": ["unhedged_baseline", "covered_call"],
                },
                "backtest": {
                    "window_start": "2024-01-01",
                    "window_end": "2024-06-30",
                    "dte_days": 30,
                    "strike_pct_above": 0.15,
                    "risk_free_rate": 0.04,
                    "volatility": 0.45,
                },
                "oos_validation": {
                    "train_start": "2024-01-01",
                    "train_end": "2024-03-31",
                    "test_start": "2024-04-01",
                    "test_end": "2024-06-30",
                    "cscv_s": 8,
                    "cscv_n": 100,
                    "walk_forward": "expanding",
                },
                "monte_carlo": {
                    "enabled": True,
                    "n_paths": 100,
                    "models": ["GBM"],
                    "horizon_years": 0.082,
                    "drift": 0.10,
                    "seed": 42,
                    "use_antithetic": True,
                },
                "stress": {"enabled": True, "start_spot": 65000, "scenarios": []},
                "execution_sensitivity": {"enabled": False},
                "regimes": {"enabled": False},
                "data_sources": {
                    "primary_spot": "massive",
                    "fallback_spot": "cryptodatadownload",
                    "allow_cdd_fallback": True,
                },
                "output": {
                    "format": "parquet",
                    "write_csv_comparison": True,
                    "write_report": True,
                    "write_presentation_summary": True,
                    "checksums": True,
                    "resolved_config": True,
                    "log_level": "INFO",
                },
                "execution": {
                    "deterministic_seeds": True,
                    "base_seed": 42,
                    "enable_checkpoints": True,
                    "resume": True,
                    "max_workers": 1,
                    "run_mode": "smoke",
                },
            }

            with open(config_path, "w") as f:
                yaml.dump(config, f)

            rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
            assert rc == 0

            assert os.path.exists(os.path.join(output_dir, "resolved_config.yaml"))
            assert os.path.exists(os.path.join(output_dir, "run_manifest.json"))
            assert os.path.exists(os.path.join(output_dir, "run_status.json"))
            assert os.path.exists(os.path.join(output_dir, "strategy_comparison.csv"))
            assert os.path.exists(os.path.join(output_dir, "presentation_summary.md"))
            assert os.path.exists(os.path.join(output_dir, "decision_pending.json"))
            assert os.path.exists(os.path.join(output_dir, "checksums.sha256"))
            assert os.path.exists(os.path.join(output_dir, "data_manifest.json"))
            assert os.path.exists(os.path.join(output_dir, "backtest_results.parquet"))
            assert os.path.exists(os.path.join(output_dir, "research_report.md"))

    def test_run_manifest_has_required_fields(self) -> None:
        import yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.yaml")
            output_dir = os.path.join(tmpdir, "results")

            config = {
                "mandate": {"btc_quantity": 100, "reference_spot_usd": 65000, "seller_discount_pct": 0.025, "target_option_yield_pct": 0.025, "execution_fee_pct": 0.005},
                "strategies": {"enabled": ["unhedged_baseline"]},
                "backtest": {"window_start": "2024-01-01", "window_end": "2024-04-01", "dte_days": 30, "strike_pct_above": 0.15, "risk_free_rate": 0.04, "volatility": 0.45},
                "oos_validation": {"train_start": "2024-01-01", "train_end": "2024-02-01", "test_start": "2024-02-01", "test_end": "2024-04-01", "cscv_s": 8, "cscv_n": 100, "walk_forward": "expanding"},
                "monte_carlo": {"enabled": False, "n_paths": 50, "models": ["GBM"], "horizon_years": 0.082, "drift": 0.10, "seed": 42, "use_antithetic": True},
                "stress": {"enabled": False, "start_spot": 65000, "scenarios": []},
                "execution_sensitivity": {"enabled": False},
                "regimes": {"enabled": False},
                "data_sources": {"primary_spot": "massive", "allow_cdd_fallback": True},
                "output": {"write_csv_comparison": True, "write_presentation_summary": True, "checksums": True, "resolved_config": True},
                "execution": {"deterministic_seeds": True, "base_seed": 42, "enable_checkpoints": True, "resume": True, "max_workers": 1, "run_mode": "smoke"},
            }

            with open(config_path, "w") as f:
                yaml.dump(config, f)

            rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
            assert rc == 0

            with open(os.path.join(output_dir, "run_manifest.json")) as f:
                manifest = json.load(f)
            assert manifest["status"] == "completed"
            assert "run_id" in manifest
            assert "started_at" in manifest
            assert "completed_at" in manifest
            assert "config_checksum" in manifest
            assert manifest["strategy_count"] >= 1


class TestResearchRunnerFullMode:
    def _make_config(self, tmpdir: str, strategies: list[str]) -> str:
        import yaml
        config = {
            "mandate": {"btc_quantity": 100, "reference_spot_usd": 65000, "seller_discount_pct": 0.025, "target_option_yield_pct": 0.025, "execution_fee_pct": 0.005},
            "strategies": {"enabled": strategies},
            "backtest": {"window_start": "2024-01-01", "window_end": "2024-06-30", "dte_days": 30, "strike_pct_above": 0.15, "risk_free_rate": 0.04, "volatility": 0.45},
            "oos_validation": {"train_start": "2024-01-01", "train_end": "2024-03-31", "test_start": "2024-04-01", "test_end": "2024-06-30", "cscv_s": 8, "cscv_n": 100, "walk_forward": "expanding"},
            "monte_carlo": {"enabled": False, "n_paths": 100, "models": ["GBM"], "horizon_years": 0.082, "drift": 0.10, "seed": 42, "use_antithetic": True},
            "stress": {"enabled": False, "start_spot": 65000, "scenarios": []},
            "execution_sensitivity": {"enabled": False},
            "regimes": {"enabled": False},
            "data_sources": {"primary_spot": "massive", "allow_cdd_fallback": False, "primary_spot_endpoint": "https://api.massive.com/v1"},
            "output": {"write_csv_comparison": True, "write_report": True, "write_presentation_summary": True, "checksums": True, "resolved_config": True},
            "execution": {"deterministic_seeds": True, "base_seed": 42, "enable_checkpoints": True, "resume": True, "max_workers": 1, "run_mode": "full"},
        }
        config_path = os.path.join(tmpdir, "test_config.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        return config_path

    @mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-api-key-mock"}, clear=True)
    def test_massive_observations_consumed(self) -> None:
        bars = _massive_bars(n=180, start="2024-01-01")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._make_config(tmpdir, ["unhedged_baseline", "covered_call"])
            output_dir = os.path.join(tmpdir, "results")

            with mock.patch.object(MassiveSpotProvider, "fetch_bars", return_value=bars):
                rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
                assert rc == 0

            with open(os.path.join(output_dir, "data_manifest.json")) as f:
                dm = json.load(f)
            assert dm["actual_provider"] == "massive"
            assert dm["observation_count"] == 180
            assert dm["fallback_used"] is False
            assert dm["provenance"] == "observed"

            with open(os.path.join(output_dir, "run_manifest.json")) as f:
                rm = json.load(f)
            assert len(rm["data_sources"]) > 0
            assert rm["status"] == "completed"
            assert os.path.exists(os.path.join(output_dir, "backtest_results.parquet"))

    @mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-api-key-mock"}, clear=True)
    def test_synthetic_rejected_in_full_mode(self) -> None:
        bars = _massive_bars(n=10, start="2024-01-01")
        for b in bars:
            b.provenance = Provenance.SIMULATED

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._make_config(tmpdir, ["unhedged_baseline"])
            output_dir = os.path.join(tmpdir, "results")

            with mock.patch.object(MassiveSpotProvider, "fetch_bars", return_value=bars):
                rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
                assert rc != 0

            with open(os.path.join(output_dir, "run_status.json")) as f:
                st = json.load(f)
            assert st["status"] == "failed"

    @mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-api-key-mock"}, clear=True)
    def test_fallback_disclosed(self) -> None:
        bars = _massive_bars(n=50, start="2024-01-01")
        for b in bars:
            b.origin = "cryptodatadownload"
            b.provenance = Provenance.OBSERVED

        with tempfile.TemporaryDirectory() as tmpdir:
            import yaml
            config = {
                "mandate": {"btc_quantity": 100, "reference_spot_usd": 65000, "seller_discount_pct": 0.025, "target_option_yield_pct": 0.025, "execution_fee_pct": 0.005},
                "strategies": {"enabled": ["unhedged_baseline"]},
                "backtest": {"window_start": "2024-01-01", "window_end": "2024-03-01", "dte_days": 30, "strike_pct_above": 0.15, "risk_free_rate": 0.04, "volatility": 0.45},
                "oos_validation": {"train_start": "2024-01-01", "train_end": "2024-02-01", "test_start": "2024-02-01", "test_end": "2024-03-01", "cscv_s": 8, "cscv_n": 100, "walk_forward": "expanding"},
                "monte_carlo": {"enabled": False, "n_paths": 100, "models": ["GBM"], "horizon_years": 0.082, "drift": 0.10, "seed": 42, "use_antithetic": True},
                "stress": {"enabled": False, "start_spot": 65000, "scenarios": []},
                "execution_sensitivity": {"enabled": False},
                "regimes": {"enabled": False},
                "data_sources": {"primary_spot": "massive", "allow_cdd_fallback": True},
                "output": {"write_csv_comparison": True, "write_report": True, "write_presentation_summary": True, "checksums": True, "resolved_config": True},
                "execution": {"deterministic_seeds": True, "base_seed": 42, "enable_checkpoints": True, "resume": True, "max_workers": 1, "run_mode": "full"},
            }
            config_path = os.path.join(tmpdir, "test_config.yaml")
            with open(config_path, "w") as f:
                yaml.dump(config, f)
            output_dir = os.path.join(tmpdir, "results")

            with mock.patch.object(MassiveSpotProvider, "fetch_bars", return_value=bars):
                rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
                assert rc == 0

            with open(os.path.join(output_dir, "data_manifest.json")) as f:
                dm = json.load(f)
            assert dm["fallback_used"] is True
            assert dm["fallback_provider"] == "cryptodatadownload"

    @mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-api-key-mock"}, clear=True)
    def test_csp_and_lbpsp_differ(self) -> None:
        bars = _massive_bars(n=180, start="2024-01-01")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._make_config(tmpdir, ["cash_secured_put", "long_btc_plus_short_put"])
            output_dir = os.path.join(tmpdir, "results")

            with mock.patch.object(MassiveSpotProvider, "fetch_bars", return_value=bars):
                rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
                assert rc == 0

            with open(os.path.join(output_dir, "strategy_comparison.csv")) as f:
                import csv
                rows = list(csv.DictReader(f))
            csp = next((r for r in rows if r["strategy_id"] == "cash_secured_put"), None)
            lbpsp = next((r for r in rows if r["strategy_id"] == "long_btc_plus_short_put"), None)
            assert csp is not None
            assert lbpsp is not None
            assert csp["total_pnl_pct"] != lbpsp["total_pnl_pct"], "CSP and LBPSP must differ"

    @mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-api-key-mock"}, clear=True)
    def test_required_parquet_files_written(self) -> None:
        bars = _massive_bars(n=180, start="2024-01-01")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._make_config(tmpdir, ["unhedged_baseline", "covered_call", "collar"])
            output_dir = os.path.join(tmpdir, "results")

            with mock.patch.object(MassiveSpotProvider, "fetch_bars", return_value=bars):
                rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
                assert rc == 0

            expected_files = [
                "backtest_results.parquet",
                "oos_results.parquet",
                "regime_results.parquet",
                "monte_carlo_results.parquet",
                "stress_results.parquet",
                "execution_sensitivity.parquet",
                "strategy_comparison.csv",
                "research_report.md",
                "presentation_summary.md",
            ]
            for fn in expected_files:
                fpath = os.path.join(output_dir, fn)
                assert os.path.exists(fpath), f"Missing: {fn}"
                assert os.path.getsize(fpath) > 0, f"Empty: {fn}"

    @mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-api-key-mock"}, clear=True)
    def test_manifests_complete(self) -> None:
        bars = _massive_bars(n=100, start="2024-01-01")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._make_config(tmpdir, ["unhedged_baseline", "covered_call"])
            output_dir = os.path.join(tmpdir, "results")

            with mock.patch.object(MassiveSpotProvider, "fetch_bars", return_value=bars):
                rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
                assert rc == 0

            with open(os.path.join(output_dir, "run_manifest.json")) as f:
                rm = json.load(f)
            assert rm["status"] == "completed"
            assert len(rm["data_sources"]) > 0
            assert rm["data_sources"][0]["source"] == "massive"
            assert rm["data_sources"][0]["record_count"] == 100

            with open(os.path.join(output_dir, "data_manifest.json")) as f:
                dm = json.load(f)
            assert dm["actual_provider"] == "massive"
            assert dm["observation_count"] == 100
            assert dm["actual_start"] is not None
            assert dm["actual_end"] is not None
            assert dm["retrieval_timestamp"] is not None
            assert dm["checksum"] != ""

    @mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-api-key-mock"}, clear=True)
    def test_invalid_outputs_not_marked_completed(self) -> None:
        bars = _massive_bars(n=0, start="2024-01-01")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._make_config(tmpdir, ["unhedged_baseline"])
            output_dir = os.path.join(tmpdir, "results")

            with mock.patch.object(MassiveSpotProvider, "fetch_bars", return_value=bars):
                rc = run_research(config_path=config_path, output_dir=output_dir, resume=False)
                assert rc != 0

            with open(os.path.join(output_dir, "run_status.json")) as f:
                st = json.load(f)
            assert st["status"] == "failed"
