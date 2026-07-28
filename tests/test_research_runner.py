"""Research runner tests — smoke test for the full pipeline."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from research.runner import run_research


class TestResearchRunner:
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
                "execution": {"deterministic_seeds": True, "base_seed": 42, "enable_checkpoints": True, "resume": True, "max_workers": 1},
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
