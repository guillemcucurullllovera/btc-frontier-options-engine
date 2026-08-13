"""C9 · Phase B — Binance physical re-estimation (hermetic, committed-daily-data findings).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED from OBSERVED Binance BTCUSDT returns; frozen Q anchor
untouched. Locks the headline correction to M4.6: with the SAME jump detector, the downside jump-size
asymmetry emerges over the full 2017-2026 daily history but is near-symmetric over the last 2 years — i.e.
the M4.6 "symmetric daily" picture was a 2-year-window artifact, not a property of BTC.

Reads only the committed daily snapshot + all three meta.json (the large intraday raw arrays are
reproducible via scripts/fetch_binance_history.py and are gitignored). The intraday multi-frequency
numbers live in docs/reports/c9_binance_reestimation.{md,json}.
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np

from vol.garch import GarchEstimator
from vol.jumps import estimate_jump_params, lee_mykland, log_returns

_HIST = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history"


def _daily_closes() -> np.ndarray:
    rows = json.loads((_HIST / "1d" / "bars.json").read_text())
    return np.array([x["close"] for x in rows], dtype=np.float64)


def _eta(r: np.ndarray, alpha: float) -> float:
    jp = estimate_jump_params(r, lee_mykland(r, window=20, alpha=alpha), dt_years=1.0 / 365.0)
    return jp.eta_downward


def test_binance_snapshots_meta_observed() -> None:
    """All three interval snapshots have OBSERVED provenance, a sha256, the basis caveat, sane counts."""
    mins = {"1d": 2900, "1h": 60000, "1m": 120000}
    for interval, floor in mins.items():
        meta = json.loads((_HIST / interval / "meta.json").read_text())
        assert meta["source"] == "binance" and meta["symbol"] == "BTCUSDT"
        assert meta["provenance"] == "OBSERVED"
        assert len(meta["sha256"]) == 64                    # sha256 present
        assert "basis_caveat" in meta and "USDT" in meta["basis_caveat"]
        assert meta["n_bars"] >= floor


def test_full_daily_history_loaded_observed() -> None:
    rows = json.loads((_HIST / "1d" / "bars.json").read_text())
    assert len(rows) > 2900                                 # ~3270 daily bars, ~8.5 years
    assert rows[0]["timestamp"].startswith("2017")          # back to 2017
    assert all(r["provenance"] == "observed" and r["close"] > 0 for r in rows[:50])
    assert all(r["origin"] == "binance" for r in rows[:50])


def test_downside_asymmetry_emerges_over_full_history() -> None:
    """THE finding: same detector (alpha=0.05), full history is more downside-asymmetric than the last 2yr."""
    r = log_returns(_daily_closes())
    eta_full = _eta(r, 0.05)
    eta_2yr = _eta(r[-730:], 0.05)
    assert eta_full > 1.2                                   # meaningful downside size asymmetry over 8.5yr
    assert eta_full > eta_2yr + 0.15                        # ... that the 2yr window (M4.6) understated
    assert eta_2yr < 1.25                                   # last-2yr reproduces the ~symmetric M4.6 picture


def test_daily_garch_high_vol_over_full_history() -> None:
    """Full-history GARCH converges with a HIGH annualised unconditional vol (crash regimes included)."""
    g = GarchEstimator(log_returns(_daily_closes())).fit()
    assert g.convergence and 0.0 < g.params.persistence < 1.0
    uncond_annual = g.params.unconditional_vol * math.sqrt(365.0)   # property is per-bar (daily)
    assert 0.55 < uncond_annual < 1.05                     # ~0.77, well above the 2yr ~0.46
