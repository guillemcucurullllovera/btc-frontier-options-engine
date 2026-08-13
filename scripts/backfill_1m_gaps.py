#!/usr/bin/env python3
"""Backfill the between-span 1-minute gaps and regenerate the 1m spans summary (S0_data · Aug-2026).

The regime-span fetch (fetch_binance_history_full.py --interval 1m --spans) left three gaps between the
five regime spans. This fills them CONTIGUOUSLY using the SAME memory-lean per-span dict path
(_collect_dicts -> _finalize_dicts -> _write_dicts) so peak memory stays ~one span, and writes each gap
into its own subdir under 1m/<label>/ (never clobbering existing span dirs or bars).

Gaps filled (each < ~600k bars to stay memory-safe):
    2018-03..2018-12   (post-2017-blowoff bear)
    2019-01..2020-01   (accumulation into pre-COVID)     [meets the 2020-02 COVID span]
    2020-06..2020-12   (post-COVID recovery to breakout)  [meets the 2021 bull span]
    2023-01..2023-12   (range / pre-ETF)                  [meets the 2024 span]

After fetching, RESCANS every 1m/<label>/meta.json and rebuilds 1m/meta.json (the spans summary) with a
contiguity assessment across all spans sorted by start. Idempotent: an already-present span dir is skipped.

Provenance: OBSERVED (Binance bulk klines via data.binance.vision). Run on the engine venv.
Usage:  python scripts/backfill_1m_gaps.py
"""
from __future__ import annotations

import gc
import json
import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.fetch_binance_history_full import (  # noqa: E402
    _OUT,
    _collect_dicts,
    _finalize_dicts,
    _month_iter,
    _write_dicts,
)

INTERVAL = "1m"

# (start, end, label) — inclusive month ranges chosen to butt exactly against the existing spans.
GAP_SPANS: list[tuple[tuple[int, int], tuple[int, int], str]] = [
    ((2018, 3), (2018, 12), "2018-03_2018-12_postblowoff_bear"),
    ((2019, 1), (2020, 1), "2019-01_2020-01_accumulation_pre_covid"),
    ((2020, 6), (2020, 12), "2020-06_2020-12_postcovid_to_breakout"),
    ((2023, 1), (2023, 12), "2023-range_pre_etf"),
]


def fetch_gap(start: tuple[int, int], end: tuple[int, int], label: str, now: datetime) -> None:
    span_dir = _OUT / INTERVAL / label
    if (span_dir / "bars.json").exists():
        print(f"[skip] {label}: already present", flush=True)
        return
    months = _month_iter(start, end)
    print(f"[fetch] {INTERVAL} gap {label} {start[0]}-{start[1]:02d}..{end[0]}-{end[1]:02d} "
          f"({len(months)} months) ...", flush=True)
    pairs = _finalize_dicts(_collect_dicts(INTERVAL, months, now), INTERVAL, now)
    meta = _write_dicts(span_dir, pairs, INTERVAL, now,
                        extra_meta={"mode": "regime_span", "span_label": label,
                                    "span_months": f"{start[0]}-{start[1]:02d}..{end[0]}-{end[1]:02d}",
                                    "backfill_note": "between-span gap fill (S0_data)"})
    v = meta["validation"]
    print(f"  -> {label}: {meta['n_bars']} bars {meta['start']} -> {meta['end']} "
          f"cov={v['coverage_pct']}% dups={v['duplicate_timestamps']} "
          f"mono={v['monotonic_strict']} largest_gap={v['largest_gap_bars']} "
          f"sha={str(meta['sha256'])[:12]}", flush=True)
    del pairs
    gc.collect()


def rebuild_summary(now: datetime) -> dict:
    """Rescan every 1m/<label>/meta.json and rebuild the spans summary with a contiguity check."""
    root = _OUT / INTERVAL
    span_metas = []
    for d in sorted(root.iterdir()):
        mp = d / "meta.json"
        bp = d / "bars.json"
        if d.is_dir() and mp.exists() and bp.exists():
            span_metas.append((d, json.loads(mp.read_text())))
    span_metas.sort(key=lambda dm: dm[1]["start"])

    spans = []
    total = 0
    for d, m in span_metas:
        v = m["validation"]
        o = m.get("overlap_vs_binance_history", {})
        spans.append({
            "label": m.get("span_label", d.name),
            "dir": str(d.relative_to(_OUT.parent)),
            "n_bars": m["n_bars"], "start": m["start"], "end": m["end"],
            "sha256": m["sha256"], "coverage_pct": v["coverage_pct"],
            "monotonic": v["monotonic_strict"], "duplicates": v["duplicate_timestamps"],
            "largest_gap_bars": v["largest_gap_bars"],
            "overlap_identical": o.get("identical_on_overlap"),
        })
        total += m["n_bars"]

    # contiguity across spans: gap in whole minutes between end of span i and start of span i+1
    def _epoch(iso: str) -> int:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())

    inter_span_gaps = []
    for a, b in zip(spans, spans[1:]):
        gap_min = (_epoch(b["start"]) - _epoch(a["end"])) // 60 - 1
        inter_span_gaps.append({"between": [a["label"], b["label"]], "gap_minutes": gap_min,
                                "contiguous": gap_min == 0})
    fully_contiguous = all(g["contiguous"] for g in inter_span_gaps)

    summary = {
        "source": "binance", "symbol": "BTCUSDT", "interval": INTERVAL, "provenance": "OBSERVED",
        "mode": "regime_spans", "n_spans": len(spans), "total_bars": total,
        "spans": spans,
        "fetched_at_utc": now.isoformat(),
        "layout": "one bars.json per regime span under 1m/<label>/ (per-span to bound memory)",
        "contiguity": {
            "spans_sorted_by_start": [s["label"] for s in spans],
            "overall_start": spans[0]["start"] if spans else None,
            "overall_end": spans[-1]["end"] if spans else None,
            "inter_span_gaps": inter_span_gaps,
            "fully_contiguous_across_spans": fully_contiguous,
        },
        "remaining_to_full_backfill": (
            "Between-span gaps 2018-03..2020-01, 2020-06..2020-12 and 2023 are now FILLED. "
            "The only remaining pre-history is 2017-08..2017-11 (before the 2017-12 blowoff span); "
            "not requested. Full contiguous 1m now spans 2017-12-01 -> now."),
    }
    (root / "meta.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    now = datetime.now(UTC)
    for start, end, label in GAP_SPANS:
        fetch_gap(start, end, label, now)
    summary = rebuild_summary(now)
    print("\n[summary] 1m spans after backfill:", flush=True)
    for s in summary["spans"]:
        print(f"  {s['start']} -> {s['end']:<26} {s['n_bars']:>8} bars  cov={s['coverage_pct']}%  "
              f"dups={s['duplicates']}  mono={s['monotonic']}  [{s['label']}]", flush=True)
    print(f"\n  total_bars={summary['total_bars']}  n_spans={summary['n_spans']}  "
          f"fully_contiguous_across_spans={summary['contiguity']['fully_contiguous_across_spans']}", flush=True)
    for g in summary["contiguity"]["inter_span_gaps"]:
        print(f"    gap {g['gap_minutes']:>6} min between {g['between'][0]} .. {g['between'][1]} "
              f"(contiguous={g['contiguous']})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
