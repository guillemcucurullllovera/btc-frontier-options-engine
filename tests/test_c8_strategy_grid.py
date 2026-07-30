"""C8 Phase 2 — deterministic strategy-grid tests with an independent oracle.

The grid's primary computation is an explicit closed-form leg decomposition.
Two independent oracles reconcile it to rtol 1e-9:

  * premium + instantaneous reprice  — a self-contained erf-based Black-Scholes
    (distinct from the scipy pricer the grid uses);
  * terminal scenario P&L / max-loss / breakevens — the existing, separately
    written strategy engine (`strategy.payoffs`) over an equivalently-constructed
    `Strategy` object.

Offline: the grid is built from the frozen Deribit fixtures (which double as a
snapshot) at a pinned reference date.  No live network.
"""

from __future__ import annotations

import math
import pathlib
import sys
from datetime import UTC, datetime
from typing import Literal, cast

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from engine.errors import ClassificationError
from engine.strategy import Strategy, StrategyKind, classify
from strategy.definitions import (
    _make_cash_leg,
    _make_spot_leg,
    _make_usd_option_leg,
)
from strategy.payoffs import breakeven_points, strategy_pnl, structural_max_loss
from strategy.strategy_grid import (
    GridExpiry,
    GridRow,
    StrategyGrid,
    atm_iv_for_expiry,
    build_grid,
)
from vol.chain import select_expiries
from vol.snapshot import load_snapshot

FIXTURE_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
)
REFERENCE: datetime = datetime(2026, 7, 30, tzinfo=UTC)
R: float = 0.04
RTOL: float = 1e-9


# ── Independent erf-based Black-Scholes (oracle pricer) ─────────────────────


def _erf_norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def erf_bs_price(s: float, k: float, r: float, sigma: float, t: float, kind: str) -> float:
    sqt = math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqt)
    d2 = d1 - sigma * sqt
    disc = math.exp(-r * t)
    if kind == "call":
        return s * _erf_norm_cdf(d1) - k * disc * _erf_norm_cdf(d2)
    return k * disc * _erf_norm_cdf(-d2) - s * _erf_norm_cdf(-d1)


def _intrinsic(s: float, k: float, kind: str) -> float:
    return max(s - k, 0.0) if kind == "call" else max(k - s, 0.0)


# ── Build the grid once from the offline fixtures ───────────────────────────


def _build_grid() -> StrategyGrid:
    snap = load_snapshot(FIXTURE_DIR)
    s0 = snap.spot.price
    sel = select_expiries(snap.instruments, snap.book_summaries, reference=REFERENCE)
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
        REFERENCE.isoformat(), str(FIXTURE_DIR), s0, R, expiries,
        snap.instruments, snap.book_summaries,
    )


GRID: StrategyGrid = _build_grid()
S0: float = GRID.s0
BLOCK: int = GRID.block_btc


# ── Oracle: reconstruct the equivalent engine Strategy ──────────────────────


def oracle_strategy(row: GridRow) -> Strategy:
    cov = row.coverage_pct / 100.0
    expiry = datetime.fromisoformat(row.expiry_utc)
    legs = []
    if row.has_holding:
        legs.append(_make_spot_leg(BLOCK, S0))
    if row.has_cash and row.option_legs:
        k = row.option_legs[0].listed_strike
        legs.append(_make_cash_leg(cov * BLOCK * k))
    for leg in row.option_legs:
        qty = leg.notional_weight * cov * BLOCK
        legs.append(_make_usd_option_leg(
            cast(Literal["call", "put"], leg.kind),
            cast(Literal["LONG", "SHORT"], leg.side),
            qty, leg.listed_strike, leg.premium_per_btc, expiry=expiry,
        ))
    try:
        canonical = classify(legs)
    except ClassificationError:
        canonical = StrategyKind.BESPOKE
    return Strategy(
        strategy_id=f"oracle_{row.structure_id}", business_label=row.business_label,
        canonical=canonical, legs=legs,
    )


def _independent_option_pnl_portfolio(row: GridRow, s: float, mode: str) -> float:
    """Option-leg P&L for the whole portfolio, recomputed independently."""
    cov = row.coverage_pct / 100.0
    total = 0.0
    for leg in row.option_legs:
        if mode == "terminal":
            value = _intrinsic(s, leg.listed_strike, leg.kind)
        else:
            value = erf_bs_price(s, leg.listed_strike, R, leg.iv, row.t_years, leg.kind)
        pnl = leg.side_sign * (leg.premium_per_btc - value)
        total += leg.notional_weight * cov * BLOCK * pnl
    return total


# ══════════════════════════════════════════════════════════════════════════
# 1. Coverage / parity: every structure is first-class
# ══════════════════════════════════════════════════════════════════════════


def test_full_toolkit_present() -> None:
    ids = {r.structure_id for r in GRID.rows}
    assert ids == {
        "unhedged_baseline", "covered_call", "long_btc_plus_short_put",
        "cash_secured_put", "collar", "call_spread", "strike_ladder",
    }
    # partial_overlay is the covered_call family at coverage<100 (canonical reflects it).
    kinds = {r.canonical_kind for r in GRID.rows}
    assert "partial_overlay" in kinds
    assert "covered_call" in kinds


def test_grid_axes_swept() -> None:
    cc = [r for r in GRID.rows if r.structure_id == "covered_call"]
    # 5 call strikes x 2 expiries x 4 coverages
    assert len(cc) == 5 * 2 * 4
    assert {r.coverage_pct for r in cc} == {25.0, 50.0, 75.0, 100.0}
    assert {r.strike_pct for r in cc} == {1.5, 3.0, 5.0, 10.0, 15.0}
    assert {r.expiry_label for r in cc} == {"28AUG26", "25SEP26"}


def test_heroes_flagged() -> None:
    heroes = {r.structure_id for r in GRID.rows if r.is_hero}
    assert heroes == {"covered_call", "long_btc_plus_short_put"}


def test_per_tenor_sigma_differs() -> None:
    # Coherence guard (a): each expiry uses its OWN ATM IV -> different sigma_h.
    by_exp = {e.label: e for e in GRID.expiries}
    assert by_exp["28AUG26"].atm_iv != by_exp["25SEP26"].atm_iv
    assert by_exp["28AUG26"].sigma_horizon != by_exp["25SEP26"].sigma_horizon


# ══════════════════════════════════════════════════════════════════════════
# 2. Premium reconciles to an independent erf-BS pricer (rtol 1e-9)
# ══════════════════════════════════════════════════════════════════════════


def test_premium_matches_independent_bs() -> None:
    for row in GRID.rows:
        for leg in row.option_legs:
            expected = erf_bs_price(S0, leg.listed_strike, R, leg.iv, row.t_years, leg.kind)
            assert leg.premium_per_btc == pytest.approx(expected, rel=RTOL)


# ══════════════════════════════════════════════════════════════════════════
# 3. Scenario P&L per leg reconciles (terminal via engine, both via erf-BS)
# ══════════════════════════════════════════════════════════════════════════


def test_terminal_total_reconciles_engine() -> None:
    for row in GRID.rows:
        strat = oracle_strategy(row)
        for cell in row.scenarios_terminal:
            expected = strategy_pnl(strat, cell.scenario_spot)
            assert cell.total.per_portfolio == pytest.approx(expected, rel=RTOL, abs=1e-6)


def test_scenario_leg_decomposition() -> None:
    for row in GRID.rows:
        for mode, cells in (
            ("terminal", row.scenarios_terminal),
            ("instantaneous", row.scenarios_instantaneous),
        ):
            for cell in cells:
                s = cell.scenario_spot
                exp_hold = (BLOCK * (s - S0)) if row.has_holding else 0.0
                exp_opt = _independent_option_pnl_portfolio(row, s, mode)
                assert cell.holding.per_portfolio == pytest.approx(exp_hold, rel=RTOL, abs=1e-6)
                assert cell.option.per_portfolio == pytest.approx(exp_opt, rel=RTOL, abs=1e-6)
                assert cell.total.per_portfolio == pytest.approx(
                    exp_hold + exp_opt, rel=RTOL, abs=1e-6
                )


def test_granularity_consistency() -> None:
    for row in GRID.rows:
        for cell in row.scenarios_terminal:
            assert cell.total.per_btc == pytest.approx(cell.total.per_portfolio / BLOCK, rel=RTOL)
            assert cell.total.per_contract == pytest.approx(cell.total.per_btc * 5, rel=RTOL)


# ══════════════════════════════════════════════════════════════════════════
# 4. Max loss (3-way) reconciles to the engine + brief identities
# ══════════════════════════════════════════════════════════════════════════


def test_max_loss_reconciles_engine() -> None:
    for row in GRID.rows:
        strat = oracle_strategy(row)
        engine_ml = structural_max_loss(strat)  # positive magnitude
        grid_ml = -row.max_loss.total.per_portfolio  # grid stores signed (negative)
        if math.isinf(engine_ml):
            assert row.max_loss.unbounded
        else:
            assert grid_ml == pytest.approx(engine_ml, rel=1e-9, abs=1e-3)
            # 3-way legs sum to total at the worst-case spot.
            legs_sum = (
                row.max_loss.holding.per_portfolio
                + row.max_loss.option.per_portfolio
                + row.max_loss.cash.per_portfolio
            )
            assert legs_sum == pytest.approx(row.max_loss.total.per_portfolio, rel=RTOL, abs=1e-6)


def test_covered_call_max_loss_identity() -> None:
    # Covered call total max loss = q*(S0 - P); overlay leg is a +premium cushion.
    row = _find("covered_call", "28AUG26", 5.0, 100.0)
    p = row.option_legs[0].premium_per_btc
    assert row.max_loss.total.per_btc == pytest.approx(-(S0 - p), rel=1e-9)
    assert row.max_loss.option.per_btc == pytest.approx(p, rel=1e-9)  # cushion >= 0
    assert row.max_loss.holding.per_btc == pytest.approx(-S0, rel=1e-9)  # BTC-inherent


def test_lbsp_max_loss_identity() -> None:
    # LBSP total max loss = q*(S0 + K - P).
    row = _find("long_btc_plus_short_put", "28AUG26", -5.0, 100.0)
    k = row.option_legs[0].listed_strike
    p = row.option_legs[0].premium_per_btc
    assert row.max_loss.total.per_btc == pytest.approx(-(S0 + k - p), rel=1e-9)


# ══════════════════════════════════════════════════════════════════════════
# 5. Breakevens reconcile to the engine root-finder
# ══════════════════════════════════════════════════════════════════════════


def test_breakevens_reconcile_engine() -> None:
    for row in GRID.rows:
        strat = oracle_strategy(row)
        engine_bes = sorted(breakeven_points(strat))
        grid_bes = sorted(row.breakeven.true_breakevens)
        assert len(grid_bes) == len(engine_bes)
        for g, e in zip(grid_bes, engine_bes, strict=True):
            assert g == pytest.approx(e, rel=1e-7, abs=1e-2)


# ══════════════════════════════════════════════════════════════════════════
# 6. Piecewise-payoff identities (not the CEO's flat x2) + leg attribution
# ══════════════════════════════════════════════════════════════════════════


def test_lbsp_slope_two_below_strike() -> None:
    row = _find("long_btc_plus_short_put", "28AUG26", -5.0, 100.0)
    k = row.option_legs[0].listed_strike
    below = [c for c in row.scenarios_terminal if c.scenario_spot < k]
    assert len(below) >= 2
    below.sort(key=lambda c: c.scenario_spot)
    a, b = below[0], below[1]
    slope = (b.total.per_btc - a.total.per_btc) / (b.scenario_spot - a.scenario_spot)
    assert slope == pytest.approx(2.0, abs=1e-6)  # +2 below strike, NOT a flat x2


def test_covered_call_capped_above_strike() -> None:
    # At coverage 100 the covered call is fully capped above the call strike (slope 0).
    row = _find("covered_call", "28AUG26", 5.0, 100.0)
    k = row.option_legs[0].listed_strike
    above = sorted(
        (c for c in row.scenarios_terminal if c.scenario_spot > k),
        key=lambda c: c.scenario_spot,
    )
    assert len(above) >= 2
    slope = (above[-1].total.per_btc - above[0].total.per_btc) / (
        above[-1].scenario_spot - above[0].scenario_spot
    )
    assert slope == pytest.approx(0.0, abs=1e-6)


def test_covered_call_overlay_nonneg_in_down_scenarios() -> None:
    # Overlay leg is a non-negative premium cushion when spot falls (downside is BTC-inherent).
    for row in GRID.rows:
        if row.structure_id != "covered_call":
            continue
        for c in row.scenarios_terminal:
            if c.scenario_spot <= S0:
                assert c.option.per_portfolio >= -1e-6


def test_lbsp_overlay_negative_below_strike() -> None:
    # Overlay leg goes negative below the strike — incremental advised downside.
    row = _find("long_btc_plus_short_put", "28AUG26", -5.0, 100.0)
    k = row.option_legs[0].listed_strike
    below = [c for c in row.scenarios_terminal if c.scenario_spot < k]
    assert below
    assert all(c.option.per_portfolio < 0 for c in below)


# ══════════════════════════════════════════════════════════════════════════
# 7. Prob-of-win labelling + greeks sanity
# ══════════════════════════════════════════════════════════════════════════


def test_prob_win_labelled_risk_neutral() -> None:
    for row in GRID.rows:
        if row.prob_win is None:
            continue
        assert "risk_neutral" in row.prob_win.measure
        assert 0.0 < row.prob_win.value < 1.0
        assert 0.0 <= row.prob_win.delta_proxy <= 1.0


def test_covered_call_reduces_delta() -> None:
    row = _find("covered_call", "28AUG26", 5.0, 100.0)
    assert row.greeks.option_delta_per_btc < 0.0  # short call: negative delta
    assert 0.0 < row.greeks.total_position_delta_per_block_btc < 1.0  # below full long
    assert row.greeks.theta_per_day_per_btc > 0.0  # short option: positive time decay
    assert row.greeks.option_vega_per_btc < 0.0  # short: negative vega


# ── helper ──────────────────────────────────────────────────────────────────


def _find(structure_id: str, expiry: str, strike_pct: float, coverage: float) -> GridRow:
    for row in GRID.rows:
        if (
            row.structure_id == structure_id
            and row.expiry_label == expiry
            and row.strike_pct == strike_pct
            and row.coverage_pct == coverage
        ):
            return row
    raise AssertionError(f"row not found: {structure_id} {expiry} {strike_pct} {coverage}")
