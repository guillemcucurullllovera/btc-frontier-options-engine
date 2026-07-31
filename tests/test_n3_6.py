"""C10 · N3.6 — observed co-jump identification (free μ_v upgrade).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED from OBSERVED data; deck & canonical main untouched. Locks
the observed co-jump: on spot-jump days (2021-2026 DVOL overlap) the price-jump and DVOL-change are strongly
NEGATIVELY correlated (rho_J ~ -0.74, significant) and the leverage is asymmetric (down-jumps spike DVOL far
more than up-jumps) — the co-jump direction/strength is now directly observed, not assumed. Recomputed from
the committed DVOL + Binance daily (not just reading the generated JSON).
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np

from vol.jumps import lee_mykland, log_returns

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DVOL = _ROOT / "market_snapshots" / "deribit_dvol_history" / "dvol_daily.json"
_SPOT = _ROOT / "market_snapshots" / "binance_history" / "1d" / "bars.json"


def _cojump() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dvol = {x["date"]: float(x["dvol"]) for x in json.loads(_DVOL.read_text())}
    bars = json.loads(_SPOT.read_text())
    dates = [b["timestamp"][:10] for b in bars]
    r = log_returns(np.array([b["close"] for b in bars], dtype=np.float64))
    rdates = dates[1:]
    dv_t = np.array([dvol.get(d, np.nan) for d in rdates])
    dv_prev = np.array([dvol.get(dates[i], np.nan) for i in range(len(rdates))])
    ddvol = dv_t - dv_prev
    dvar = dv_t ** 2 - dv_prev ** 2
    jd = lee_mykland(r, window=20, alpha=0.05).is_jump & ~np.isnan(ddvol)
    return r[jd], ddvol[jd], dvar[jd]


def test_observed_cojump_rho_negative_significant_and_asymmetric() -> None:
    sj, dd, _ = _cojump()
    n = sj.size
    assert n >= 15                                              # ~20 spot-jump days in the overlap
    rho = float(np.corrcoef(sj, dd)[0, 1])
    rho_se = (1 - rho ** 2) / math.sqrt(max(n - 2, 1))
    assert rho < -0.4                                           # strong negative price-vol co-jump
    assert abs(rho) > 2 * rho_se                                # significant (decision-grade sign/strength)
    # asymmetric leverage: down-jumps spike implied vol far more than up-jumps
    assert float(np.mean(dd[sj < 0])) > float(np.mean(dd[sj > 0]))


def test_observed_muv_has_real_magnitude() -> None:
    """The implied-variance jump on co-jump days is materially positive (mu_v is data-anchored, ~>=0.10)."""
    _, dd, dvar = _cojump()
    assert float(np.mean(dvar)) > 0.05                         # implied-var jump ~0.11 -> mu_v lower bound ~0.12
    assert float(np.mean(dd)) > 0.03                           # DVOL rises on jump days (not ~0 like baseline)
