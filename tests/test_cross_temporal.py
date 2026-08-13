"""C9 · Phase E — cross-temporal robustness (regime stability of the physical dynamics).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED; frozen Q anchor untouched. Locks the dossier findings:
(1) realized vol SECULARLY DECLINES (early regime >> recent), (2) the VRP vs the frozen Q is negative in
every regime but shrinks toward neutral, (3) volatility roughness H is structurally LOW in every regime
(vol is rough regardless of the market state). Vol/VRP are recomputed from the committed daily bars; the
roughness H (needs the gitignored hourly RV) is read from the committed cross-temporal JSON artifact.
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np

from vol.jumps import log_returns

_HIST = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history"
_JSON = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c9_cross_temporal.json"
_Q_IMPLIED = 0.37


def _rvol(lo: str, hi: str) -> float:
    rows = json.loads((_HIST / "1d" / "bars.json").read_text())
    dates = np.array([r["timestamp"][:10] for r in rows])
    close = np.array([r["close"] for r in rows], dtype=np.float64)
    m = (dates[1:] >= lo) & (dates[1:] <= hi)
    return float(np.std(log_returns(close)[m]) * math.sqrt(365))


def test_vol_secularly_declines() -> None:
    early = _rvol("2017-08-01", "2018-12-31")
    recent = _rvol("2024-07-01", "2026-07-31")
    assert early > 0.75                                    # ~0.92 in the early regime
    assert recent < 0.60                                   # ~0.46 recently
    assert early > recent + 0.25                           # vol roughly halved over the sample


def test_vrp_negative_every_regime_but_shrinks() -> None:
    early_vrp = _Q_IMPLIED - _rvol("2017-08-01", "2018-12-31")
    recent_vrp = _Q_IMPLIED - _rvol("2024-07-01", "2026-07-31")
    assert early_vrp < 0.0 and recent_vrp < 0.0           # realized > frozen implied in both -> negative VRP
    assert early_vrp < recent_vrp - 0.2                    # far more negative early; near-neutral recently


def test_roughness_structurally_low_all_regimes() -> None:
    """Every window with realized-variance data is rough (H well below 0.5)."""
    data = json.loads(_JSON.read_text())
    hs = [w["roughness_H"] for w in data["windows"] if w["roughness_H"] is not None]
    assert len(hs) >= 4
    assert all(h < 0.15 for h in hs)                       # rough in every regime (H ~0.02-0.10)
    # and the roughness cross-check to Phase A is recorded
    assert "rough" in data["roughness_note"].lower()
