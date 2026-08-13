#!/usr/bin/env python3
"""Cross-temporal robustness: re-estimate P dynamics + vol roughness across regimes (C9 · Phase E).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED from OBSERVED Binance history; frozen Q anchor untouched.
Re-estimates the physical parameters on 6 contiguous regime windows (2017-2026) and reports a STABILITY
TABLE for the dossier: realized vol, GARCH persistence/unconditional vol, jump intensity/asymmetry, an
SV-MLE vol level, and the volatility ROUGHNESS H (Gatheral-Jaisson-Rosenbaum, from daily realized variance
built from the hourly data), plus the VRP against the frozen Q anchor.

DATA-GAP (documented): the Q model (Heston/Bates smile) CANNOT be re-calibrated historically — we hold a
single frozen option chain, not historical surfaces. So Q is held at the frozen anchor (implied ATM ~0.37 /
calibrated Q-vol 0.50) and only the PHYSICAL side is re-estimated per window; the VRP-stability uses that
frozen Q. Writes docs/reports/c9_cross_temporal.json.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vol.filter import sv_mle
from vol.garch import GarchEstimator
from vol.jumps import estimate_jump_params, lee_mykland, log_returns

_HIST = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c9_cross_temporal.json"
_Q_IMPLIED = 0.37                 # frozen anchor ATM implied (DVOL); Q-calibrated vol 0.50 also noted

# Regime windows (contiguous), labelled by the dominant market regime.
_WINDOWS = [
    ("2017-08_2018-12_earlybear", "2017-08-01", "2018-12-31"),
    ("2019-01_2020-06_precovid",  "2019-01-01", "2020-06-30"),
    ("2020-07_2021-12_bull",      "2020-07-01", "2021-12-31"),
    ("2022-01_2022-12_lunaftx",   "2022-01-01", "2022-12-31"),
    ("2023-01_2024-06_recovery",  "2023-01-01", "2024-06-30"),
    ("2024-07_2026-07_recent",    "2024-07-01", "2026-07-31"),
]


def _daily() -> tuple[np.ndarray, np.ndarray]:
    rows = json.loads((_HIST / "1d" / "bars.json").read_text())
    return (np.array([r["timestamp"][:10] for r in rows]),
            np.array([r["close"] for r in rows], dtype=np.float64))


def _daily_rv_from_hourly() -> tuple[np.ndarray, np.ndarray]:
    rows = json.loads((_HIST / "1h" / "bars.json").read_text())
    ts = np.array([r["timestamp"][:10] for r in rows])
    lr = np.diff(np.log(np.array([r["close"] for r in rows], dtype=np.float64)))
    days = ts[1:]
    uniq = np.array(sorted(set(days)))
    rv = np.array([np.sum(lr[days == d] ** 2) for d in uniq])
    return uniq, rv


def _hurst_gjr(rv: np.ndarray, qs: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)) -> float:
    """Roughness H from the scaling of log-realized-vol increments: m(q,Delta) ~ Delta^{qH}."""
    ell = 0.5 * np.log(np.maximum(rv, 1e-12))
    hs = []
    for q in qs:
        logm, logd = [], []
        for d in range(1, min(30, rv.size // 4)):
            inc = np.abs(ell[d:] - ell[:-d]) ** q
            if inc.size > 5:
                logm.append(math.log(float(np.mean(inc))))
                logd.append(math.log(d))
        if len(logd) > 3:
            hs.append(float(np.polyfit(logd, logm, 1)[0]) / q)
    return float(np.mean(hs)) if hs else float("nan")


def main() -> int:
    dates, close = _daily()
    rv_dates, rv = _daily_rv_from_hourly()
    windows = []
    for label, lo, hi in _WINDOWS:
        m = (dates[1:] >= lo) & (dates[1:] <= hi)          # returns aligned to dates[1:]
        r = log_returns(close)[m]
        if r.size < 120:
            continue
        rvol = float(np.std(r) * math.sqrt(365))
        g = GarchEstimator(r).fit()
        jp = estimate_jump_params(r, lee_mykland(r, window=20, alpha=0.05), dt_years=1.0 / 365.0)
        svm = sv_mle(r, dt=1.0 / 365.0)
        rvm = (rv_dates >= lo) & (rv_dates <= hi)
        seg = rv[rvm]
        hurst = _hurst_gjr(seg) if seg.size > 120 else None
        windows.append({
            "window": label, "n_obs": int(r.size), "start": lo, "end": hi,
            "realized_vol_annual": rvol,
            "garch_persistence": g.params.persistence,
            "garch_uncond_vol_annual": g.params.unconditional_vol * math.sqrt(365),
            "jump_lam_annual": jp.lam_annual, "jump_eta_downward": jp.eta_downward,
            "jump_frac_downward": jp.frac_downward,
            "svmle_theta_vol_annual": math.sqrt(max(svm.theta, 0.0)),
            "roughness_H": hurst,
            "vrp_vs_frozen_Q": _Q_IMPLIED - rvol,          # implied(0.37) - realized
        })

    def _stab(key: str) -> dict[str, float]:
        vals = [w[key] for w in windows if w[key] is not None]
        a = np.array(vals, dtype=np.float64)
        return {"min": float(a.min()), "max": float(a.max()), "mean": float(a.mean()),
                "cov": float(a.std() / abs(a.mean())) if a.mean() != 0 else float("nan")}

    stability = {k: _stab(k) for k in (
        "realized_vol_annual", "garch_persistence", "garch_uncond_vol_annual",
        "jump_lam_annual", "jump_eta_downward", "svmle_theta_vol_annual", "roughness_H", "vrp_vs_frozen_Q")}

    out = {
        "q_recalibration": ("NOT POSSIBLE across history: only one frozen option chain exists (no historical "
                            "surfaces). Q held at the frozen anchor (ATM implied ~0.37 / calibrated Q-vol 0.50); "
                            "only P re-estimated per window; VRP-stability uses the frozen Q."),
        "windows": windows, "stability": stability, "q_implied_frozen": _Q_IMPLIED,
        "roughness_note": ("H from daily RV (hourly-built, 2019+); RV measurement noise biases H DOWN, so the "
                           "true H may be somewhat higher. Consistent with Phase A Q-surface H~0.20 -> vol is ROUGH."),
    }
    _OUT.write_text(json.dumps(out, indent=2))

    print(f"{'window':30}{'n':>5}{'rvol':>7}{'persist':>8}{'uncvol':>7}{'lam':>6}{'eta':>6}{'H':>7}{'VRP':>7}")
    for w in windows:
        h = f"{w['roughness_H']:.3f}" if w["roughness_H"] is not None else "  n/a"
        print(f"{w['window']:30}{w['n_obs']:5d}{w['realized_vol_annual']:7.2f}{w['garch_persistence']:8.3f}"
              f"{w['garch_uncond_vol_annual']:7.2f}{w['jump_lam_annual']:6.1f}{w['jump_eta_downward']:6.2f}"
              f"{h:>7}{w['vrp_vs_frozen_Q']:7.2f}", flush=True)
    print("\nstability (min/max/CoV):")
    for k, s in stability.items():
        print(f"  {k:26} {s['min']:.3f} / {s['max']:.3f} / CoV {s['cov']:.2f}", flush=True)
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
