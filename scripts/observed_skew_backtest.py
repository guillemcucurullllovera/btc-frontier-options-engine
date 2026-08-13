#!/usr/bin/env python3
"""Monthly-cadence 40% laddered covered-call backtest priced off OBSERVED SKEW (E1 · Aug-2026).

For each monthly OBSERVED surface (Tardis first-of-month, or a raw Deribit archive day) this:
  1. fits the arb-free SVI surface, picks the listed expiry nearest ``--dte`` days,
  2. prices the 40% laddered covered call (12,000 BTC = 4x3,000 at +4/+6.67/+9.33/+12% OTM)
     off the OBSERVED per-strike skew (SVI-interpolated IV at each ladder strike) via Black-76,
  3. (if a forward Binance path exists) realizes the short-call P&L at entry+DTE and the VRP
     (ATM implied IV vs realized vol over the holding month).

Income is the sum of the four tranche premiums on 12,000 BTC -> re-tied to the authoritative
$10.6M/cycle. Provenance: premiums CALCULATED from OBSERVED skew; realized P&L CALCULATED from
OBSERVED Binance spot; VRP = OBSERVED implied vs OBSERVED realized.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.data_models import BookSummary  # noqa: E402
from pricing.black76 import price_black76  # noqa: E402
from vol.chain_surface import fit_svi_surface, slices_from_book_summaries  # noqa: E402

SURF_ROOT = ROOT / "market_snapshots" / "deribit_surface_history_free"
BINANCE_1D = ROOT / "market_snapshots" / "binance_history_full" / "1d" / "bars.json"

BLOCK_BTC = 30_000.0
COVER_FRAC = 0.40
LADDER_PCTS = (0.04, 0.0667, 0.0933, 0.12)   # +4/+6.67/+9.33/+12%
TRANCHE_BTC = BLOCK_BTC * COVER_FRAC / len(LADDER_PCTS)   # 3,000 each


def load_binance_1d() -> list[tuple[datetime, float]]:
    if not BINANCE_1D.exists():
        return []
    rows = json.loads(BINANCE_1D.read_text())
    return [(datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")), float(r["close"]))
            for r in rows]


def spot_at(path: list[tuple[datetime, float]], when: datetime) -> float | None:
    best = None
    for ts, c in path:
        if ts <= when:
            best = c
        else:
            break
    return best


def books_from_tardis(surface_json: pathlib.Path, ref: datetime) -> list[BookSummary]:
    data = json.loads(surface_json.read_text())
    out = []
    for r in data["rows"]:
        try:
            out.append(BookSummary(
                instrument_name=r["instrument_name"], mark_price=r["mark_price"],
                mark_iv=r["mark_iv"], bid_price=r["bid_price"], bid_iv=r["bid_iv"],
                ask_price=r["ask_price"], ask_iv=r["ask_iv"],
                open_interest=r["open_interest"], underlying_price=r["underlying_price"],
                timestamp=ref))
        except Exception:
            continue
    return out


def books_from_deribit_archive(book_json: pathlib.Path, ref: datetime) -> list[BookSummary]:
    rows = json.loads(book_json.read_text())
    out = []
    for s in rows:
        try:
            out.append(BookSummary(
                instrument_name=s["instrument_name"], mark_price=s.get("mark_price", 0.0),
                mark_iv=s.get("mark_iv") or 0.0, bid_price=s.get("bid_price"),
                bid_iv=s.get("bid_iv"), ask_price=s.get("ask_price"), ask_iv=s.get("ask_iv"),
                open_interest=s.get("open_interest", 0.0),
                underlying_price=s.get("underlying_price", 0.0), timestamp=ref))
        except Exception:
            continue
    return out


def price_cycle(books, ref, dte_target, spot_override=None):
    """Price the laddered CC off the observed skew. Returns dict or None."""
    slices = slices_from_book_summaries(books, reference=ref, min_strikes=5)
    slices = [s for s in slices if s.T * 365.0 >= 7.0]
    if not slices:
        return None
    # spot = median underlying across the chain (index proxy)
    spot = spot_override or float(np.median([b.underlying_price for b in books
                                             if b.underlying_price > 0]))
    # pick expiry nearest dte_target
    tgt = min(slices, key=lambda s: abs(s.T * 365.0 - dte_target))
    fit = fit_svi_surface(slices)
    fitmap = {f.label: f for f in fit.slices}
    f_tgt = fitmap.get(tgt.label)
    F = tgt.forward
    T = tgt.T
    legs = []
    total_prem_usd = 0.0
    for pct in LADDER_PCTS:
        K = spot * (1.0 + pct)
        k = float(np.log(K / F))
        if f_tgt is not None:
            iv = float(f_tgt.params.iv(k))
        else:                        # fallback: interpolate observed mark_iv in k
            iv = float(np.interp(k, tgt.k, tgt.mark_iv))
        prem_per_btc = price_black76(F, K, 0.0, iv, T, "call")   # USD per BTC
        prem_usd = prem_per_btc * TRANCHE_BTC
        total_prem_usd += prem_usd
        legs.append({"pct": pct, "strike": round(K, 1), "iv": round(iv, 4),
                     "prem_per_btc": round(prem_per_btc, 2), "prem_usd": round(prem_usd, 1)})
    # ATM implied for VRP
    atm_iv = float(np.interp(0.0, tgt.k, tgt.mark_iv))
    return {"spot": spot, "forward": F, "expiry": tgt.label, "T_days": round(T * 365.0, 2),
            "atm_iv": round(atm_iv, 4), "legs": legs,
            "cycle_income_usd": round(total_prem_usd, 1),
            "cycle_income_pct_block": round(total_prem_usd / (BLOCK_BTC * spot) * 100, 4)}


def realize(cyc, ref, path):
    """Realized short-call P&L at entry+DTE + realized vol (VRP). Needs Binance path."""
    exp_dt = ref + timedelta(days=cyc["T_days"])
    S_T = spot_at(path, exp_dt)
    if S_T is None:
        return None
    # realized vol over holding window (annualized)
    seg = [(ts, c) for ts, c in path if ref <= ts <= exp_dt]
    rv = None
    if len(seg) > 3:
        rets = np.diff(np.log([c for _, c in seg]))
        rv = float(np.std(rets) * np.sqrt(365.0))
    pnl = 0.0
    n_exer = 0
    for leg in cyc["legs"]:
        payoff = max(S_T - leg["strike"], 0.0)          # short call pays this out
        pnl += (leg["prem_per_btc"] - payoff) * TRANCHE_BTC
        if S_T > leg["strike"]:
            n_exer += 1
    return {"S_T": round(S_T, 1), "realized_vol": round(rv, 4) if rv else None,
            "vrp_atm": round(cyc["atm_iv"] - rv, 4) if rv else None,
            "short_call_pnl_usd": round(pnl, 1), "n_tranches_itm": n_exer,
            "exercised": n_exer > 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dte", type=float, default=31.0)
    ap.add_argument("--archive", help="raw Deribit archive book_summary.json (single-day demo)")
    ap.add_argument("--archive-date", help="YYYY-MM-DD for --archive ref")
    a = ap.parse_args()
    path = load_binance_1d()
    results = []

    if a.archive:
        ref = datetime.fromisoformat(a.archive_date + "T00:00:00+00:00")
        books = books_from_deribit_archive(pathlib.Path(a.archive), ref)
        cyc = price_cycle(books, ref, a.dte)
        if cyc:
            r = {"month": a.archive_date, "source": "deribit_archive", **cyc}
            rz = realize(cyc, ref, path)
            if rz:
                r["realized"] = rz
            results.append(r)

    # Tardis monthly surfaces (if fetched)
    if SURF_ROOT.is_dir():
        for d in sorted(x for x in SURF_ROOT.iterdir() if x.is_dir()):
            sj = d / "surface.json"
            if not sj.exists():
                continue
            y, m = map(int, d.name.split("-"))
            ref = datetime(y, m, 1, tzinfo=UTC)
            books = books_from_tardis(sj, ref)
            cyc = price_cycle(books, ref, a.dte)
            if not cyc:
                continue
            r = {"month": d.name, "source": "tardis_free", **cyc}
            rz = realize(cyc, ref, path)
            if rz:
                r["realized"] = rz
            results.append(r)

    for r in results:
        line = (f"{r['month']} [{r['source']:15s}] spot=${r['spot']:>9,.0f} "
                f"exp={r['expiry']:>8s}({r['T_days']:.0f}d) "
                f"income=${r['cycle_income_usd']/1e6:6.2f}M "
                f"({r['cycle_income_pct_block']:.2f}% blk) atmIV={r['atm_iv']}")
        if "realized" in r:
            rz = r["realized"]
            line += (f" | S_T=${rz['S_T']:>9,.0f} rv={rz['realized_vol']} "
                     f"VRP={rz['vrp_atm']} pnl=${rz['short_call_pnl_usd']/1e6:6.2f}M "
                     f"exer={rz['n_tranches_itm']}/4")
        print(line)

    real = [r for r in results if "realized" in r]
    summary = {"n_cycles": len(results), "n_realized": len(real),
               "authoritative_target_usd": 10_600_000}
    if results:
        inc = np.array([r["cycle_income_usd"] for r in results])
        summary["income_usd"] = {"median": round(float(np.median(inc)), 1),
                                 "mean": round(float(np.mean(inc)), 1),
                                 "min": round(float(inc.min()), 1),
                                 "max": round(float(inc.max()), 1)}
    if real:
        vrp = np.array([r["realized"]["vrp_atm"] for r in real
                        if r["realized"]["vrp_atm"] is not None])
        pnl = np.array([r["realized"]["short_call_pnl_usd"] for r in real])
        exer = np.array([1.0 if r["realized"]["exercised"] else 0.0 for r in real])
        summary["vrp_atm"] = {"mean": round(float(vrp.mean()), 4),
                              "frac_positive": round(float(np.mean(vrp > 0)), 3)} if vrp.size else None
        summary["short_call_pnl_usd"] = {"mean": round(float(pnl.mean()), 1),
                                         "total": round(float(pnl.sum()), 1)}
        summary["p_exercise"] = round(float(exer.mean()), 3)
    out = SURF_ROOT / "_observed_skew_backtest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "cycles": results}, indent=2))
    print("\n=== OBSERVED-SKEW BACKTEST SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
