#!/usr/bin/env python3
"""Shared CEO-grid column layout (C10 · N7) — surface grid.json in the CEO's Excel column set.

SIMULATED / diagnostic; MS-26-gated; holder-basis; no best/optimal. This is a SURFACING / reformat layer
— it recomputes NOTHING; every value is read straight out of a deck-input grid row (grid.json / the
in-memory StrategyGrid). It reproduces the column layout of the CEO's working Excel
(meeting_change_input/excelmadebyceoduringpresentation_options_strategy.xlsx) — Structure, Premium,
Contracts/Exposure (= coverage), Premium in USD, Time days, Prob of Win, Break-even, max loss BTC / Option
/ total, Weekly vola, weeks, the +/-sigma P&L scenarios, Total Exposure, BTC, Options contracts, Total P&L
portfolio, opportunity cost, "Esta no es nuestra culpa" (not-our-fault), INF (uncapped-loss marker) — filled
with THIS engine's values. Both the hand-off markdown tables and the machine-readable grid_summary.csv
consume `ceo_row()` so they stay identical by construction.
"""

from __future__ import annotations

import math
from typing import Any

BLOCK_BTC = 30_000          # the 30,000-BTC block (deck reference quantity)
CME_CONTRACT_BTC = 5        # CME BTC futures/options contract size
_WEEKS_PER_YEAR = 52.0


def _scalar(x: Any) -> float | None:
    """A per-BTC (or plain) scalar out of a Granular dict / passthrough."""
    if isinstance(x, dict):
        for k in ("per_btc", "value", "total"):
            if k in x and not isinstance(x[k], dict | list):
                return float(x[k])
        return None
    return None if x is None else float(x)


def _scen_port(r: dict[str, Any], k: float) -> float | None:
    """Terminal PORTFOLIO P&L (per_portfolio) at the k-sigma scenario."""
    for s in r.get("scenarios_terminal_portfolio", []) or []:
        if s.get("k_sigma") == k:
            return float(s["total"]["per_portfolio"])
    return None


def _oppcost(r: dict[str, Any], k: float, field: str) -> float | None:
    """Foregone upside gain at the +k-sigma scenario (opportunity cost, NOT a loss)."""
    for o in r.get("opportunity_cost", []) or []:
        if o.get("k_sigma") == k:
            return float(o["foregone"][field])
    return None


def _legs(r: dict[str, Any]) -> list[dict[str, Any]]:
    return list(r.get("option_legs", []) or [])


def put_floor(r: dict[str, Any]) -> float | None:
    """The protective LONG-put %OTM (disambiguates the two collar variants); None if no long put."""
    for le in _legs(r):
        if le.get("kind") == "put" and le.get("side") == "LONG" and le.get("requested_pct") is not None:
            return float(le["requested_pct"])
    return None


def sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
    """Deterministic grid ordering (put-floor tiebreak groups the collar variants, 10% floor first)."""
    return (r["structure_id"], r["dte_days"], r.get("strike_pct") or 0.0, r["coverage_pct"],
            put_floor(r) if put_floor(r) is not None else 0.0)


def uncapped_inf(r: dict[str, Any]) -> str:
    """The CEO's 'INF' marker: a short-call leg's standalone loss is unbounded (uncapped upside-loss).

    It is COVERED by the 30,000-BTC holding, so the full position's total max-loss is finite (shown)."""
    legs = _legs(r)
    short_call = any(le.get("kind") == "call" and le.get("side") == "SHORT" for le in legs)
    long_call = any(le.get("kind") == "call" and le.get("side") == "LONG" for le in legs)
    if not legs:
        return "n/a"
    return "INF*" if (short_call and not long_call) else "no"


def weekly_vol(r: dict[str, Any]) -> float | None:
    """Weekly-vol equivalent of the annualised DVOL (the CEO's 'Weekly vola'); DVOL stays primary."""
    iv = r.get("atm_iv")
    return None if iv is None else float(iv) / math.sqrt(_WEEKS_PER_YEAR)


def not_our_fault(r: dict[str, Any]) -> str:
    """N7d — the opportunity-cost / 'Esta no es nuestra culpa' framing, per row (holder-basis)."""
    legs = _legs(r)
    short_call = any(le.get("kind") == "call" and le.get("side") == "SHORT" for le in legs)
    short_put = any(le.get("kind") == "put" and le.get("side") == "SHORT" for le in legs)
    if not legs:
        return "Baseline: full BTC exposure, no overlay — the down-scenario is entirely the held BTC."
    if short_put and not short_call:
        return ("Sub-strike outcome = acquiring more of the BTC you already hold at the effective entry; "
                "the down-scenario is BTC's inherent risk, not the overlay.")
    if short_call:
        return ("Capped upside above the strike = opportunity cost (foregone gain), NOT a loss; "
                "the down-scenario is the held BTC's inherent risk, not the overlay.")
    return ("Down-scenarios are inherent to holding 30,000 BTC (existing exposure), not created by the "
            "overlay; any capped upside is opportunity cost, not a loss.")


# Ordered (header, extractor) — the CEO's Excel column layout, filled from a grid row. Extractors return
# raw numbers/strings (no formatting), so the CSV and the markdown tables share ONE definition.
CEO_COLUMNS: list[tuple[str, Any]] = [
    ("Structure", lambda r: r.get("business_label")),
    ("Strike %OTM", lambda r: r.get("strike_pct")),
    ("Contracts/Exposure (coverage)", lambda r: (r.get("coverage_pct") or 0.0) / 100.0),
    ("Expiry", lambda r: r.get("expiry_label")),
    ("Time days", lambda r: r.get("dte_days")),
    ("weeks", lambda r: (r.get("dte_days") or 0.0) / 7.0),
    ("Premium %", lambda r: (r.get("premium") or {}).get("pct_of_spot")),
    ("Premium USD/BTC", lambda r: (r.get("premium") or {}).get("net_per_btc")),
    ("Premium USD/contract(5BTC)", lambda r: (r.get("premium") or {}).get("per_contract")),
    ("Premium USD/portfolio", lambda r: (r.get("premium") or {}).get("per_portfolio")),
    ("Prob of Win", lambda r: _scalar(r.get("prob_win"))),
    ("Break-even %OTM", lambda r: (r.get("breakeven") or {}).get("strike_pct_otm")),
    ("Break-even true", lambda r: ((r.get("breakeven") or {}).get("true_breakevens") or [None])[0]),
    ("Total Exposure USD", lambda r: (r.get("max_loss") or {}).get("capital_usd")),
    ("Max loss BTC-leg /BTC", lambda r: _scalar((r.get("max_loss") or {}).get("holding"))),
    ("Max loss Option-leg /BTC", lambda r: _scalar((r.get("max_loss") or {}).get("option"))),
    ("Max loss total /BTC", lambda r: _scalar((r.get("max_loss") or {}).get("total"))),
    ("Max loss total /portfolio", lambda r: ((r.get("max_loss") or {}).get("total") or {}).get("per_portfolio")),
    ("BTC (block)", lambda r: BLOCK_BTC),
    ("Options contracts", lambda r: BLOCK_BTC * (r.get("coverage_pct") or 0.0) / 100.0 / CME_CONTRACT_BTC),
    ("Ann. DVOL", lambda r: r.get("atm_iv")),
    ("Weekly vola", weekly_vol),
    ("P&L portfolio -2sigma", lambda r: _scen_port(r, -2.0)),
    ("P&L portfolio -1sigma", lambda r: _scen_port(r, -1.0)),
    ("P&L portfolio 0", lambda r: _scen_port(r, 0.0)),
    ("P&L portfolio +1sigma", lambda r: _scen_port(r, 1.0)),
    ("P&L portfolio +2sigma", lambda r: _scen_port(r, 2.0)),
    ("Opportunity cost +1sigma /BTC", lambda r: _oppcost(r, 1.0, "per_btc")),
    ("Opportunity cost +2sigma /BTC", lambda r: _oppcost(r, 2.0, "per_btc")),
    ("Opportunity cost +2sigma /portfolio", lambda r: _oppcost(r, 2.0, "per_portfolio")),
    ("Theta/day /BTC", lambda r: (r.get("greeks") or {}).get("theta_per_day_per_btc")),
    ("Uncapped-loss (INF)?", uncapped_inf),
    ("Not-our-fault framing", not_our_fault),
]
CEO_HEADERS: list[str] = [h for h, _ in CEO_COLUMNS]


def ceo_row(r: dict[str, Any]) -> dict[str, Any]:
    """A grid row surfaced as an ordered dict in the CEO's column layout (raw values; no recompute)."""
    return {h: fn(r) for h, fn in CEO_COLUMNS}
