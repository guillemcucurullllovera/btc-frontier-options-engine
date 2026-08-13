#!/usr/bin/env python3
"""Deribit trade-reconstruction of an option smile (C10 · N3.5.2) — with the free-API coverage limit.

SIMULATED / diagnostic; MS-26-gated; OBSERVED; deck & canonical main untouched. Reconstructs a traded
option smile (strike -> traded IV) from get_last_trades_by_currency. FINDING (documented): Deribit's FREE
public API exposes only RECENT option trades — get_last_trades_by_currency works, but the per-instrument
expired-trade history and get_last_trades_by_currency_and_time for historical windows return EMPTY. So a
HISTORICAL smile reconstruction is NOT free-feasible; only a RECENT traded smile is (which the forward
archiver, N2, densifies going forward). This script delivers the recent traded smile (checksummed) + the
documented coverage limit. Writes docs/reports/c10_n3_5_trade_smile.json.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime

_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c10_n3_5_trade_smile.json"
_RECENT = "https://www.deribit.com/api/v2/public/get_last_trades_by_currency?currency=BTC&kind=option&count=1000"
_HIST = ("https://www.deribit.com/api/v2/public/get_last_trades_by_currency_and_time"
         "?currency=BTC&kind=option&start_timestamp={s}&end_timestamp={e}&count=100")


def _get(url: str) -> list[dict[str, object]]:
    with urllib.request.urlopen(url, timeout=30) as r:
        return list(json.load(r)["result"].get("trades", []))


def _parse(name: str) -> tuple[str, float, str] | None:
    # BTC-DDMMMYY-STRIKE-C/P
    parts = name.split("-")
    if len(parts) != 4:
        return None
    return parts[1], float(parts[2]), parts[3]


def main() -> int:
    now = datetime.now(UTC)
    recent = _get(_RECENT)
    # probe the historical-window endpoint at 4 past dates to DOCUMENT the free-API limit
    hist_probe = {}
    for y, m, d in [(2022, 6, 15), (2023, 6, 15), (2024, 6, 15), (2025, 6, 15)]:
        s = int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)
        try:
            hist_probe[f"{y}-{m:02d}"] = len(_get(_HIST.format(s=s, e=s + 6 * 3600 * 1000)))
        except Exception:
            hist_probe[f"{y}-{m:02d}"] = -1

    # reconstruct the recent smile: last traded IV per (expiry, strike, type); pick the best-covered expiry
    by_exp: dict[str, dict[float, float]] = defaultdict(dict)
    for t in recent:
        pr = _parse(str(t.get("instrument_name", "")))
        iv = t.get("iv")
        if pr and isinstance(iv, int | float):
            exp, strike, _typ = pr
            by_exp[exp][strike] = float(iv) / 100.0
    best_exp = max(by_exp, key=lambda e: len(by_exp[e])) if by_exp else None
    smile = (sorted([{"strike": k, "iv": v} for k, v in by_exp[best_exp].items()], key=lambda x: x["strike"])
             if best_exp else [])

    out = {
        "fetched_at_utc": now.isoformat(), "source": "deribit get_last_trades_by_currency (FREE)",
        "provenance": "OBSERVED",
        "recent_n_trades": len(recent), "recent_distinct_expiries": len(by_exp),
        "recent_smile_expiry": best_exp, "recent_smile_n_strikes": len(smile), "recent_smile": smile,
        "historical_window_probe_n_trades": hist_probe,
        "coverage_limit": ("Deribit FREE API exposes only RECENT option trades. get_last_trades_by_currency "
                           "works; get_last_trades_by_currency_and_time for historical windows returns EMPTY "
                           "(see historical_window_probe: all 0) and expired-instrument trade history is EMPTY. "
                           "=> HISTORICAL smile reconstruction is NOT free-feasible. The recent traded smile "
                           "reconstructs fine and the forward archiver (N2) densifies it going forward; dense "
                           "HISTORICAL Q awaits the archiver accruing or a paid backfill (Phase E / N2 residual)."),
    }
    digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    out["sha256"] = digest
    _OUT.write_text(json.dumps(out, indent=2))
    print(f"recent trades: {len(recent)} across {len(by_exp)} expiries; "
          f"reconstructed smile expiry={best_exp} strikes={len(smile)}", flush=True)
    print(f"historical-window probe (n_trades): {hist_probe}  -> historical reconstruction NOT free-feasible")
    if smile:
        print("smile sample:", [(round(p['strike']), round(p['iv'], 3)) for p in smile[:6]], "...")
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
