"""C8 Phase 3 - rolling-lifecycle Monte Carlo for the two hero structures.

DIAGNOSTIC / SIMULATED ONLY. Per FRONTIER_ORCHESTRATION sec 8 and the pending
MS-26 (approved simulation methodology), these outputs are labelled SIMULATED and
are not decision evidence; no ranking, optimality or convergence claim is made.

Built ON the C7 engine (strategy.multi_cycle_mc): it reuses the deterministic,
chunked, antithetic path generation and MultiCycleMCConfig, and calibrates the
volatility to the live snapshot (per-tenor ATM IV / DVOL - not the ASSUMED 0.45)
and r to the observed Deribit rate. The rolling lifecycle re-strikes every cycle
at entry*(1 +/- strike_target_pct) on the real ~29-day monthly cadence.

This module adds the Slide-5 metric framework on top of the C7 base metrics:
prob-of-loss, VaR95, ES97.5, EAC, max drawdown, ITM/touch frequency - and carries
the BTC-inherent (holding) vs overlay (advised) P&L decomposition into the MC.

Its per-path economics are re-implemented independently of the C7 vectorised core;
the base metrics (mean/median/std P&L) reconcile to strategy.multi_cycle_mc, and a
scalar single-path oracle reconciles the extended metrics (see the Phase-3 tests).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from config.models import Provenance
from engine.errors import ValidationError
from engine.strategy import Strategy
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    _generate_chunk_paths,
    _iter_chunks,
    _seller_discount_threshold,
    _unit_premiums,
)

# Rolling re-strike is well-defined for these holding-inclusive archetypes. The three
# mandate archetypes are covered_call (premium), long_btc_plus_short_put (accumulation)
# and collar (protection); partial_overlay is a coverage-varied covered call.
ARCHETYPE_KINDS: frozenset[str] = frozenset(
    {"covered_call", "partial_overlay", "long_btc_plus_short_put", "collar"}
)
HERO_KINDS = ARCHETYPE_KINDS  # backwards-compatible alias
PARTIAL_OVERLAY_RATIO: float = 0.5
PENDING_DECISION_REFS: tuple[str, ...] = ("D-1", "D-4", "D-7", "D-9", "D-10", "MS-25", "MS-26")


@dataclass(frozen=True)
class HeroMCResult:
    strategy_id: str
    strategy_kind: str
    business_label: str
    # configuration / calibration (all SIMULATED assumptions)
    n_paths: int
    n_cycles: int
    model: str
    seed: int
    initial_spot: float
    volatility: float
    volatility_source: str
    risk_free_rate: float
    risk_free_source: str
    drift: float
    cycle_length_days: float
    strike_target_pct: float

    # ── Slide-5 diagnostic metric framework (SIMULATED) ──
    probability_of_loss: float = 0.0
    var_95_usd: float = 0.0                      # VaR95 = -(5th percentile of P&L)
    var_95_pct_capital: float = 0.0
    expected_shortfall_975_usd: float = 0.0      # ES97.5 = mean loss in worst 2.5% tail
    expected_shortfall_975_pct_capital: float = 0.0
    # Diagnostic rolling-programme effective cost under simulation (NOT the Slide-1
    # acquisition EAC); drift-dependent - see eac_note.
    mean_rolling_programme_eac_usd_per_btc: float = 0.0
    rolling_programme_eac_5_usd_per_btc: float = 0.0
    rolling_programme_eac_95_usd_per_btc: float = 0.0
    eac_note: str = (
        "SIMULATED diagnostic rolling-programme effective cost/BTC under the rolling re-strike "
        "programme; distinct from the Slide-1 one-off acquisition EAC; varies with the ASSUMED drift."
    )
    mean_max_drawdown_usd: float = 0.0
    mean_max_drawdown_pct_capital: float = 0.0
    p95_max_drawdown_usd: float = 0.0
    mean_itm_frequency: float = 0.0              # mean per-cycle share the short option expired ITM
    mean_touch_frequency: float = 0.0            # mean per-cycle share the path touched the strike

    # ── Total terminal P&L (front-and-centre), USD / per-BTC / % of block ──
    total_pnl_mean_usd: float = 0.0
    total_pnl_median_usd: float = 0.0
    total_pnl_p5_usd: float = 0.0
    total_pnl_p25_usd: float = 0.0
    total_pnl_p75_usd: float = 0.0
    total_pnl_p95_usd: float = 0.0
    total_pnl_mean_per_btc: float = 0.0
    total_pnl_median_per_btc: float = 0.0
    total_pnl_p5_per_btc: float = 0.0
    total_pnl_p95_per_btc: float = 0.0
    total_pnl_mean_pct_block: float = 0.0
    total_pnl_p5_pct_block: float = 0.0
    total_pnl_p95_pct_block: float = 0.0

    # ── BTC-inherent vs overlay (advised) decomposition ──
    mean_holding_pnl_usd: float = 0.0            # qty*(final_spot - S0): inherent BTC exposure
    median_holding_pnl_usd: float = 0.0
    mean_holding_pnl_per_btc: float = 0.0
    mean_overlay_gross_pnl_usd: float = 0.0      # premiums - payouts (pre-fee, the advised leg)
    median_overlay_gross_pnl_usd: float = 0.0
    mean_overlay_gross_pnl_per_btc: float = 0.0
    structuring_fee_usd: float = 0.0             # deterministic D-1 line (separate)
    mean_total_pnl_pre_fee_usd: float = 0.0
    mean_total_pnl_post_fee_usd: float = 0.0

    # ── base distribution (for reconciliation to the C7 engine) ──
    mean_outcome_usd: float = 0.0
    median_outcome_usd: float = 0.0
    std_outcome_usd: float = 0.0
    percentile_5_usd: float = 0.0
    percentile_1_usd: float = 0.0
    mc_standard_error: float = 0.0
    probability_of_exceeding_seller_discount: float = 0.0

    capital_base: float = 0.0
    n_non_finite: int = 0                        # gate: must be 0

    provenance: Provenance = Provenance.SIMULATED
    pending_decision_refs: tuple[str, ...] = PENDING_DECISION_REFS
    assumptions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ExtendedPerPath:
    pnl_post_fee: np.ndarray
    holding_pnl: np.ndarray
    overlay_gross: np.ndarray
    max_drawdown: np.ndarray
    itm_count: np.ndarray
    touch_count: np.ndarray
    eac: np.ndarray


# ── extended per-path economics (independent of the C7 vectorised core) ────────


def _extended_cycles_vectorized(
    kind: str, paths: np.ndarray, config: MultiCycleMCConfig, fee: float
) -> _ExtendedPerPath:
    """Rolling-lifecycle economics for one hero over a (m, total_steps+1) path block.

    Options are cash-settled (BTC inventory constant); each cycle re-strikes at
    entry*(1 +/- p). Tracks per-cycle ITM (exit past strike) and touch (intra-cycle
    extremum past strike), and the portfolio MTM drawdown across cycle boundaries.
    """
    if kind not in ARCHETYPE_KINDS:
        raise ValidationError(f"hero MC supports {sorted(ARCHETYPE_KINDS)}, got {kind!r}")
    m = paths.shape[0]
    steps = config.n_steps_per_cycle
    total_steps = config.total_steps
    qty = config.btc_quantity
    overlay_qty = qty * PARTIAL_OVERLAY_RATIO if kind == "partial_overlay" else qty
    p = config.strike_target_pct
    s0 = config.initial_spot
    call_u, put_u = _unit_premiums(config)

    cash = np.full(m, -fee)               # premiums accumulate here; fee charged once up-front
    itm = np.zeros(m)
    touch = np.zeros(m)
    v0 = qty * s0 - fee                   # portfolio MTM at t0 (after fee)
    peak = np.full(m, v0)
    max_dd = np.zeros(m)

    for c in range(config.n_cycles):
        entry = paths[:, c * steps]
        end_idx = min((c + 1) * steps, total_steps)
        exit_ = paths[:, end_idx]
        seg = paths[:, c * steps : end_idx + 1]
        if kind in ("covered_call", "partial_overlay"):
            strike = entry * (1.0 + p)
            cash = cash + entry * call_u * overlay_qty
            cash = cash - np.maximum(exit_ - strike, 0.0) * overlay_qty
            itm = itm + (exit_ > strike)
            touch = touch + (seg.max(axis=1) >= strike)
        elif kind == "long_btc_plus_short_put":
            strike = entry * (1.0 - p)
            cash = cash + entry * put_u * qty
            cash = cash - np.maximum(strike - exit_, 0.0) * qty
            itm = itm + (exit_ < strike)
            touch = touch + (seg.min(axis=1) <= strike)
        else:  # collar: short call at +p (cap) + long put at -p (floor), symmetric
            strike_c = entry * (1.0 + p)
            strike_p = entry * (1.0 - p)
            cash = cash + (entry * call_u - entry * put_u) * qty
            cash = cash - np.maximum(exit_ - strike_c, 0.0) * qty
            cash = cash + np.maximum(strike_p - exit_, 0.0) * qty
            itm = itm + (exit_ > strike_c)               # short-call cap exercised
            touch = touch + (seg.max(axis=1) >= strike_c)
        v = cash + qty * exit_            # MTM at cycle boundary
        peak = np.maximum(peak, v)
        max_dd = np.maximum(max_dd, peak - v)

    final_spot = paths[:, -1]
    holding_pnl = qty * (final_spot - s0)
    overlay_gross = cash + fee            # premiums - payouts (strip the fee back out)
    pnl_post_fee = holding_pnl + overlay_gross - fee
    initial_capital = qty * s0
    eac = (initial_capital - cash) / qty  # cost basis net of accumulated option cash, per BTC
    return _ExtendedPerPath(
        pnl_post_fee=pnl_post_fee,
        holding_pnl=holding_pnl,
        overlay_gross=overlay_gross,
        max_drawdown=max_dd,
        itm_count=itm,
        touch_count=touch,
        eac=eac,
    )


def _extended_path_scalar(
    kind: str, path: np.ndarray, config: MultiCycleMCConfig, fee: float
) -> tuple[float, float, float, float, int, int, float]:
    """Independent scalar reference for ONE path (test oracle).

    Returns (pnl_post_fee, holding_pnl, overlay_gross, max_drawdown, itm, touch, eac).
    """
    steps = config.n_steps_per_cycle
    total_steps = config.total_steps
    qty = config.btc_quantity
    overlay_qty = qty * PARTIAL_OVERLAY_RATIO if kind == "partial_overlay" else qty
    p = config.strike_target_pct
    s0 = config.initial_spot
    call_u, put_u = _unit_premiums(config)

    cash = -fee
    itm = 0
    touch = 0
    peak = qty * s0 - fee
    max_dd = 0.0
    for c in range(config.n_cycles):
        entry = float(path[c * steps])
        end_idx = min((c + 1) * steps, total_steps)
        exit_ = float(path[end_idx])
        seg = path[c * steps : end_idx + 1]
        if kind in ("covered_call", "partial_overlay"):
            strike = entry * (1.0 + p)
            cash += entry * call_u * overlay_qty
            cash -= max(exit_ - strike, 0.0) * overlay_qty
            itm += int(exit_ > strike)
            touch += int(float(seg.max()) >= strike)
        elif kind == "long_btc_plus_short_put":
            strike = entry * (1.0 - p)
            cash += entry * put_u * qty
            cash -= max(strike - exit_, 0.0) * qty
            itm += int(exit_ < strike)
            touch += int(float(seg.min()) <= strike)
        else:  # collar
            strike_c = entry * (1.0 + p)
            strike_p = entry * (1.0 - p)
            cash += (entry * call_u - entry * put_u) * qty
            cash -= max(exit_ - strike_c, 0.0) * qty
            cash += max(strike_p - exit_, 0.0) * qty
            itm += int(exit_ > strike_c)
            touch += int(float(seg.max()) >= strike_c)
        v = cash + qty * exit_
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    final_spot = float(path[-1])
    holding_pnl = qty * (final_spot - s0)
    overlay_gross = cash + fee
    pnl_post_fee = holding_pnl + overlay_gross - fee
    eac = (qty * s0 - cash) / qty
    return pnl_post_fee, holding_pnl, overlay_gross, max_dd, itm, touch, eac


# ── driver ─────────────────────────────────────────────────────────────────────


def run_hero_lifecycle_mc(
    strategy: Strategy,
    config: MultiCycleMCConfig,
    *,
    volatility_source: str = "calibrated: per-tenor ATM IV (snapshot)",
    risk_free_source: str = "observed (deribit interest_rate)",
) -> HeroMCResult:
    """Run the rolling-lifecycle diagnostic MC for one hero and finalise Slide-5 metrics."""
    kind = strategy.canonical.value
    fee = config.asym_fee_usd
    plan = _iter_chunks(config.n_paths, config.chunk_size, config.use_antithetic)

    parts: dict[str, list[np.ndarray]] = {
        "pnl": [], "hold": [], "overlay": [], "dd": [], "itm": [], "touch": [], "eac": [],
    }
    for chunk_index, _start, count in plan:
        paths = _generate_chunk_paths(config, chunk_index, count)
        ext = _extended_cycles_vectorized(kind, paths, config, fee)
        parts["pnl"].append(ext.pnl_post_fee)
        parts["hold"].append(ext.holding_pnl)
        parts["overlay"].append(ext.overlay_gross)
        parts["dd"].append(ext.max_drawdown)
        parts["itm"].append(ext.itm_count)
        parts["touch"].append(ext.touch_count)
        parts["eac"].append(ext.eac)

    pnl = np.concatenate(parts["pnl"])
    hold = np.concatenate(parts["hold"])
    overlay = np.concatenate(parts["overlay"])
    dd = np.concatenate(parts["dd"])
    itm = np.concatenate(parts["itm"])
    touch = np.concatenate(parts["touch"])
    eac = np.concatenate(parts["eac"])
    return _finalize_hero(
        strategy, config, pnl, hold, overlay, dd, itm, touch, eac, fee,
        volatility_source, risk_free_source,
    )


def _finalize_hero(
    strategy: Strategy,
    config: MultiCycleMCConfig,
    pnl: np.ndarray,
    hold: np.ndarray,
    overlay: np.ndarray,
    dd: np.ndarray,
    itm: np.ndarray,
    touch: np.ndarray,
    eac: np.ndarray,
    fee: float,
    volatility_source: str,
    risk_free_source: str,
) -> HeroMCResult:
    n = pnl.shape[0]
    capital = config.capital_base
    block = config.btc_quantity
    n_non_finite = int(np.count_nonzero(~np.isfinite(pnl)))

    p1 = float(np.percentile(pnl, 1))
    p5 = float(np.percentile(pnl, 5))
    p25 = float(np.percentile(pnl, 25))
    p75 = float(np.percentile(pnl, 75))
    p95 = float(np.percentile(pnl, 95))
    mean_pnl = float(np.mean(pnl))
    median_pnl = float(np.median(pnl))
    var95 = -p5  # VaR95: magnitude of the 5th-percentile loss
    losses = -pnl
    tail_cut = float(np.percentile(losses, 97.5))
    es975 = float(np.mean(losses[losses >= tail_cut])) if n else 0.0

    valid_eac = eac[np.isfinite(eac)]
    mean_eac = float(np.mean(valid_eac)) if valid_eac.size else float("nan")
    eac5 = float(np.percentile(valid_eac, 5)) if valid_eac.size else float("nan")
    eac95 = float(np.percentile(valid_eac, 95)) if valid_eac.size else float("nan")

    std_pnl = float(np.std(pnl))
    mc_se = std_pnl / math.sqrt(n) if n else 0.0

    return HeroMCResult(
        strategy_id=strategy.strategy_id,
        strategy_kind=strategy.canonical.value,
        business_label=strategy.business_label,
        n_paths=n,
        n_cycles=config.n_cycles,
        model=config.model,
        seed=config.seed,
        initial_spot=config.initial_spot,
        volatility=config.volatility,
        volatility_source=volatility_source,
        risk_free_rate=config.risk_free_rate,
        risk_free_source=risk_free_source,
        drift=config.drift,
        cycle_length_days=config.cycle_length_years * 365.0,
        strike_target_pct=config.strike_target_pct,
        probability_of_loss=float(np.mean(pnl < 0.0)),
        var_95_usd=var95,
        var_95_pct_capital=100.0 * var95 / capital,
        expected_shortfall_975_usd=es975,
        expected_shortfall_975_pct_capital=100.0 * es975 / capital,
        mean_rolling_programme_eac_usd_per_btc=mean_eac,
        rolling_programme_eac_5_usd_per_btc=eac5,
        rolling_programme_eac_95_usd_per_btc=eac95,
        mean_max_drawdown_usd=float(np.mean(dd)),
        mean_max_drawdown_pct_capital=100.0 * float(np.mean(dd)) / capital,
        p95_max_drawdown_usd=float(np.percentile(dd, 95)),
        mean_itm_frequency=float(np.mean(itm)) / config.n_cycles,
        mean_touch_frequency=float(np.mean(touch)) / config.n_cycles,
        total_pnl_mean_usd=mean_pnl,
        total_pnl_median_usd=median_pnl,
        total_pnl_p5_usd=p5,
        total_pnl_p25_usd=p25,
        total_pnl_p75_usd=p75,
        total_pnl_p95_usd=p95,
        total_pnl_mean_per_btc=mean_pnl / block,
        total_pnl_median_per_btc=median_pnl / block,
        total_pnl_p5_per_btc=p5 / block,
        total_pnl_p95_per_btc=p95 / block,
        total_pnl_mean_pct_block=100.0 * mean_pnl / capital,
        total_pnl_p5_pct_block=100.0 * p5 / capital,
        total_pnl_p95_pct_block=100.0 * p95 / capital,
        mean_holding_pnl_usd=float(np.mean(hold)),
        median_holding_pnl_usd=float(np.median(hold)),
        mean_holding_pnl_per_btc=float(np.mean(hold)) / block,
        mean_overlay_gross_pnl_usd=float(np.mean(overlay)),
        median_overlay_gross_pnl_usd=float(np.median(overlay)),
        mean_overlay_gross_pnl_per_btc=float(np.mean(overlay)) / block,
        structuring_fee_usd=fee,
        mean_total_pnl_pre_fee_usd=mean_pnl + fee,
        mean_total_pnl_post_fee_usd=mean_pnl,
        mean_outcome_usd=mean_pnl,
        median_outcome_usd=median_pnl,
        std_outcome_usd=std_pnl,
        percentile_5_usd=p5,
        percentile_1_usd=p1,
        mc_standard_error=mc_se,
        probability_of_exceeding_seller_discount=float(
            np.mean(pnl > _seller_discount_threshold(config))
        ),
        capital_base=capital,
        n_non_finite=n_non_finite,
        assumptions={**config.assumptions_dict(), "provenance": "SIMULATED"},
    )
