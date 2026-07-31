#!/usr/bin/env python3
"""Cross-temporal Q-calibration + residual tracking over the Deribit surface archive (C10 · N2).

SIMULATED / diagnostic; MS-26-gated; OBSERVED surfaces; deck & canonical main untouched. Re-calibrates a
Q model (Heston) to each daily surface in market_snapshots/deribit_surface_archive/ and tracks the
parameter path + calibration residual (ARPE / RMSE_IV) over time — the cross-temporal Q-stability that
Phase E flagged as data-gated. **DATA-GATED:** produces a stability series only once the archive has
accrued >= 2 days (weeks for a meaningful series, or a paid backfill); with a single day it runs a
one-point smoke and reports the accrual status. Writes docs/reports/c10_n2_q_archive.json.

Usage:  python scripts/cross_temporal_q.py
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.data_models import BookSummary, OptionInstrument
from vol.calibrate import calibrate_heston
from vol.chain_surface import ingest_chain_slices

_ARCHIVE = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "deribit_surface_archive"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c10_n2_q_archive.json"


def _calibrate_date(date_dir: pathlib.Path) -> dict[str, Any] | None:
    insts = [OptionInstrument.model_validate(d)
             for d in json.loads((date_dir / "instruments.json").read_text())]
    books = [BookSummary.model_validate(d)
             for d in json.loads((date_dir / "book_summary.json").read_text())]
    ref = datetime.fromisoformat(date_dir.name + "T00:00:00+00:00")
    slices = ingest_chain_slices(insts, books, ref)
    if len([s for s in slices if s.k.size >= 5 and s.T >= 14.0 / 365.0]) < 2:
        return None
    cal = calibrate_heston(slices, n_starts=2, N=96, L=12.0)
    p = cal.params
    return {"date": date_dir.name, "arpe": cal.arpe, "rmse_iv": cal.rmse_iv, "n_options": cal.n_options,
            "v0": p.v0, "kappa": p.kappa, "theta": p.theta, "vol_of_vol": p.vol_of_vol, "rho": p.rho,
            "atm_vol": math.sqrt(max(p.theta, 0.0))}


def main() -> int:
    dates = sorted(d for d in _ARCHIVE.glob("*") if d.is_dir() and (d / "instruments.json").exists())
    per_day = [row for d in dates if (row := _calibrate_date(d)) is not None]

    stability: dict[str, Any] = {}
    if len(per_day) >= 2:
        for key in ("arpe", "atm_vol", "kappa", "vol_of_vol", "rho"):
            a = np.array([row[key] for row in per_day], dtype=np.float64)
            stability[key] = {"min": float(a.min()), "max": float(a.max()), "mean": float(a.mean()),
                              "cov": float(a.std() / abs(a.mean())) if a.mean() != 0 else float("nan")}

    n = len(per_day)
    status = ("MATURE — cross-temporal Q-stability series available" if n >= 20 else
              f"ACCRUING — {n} day(s) archived; a meaningful stability series needs weeks of daily "
              f"accrual (or a paid backfill). The pipeline is READY; it is DATA-GATED on the archive.")
    out = {
        "generated_utc": datetime.now(UTC).isoformat(), "n_days": n, "status": status,
        "per_day": per_day, "stability": stability,
        "data_gate": ("Cross-temporal Q-calibration requires historical option SURFACES. This pipeline runs "
                      "per archived day and is ready; results are gated on the daily archiver accruing "
                      "(scripts/deribit_surface_archiver.py) or a paid backfill (see c10_n2_q_archive.md)."),
    }
    _OUT.write_text(json.dumps(out, indent=2))
    print(f"n_days={n}  status={status}", flush=True)
    for row in per_day:
        print(f"  {row['date']}: ARPE={row['arpe']*100:.2f}% atm_vol={row['atm_vol']:.3f} "
              f"kappa={row['kappa']:.2f} volvol={row['vol_of_vol']:.2f} rho={row['rho']:.3f} "
              f"(n={row['n_options']})", flush=True)
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
