#!/usr/bin/env python3
"""Free cross-temporal Q-vol stability + VRP-over-time from DVOL (C10 · N3.1).

SIMULATED / diagnostic; MS-26-gated; OBSERVED; deck & canonical main untouched. Uses the FREE Deribit DVOL
history (ATM Q-vol level, 2021-2026) + the Binance realized returns to deliver the cross-temporal Q-vol
stability and the honest implied-vs-realized VRP over time — the free replacement for the paid-backfill
Q-stability (Phase E / N2 data gap), at the ATM level. Full-smile Q-stability still awaits the forward
archiver accruing or a reconstruction (coverage caveat documented). Writes docs/reports/c10_n3_q_vol_stability.json.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DVOL = _ROOT / "market_snapshots" / "deribit_dvol_history" / "dvol_daily.json"
_SPOT = _ROOT / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_OUT = _ROOT / "docs" / "reports" / "c10_n3_q_vol_stability.json"
_FWD = 30                                           # DVOL is 30d ATM IV -> compare to 30d-forward realized


def main() -> int:
    dvol = {x["date"]: float(x["dvol"]) for x in json.loads(_DVOL.read_text())}
    bars = json.loads(_SPOT.read_text())
    dates = [b["timestamp"][:10] for b in bars]
    close = np.array([b["close"] for b in bars], dtype=np.float64)
    logret = np.diff(np.log(close))                 # aligned to dates[1:]
    idx = {d: i for i, d in enumerate(dates[1:])}

    days: list[str] = []
    dv: list[float] = []
    rvf: list[float] = []
    for d, q in sorted(dvol.items()):
        i = idx.get(d)
        if i is None or i + _FWD >= len(logret):
            continue
        days.append(d)
        dv.append(q)
        rvf.append(float(np.std(logret[i:i + _FWD]) * math.sqrt(365)))   # 30d-forward realized (annualised)
    dvols, rvfs = np.array(dv), np.array(rvf)
    vrps = dvols - rvfs
    years = sorted({d[:4] for d in days})
    yr_arr = np.array([d[:4] for d in days])
    by_year: dict[str, dict[str, float]] = {
        yr: {"dvol_q_atm": float(dvols[yr_arr == yr].mean()),
             "rv_fwd_realized": float(rvfs[yr_arr == yr].mean()),
             "vrp_implied_minus_realized": float(vrps[yr_arr == yr].mean())}
        for yr in years}
    q_lo, q_hi = float(dvols.min()), float(dvols.max())
    q_cov, vrp_mean, vrp_fpos = float(dvols.std() / dvols.mean()), float(vrps.mean()), float(np.mean(vrps > 0))
    stability: dict[str, object] = {
        "q_atm_vol_range": [q_lo, q_hi], "q_atm_vol_cov": q_cov,
        "vrp_mean": vrp_mean, "vrp_frac_positive": vrp_fpos, "n_days": len(days),
    }
    out = {
        "source": "free Deribit DVOL (ATM Q-vol) + Binance realized returns",
        "coverage": ("ATM Q-vol level ONLY (DVOL = 30d ATM IV), 2021-2026, from FREE data. Full-smile "
                     "cross-temporal Q-stability (skew/term-structure) still awaits the forward archiver "
                     "accruing or a trade-reconstruction; a paid backfill is an OPTIONAL accelerant, not "
                     "required for the ATM-level signal."),
        "by_year": by_year, "stability": stability,
        "note": "VRP = DVOL_t (implied) - realized vol over [t, t+30d]. Positive => vol sellers earn.",
    }
    _OUT.write_text(json.dumps(out, indent=2))

    print(f"{'year':6}{'DVOL(Q ATM)':>13}{'RV_fwd(P)':>11}{'VRP':>9}")
    for yr, v in by_year.items():
        print(f"{yr:6}{v['dvol_q_atm']:13.3f}{v['rv_fwd_realized']:11.3f}{v['vrp_implied_minus_realized']:9.3f}")
    print(f"\nQ-ATM-vol range {q_lo:.2f}-{q_hi:.2f} (CoV {q_cov:.2f}); "
          f"VRP mean {vrp_mean:+.3f}, frac+ {vrp_fpos:.2f} over {len(days)} days")
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
