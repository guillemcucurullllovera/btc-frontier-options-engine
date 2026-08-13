#!/usr/bin/env python3
"""Historical ARPE across the FREE monthly Tardis surfaces (E1 · Aug-2026).

For every monthly OBSERVED surface under
``market_snapshots/deribit_surface_history_free/<YYYY-MM>/surface.json`` this fits the arb-free
per-slice SVI surface (``vol.chain_surface.fit_svi_surface``) and measures the price-space
repricing ARPE on the tradeable core (|delta| in [0.10,0.90]) via ``vol.reprice_gate`` — the
exact D2 pipeline, now run across ~89 snapshots instead of the single 2026-07-30 fixture.

Question answered: does the <=2% tradeable-core result hold OVER TIME and ACROSS REGIMES?

Provenance: CALCULATED from OBSERVED (Tardis first-of-month Deribit marks).
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.data_models import BookSummary  # noqa: E402
from vol.chain_surface import slices_from_book_summaries  # noqa: E402
from vol.reprice_gate import (  # noqa: E402
    price_reprice_report,
    spreads_from_book_summaries,
    svi_iv_getter,
)

SURF_ROOT = ROOT / "market_snapshots" / "deribit_surface_history_free"


def load_books(surface_json: pathlib.Path, ref: datetime) -> list[BookSummary]:
    data = json.loads(surface_json.read_text())
    out: list[BookSummary] = []
    for r in data["rows"]:
        try:
            out.append(BookSummary(
                instrument_name=r["instrument_name"],
                mark_price=r["mark_price"],
                mark_iv=r["mark_iv"],
                bid_price=r["bid_price"],
                bid_iv=r["bid_iv"],
                ask_price=r["ask_price"],
                ask_iv=r["ask_iv"],
                open_interest=r["open_interest"],
                underlying_price=r["underlying_price"],
                timestamp=ref,
            ))
        except Exception:
            continue
    return out


def analyse_month(month_dir: pathlib.Path) -> dict | None:
    sj = month_dir / "surface.json"
    if not sj.exists():
        return None
    y, m = map(int, month_dir.name.split("-"))
    ref = datetime(y, m, 1, 0, 0, tzinfo=UTC)
    books = load_books(sj, ref)
    slices = slices_from_book_summaries(books, reference=ref, min_strikes=5)
    slices = [s for s in slices if s.T * 365.0 >= 14.0]  # match D2 t_floor
    if len(slices) < 1:
        return {"month": month_dir.name, "ok": False, "reason": "no 14d+ slices",
                "n_books": len(books)}
    smap = spreads_from_book_summaries(books)
    out: dict[str, object] = {"month": month_dir.name, "ok": True,
                              "n_books": len(books), "n_slices": len(slices),
                              "spot": float(np.median([s.forward for s in slices]))}
    for lo, hi, key in [(0.10, 0.90, "b1090"), (0.15, 0.85, "b1585"), (0.05, 0.95, "b0595")]:
        rep = price_reprice_report(slices, svi_iv_getter(slices), delta_band=(lo, hi),
                                   spread_map=smap)
        out[key] = {
            "arpe_core": round(rep.arpe_core * 100, 4),
            "iv_rmse_core": round(rep.iv_rmse_core * 100, 3),
            "within_spread": round(rep.within_spread_frac_core * 100, 1)
            if np.isfinite(rep.within_spread_frac_core) else None,
            "n_core": rep.n_core,
            "arpe_all": round(rep.arpe_all * 100, 4),
            "n_all": rep.n_all,
        }
    return out


def main() -> int:
    dirs = sorted(d for d in SURF_ROOT.iterdir() if d.is_dir())
    results = []
    for d in dirs:
        try:
            r = analyse_month(d)
        except Exception as e:  # noqa: BLE001
            r = {"month": d.name, "ok": False, "reason": f"{type(e).__name__}: {e}"}
        if r is None:
            continue
        results.append(r)
        if r.get("ok"):
            c = r["b1090"]
            print(f"{r['month']}  spot=${r['spot']:>9,.0f}  slices={r['n_slices']:2d}  "
                  f"core[.10-.90] ARPE={c['arpe_core']:5.2f}%  n={c['n_core']:3d}  "
                  f"within={c['within_spread']}%  whole={c['arpe_all']:5.2f}%")
        else:
            print(f"{r['month']}  SKIP: {r.get('reason')}")

    ok = [r for r in results if r.get("ok")]
    arpe = np.array([r["b1090"]["arpe_core"] for r in ok])
    arpe15 = np.array([r["b1585"]["arpe_core"] for r in ok])
    arpe05 = np.array([r["b0595"]["arpe_core"] for r in ok])
    allc = np.array([r["b1090"]["arpe_all"] for r in ok])
    summary = {
        "n_months_ok": len(ok),
        "core_1090": {
            "median": round(float(np.median(arpe)), 3),
            "mean": round(float(np.mean(arpe)), 3),
            "p25": round(float(np.percentile(arpe, 25)), 3),
            "p75": round(float(np.percentile(arpe, 75)), 3),
            "min": round(float(arpe.min()), 3), "max": round(float(arpe.max()), 3),
            "frac_le_2pct": round(float(np.mean(arpe <= 2.0)), 3),
            "frac_le_2p5pct": round(float(np.mean(arpe <= 2.5)), 3),
        },
        "core_1585_median": round(float(np.median(arpe15)), 3),
        "core_0595_median": round(float(np.median(arpe05)), 3),
        "whole_chain_median": round(float(np.median(allc)), 3),
    }
    outp = SURF_ROOT / "_hist_arpe.json"
    outp.write_text(json.dumps({"summary": summary, "months": results}, indent=2))
    print("\n=== HISTORICAL ARPE SUMMARY (tradeable core |delta| 0.10-0.90) ===")
    print(json.dumps(summary, indent=2))
    print("written:", outp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
