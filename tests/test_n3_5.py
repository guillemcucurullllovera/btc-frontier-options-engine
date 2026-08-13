"""C10 · N3.5 — free-data solidification (intraday jump evidence + free-API coverage limit).

SIMULATED / diagnostic; MS-26-gated; deck & canonical main untouched. Locks: (N3.5.1) intraday (5m) jump
asymmetry is MILD in every regime (η well below the daily 1.42) — the downside asymmetry is a daily-scale,
all-regime feature, not a recent-window artifact; (N3.5.2) the recent traded smile reconstructs but the
Deribit FREE API exposes no HISTORICAL option trades (documented coverage limit). Both read committed
evidence (the raw 5m array + live trades are reproducible, not committed).
"""

from __future__ import annotations

import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FIX = _ROOT / "market_snapshots" / "binance_5m_jumps" / "regime_stats.json"
_SMILE = _ROOT / "docs" / "reports" / "c10_n3_5_trade_smile.json"
_DAILY_ETA = 1.42                                       # Phase B full-history DAILY downside asymmetry


def test_intraday_symmetric_across_all_regimes() -> None:
    fix = json.loads(_FIX.read_text())
    assert fix["n_bars"] > 700_000                     # ~787k 5m bars, 2019-2026
    etas = list(fix["by_regime_eta"].values())
    assert len(etas) >= 4
    assert max(etas) < 1.25                            # intraday MILD in every regime (incl. crashes)
    assert fix["full_eta"] < 1.25                      # full-history intraday ~symmetric
    assert max(etas) < _DAILY_ETA - 0.15               # ... and clearly below the DAILY asymmetry (1.42)


def test_trade_smile_recent_works_historical_free_limit() -> None:
    d = json.loads(_SMILE.read_text())
    assert d["provenance"] == "OBSERVED" and len(d["sha256"]) == 64
    assert d["recent_smile_n_strikes"] >= 5            # recent reconstruction mechanism works
    # the documented FREE-API coverage limit: historical windows return no trades
    assert all(n == 0 for n in d["historical_window_probe_n_trades"].values())
    assert "not free-feasible" in d["coverage_limit"].lower() or "not" in d["coverage_limit"].lower()
