#!/usr/bin/env python3
"""C8 Phase 1 — live market snapshot, IV surface, liquid-expiry selection,
realised-vol comparison.

Freezes one atomic pull of the Deribit public endpoints (spot index, DVOL,
option instruments, per-instrument book summary) under ``market_snapshots/<UTC>/``
with SHA-256 checksums + git SHA, then derives the Phase-1 evidence:

  * nearest liquid listed expiries around 30/45/60 days (exact calendar +
    days-left), with any target collapse surfaced explicitly;
  * per-(strike,expiry) IV lookup (direct listed OBSERVED mark_iv, smile
    fallback) previewed over the swept OTM strike grid;
  * IV-surface fit diagnostics;
  * realised vol from observed spot history (comparison only, 365-day
    annualisation) versus the live DVOL headline.

Usage:
  python scripts/snapshot_market.py --refresh    # pull live + freeze (needs egress)
  python scripts/snapshot_market.py              # replay latest frozen snapshot (offline)

Massive is the primary historical spot source for realised vol; if unavailable
the realised-vol comparison is reported UNAVAILABLE (never fabricated).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timedelta
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.data_models import HistoricalSpotBar
from vol.chain import ExpirySelection, iv_for, select_expiries, snap_to_listed_strike
from vol.history import MassiveSpotProvider
from vol.realised import RealisedVol, realised_vol_windows
from vol.snapshot import (
    MarketSnapshot,
    freeze_live_snapshot,
    latest_snapshot_dir,
    load_snapshot,
)
from vol.surface import SurfaceError, fit_surface

logger = logging.getLogger("c8.snapshot")

REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT: pathlib.Path = REPO_ROOT / "market_snapshots"
FIXTURES_DIR: pathlib.Path = REPO_ROOT / "tests" / "fixtures"
CANONICAL_ENV: pathlib.Path = pathlib.Path(
    "/home/francisco/btc/btc_engine_frontier/.env"
)
SPOT_HISTORY_FILE: str = "spot_history.json"
PHASE1_SUMMARY_FILE: str = "phase1_summary.json"

# LOCKED grid dimensions (C8 brief §2): calls/puts at these %OTM off live spot.
CALL_OTM_PCT: tuple[float, ...] = (1.5, 3.0, 5.0, 10.0, 15.0)
PUT_OTM_PCT: tuple[float, ...] = (3.0, 5.0, 10.0)
TARGETS_DAYS: tuple[float, ...] = (30.0, 45.0, 60.0)
DVOL_COMPARISON_WINDOW_DAYS: int = 30


# ── Snapshot resolution ────────────────────────────────────────────────────


def resolve_snapshot(refresh: bool, out_root: pathlib.Path) -> MarketSnapshot:
    """Freeze a live snapshot (--refresh) or replay the latest frozen one."""
    if refresh:
        logger.info("Refreshing: pulling live Deribit public endpoints...")
        snap = freeze_live_snapshot(out_root)
        logger.info("Froze snapshot at %s", snap.directory)
        return snap

    frozen = latest_snapshot_dir(out_root)
    if frozen is not None:
        logger.info("Replaying latest frozen snapshot: %s", frozen)
        return load_snapshot(frozen)

    logger.warning(
        "No frozen snapshot under %s; replaying offline fixtures %s. "
        "Run with --refresh to freeze a live snapshot.",
        out_root,
        FIXTURES_DIR,
    )
    return load_snapshot(FIXTURES_DIR)


# ── Realised-vol spot history (comparison only) ────────────────────────────


def _massive_api_key() -> str | None:
    key = os.environ.get("MASSIVE_API_KEY")
    if key:
        return key
    if CANONICAL_ENV.exists():
        for line in CANONICAL_ENV.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("MASSIVE_API_KEY="):
                value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                return value or None
    return None


def _fetch_spot_history(
    reference: datetime, lookback_days: int
) -> list[HistoricalSpotBar] | None:
    """Best-effort daily spot history from Massive; None if unavailable.

    Only the exception *type* is logged (never the message), because Massive
    error messages can embed the API key in the request URL.
    """
    key = _massive_api_key()
    if not key:
        logger.warning("MASSIVE_API_KEY unavailable; realised vol will be UNAVAILABLE.")
        return None
    provider = MassiveSpotProvider(api_key=key)
    start = reference - timedelta(days=lookback_days)
    try:
        bars = provider.fetch_bars(start=start, end=reference)
    except Exception as exc:  # degrade gracefully; log only the exception type
        logger.warning(
            "Massive spot-history fetch failed (%s); realised vol UNAVAILABLE.",
            type(exc).__name__,
        )
        return None
    logger.info("Fetched %d daily spot bars from Massive.", len(bars))
    return bars


def _freeze_spot_history(snap_dir: pathlib.Path, bars: list[HistoricalSpotBar]) -> None:
    payload = [b.model_dump(mode="json") for b in bars]
    (snap_dir / SPOT_HISTORY_FILE).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_frozen_spot_history(
    snap_dir: pathlib.Path,
) -> list[HistoricalSpotBar] | None:
    path = snap_dir / SPOT_HISTORY_FILE
    if not path.exists():
        return None
    data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [HistoricalSpotBar.model_validate(d) for d in data]


def resolve_spot_history(
    snap: MarketSnapshot, refresh: bool, reference: datetime, lookback_days: int
) -> list[HistoricalSpotBar] | None:
    """Frozen history on replay; fetch + freeze on --refresh into a real snapshot."""
    frozen = _load_frozen_spot_history(snap.directory)
    if frozen is not None:
        logger.info("Using frozen spot history (%d bars).", len(frozen))
        return frozen
    if not refresh:
        return None
    bars = _fetch_spot_history(reference, lookback_days)
    if bars and snap.directory.parent == DEFAULT_OUT_ROOT:
        _freeze_spot_history(snap.directory, bars)
        logger.info("Froze spot history into %s", snap.directory / SPOT_HISTORY_FILE)
    return bars


# ── Phase-1 derivations ────────────────────────────────────────────────────


def _iv_preview(snap: MarketSnapshot, selection: ExpirySelection) -> list[dict[str, Any]]:
    """Preview per-(strike,expiry) IV over the swept OTM grid for each expiry.

    Demonstrates the Phase-1 IV lookup end-to-end; the full grid is Phase 2.
    """
    spot = snap.spot.price
    rows: list[dict[str, Any]] = []
    for exp in selection.distinct:
        for kind, pcts, sign in (("call", CALL_OTM_PCT, 1.0), ("put", PUT_OTM_PCT, -1.0)):
            for pct in pcts:
                requested = spot * (1.0 + sign * pct / 100.0)
                listed, name = snap_to_listed_strike(
                    snap.instruments, exp.expiry, kind, requested
                )
                lk = iv_for(listed, exp.expiry, kind, snap.instruments, snap.book_summaries)
                rows.append(
                    {
                        "expiry": exp.label,
                        "days_to_expiry": round(exp.days_to_expiry, 2),
                        "kind": kind,
                        "requested_pct_otm": sign * pct,
                        "requested_strike": round(requested, 2),
                        "listed_strike": listed,
                        "instrument": name,
                        "iv": round(lk.iv, 6),
                        "iv_provenance": lk.provenance.value,
                        "iv_source": lk.source,
                    }
                )
    return rows


def _surface_diag(snap: MarketSnapshot) -> dict[str, Any]:
    try:
        surf = fit_surface(snap.book_summaries)
    except SurfaceError as exc:
        return {"available": False, "error": str(exc)}
    return {
        "available": True,
        "method": surf.method,
        "n_points": len(surf.points),
        "fit_rmse": surf.fit_rmse,
        "note": (
            "vol/surface.py fits a delta-parameterised smile for diagnostics; "
            "grid IV uses direct listed mark_iv (strike-space smile fallback)."
        ),
    }


def _selection_dict(selection: ExpirySelection) -> dict[str, Any]:
    return {
        "reference": selection.reference.isoformat(),
        "targets_days": list(TARGETS_DAYS),
        "collapsed": selection.collapsed,
        "notes": selection.notes,
        "per_target": [
            {
                "target_days": t.target_days,
                "selected_expiry": t.selected.label,
                "expiry_utc": t.selected.expiry.isoformat(),
                "days_to_expiry": round(t.selected.days_to_expiry, 4),
            }
            for t in selection.targets
        ],
        "distinct_expiries": [
            {
                "label": e.label,
                "expiry_utc": e.expiry.isoformat(),
                "days_to_expiry": round(e.days_to_expiry, 4),
                "n_instruments": e.n_instruments,
                "n_liquid": e.n_liquid,
                "total_open_interest": round(e.total_open_interest, 2),
            }
            for e in selection.distinct
        ],
    }


def _realised_dict(results: list[RealisedVol]) -> list[dict[str, Any]]:
    return [
        {
            "window_days": r.window_days,
            "available": r.available,
            "sigma_annual": round(r.sigma_annual, 6) if r.available else None,
            "n_returns": r.n_returns,
            "annualisation_days": r.annualisation_days,
            "start": r.start.isoformat() if r.start else None,
            "end": r.end.isoformat() if r.end else None,
            "provenance": r.provenance.value,
            "origin": r.origin,
        }
        for r in results
    ]


def build_summary(
    snap: MarketSnapshot,
    selection: ExpirySelection,
    realised: list[RealisedVol],
    reference: datetime,
) -> dict[str, Any]:
    dvol_latest = snap.meta.dvol_latest
    rv30 = next(
        (r for r in realised if r.window_days == DVOL_COMPARISON_WINDOW_DAYS and r.available),
        None,
    )
    return {
        "phase": "C8 Phase 1 — live market snapshot + IV surface",
        "snapshot": {
            "as_of_utc": snap.meta.created_at.isoformat(),
            "directory": str(snap.directory),
            "git_sha": snap.meta.git_sha,
            "git_branch": snap.meta.git_branch,
            "endpoints": snap.meta.endpoints,
            "checksums_sha256": snap.meta.checksums,
            "provenance": snap.meta.provenance,
            "origin": snap.meta.origin,
        },
        "reference_anchors": {
            "live_spot_usd": snap.spot.price,
            "live_spot_provenance": snap.spot.provenance.value,
            "mandate_reference_spot_usd": 65000.0,
            "note": "Compute off live spot; $65,000 retained only as the stated mandate reference.",
        },
        "headline_vol": {
            "dvol_latest": dvol_latest,
            "dvol_provenance": "observed" if dvol_latest is not None else "unavailable",
            "note": "DVOL is the 30-day BTC implied-vol index (headline only); "
            "per-tenor scenario sigma uses each expiry's own ATM IV (Phase 2).",
        },
        "expiry_selection": _selection_dict(selection),
        "otm_grid": {
            "call_pct_otm": list(CALL_OTM_PCT),
            "put_pct_otm": list(PUT_OTM_PCT),
        },
        "iv_preview": _iv_preview(snap, selection),
        "iv_surface_diagnostics": _surface_diag(snap),
        "realised_vol_comparison": {
            "annualisation_days": 365,
            "estimator": "close_to_close_log_return_sample_std",
            "windows": _realised_dict(realised),
            "dvol_vs_realised_30d": (
                None
                if (dvol_latest is None or rv30 is None)
                else {
                    "dvol": round(dvol_latest, 6),
                    "realised_30d": round(rv30.sigma_annual, 6),
                    "spread": round(dvol_latest - rv30.sigma_annual, 6),
                    "note": "implied (DVOL) minus realised; comparison marker only.",
                }
            ),
        },
        "provenance_labels": {
            "iv": "OBSERVED (deribit mark_iv) with MODEL_RECONSTRUCTED smile fallback",
            "dvol": "OBSERVED (deribit)",
            "spot": "OBSERVED (deribit index)",
            "realised_vol": "OBSERVED (massive) / UNAVAILABLE",
            "36pct_ceo_45pct_engine": "labelled comparison markers only — not pricing inputs",
        },
        "pending_gates_not_resolved_here": [
            "D-1 fee base",
            "D-4/D-7 put-sleeve scope",
            "D-9 hedge model",
            "D-10 loss budget",
            "MS-25 objective function",
            "MS-26 sim methodology",
            "CSCV/PBO/DSR PENDING_METHOD",
        ],
    }


def _print_human(summary: dict[str, Any]) -> None:
    s = summary
    snap = s["snapshot"]
    print("\n" + "=" * 72)
    print("C8 PHASE 1 — LIVE MARKET SNAPSHOT GATE")
    print("=" * 72)
    print(f"as of (UTC)   : {snap['as_of_utc']}")
    print(f"git SHA       : {snap['git_sha']}  branch: {snap['git_branch']}")
    print(f"snapshot dir  : {snap['directory']}")
    print(f"live spot USD : {s['reference_anchors']['live_spot_usd']}  "
          f"(mandate ref {s['reference_anchors']['mandate_reference_spot_usd']})")
    print(f"DVOL (30d idx): {s['headline_vol']['dvol_latest']}")
    print("\nChecksums (sha256):")
    for name, digest in snap["checksums_sha256"].items():
        print(f"  {name:<20} {digest}")
    sel = s["expiry_selection"]
    print(f"\nExpiry selection (targets {sel['targets_days']}d, "
          f"collapsed={sel['collapsed']}):")
    for t in sel["per_target"]:
        print(f"  target {t['target_days']:>5}d -> {t['selected_expiry']:<9} "
              f"({t['expiry_utc']}, {t['days_to_expiry']:.2f} days left)")
    print("  distinct listed expiries:")
    for e in sel["distinct_expiries"]:
        print(f"    {e['label']:<9} {e['expiry_utc']}  {e['days_to_expiry']:.2f}d  "
              f"liquid={e['n_liquid']}/{e['n_instruments']}  OI={e['total_open_interest']}")
    for note in sel["notes"]:
        print(f"  NOTE: {note}")
    diag = s["iv_surface_diagnostics"]
    if diag.get("available"):
        print(f"\nIV surface: {diag['n_points']} points, method={diag['method']}, "
              f"rmse={diag['fit_rmse']}")
    rv = s["realised_vol_comparison"]
    print("\nRealised vol (comparison only, 365d annualised):")
    for w in rv["windows"]:
        if w["available"]:
            print(f"  {w['window_days']:>3}d window: sigma={w['sigma_annual']} "
                  f"({w['origin']}, {w['n_returns']} returns)")
        else:
            print(f"  {w['window_days']:>3}d window: UNAVAILABLE ({w['origin']})")
    if rv["dvol_vs_realised_30d"]:
        c = rv["dvol_vs_realised_30d"]
        print(f"  DVOL {c['dvol']} vs realised_30d {c['realised_30d']} "
              f"(spread {c['spread']})")
    print("=" * 72 + "\n")


# ── Entry point ────────────────────────────────────────────────────────────


def run(refresh: bool, out_root: pathlib.Path) -> dict[str, Any]:
    snap = resolve_snapshot(refresh, out_root)
    reference = snap.meta.created_at

    selection = select_expiries(
        snap.instruments,
        snap.book_summaries,
        reference=reference,
        targets_days=TARGETS_DAYS,
    )

    windows = sorted(
        {round(e.days_to_expiry) for e in selection.distinct}
        | {DVOL_COMPARISON_WINDOW_DAYS}
    )
    lookback = max(windows) + 7
    bars = resolve_spot_history(snap, refresh, reference, lookback)
    realised = realised_vol_windows(
        bars or [], windows, reference=reference, annualisation_days=365.0
    )

    summary = build_summary(snap, selection, realised, reference)

    summary_dir = (
        snap.directory
        if snap.directory.parent == DEFAULT_OUT_ROOT
        else out_root
    )
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / PHASE1_SUMMARY_FILE
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote Phase-1 summary to %s", summary_path)

    _print_human(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="C8 Phase 1 — live market snapshot + IV surface + expiry selection"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Pull live Deribit endpoints and freeze a new snapshot (needs egress)",
    )
    parser.add_argument(
        "--out-root",
        type=pathlib.Path,
        default=DEFAULT_OUT_ROOT,
        help="Root directory for frozen snapshots (default: market_snapshots/)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run(refresh=args.refresh, out_root=args.out_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
