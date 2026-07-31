#!/usr/bin/env python3
"""Full-history 5-minute intraday jump detection by regime (C10 · N3.5.1).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED from OBSERVED Binance 5m returns; deck & canonical main
untouched. Phase B's intraday jump picture (downside asymmetry is a daily/long-history effect; intraday is
symmetric microstructure) used only the recent 90 days of 1m. N3.5.1 tests it across the FULL history and
BY REGIME using 5-minute bars 2019->now (data.binance.vision, no auth), so the conclusion is not a
recent-window artifact. Writes docs/reports/c10_n3_5_intraday.json + a small committed regime fixture; the
raw 5m array is reproducible via the fetch (not committed, ~120 MB).
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sys
from datetime import UTC, datetime

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vol.binance import BinanceKlinesProvider
from vol.jumps import bipower_variation, estimate_jump_params, lee_mykland, log_returns

_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c10_n3_5_intraday.json"
_FIX = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_5m_jumps" / "regime_stats.json"
_DT_5M = 1.0 / (365.0 * 288.0)
_BPY_5M = 365.0 * 288.0
_WINDOW = 120                       # local-bipower window (bars) ~ 10h at 5m
_REGIMES = [
    ("2019_precovid", "2019-01-01", "2020-06-30"), ("2020_21_bull", "2020-07-01", "2021-12-31"),
    ("2022_lunaftx", "2022-01-01", "2022-12-31"), ("2023_24_recovery", "2023-01-01", "2024-06-30"),
    ("2024_26_recent", "2024-07-01", "2026-07-31"),
]


def _month_iter(y0: int, m0: int, y1: int, m1: int) -> list[tuple[int, int]]:
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _fetch_5m() -> tuple[np.ndarray, np.ndarray]:
    prov = BinanceKlinesProvider(interval="5m")
    now = datetime.now(UTC)
    ts: list[str] = []
    close: list[float] = []
    for (y, m) in _month_iter(2019, 1, now.year, now.month):
        try:
            for b in prov.fetch_bulk_month(y, m):
                ts.append(b.timestamp.isoformat()[:10])
                close.append(b.close)
        except Exception as exc:
            print(f"  [warn] 5m {y}-{m:02d}: {type(exc).__name__}", flush=True)
    prov.close()
    return np.array(ts), np.array(close, dtype=np.float64)


def _jump_stats(r: np.ndarray) -> dict[str, float]:
    det = lee_mykland(r, window=_WINDOW, alpha=0.05)
    jp = estimate_jump_params(r, det, dt_years=_DT_5M)
    bpv = bipower_variation(r)
    rv = float(np.sum(r ** 2))
    return {"n_obs": int(r.size), "lam_annual": jp.lam_annual, "frac_downward": jp.frac_downward,
            "eta_downward": jp.eta_downward, "jump_var_share": float(bpv.jump_variation / rv) if rv > 0 else 0.0,
            "realized_vol_annual": float(np.std(r) * math.sqrt(_BPY_5M))}


def main() -> int:
    ts, close = _fetch_5m()
    print(f"5m bars: {close.size} {ts[0]}..{ts[-1]}", flush=True)
    r_all = log_returns(close)
    dates = ts[1:]                                          # aligned to returns

    full = _jump_stats(r_all)
    regimes = {}
    for label, lo, hi in _REGIMES:
        mask = (dates >= lo) & (dates <= hi)
        if mask.sum() > 5000:
            regimes[label] = _jump_stats(r_all[mask])

    etas = [v["eta_downward"] for v in regimes.values()]
    result = {
        "interval": "5m", "n_bars": int(close.size), "start": ts[0], "end": ts[-1],
        "window_bars": _WINDOW, "full_history": full, "by_regime": regimes,
        "eta_range_across_regimes": [float(min(etas)), float(max(etas))],
        "all_intraday_symmetric": all(e < 1.15 for e in etas),
        "note": ("Intraday (5m) jump asymmetry by regime. Tests whether the Phase B finding — downside "
                 "asymmetry is a daily/long-history effect, intraday ~symmetric microstructure — holds "
                 "across ALL regimes (incl. crashes), not just the recent 90 days."),
    }
    _OUT.write_text(json.dumps(result, indent=2))
    _FIX.parent.mkdir(parents=True, exist_ok=True)
    fix = {"by_regime_eta": {k: round(v["eta_downward"], 3) for k, v in regimes.items()},
           "full_eta": round(full["eta_downward"], 3), "n_bars": int(close.size),
           "sha256": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()}
    _FIX.write_text(json.dumps(fix, indent=2))

    print(f"\n{'regime':20}{'n_obs':>10}{'lam/yr':>10}{'frac_dn':>9}{'eta':>7}{'jumpvar':>9}{'rvol':>7}")
    print(f"{'FULL 2019-26':20}{full['n_obs']:10d}{full['lam_annual']:10.0f}{full['frac_downward']:9.3f}"
          f"{full['eta_downward']:7.2f}{full['jump_var_share']:9.3f}{full['realized_vol_annual']:7.2f}")
    for k, v in regimes.items():
        print(f"{k:20}{v['n_obs']:10d}{v['lam_annual']:10.0f}{v['frac_downward']:9.3f}"
              f"{v['eta_downward']:7.2f}{v['jump_var_share']:9.3f}{v['realized_vol_annual']:7.2f}")
    print(f"\neta range across regimes {result['eta_range_across_regimes']}; "
          f"all intraday ~symmetric (<1.15): {result['all_intraday_symmetric']}")
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
