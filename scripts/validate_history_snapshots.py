#!/usr/bin/env python3
"""Independent validator for the binance_history_full snapshots (S0_data · Aug-2026).

Re-derives every validation number DIRECTLY from the bars.json bytes (does NOT trust meta.json),
using a memory-lean regex extraction of (timestamp, close) per record rather than a full JSON parse.

Checks per snapshot:
  * n_bars, first/last timestamp (date range)
  * strictly monotonic timestamps, 0 duplicate timestamps
  * step census: expected-if-contiguous, missing-within-span, coverage %, largest gap
  * sha256 of the exact bars.json bytes (compared to meta when meta's basis is the file bytes)
  * cross-check vs the recorded meta.json (n_bars / start / end / monotonic / dups)
  * overlap-identical vs the existing binance_history/<interval> snapshot on shared timestamps (close)

Prints a single JSON report to stdout. Provenance of the data: OBSERVED. Run on the engine venv.
Usage:  python scripts/validate_history_snapshots.py [--targets 5m,1d,1h,1m,1m-spans]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from datetime import UTC, datetime

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots"
_FULL = _ROOT / "binance_history_full"
_EXISTING = _ROOT / "binance_history"
_STEP = {"1d": 86_400, "1h": 3_600, "5m": 300, "1m": 60}

_REC = re.compile(rb'"timestamp":\s*"([^"]+)".*?"close":\s*([-0-9.eE+]+)')


def _epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _extract(path: pathlib.Path) -> tuple[list[int], dict[str, float], str, str, bytes]:
    raw = path.read_bytes()
    epochs: list[int] = []
    close_by_iso: dict[str, float] = {}
    first_iso = last_iso = ""
    for mobj in _REC.finditer(raw):
        iso = mobj.group(1).decode()
        c = float(mobj.group(2))
        e = _epoch(iso)
        epochs.append(e)
        close_by_iso[iso] = round(c, 8)
        if not first_iso:
            first_iso = iso
        last_iso = iso
    return epochs, close_by_iso, first_iso, last_iso, raw


def _census(epochs: list[int], step: int) -> dict:
    n = len(epochs)
    monotonic = all(epochs[i] < epochs[i + 1] for i in range(n - 1))
    dups = n - len(set(epochs))
    missing = 0
    max_gap = 0
    n_gaps = 0
    for i in range(n - 1):
        d = epochs[i + 1] - epochs[i]
        if d > step:
            missing += d // step - 1
            max_gap = max(max_gap, d // step)
            n_gaps += 1
    span = (epochs[-1] - epochs[0]) // step + 1 if n else 0
    return {
        "n_bars": n, "monotonic_strict": monotonic, "duplicate_timestamps": dups,
        "span_bars_expected_if_contiguous": span, "missing_bars_within_span": missing,
        "coverage_pct": round(100.0 * n / span, 4) if span else None,
        "n_gaps_gt_1_step": n_gaps, "largest_gap_bars": max_gap,
    }


def _overlap(interval: str, close_by_iso: dict[str, float]) -> dict:
    ep = _EXISTING / interval / "bars.json"
    if not ep.exists():
        return {"status": "no_existing_snapshot"}
    _, old_close, _, _, _ = _extract(ep)
    shared = set(old_close) & set(close_by_iso)
    mism = [t for t in shared if old_close[t] != close_by_iso[t]]
    return {"existing_n": len(old_close), "shared_timestamps": len(shared),
            "close_mismatches": len(mism),
            "identical_on_overlap": len(shared) > 0 and len(mism) == 0,
            "sample_mismatches": [{"ts": t, "old": old_close[t], "new": close_by_iso[t]}
                                  for t in sorted(mism)[:5]]}


def _validate_file(path: pathlib.Path, interval: str, do_overlap: bool = True) -> dict:
    step = _STEP[interval]
    epochs, close_by_iso, first_iso, last_iso, raw = _extract(path)
    census = _census(epochs, step)
    sha_file = hashlib.sha256(raw).hexdigest()
    meta_path = path.parent / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    mv = meta.get("validation", {})
    sha_basis_is_file = meta.get("sha256_basis", "").startswith("sha256 over the exact")
    result = {
        "path": str(path.relative_to(_ROOT.parent)), "interval": interval,
        "first_ts": first_iso, "last_ts": last_iso,
        "recomputed": census,
        "sha256_file_bytes": sha_file,
        "meta_crosscheck": {
            "n_bars_match": census["n_bars"] == meta.get("n_bars"),
            "start_match": first_iso == (meta.get("start") or "").replace("+00:00", "Z"),
            "end_match": last_iso == (meta.get("end") or "").replace("+00:00", "Z"),
            "monotonic_match": census["monotonic_strict"] == mv.get("monotonic_strict"),
            "dups_match": census["duplicate_timestamps"] == mv.get("duplicate_timestamps"),
            "coverage_match": census["coverage_pct"] == mv.get("coverage_pct"),
            "meta_n_bars": meta.get("n_bars"), "meta_start": meta.get("start"),
            "meta_end": meta.get("end"), "meta_coverage_pct": mv.get("coverage_pct"),
        },
        "sha256_matches_meta": (sha_file == meta.get("sha256")) if sha_basis_is_file else "n/a (meta sha is over sorted re-dump, not file bytes)",
    }
    if do_overlap:
        result["overlap_vs_existing"] = _overlap(interval, close_by_iso)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="5m,1d,1h,1m-spans")
    args = ap.parse_args()
    targets = args.targets.split(",")
    out: list[dict] = []

    if "1d" in targets:
        out.append(_validate_file(_FULL / "1d" / "bars.json", "1d"))
    if "1h" in targets:
        out.append(_validate_file(_FULL / "1h" / "bars.json", "1h"))
    if "5m" in targets:
        out.append(_validate_file(_FULL / "5m" / "bars.json", "5m"))
    if "1m-spans" in targets:
        span_dirs = sorted(d for d in (_FULL / "1m").iterdir()
                           if d.is_dir() and (d / "bars.json").exists())
        span_results = []
        for d in span_dirs:
            span_results.append(_validate_file(d / "bars.json", "1m"))
        # contiguity across spans (sorted by first_ts)
        span_results.sort(key=lambda r: r["first_ts"])
        gaps = []
        for a, b in zip(span_results, span_results[1:]):
            gm = (_epoch(b["first_ts"]) - _epoch(a["last_ts"])) // 60 - 1
            gaps.append({"between": [a["path"], b["path"]], "gap_minutes": gm, "contiguous": gm == 0})
        out.append({"interval": "1m", "mode": "regime_spans", "n_spans": len(span_results),
                    "total_bars": sum(r["recomputed"]["n_bars"] for r in span_results),
                    "overall_start": span_results[0]["first_ts"] if span_results else None,
                    "overall_end": span_results[-1]["last_ts"] if span_results else None,
                    "spans": span_results,
                    "inter_span_gaps": gaps,
                    "fully_contiguous_across_spans": all(g["contiguous"] for g in gaps)})

    print(json.dumps({"generated_utc": datetime.now(UTC).isoformat(), "results": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
