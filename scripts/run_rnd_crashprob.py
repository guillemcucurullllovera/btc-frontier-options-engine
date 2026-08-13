#!/usr/bin/env python3
"""Extract the market-implied RND + crash probabilities from an OBSERVED Deribit surface (A5 / D4).

Loads a snapshot dir (the reprice-gate fixture, or ``market_snapshots/deribit_surface_archive/<date>``),
fits the arb-free SVI surface, runs Breeden-Litzenberger (``vol.rnd.extract_rnd``), and writes
``market_snapshots/rnd/<date>_rnd.json`` with, per usable tenor: the crash ladder (-20/-30/-40/-50%),
the upside ladder, market-implied P(exercise) at the mandate ladder strikes, RND moments, gate results,
and a Q-vs-P column left blank for the MC agent to fill.

CALCULATED_FROM_OBSERVED, MODELED-Q. Canonical main untouched. Run with the frontier venv:
  /home/francisco/btc/btc_engine_frontier/.venv/bin/python scripts/run_rnd_crashprob.py [snapshot_dir]
"""

from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import asdict
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.data_models import BookSummary, OptionInstrument
from vol.chain_surface import ingest_chain_slices
from vol.rnd import extract_rnd

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DEFAULT = _ROOT / "market_snapshots" / "deribit_surface_archive" / "2026-07-31"
# Mandate covered-call ladder strikes (+6/10/14/18% off S0) for the market-implied P(exercise) check.
_LADDER_PCTS = (0.06, 0.10, 0.14, 0.18)


def _read_json(path: pathlib.Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_dir(directory: pathlib.Path) -> tuple[list[OptionInstrument], list[BookSummary], float, datetime]:
    """Load instruments + book summaries + spot + reference time from a snapshot dir.

    Works for both the reprice-gate fixture (``index_price.json``) and the daily surface archive
    (``index.json``); both carry ``instruments.json`` + ``book_summary.json``.
    """
    instruments = [OptionInstrument.model_validate(r) for r in _read_json(directory / "instruments.json")]
    books = [BookSummary.model_validate(r) for r in _read_json(directory / "book_summary.json")]

    spot = 0.0
    for name in ("index.json", "index_price.json"):
        p = directory / name
        if p.exists():
            spot = float(_read_json(p)["price"])   # type: ignore[index,call-overload]
            break
    if spot <= 0:                                    # fall back to median observed underlying
        ups = [b.underlying_price for b in books if b.underlying_price > 0]
        spot = float(sorted(ups)[len(ups) // 2]) if ups else 0.0

    ref = min((b.timestamp for b in books), default=datetime.now(UTC))
    return instruments, books, spot, ref


def main(argv: list[str]) -> int:
    directory = pathlib.Path(argv[1]) if len(argv) > 1 else _DEFAULT
    date_tag = directory.name
    instruments, books, spot, ref = _load_dir(directory)
    slices = ingest_chain_slices(instruments, books, ref)
    ladder = tuple(spot * (1.0 + pct) for pct in _LADDER_PCTS)
    # vega_price (Gatheral §5.2 price-relative) aligns the SVI fit with the price-space ARPE the
    # reprice gate scores; it tightens the RND round-trip on the deck tenor (28AUG26: 5.6%->4.0%).
    report = extract_rnd(slices, spot=spot, ladder_strikes=ladder, objective="vega_price")

    out_dir = _ROOT / "market_snapshots" / "rnd"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_tag}_rnd.json"
    payload = {
        "asof": ref.isoformat(),
        "source_dir": str(directory),
        "spot_usd": spot,
        "ladder_strikes_usd": list(ladder),
        "ladder_pcts": list(_LADDER_PCTS),
        "n_slices_scored": report.n_slices,
        "method": "Breeden-Litzenberger on arb-free SVI (Rotunno §2.1; density>=0 by SVI convexity)",
        "honesty_lock": ("MODELED-Q = market-implied / risk-neutral (what the market CHARGES for "
                         "downside), NOT the physical probability BTC will crash. Q OVERSTATES P "
                         "(pricing kernel larger in bad states). Q-vs-P gap = tail-risk premium; the "
                         "P leg comes from the MC/historical engine and is NEVER blended here."),
        "provenance": report.provenance,
        "q_minus_p_vrp_note": "P_crash column left blank for the MC agent (svjj_mc_tails) to fill.",
        "slices": [asdict(s) for s in report.slices],
    }
    out_path.write_text(json.dumps(payload, indent=2))

    print(f"RND on OBSERVED surface {date_tag}  S0=${spot:,.0f}  scored {report.n_slices} tenor(s)")
    hdr = (f"{'tenor':>9}{'Tdays':>7}{'nK':>4}{'skew':>7}{'P(-20%)':>9}{'P(-30%)':>9}"
           f"{'P(-40%)':>9}{'P(-50%)':>9}{'RTarpe%':>9}{'gates':>7}")
    print(hdr)
    for s in report.slices:
        c = s.crash_prob
        ex = "*" if any(s.crash_extrapolated.values()) else " "
        print(f"{s.label:>9}{s.T_days:>7.0f}{s.n_strikes:>4}{s.rnd_skew:>7.2f}"
              f"{c['-20%']*100:>8.2f}%{c['-30%']*100:>8.2f}%{c['-40%']*100:>8.2f}{ex}"
              f"{c['-50%']*100:>7.2f}{ex}{s.roundtrip_arpe_core*100:>8.2f}%"
              f"{'PASS' if s.gates_pass else 'FAIL':>7}")
    print("  (* = threshold below deepest OBSERVED strike -> EXTRAPOLATED, MODELED-Q wide band)")
    print("\nMarket-implied P(exercise) at the +6/10/14/18% ladder strikes (deck-relevant tenor):")
    deck = next((s for s in report.slices if 25.0 <= s.T_days < 45.0), report.slices[0] if report.slices else None)
    if deck is not None:
        print(f"  {deck.label} ({deck.T_days:.0f}d):  "
              + "  ".join(f"${int(k):,}:{v*100:.1f}%" for k, v in deck.exercise_prob.items()))
        print(f"  RND-implied ATM IV {deck.atm_iv_svi*100:.2f}% vs OBSERVED ATM {deck.atm_iv_observed*100:.2f}%  "
              f"| pre-norm mass {deck.prenorm_mass:.4f} | min f {deck.min_density:.2e}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
