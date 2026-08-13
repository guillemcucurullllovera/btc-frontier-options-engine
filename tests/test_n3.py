"""C10 · N3 — free Q-vol stability + PF-based parameter uncertainty (last MS-25 condition).

SIMULATED / diagnostic; MS-26-gated; OBSERVED / P-ESTIMATED; deck & canonical main untouched. Locks:
(N3.1) the free DVOL Q-vol level halved 2021->2026 and the forward VRP is positive (recomputed from the
committed DVOL + Binance daily); (N3.3) the particle filter is healthy on the real returns (validated
operational parameter-uncertainty source); (N3.2) the committed SVCJ-retry result shows convergence
improving on shorter windows but still not converging (returns-only weak identification).
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np

from vol.filter import bootstrap_particle_filter
from vol.jumps import log_returns

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DVOL = _ROOT / "market_snapshots" / "deribit_dvol_history" / "dvol_daily.json"
_SPOT = _ROOT / "market_snapshots" / "binance_history" / "1d" / "bars.json"


def test_free_dvol_qvol_declines_and_forward_vrp_positive() -> None:
    """N3.1: DVOL (Q ATM) halves 2021->2026 and implied exceeds 30d-forward realized on most days."""
    meta = json.loads((_DVOL.parent / "meta.json").read_text())
    assert meta["source"] == "deribit" and meta["provenance"] == "OBSERVED" and len(meta["sha256"]) == 64
    dvol = {x["date"]: float(x["dvol"]) for x in json.loads(_DVOL.read_text())}
    assert len(dvol) > 1500                                     # ~1955 daily DVOL obs (2021-2026)
    y2021 = np.mean([v for d, v in dvol.items() if d[:4] == "2021"])
    y2026 = np.mean([v for d, v in dvol.items() if d[:4] == "2026"])
    assert y2021 > 0.8 and y2026 < 0.55 and y2021 > 1.6 * y2026     # Q-ATM-vol roughly halved

    bars = json.loads(_SPOT.read_text())
    dates = [b["timestamp"][:10] for b in bars]
    lr = np.diff(np.log(np.array([b["close"] for b in bars], dtype=np.float64)))
    idx = {d: i for i, d in enumerate(dates[1:])}
    vrps = [dvol[d] - float(np.std(lr[i:i + 30]) * math.sqrt(365))
            for d in dvol if (i := idx.get(d)) is not None and i + 30 < lr.size]
    assert np.mean(np.array(vrps) > 0) > 0.6                    # forward VRP positive most days (~0.75)


def test_pf_healthy_on_real_returns() -> None:
    """N3.3: the particle filter (the validated operational uncertainty source) has a healthy ESS."""
    r = log_returns(np.array([b["close"] for b in json.loads(_SPOT.read_text())], dtype=np.float64))
    theta = float(np.var(r) * 365)
    pf = bootstrap_particle_filter(r, kappa=3.0, theta=theta, vol_of_vol=0.8, dt=1 / 365, n_particles=1200)
    assert float(np.mean(pf.ess)) > 300.0                      # healthy effective sample size
    assert np.all(pf.filtered_variance > 0)


def test_svcj_retry_improves_on_shorter_windows() -> None:
    """N3.2: the committed retry shows worst R-hat DECREASING full->3yr->2yr (non-stationarity part of it),
    but still not converging (weak returns-only identification -> PF fallback)."""
    d = json.loads((_ROOT / "docs" / "reports" / "c10_n3_svcj_retry.json").read_text())
    by = {row["label"]: row for row in d["results"]}
    assert by["full_2017_2026"]["worst_rhat"] > by["recent_2yr_stationary"]["worst_rhat"]
    assert not any(row["converged_all"] for row in d["results"])   # none fully converge (honest)
