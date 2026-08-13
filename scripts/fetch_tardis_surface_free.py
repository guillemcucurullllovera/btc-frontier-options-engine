#!/usr/bin/env python3
"""Fetch FREE first-of-month Deribit options-surface snapshots from Tardis.dev (E1 · Aug-2026).

Zero-cost historical IV surface. Tardis.dev publishes the first day of each month of its
normalised ``options_chain`` CSV for FREE (no API key):

    https://datasets.tardis.dev/v1/deribit/options_chain/<YYYY>/<MM>/01/OPTIONS.csv.gz

The full-day file is huge (0.3-13 GB gzip), but it BEGINS with a full initial-snapshot burst
of every listed instrument at ~00:00:00 UTC (Tardis emits the current ticker for all
instruments on (re)connect, tightly clustered in local_timestamp). We STREAM-decompress and
STOP after that burst -> a complete 00:00 UTC chain snapshot for a few tens of KB to a few MB.

Columns (OBSERVED): exchange,symbol,timestamp,local_timestamp,type,strike_price,expiration,
open_interest,last_price,bid_price,bid_amount,bid_iv,ask_price,ask_amount,ask_iv,mark_price,
mark_iv,underlying_index,underlying_price,delta,gamma,vega,theta,rho.
IVs are in PERCENT on Tardis -> divided by 100 to decimal here (engine BookSummary convention).

Output (NEW dir, nothing clobbered):
    market_snapshots/deribit_surface_history_free/<YYYY-MM>/surface.json  (BookSummary-shaped rows)
    market_snapshots/deribit_surface_history_free/<YYYY-MM>/meta.json     (provenance + validation)

Provenance: OBSERVED (raw Deribit marks via Tardis).  Runs on the engine venv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import zlib
from datetime import UTC, datetime

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
BASE = "https://datasets.tardis.dev/v1/deribit/options_chain/{y:04d}/{m:02d}/01/OPTIONS.csv.gz"
OUT_ROOT = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "deribit_surface_history_free"
WINDOW_US = 15_000_000          # 15 s initial-snapshot window
MAX_BYTES = 120 * 1024 * 1024   # hard download guard per month


def months(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _f(x: bytes) -> float | None:
    s = x.decode().strip()
    return float(s) if s else None


def fetch_month(y: int, m: int) -> dict | None:
    url = BASE.format(y=y, m=m)
    r = None
    for attempt in range(6):
        r = requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=180)
        if r.status_code == 200:
            break
        if r.status_code in (429, 500, 502, 503):
            r.close()
            wait = min(60, 5 * 2 ** attempt)
            print(f"  {y}-{m:02d}: HTTP {r.status_code}, backoff {wait}s (attempt {attempt+1})")
            time.sleep(wait)
            continue
        r.close()
        print(f"  {y}-{m:02d}: HTTP {r.status_code} (skip)")
        return None
    if r is None or r.status_code != 200:
        print(f"  {y}-{m:02d}: gave up after retries")
        return None
    d = zlib.decompressobj(31)
    idx: dict[str, int] | None = None
    rows: dict[bytes, list[bytes]] = {}      # symbol -> first-seen field list (BTC only)
    first_local: int | None = None
    comp = 0
    tail = b""
    done = False
    for chunk in r.iter_content(1 << 16):
        comp += len(chunk)
        if comp > MAX_BYTES:
            done = True
        data = tail + d.decompress(chunk)
        *lines, tail = data.split(b"\n")
        for ln in lines:
            if idx is None:
                idx = {c: i for i, c in enumerate(ln.decode().split(","))}
                continue
            f = ln.split(b",")
            if len(f) < len(idx):
                continue
            try:
                local = int(f[idx["local_timestamp"]])
            except ValueError:
                continue
            if first_local is None:
                first_local = local
            if local > first_local + WINDOW_US:
                done = True
                break
            sym = f[idx["symbol"]]
            if sym.startswith(b"BTC-") and sym not in rows:
                rows[sym] = f
        if done:
            break
    r.close()
    if idx is None or not rows:
        print(f"  {y}-{m:02d}: no BTC rows parsed (skip)")
        return None

    # Build BookSummary-shaped records; IVs percent -> decimal.
    ref_ts = None
    underlyings: list[float] = []
    recs: list[dict] = []
    for sym, f in rows.items():
        try:
            mark_iv = _f(f[idx["mark_iv"]])
            if not mark_iv or mark_iv <= 0:
                continue
            up = _f(f[idx["underlying_price"]])
            ts = int(f[idx["timestamp"]])
            recs.append({
                "instrument_name": sym.decode(),
                "mark_price": _f(f[idx["mark_price"]]) or 0.0,
                "mark_iv": mark_iv / 100.0,
                "bid_price": _f(f[idx["bid_price"]]),
                "bid_iv": (_f(f[idx["bid_iv"]]) / 100.0) if _f(f[idx["bid_iv"]]) else None,
                "ask_price": _f(f[idx["ask_price"]]),
                "ask_iv": (_f(f[idx["ask_iv"]]) / 100.0) if _f(f[idx["ask_iv"]]) else None,
                "open_interest": _f(f[idx["open_interest"]]) or 0.0,
                "underlying_price": up or 0.0,
                "delta": _f(f[idx["delta"]]),
                "timestamp": ts,
            })
            if up:
                underlyings.append(up)
            if ref_ts is None:
                ref_ts = int(f[idx["local_timestamp"]])
        except (ValueError, KeyError):
            continue

    payload = {
        "provenance": "OBSERVED",
        "source": url,
        "exchange": "deribit",
        "data_type": "options_chain",
        "month": f"{y:04d}-{m:02d}",
        "snapshot_utc": datetime.fromtimestamp(ref_ts / 1e6, UTC).isoformat() if ref_ts else None,
        "rows": recs,
    }
    return {"payload": payload, "comp_bytes": comp, "underlyings": underlyings}


def validate(payload: dict) -> dict:
    from vol.chain import parse_instrument_name
    recs = payload["rows"]
    liquid = [r for r in recs if r["mark_iv"] > 0 and r["bid_price"] is not None
              and r["ask_price"] is not None and r["open_interest"] > 0]
    exps: dict[str, int] = {}
    for r in recs:
        p = parse_instrument_name(r["instrument_name"])
        if p:
            exps[p.expiry.isoformat()] = exps.get(p.expiry.isoformat(), 0) + 1
    ref = datetime.fromisoformat(payload["snapshot_utc"]) if payload["snapshot_utc"] else None
    tenors_days = sorted({round((datetime.fromisoformat(e + "T08:00:00+00:00") - ref).total_seconds() / 86400.0, 1)
                          for e in exps} if ref else set())
    mivs = [r["mark_iv"] for r in recs]
    unders = [r["underlying_price"] for r in recs if r["underlying_price"] > 0]
    under = sorted(unders)[len(unders) // 2] if unders else None
    # ATM IV: nearest positive tenor expiry w/ most strikes, strike closest to underlying
    atm_iv = None
    if ref and under:
        fut = [(e, n) for e, n in exps.items()
               if datetime.fromisoformat(e + "T08:00:00+00:00") > ref]
        if fut:
            near = min(fut, key=lambda en: datetime.fromisoformat(en[0] + "T08:00:00+00:00"))[0]
            cand = [r for r in liquid if (parse_instrument_name(r["instrument_name"]) or
                    type("x", (), {"expiry": None})).expiry and
                    parse_instrument_name(r["instrument_name"]).expiry.isoformat() == near]
            if cand:
                best = min(cand, key=lambda r: abs(parse_instrument_name(r["instrument_name"]).strike - under))
                atm_iv = round(best["mark_iv"], 4)
    return {
        "n_btc": len(recs), "n_liquid": len(liquid), "n_expiries": len(exps),
        "tenors_days": [t for t in tenors_days if t > 0][:40],
        "underlying_usd": under,
        "mark_iv_min": round(min(mivs), 4) if mivs else None,
        "mark_iv_median": round(sorted(mivs)[len(mivs) // 2], 4) if mivs else None,
        "mark_iv_max": round(max(mivs), 4) if mivs else None,
        "atm_iv_near": atm_iv,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-04")
    ap.add_argument("--end", default="2026-08")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    sy, sm = map(int, a.start.split("-"))
    ey, em = map(int, a.end.split("-"))
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    ok = 0
    for y, m in months((sy, sm), (ey, em)):
        outdir = OUT_ROOT / f"{y:04d}-{m:02d}"
        if (outdir / "surface.json").exists() and not a.force:
            print(f"  {y}-{m:02d}: exists (skip)")
            ok += 1
            continue
        res = fetch_month(y, m)
        if res is None:
            continue
        outdir.mkdir(parents=True, exist_ok=True)
        body = json.dumps(res["payload"], separators=(",", ":")).encode()
        (outdir / "surface.json").write_bytes(body)
        val = validate(res["payload"])
        meta = {
            "provenance": "OBSERVED", "source": res["payload"]["source"],
            "month": f"{y:04d}-{m:02d}", "snapshot_utc": res["payload"]["snapshot_utc"],
            "sha256": hashlib.sha256(body).hexdigest(),
            "downloaded_bytes_gz": res["comp_bytes"], "validation": val,
        }
        (outdir / "meta.json").write_text(json.dumps(meta, indent=2))
        print(f"  {y}-{m:02d}: BTC={val['n_btc']:5d} liq={val['n_liquid']:5d} "
              f"exp={val['n_expiries']:2d} spot=${val['underlying_usd']:,.0f} "
              f"atmIV={val['atm_iv_near']} dl={res['comp_bytes']/1e6:.2f}MB")
        ok += 1
        time.sleep(3.0)  # polite pacing to avoid 429
    print(f"\nDone: {ok} months under {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
