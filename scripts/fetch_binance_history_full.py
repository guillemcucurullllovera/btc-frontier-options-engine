#!/usr/bin/env python3
"""Fetch FULL-history / FULL-granularity Binance BTCUSDT klines into checksummed snapshots.

Extends ``fetch_binance_history.py`` (D1 data-recovery run, 2026-08-12). Writes to a NEW output root
``market_snapshots/binance_history_full/`` so the existing ``binance_history/`` snapshots are NOT clobbered.

Adds/extends:
  * 5m — FULL history 2017-08 -> now (the real gap: 5m price bars were never saved, only jump stats),
  * 1m — regime-critical spans (or a custom month range) from the 2017-era bulk archive,
  * 1d / 1h — refreshed to today.

Bulk history comes from the public ``data.binance.vision`` archive (no auth); the current-month tail from
the public REST endpoint. The incomplete current bar is excluded. Provenance OBSERVED, origin ``binance``.

Each snapshot is ``bars.json`` (list of HistoricalSpotBar) + ``meta.json`` with source, provenance, basis
caveat, date range, n_bars, sha256 over the canonical bars payload, and an embedded VALIDATION report
(monotonicity, duplicates, gap census, and an overlap-identical check vs the existing binance_history
snapshot on the shared window).

Usage:
  python scripts/fetch_binance_history_full.py --interval 1d
  python scripts/fetch_binance_history_full.py --interval 1h
  python scripts/fetch_binance_history_full.py --interval 5m                 # full 2017-08 -> now
  python scripts/fetch_binance_history_full.py --interval 1m --spans         # regime-critical spans
  python scripts/fetch_binance_history_full.py --interval 1m --start 2017-08 --end 2026-08   # full 1m
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import pathlib
import sys
import time
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.data_models import HistoricalSpotBar
from vol.binance import BinanceKlinesProvider, HistoricalSpotNotFound

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots"
_OUT = _ROOT / "binance_history_full"
_EXISTING = _ROOT / "binance_history"          # for overlap-identical validation
_INTERVAL_SECONDS = {"1d": 86_400, "1h": 3_600, "5m": 300, "1m": 60}
_DEFAULT_START = {"1d": (2017, 8), "1h": (2019, 1), "5m": (2017, 8), "1m": (2017, 8)}

# Regime-critical 1m spans (inclusive month ranges) — the market events that drive tail calibration.
_REGIME_SPANS: list[tuple[tuple[int, int], tuple[int, int], str]] = [
    ((2017, 12), (2018, 2), "2017-12_2018-02_blowoff_top_and_crash"),
    ((2020, 2), (2020, 5), "2020-covid-crash-and-recovery"),
    ((2021, 1), (2021, 12), "2021-double-peak-bull"),
    ((2022, 1), (2022, 12), "2022-luna-3ac-ftx-bear"),
    ((2024, 1), (2026, 12), "2024-2026-recent-etf-halving-regime"),  # clamped to now below
]

_BASIS_CAVEAT = (
    "BTCUSDT (USDT-quoted Binance spot) vs the Deribit USD index: price LEVELS differ by the small/"
    "stationary USDT basis + exchange composition; LOG-RETURNS (the input to all physical dynamics "
    "estimation) are an excellent BTC/USD proxy. Frozen option/DVOL anchor untouched."
)


def _month_iter(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    y, m = start
    out = []
    while (y, m) <= end:
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _fetch_bulk_retry(prov: BinanceKlinesProvider, y: int, m: int, interval: str,
                      retries: int = 3) -> list[HistoricalSpotBar]:
    for attempt in range(retries):
        try:
            return prov.fetch_bulk_month(y, m)
        except HistoricalSpotNotFound:
            return []                                   # month genuinely absent (pre-listing) -> empty
        except Exception as exc:                        # transient network -> backoff + retry
            if attempt == retries - 1:
                print(f"  [warn] bulk {interval} {y}-{m:02d} gave up: {type(exc).__name__}", flush=True)
                return []
            time.sleep(1.5 * (attempt + 1))
    return []


def _collect(interval: str, months: list[tuple[int, int]], now: datetime) -> list[HistoricalSpotBar]:
    prov = BinanceKlinesProvider(interval=interval)
    bars: list[HistoricalSpotBar] = []
    n_months = len(months)
    for i, (y, m) in enumerate(months):
        if (y, m) == (now.year, now.month):
            continue                                    # current month filled by REST below
        got = _fetch_bulk_retry(prov, y, m, interval)
        bars.extend(got)
        if interval in ("5m", "1m"):
            print(f"  [{i + 1:>3}/{n_months}] bulk {interval} {y}-{m:02d}: "
                  f"{len(got):>6} bars  (running {len(bars):>8})", flush=True)
    # current-month tail via REST from the last bulk bar
    rest_start = (bars[-1].timestamp + timedelta(seconds=1)) if bars else (
        datetime(months[0][0], months[0][1], 1, tzinfo=UTC))
    try:
        tail = prov.fetch_rest(rest_start, now)
        bars.extend(tail)
        print(f"  REST tail {interval}: {len(tail)} bars from {rest_start.date()}", flush=True)
    except Exception as exc:
        print(f"  [warn] REST {interval} tail: {type(exc).__name__}", flush=True)
    prov.close()
    return bars


def _finalize(bars: list[HistoricalSpotBar], interval: str, now: datetime) -> list[HistoricalSpotBar]:
    """dedup + sort + drop the incomplete current bar."""
    step = _INTERVAL_SECONDS[interval]
    now_s = now.timestamp()
    uniq = {b.timestamp: b for b in bars}
    return [b for b in sorted(uniq.values(), key=lambda x: x.timestamp)
            if b.timestamp.timestamp() + step <= now_s]


def _validate(bars: list[HistoricalSpotBar], interval: str) -> dict[str, object]:
    step = _INTERVAL_SECONDS[interval]
    ts = [int(b.timestamp.timestamp()) for b in bars]
    n = len(ts)
    monotonic = all(ts[i] < ts[i + 1] for i in range(n - 1))
    dups = n - len(set(ts))
    gaps: list[tuple[str, str, int]] = []
    max_gap_bars = 0
    missing_est = 0
    for i in range(n - 1):
        d = ts[i + 1] - ts[i]
        if d != step:
            missing = d // step - 1
            missing_est += max(missing, 0)
            if d > step:
                max_gap_bars = max(max_gap_bars, int(d // step))
                if len(gaps) < 40:                      # keep the largest offenders below
                    gaps.append((datetime.fromtimestamp(ts[i], UTC).isoformat(),
                                 datetime.fromtimestamp(ts[i + 1], UTC).isoformat(), int(d // step)))
    gaps.sort(key=lambda g: -g[2])
    span_bars_expected = (ts[-1] - ts[0]) // step + 1 if n else 0
    return {
        "n_bars": n,
        "monotonic_strict": monotonic,
        "duplicate_timestamps": dups,
        "step_seconds": step,
        "span_bars_expected_if_contiguous": span_bars_expected,
        "missing_bars_within_span": missing_est,
        "coverage_pct": round(100.0 * n / span_bars_expected, 4) if span_bars_expected else None,
        "n_gaps_gt_1_step": sum(1 for i in range(n - 1) if ts[i + 1] - ts[i] > step),
        "largest_gap_bars": max_gap_bars,
        "top_gaps": [{"from": a, "to": b, "gap_bars": g} for a, b, g in gaps[:15]],
    }


def _overlap_check(bars: list[HistoricalSpotBar], interval: str) -> dict[str, object]:
    """Compare against the existing binance_history snapshot on the shared window (close prices)."""
    existing_path = _EXISTING / interval / "bars.json"
    if not existing_path.exists():
        return {"status": "no_existing_snapshot"}
    old = json.loads(existing_path.read_text())
    old_close = {r["timestamp"]: round(float(r["close"]), 8) for r in old}
    new_close = {b.timestamp.isoformat().replace("+00:00", "Z"): round(float(b.close), 8) for b in bars}
    shared = set(old_close) & set(new_close)
    mismatches = [t for t in shared if old_close[t] != new_close[t]]
    return {
        "existing_n": len(old), "new_n": len(bars), "shared_timestamps": len(shared),
        "close_mismatches": len(mismatches),
        "sample_mismatches": [
            {"ts": t, "old": old_close[t], "new": new_close[t]} for t in sorted(mismatches)[:5]
        ],
        "identical_on_overlap": len(shared) > 0 and len(mismatches) == 0,
    }


def _write(interval: str, bars: list[HistoricalSpotBar], now: datetime,
           extra_meta: dict[str, object]) -> dict[str, object]:
    payload = [b.model_dump(mode="json") for b in bars]
    blob = json.dumps(payload)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    validation = _validate(bars, interval)
    overlap = _overlap_check(bars, interval)
    meta = {
        "source": "binance", "symbol": "BTCUSDT", "interval": interval, "provenance": "OBSERVED",
        "n_bars": len(bars),
        "start": bars[0].timestamp.isoformat() if bars else None,
        "end": bars[-1].timestamp.isoformat() if bars else None,
        "sha256": digest, "fetched_at_utc": now.isoformat(),
        "bulk_source": "data.binance.vision", "rest_source": "api.binance.com/api/v3/klines",
        "basis_caveat": _BASIS_CAVEAT,
        "note": "incomplete current bar excluded; timestamps normalised (ms/µs->s).",
        "validation": validation,
        "overlap_vs_binance_history": overlap,
        **extra_meta,
    }
    out_dir = _OUT / interval
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bars.json").write_text(blob)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def _run_range(interval: str, start: tuple[int, int], now: datetime) -> dict[str, object]:
    months = _month_iter(start, (now.year, now.month))
    print(f"[fetch] {interval} {start[0]}-{start[1]:02d} -> {now.year}-{now.month:02d} "
          f"({len(months)} months) ...", flush=True)
    bars = _finalize(_collect(interval, months, now), interval, now)
    meta = _write(interval, bars, now, extra_meta={"mode": "full_range",
                                                   "range_start_month": f"{start[0]}-{start[1]:02d}"})
    return meta


# ── memory-lean dict path (for 1m: 2.7M+ bars would OOM as pydantic objects) ──
def _collect_dicts(interval: str, months: list[tuple[int, int]], now: datetime) -> list[dict]:
    """Like _collect but model_dumps each month immediately -> plain dicts (caps live pydantic at 1 month)."""
    prov = BinanceKlinesProvider(interval=interval)
    rows: list[dict] = []
    last_ts: datetime | None = None
    for (y, m) in months:
        if (y, m) == (now.year, now.month):
            continue
        got = _fetch_bulk_retry(prov, y, m, interval)
        for b in got:
            rows.append(b.model_dump(mode="json"))
            last_ts = b.timestamp if (last_ts is None or b.timestamp > last_ts) else last_ts
        print(f"  bulk {interval} {y}-{m:02d}: {len(got):>6} rows (running {len(rows):>8})", flush=True)
        del got
    # REST tail ONLY when the span reaches the current (incomplete) month; historical spans are fully
    # covered by complete bulk months, so a REST tail there would fetch span-end..now (millions of bars).
    if months[-1] == (now.year, now.month) and last_ts is not None:
        rest_start = last_ts + timedelta(seconds=1)
        try:
            tail = prov.fetch_rest(rest_start, now)
            rows.extend(b.model_dump(mode="json") for b in tail)
            print(f"  REST tail {interval}: {len(tail)} rows from {rest_start.date()}", flush=True)
        except Exception as exc:
            print(f"  [warn] REST {interval} tail: {type(exc).__name__}", flush=True)
    prov.close()
    return rows


def _finalize_dicts(rows: list[dict], interval: str, now: datetime) -> list[tuple[int, dict]]:
    """dedup by ISO-ts string, sort, drop the incomplete current bar. Returns (epoch, row) pairs."""
    step = _INTERVAL_SECONDS[interval]
    now_s = now.timestamp()
    uniq = {r["timestamp"]: r for r in rows}                 # ISO-8601 'Z' strings sort lexicographically
    out: list[tuple[int, dict]] = []
    for ts, r in uniq.items():
        e = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
        if e + step <= now_s:
            out.append((e, r))
    out.sort(key=lambda p: p[0])
    return out


def _validate_epochs(pairs: list[tuple[int, dict]], interval: str) -> dict[str, object]:
    step = _INTERVAL_SECONDS[interval]
    ts = [e for e, _ in pairs]
    n = len(ts)
    monotonic = all(ts[i] < ts[i + 1] for i in range(n - 1))
    dups = n - len(set(ts))
    gaps: list[tuple[str, str, int]] = []
    max_gap = 0
    missing = 0
    for i in range(n - 1):
        d = ts[i + 1] - ts[i]
        if d != step and d > step:
            missing += d // step - 1
            max_gap = max(max_gap, int(d // step))
            if len(gaps) < 60:
                gaps.append((datetime.fromtimestamp(ts[i], UTC).isoformat(),
                             datetime.fromtimestamp(ts[i + 1], UTC).isoformat(), int(d // step)))
    gaps.sort(key=lambda g: -g[2])
    span = (ts[-1] - ts[0]) // step + 1 if n else 0
    return {"n_bars": n, "monotonic_strict": monotonic, "duplicate_timestamps": dups,
            "step_seconds": step, "span_bars_expected_if_contiguous": span,
            "missing_bars_within_span": missing,
            "coverage_pct": round(100.0 * n / span, 4) if span else None,
            "largest_gap_bars": max_gap,
            "top_gaps": [{"from": a, "to": b, "gap_bars": g} for a, b, g in gaps[:10]]}


def _overlap_epochs(pairs: list[tuple[int, dict]], interval: str) -> dict[str, object]:
    existing_path = _EXISTING / interval / "bars.json"
    if not existing_path.exists():
        return {"status": "no_existing_snapshot"}
    old = json.loads(existing_path.read_text())
    old_close = {r["timestamp"]: round(float(r["close"]), 8) for r in old}
    new_close = {r["timestamp"]: round(float(r["close"]), 8) for _, r in pairs}
    shared = set(old_close) & set(new_close)
    mism = [t for t in shared if old_close[t] != new_close[t]]
    return {"existing_n": len(old), "new_n": len(pairs), "shared_timestamps": len(shared),
            "close_mismatches": len(mism), "identical_on_overlap": len(shared) > 0 and len(mism) == 0,
            "sample_mismatches": [{"ts": t, "old": old_close[t], "new": new_close[t]} for t in sorted(mism)[:5]]}


def _write_dicts(out_dir: pathlib.Path, pairs: list[tuple[int, dict]], interval: str,
                 now: datetime, extra_meta: dict[str, object]) -> dict[str, object]:
    """Single serialization: sha256 over the EXACT bytes written (reproducible), no double-dump."""
    rows = [r for _, r in pairs]
    blob = json.dumps(rows)
    digest = hashlib.sha256(blob.encode()).hexdigest()
    meta = {
        "source": "binance", "symbol": "BTCUSDT", "interval": interval, "provenance": "OBSERVED",
        "n_bars": len(rows),
        "start": rows[0]["timestamp"] if rows else None, "end": rows[-1]["timestamp"] if rows else None,
        "sha256": digest, "sha256_basis": "sha256 over the exact bars.json bytes as written",
        "fetched_at_utc": now.isoformat(),
        "bulk_source": "data.binance.vision", "rest_source": "api.binance.com/api/v3/klines",
        "basis_caveat": _BASIS_CAVEAT,
        "note": "incomplete current bar excluded; timestamps normalised (ms/µs->s).",
        "validation": _validate_epochs(pairs, interval),
        "overlap_vs_binance_history": _overlap_epochs(pairs, interval),
        **extra_meta,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bars.json").write_text(blob)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def _run_spans(interval: str, now: datetime) -> dict[str, object]:
    """Per-span, memory-lean 1m fetch: each regime span -> its own bars.json (peak mem = one span)."""
    spans_summary = []
    total_bars = 0
    for (s, e, label) in _REGIME_SPANS:
        e = min(e, (now.year, now.month))
        months = _month_iter(s, e)
        print(f"[fetch] {interval} span {label} {s[0]}-{s[1]:02d}..{e[0]}-{e[1]:02d} "
              f"({len(months)} months) ...", flush=True)
        pairs = _finalize_dicts(_collect_dicts(interval, months, now), interval, now)
        span_dir = _OUT / interval / label
        meta = _write_dicts(span_dir, pairs, interval, now,
                            extra_meta={"mode": "regime_span", "span_label": label,
                                        "span_months": f"{s[0]}-{s[1]:02d}..{e[0]}-{e[1]:02d}"})
        v = meta["validation"]
        o = meta["overlap_vs_binance_history"]
        print(f"  -> {label}: {meta['n_bars']} bars {meta['start']} -> {meta['end']} "
              f"cov={v['coverage_pct']}% dups={v['duplicate_timestamps']} "
              f"overlap_identical={o.get('identical_on_overlap')} sha={str(meta['sha256'])[:12]}", flush=True)
        spans_summary.append({"label": label, "dir": str(span_dir.relative_to(_OUT.parent)),
                              "n_bars": meta["n_bars"], "start": meta["start"], "end": meta["end"],
                              "sha256": meta["sha256"], "coverage_pct": v["coverage_pct"],
                              "monotonic": v["monotonic_strict"], "duplicates": v["duplicate_timestamps"],
                              "largest_gap_bars": v["largest_gap_bars"],
                              "overlap_identical": o.get("identical_on_overlap")})
        total_bars += meta["n_bars"]
        del pairs
        gc.collect()
    summary = {
        "source": "binance", "symbol": "BTCUSDT", "interval": interval, "provenance": "OBSERVED",
        "mode": "regime_spans", "n_spans": len(spans_summary), "total_bars": total_bars,
        "spans": spans_summary, "fetched_at_utc": now.isoformat(),
        "layout": "one bars.json per regime span under 1m/<label>/ (per-span to bound memory)",
        "remaining_to_full_backfill": (
            "Between-span months NOT fetched: 2018-03..2020-01 and 2020-06..2020-12 and 2023-01..2023-12. "
            "To complete a contiguous full-history 1m (~4.7M bars, ~1.15 GB) fetch the gaps per-year, e.g. "
            "python scripts/fetch_binance_history_full.py --interval 1m --start 2023-01 --end 2023-12 "
            "(the --start/--end range mode uses the pydantic path; for >~1.5M-bar ranges prefer running "
            "year-by-year to stay within memory, or extend _run_spans-style per-year dict writing)."),
    }
    (_OUT / interval).mkdir(parents=True, exist_ok=True)
    (_OUT / interval / "meta.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[done] {interval} regime spans: {total_bars} bars across {len(spans_summary)} spans", flush=True)
    return {"validation": {"monotonic_strict": all(x["monotonic"] for x in spans_summary),
                           "duplicate_timestamps": sum(x["duplicates"] for x in spans_summary),
                           "coverage_pct": "per-span (see spans)",
                           "missing_bars_within_span": "per-span",
                           "largest_gap_bars": max((x["largest_gap_bars"] for x in spans_summary), default=0)},
            "overlap_vs_binance_history": {"shared_timestamps": "per-span",
                                           "close_mismatches": sum(0 if x["overlap_identical"] in (True, None)
                                                                   else 1 for x in spans_summary),
                                           "identical_on_overlap": "per-span"},
            "n_bars": total_bars, "start": spans_summary[0]["start"] if spans_summary else None,
            "end": spans_summary[-1]["end"] if spans_summary else None,
            "sha256": "per-span (see 1m/*/meta.json)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", required=True, choices=["1d", "1h", "5m", "1m"])
    ap.add_argument("--start", default=None, help="YYYY-MM start month (bulk)")
    ap.add_argument("--end", default=None, help="YYYY-MM end month (default now)")
    ap.add_argument("--spans", action="store_true", help="1m: fetch regime-critical spans only")
    args = ap.parse_args()
    now = datetime.now(UTC)

    if args.spans:
        meta = _run_spans(args.interval, now)
    else:
        if args.start:
            y, m = (int(x) for x in args.start.split("-"))
            start = (y, m)
        else:
            start = _DEFAULT_START[args.interval]
        meta = _run_range(args.interval, start, now)

    v = meta["validation"]
    o = meta["overlap_vs_binance_history"]
    print(f"\n[done] {args.interval}: {meta['n_bars']} bars {meta['start']} -> {meta['end']} "
          f"sha={str(meta['sha256'])[:12]}", flush=True)
    print(f"  validation: monotonic={v['monotonic_strict']} dups={v['duplicate_timestamps']} "
          f"coverage={v['coverage_pct']}% missing_in_span={v['missing_bars_within_span']} "
          f"largest_gap={v['largest_gap_bars']} bars", flush=True)
    print(f"  overlap: shared={o.get('shared_timestamps')} mismatches={o.get('close_mismatches')} "
          f"identical={o.get('identical_on_overlap')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
