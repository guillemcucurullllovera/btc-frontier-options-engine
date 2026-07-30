#!/usr/bin/env python3
"""C8 Phase 2 — build the deterministic strategy grid off the frozen anchor.

Loads the promoted market snapshot, selects the two real listed expiries, builds
the full strategy grid (8-structure toolkit + 2 heroes x strike% x expiry x
coverage), and emits it as JSON alongside a human-readable sample slice for the
two heroes plus one non-hero structure (with leg decomposition).

Usage:
  python scripts/build_strategy_grid.py                 # uses the promoted anchor
  python scripts/build_strategy_grid.py --snapshot DIR  # a specific snapshot dir
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from strategy.strategy_grid import (
    GridExpiry,
    GridRow,
    StrategyGrid,
    atm_iv_for_expiry,
    build_grid,
)
from vol.chain import select_expiries
from vol.snapshot import load_snapshot, promoted_anchor_dir

logger = logging.getLogger("c8.grid")

REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT: pathlib.Path = REPO_ROOT / "market_snapshots"
FIXTURES_DIR: pathlib.Path = REPO_ROOT / "tests" / "fixtures"
GRID_FILE: str = "strategy_grid.json"
RISK_FREE_RATE: float = 0.04  # config/params.yaml risk_free_rate_pct (business parameter)


def build_from_snapshot(snapshot_dir: pathlib.Path) -> StrategyGrid:
    snap = load_snapshot(snapshot_dir)
    s0 = snap.spot.price
    ref = snap.meta.created_at
    sel = select_expiries(snap.instruments, snap.book_summaries, reference=ref)
    expiries: list[GridExpiry] = []
    for e in sel.distinct:
        aiv = atm_iv_for_expiry(e.expiry.isoformat(), s0, snap.instruments, snap.book_summaries)
        expiries.append(GridExpiry(
            label=e.label,
            expiry_utc=e.expiry.isoformat(),
            dte_days=e.days_to_expiry,
            t_years=e.days_to_expiry / 365.0,
            atm_iv=aiv,
            sigma_horizon=aiv * math.sqrt(e.days_to_expiry / 365.0),
        ))
    return build_grid(
        ref.isoformat(), str(snapshot_dir), s0, RISK_FREE_RATE, expiries,
        snap.instruments, snap.book_summaries,
    )


def _print_row(row: GridRow, s0: float) -> None:
    print(f"\n  [{row.structure_id}] {row.business_label}"
          f"  ({row.canonical_kind}{', HERO' if row.is_hero else ''})")
    print(f"    expiry {row.expiry_label} ({row.dte_days:.2f}d, T={row.t_years:.4f})  "
          f"coverage {row.coverage_pct:g}%  strike% {row.strike_pct}")
    for leg in row.option_legs:
        print(f"    leg: {leg.side} {leg.kind} {leg.instrument}  K={leg.listed_strike:g}  "
              f"iv={leg.iv:.4f} ({leg.iv_provenance})  premium/BTC={leg.premium_per_btc:.2f}")
    pr = row.premium
    print(f"    net premium: {pr.net_per_btc:.2f}/BTC  {pr.pct_of_spot:.3f}% spot  "
          f"{pr.per_contract:.0f}/contract  {pr.per_portfolio:,.0f}/portfolio  "
          f"(CEO ref {pr.ceo_reference_pct}%, deck {pr.deck_reference_pct}%)")
    if row.prob_win is not None:
        print(f"    prob-win: {row.prob_win.value:.4f}  [{row.prob_win.measure}]  "
              f"delta-proxy {row.prob_win.delta_proxy:.4f}")
    ml = row.max_loss
    print(f"    max loss (3-way) at S_T={ml.worst_case_spot:.0f}:  "
          f"holding {ml.holding.per_btc:,.0f}/BTC  option {ml.option.per_btc:,.0f}/BTC  "
          f"total {ml.total.per_btc:,.0f}/BTC")
    print(f"        total {ml.total.per_portfolio:,.0f} portfolio  "
          f"{ml.total_pct_of_notional*100:.1f}% notional  "
          f"{ml.total_pct_of_capital*100:.1f}% capital (cap {ml.capital_usd:,.0f})"
          f"{'  UNBOUNDED' if ml.unbounded else ''}")
    print(f"    breakevens: strike%OTM={row.breakeven.strike_pct_otm}  "
          f"true={[round(b, 1) for b in row.breakeven.true_breakevens]}")
    if row.effective_net_price is not None:
        print(f"    effective net acquisition price: {row.effective_net_price:,.0f}")
    g = row.greeks
    print(f"    greeks/BTC: opt delta {g.option_delta_per_btc:+.4f}  vega {g.option_vega_per_btc:+.1f}  "
          f"theta/day {g.theta_per_day_per_btc:+.2f}  |  total pos delta {g.total_position_delta_per_block_btc:+.4f}")
    rr = row.risk_reward
    p2ml = f"{rr.premium_to_max_loss:.4f}" if rr.premium_to_max_loss is not None else "n/a"
    ud = f"{rr.upside_downside_2sigma:.3f}" if rr.upside_downside_2sigma is not None else "n/a"
    print(f"    risk-reward: premium/max-loss={p2ml}  upside/downside(2sigma)={ud}")
    print(f"    sigma_h={row.sigma_horizon:.4f}  scenarios (k-sigma | %move | S_T | "
          f"hold/BTC | option/BTC | TOTAL/BTC | %port):")
    for tag, cells in (("INSTANT", row.scenarios_instantaneous), ("TERMINAL", row.scenarios_terminal)):
        print(f"      {tag}:")
        for c in cells:
            print(f"        {c.k_sigma:+.0f}s {c.pct_move*100:+6.1f}% S={c.scenario_spot:8.0f}  "
                  f"{c.holding.per_btc:+9.0f}  {c.option.per_btc:+9.0f}  {c.total.per_btc:+9.0f}  "
                  f"{c.pct_of_portfolio*100:+6.1f}%")
    print(f"    attractive when: {row.attractive_when}")


def print_sample_slice(grid: StrategyGrid) -> None:
    print("\n" + "=" * 78)
    print("C8 PHASE 2 — STRATEGY GRID SAMPLE SLICE")
    print("=" * 78)
    print(f"as of {grid.as_of_utc}  |  S0={grid.s0:,.2f}  r={grid.r}  "
          f"block={grid.block_btc:,} BTC ({grid.block_btc // grid.cme_contract_btc:,} CME contracts)")
    for e in grid.expiries:
        print(f"  expiry {e.label}: DTE={e.dte_days:.2f}  ATM_IV={e.atm_iv:.4f}  "
              f"sigma_h={e.sigma_horizon:.4f}")
    print(f"  total rows: {len(grid.rows)}")

    def pick(structure_id: str, strike_pct: float | None) -> GridRow | None:
        for row in grid.rows:
            if (row.structure_id == structure_id and row.expiry_label == "28AUG26"
                    and row.coverage_pct == 100.0 and row.strike_pct == strike_pct):
                return row
        return None

    print("\n--- HERO 1: Covered Call (Long BTC + Short Call), 28AUG26, 5% OTM, 100% coverage ---")
    r1 = pick("covered_call", 5.0)
    if r1:
        _print_row(r1, grid.s0)
    print("\n--- HERO 2: Long BTC + Short Put, 28AUG26, 5% OTM, 100% coverage ---")
    r2 = pick("long_btc_plus_short_put", -5.0)
    if r2:
        _print_row(r2, grid.s0)
    print("\n--- NON-HERO: Cash-Secured Put, 28AUG26, 5% OTM, 100% coverage ---")
    r3 = pick("cash_secured_put", -5.0)
    if r3:
        _print_row(r3, grid.s0)

    print("\nFraming notes:")
    for note in grid.framing_notes:
        print(f"  - {note}")
    print(f"\nDisclaimer: {grid.disclaimer}")
    print("=" * 78 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="C8 Phase 2 — build the strategy grid")
    parser.add_argument("--snapshot", type=pathlib.Path, default=None,
                        help="Snapshot dir (default: promoted anchor, then fixtures)")
    parser.add_argument("--out", type=pathlib.Path, default=None,
                        help="Grid JSON output path (default: <snapshot>/strategy_grid.json)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    snapshot_dir = args.snapshot or promoted_anchor_dir(DEFAULT_OUT_ROOT) or FIXTURES_DIR
    logger.info("Building strategy grid from snapshot %s", snapshot_dir)
    grid = build_from_snapshot(snapshot_dir)

    out = args.out or (snapshot_dir / GRID_FILE)
    out.write_text(json.dumps(dataclasses.asdict(grid), indent=2), encoding="utf-8")
    logger.info("Wrote strategy grid (%d rows) to %s", len(grid.rows), out)

    print_sample_slice(grid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
