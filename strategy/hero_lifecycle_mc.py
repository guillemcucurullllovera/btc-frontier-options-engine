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
from pricing.black_scholes import price as bs_price
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    _generate_chunk_paths,
    _iter_chunks,
    _seller_discount_threshold,
)

# The full grid of structures now runs through the rolling-lifecycle MC.
HOLDING_KINDS: frozenset[str] = frozenset(
    {"covered_call", "partial_overlay", "long_btc_plus_short_put", "collar", "strike_ladder"}
)
CASH_KINDS: frozenset[str] = frozenset({"cash_secured_put"})
OPTION_ONLY_KINDS: frozenset[str] = frozenset({"call_spread"})
ALL_MC_KINDS: frozenset[str] = HOLDING_KINDS | CASH_KINDS | OPTION_ONLY_KINDS
ARCHETYPE_KINDS = ALL_MC_KINDS   # backwards-compatible alias (now the full grid)
HERO_KINDS = ALL_MC_KINDS
PARTIAL_OVERLAY_RATIO: float = 0.5
CALL_SPREAD_LONG_MULTIPLE: float = 2.0        # credit spread: long call at 1 + 2p
LADDER_STRIKE_MULTS: tuple[float, ...] = (1.05, 1.10, 1.15)  # short-call rungs, equal weight
PENDING_DECISION_REFS: tuple[str, ...] = ("D-1", "D-4", "D-7", "D-9", "D-10", "MS-25", "MS-26")

# A leg = (option_kind, side, strike_multiple, notional_weight). Strike = entry * multiple.
LegSpec = tuple[str, str, float, float]


def leg_specs(kind: str, p: float) -> list[LegSpec]:
    """Rolling-cycle option legs for a structure at strike distance *p*."""
    if kind == "covered_call":
        return [("call", "SHORT", 1.0 + p, 1.0)]
    if kind == "partial_overlay":
        return [("call", "SHORT", 1.0 + p, PARTIAL_OVERLAY_RATIO)]
    if kind == "long_btc_plus_short_put":
        return [("put", "SHORT", 1.0 - p, 1.0)]
    if kind == "collar":
        return [("call", "SHORT", 1.0 + p, 1.0), ("put", "LONG", 1.0 - p, 1.0)]
    if kind == "cash_secured_put":
        return [("put", "SHORT", 1.0 - p, 1.0)]
    if kind == "call_spread":  # CREDIT: short lower strike / long higher strike
        return [("call", "SHORT", 1.0 + p, 1.0),
                ("call", "LONG", 1.0 + CALL_SPREAD_LONG_MULTIPLE * p, 1.0)]
    if kind == "strike_ladder":
        w = 1.0 / len(LADDER_STRIKE_MULTS)
        return [("call", "SHORT", m, w) for m in LADDER_STRIKE_MULTS]
    raise ValidationError(f"MC does not support structure kind {kind!r}")


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
    # VRP: paths diffuse at diffusion_vol; premia priced at pricing_vol.
    diffusion_vol: float = 0.0
    pricing_vol: float = 0.0
    vol_regime: str = "fair_value"       # "fair_value" (implied=implied) | "vrp" (implied>realised)
    # Bootstrap SE + 95% CI per metric: {metric: {se, ci_lo, ci_hi}} (U5).
    metric_ci: dict[str, dict[str, float]] = field(default_factory=dict)

    # ── Slide-5 diagnostic metric framework (SIMULATED) ──
    probability_of_loss: float = 0.0
    var_95_usd: float = 0.0                      # VaR95 = -(5th percentile of P&L)
    var_95_pct_capital: float = 0.0
    expected_shortfall_975_usd: float = 0.0      # ES97.5 = mean loss in worst 2.5% tail
    expected_shortfall_975_pct_capital: float = 0.0
    cvar_95_usd: float = 0.0                      # CVaR95 (coherent) for the loss-budget frontier
    cvar_99_usd: float = 0.0
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
    kind: str, paths: np.ndarray, config: MultiCycleMCConfig, fee: float,
    unit_prems: list[float], holder_basis: bool = False,
) -> _ExtendedPerPath:
    """Rolling-lifecycle economics over a (m, total_steps+1) path block.

    Generic over the structure's option legs (``leg_specs``). Premiums use the
    supplied per-leg unit premia (priced at the PRICING vol); payouts use the
    simulated (DIFFUSION-vol) paths — decoupling them yields the variance-risk-
    premium case. Options are cash-settled; each cycle re-strikes at entry*mult.
    Tracks per-cycle ITM/touch on the primary short leg and the cumulative-P&L
    drawdown across cycle boundaries (uniform for holding and no-holding kinds).
    """
    legs = leg_specs(kind, config.strike_target_pct)
    m = paths.shape[0]
    steps = config.n_steps_per_cycle
    total_steps = config.total_steps
    qty = config.btc_quantity
    s0 = config.initial_spot
    # holder_basis: the client already owns 30,000 BTC, so every structure (incl. CSP /
    # call spread) sits on top of the holding — a consistent total-portfolio (holder) basis.
    btc = qty if (kind in HOLDING_KINDS or holder_basis) else 0.0
    prim = next((i for i, leg in enumerate(legs) if leg[1] == "SHORT"), 0)

    cash = np.full(m, -fee)               # fee charged once up-front; net option cash accrues here
    itm = np.zeros(m)
    touch = np.zeros(m)
    peak = np.full(m, -fee)               # cumulative-P&L drawdown from V0 = -fee
    max_dd = np.zeros(m)

    for c in range(config.n_cycles):
        entry = paths[:, c * steps]
        end_idx = min((c + 1) * steps, total_steps)
        exit_ = paths[:, end_idx]
        seg = paths[:, c * steps : end_idx + 1]
        for i, (opt, side, mult, w) in enumerate(legs):
            strike = entry * mult
            premium = entry * unit_prems[i]
            if opt == "call":
                payout = np.maximum(exit_ - strike, 0.0)
            else:
                payout = np.maximum(strike - exit_, 0.0)
            credit = 1.0 if side == "SHORT" else -1.0
            cash = cash + w * qty * credit * (premium - payout)
            if i == prim:
                if opt == "call":
                    itm = itm + (exit_ > strike)
                    touch = touch + (seg.max(axis=1) >= strike)
                else:
                    itm = itm + (exit_ < strike)
                    touch = touch + (seg.min(axis=1) <= strike)
        v = btc * (exit_ - s0) + cash     # cumulative P&L at the cycle boundary
        peak = np.maximum(peak, v)
        max_dd = np.maximum(max_dd, peak - v)

    final_spot = paths[:, -1]
    holding_pnl = btc * (final_spot - s0)
    overlay_gross = cash + fee            # net premiums - payouts (strip the fee back out)
    pnl_post_fee = holding_pnl + overlay_gross - fee
    # rolling-programme cost basis per BTC held; undefined (nan) when no BTC accumulated.
    eac = (qty * s0 - cash) / qty if btc > 0.0 else np.full(m, np.nan)
    return _ExtendedPerPath(
        pnl_post_fee=pnl_post_fee, holding_pnl=holding_pnl, overlay_gross=overlay_gross,
        max_drawdown=max_dd, itm_count=itm, touch_count=touch, eac=eac,
    )


def _extended_path_scalar(
    kind: str, path: np.ndarray, config: MultiCycleMCConfig, fee: float,
    unit_prems: list[float],
) -> tuple[float, float, float, float, int, int, float]:
    """Independent scalar reference for ONE path (test oracle).

    Returns (pnl_post_fee, holding_pnl, overlay_gross, max_drawdown, itm, touch, eac).
    """
    legs = leg_specs(kind, config.strike_target_pct)
    steps = config.n_steps_per_cycle
    total_steps = config.total_steps
    qty = config.btc_quantity
    s0 = config.initial_spot
    btc = qty if kind in HOLDING_KINDS else 0.0
    prim = next((i for i, leg in enumerate(legs) if leg[1] == "SHORT"), 0)

    cash = -fee
    itm = 0
    touch = 0
    peak = -fee
    max_dd = 0.0
    for c in range(config.n_cycles):
        entry = float(path[c * steps])
        end_idx = min((c + 1) * steps, total_steps)
        exit_ = float(path[end_idx])
        seg = path[c * steps : end_idx + 1]
        for i, (opt, side, mult, w) in enumerate(legs):
            strike = entry * mult
            premium = entry * unit_prems[i]
            payout = max(exit_ - strike, 0.0) if opt == "call" else max(strike - exit_, 0.0)
            credit = 1.0 if side == "SHORT" else -1.0
            cash += w * qty * credit * (premium - payout)
            if i == prim:
                if opt == "call":
                    itm += int(exit_ > strike)
                    touch += int(float(seg.max()) >= strike)
                else:
                    itm += int(exit_ < strike)
                    touch += int(float(seg.min()) <= strike)
        v = btc * (exit_ - s0) + cash
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    final_spot = float(path[-1])
    holding_pnl = btc * (final_spot - s0)
    overlay_gross = cash + fee
    pnl_post_fee = holding_pnl + overlay_gross - fee
    eac = (qty * s0 - cash) / qty if btc > 0.0 else float("nan")
    return pnl_post_fee, holding_pnl, overlay_gross, max_dd, itm, touch, eac


# ── driver ─────────────────────────────────────────────────────────────────────


def unit_premiums_for(kind: str, config: MultiCycleMCConfig, pricing_vol: float) -> list[float]:
    """Per-leg spot-normalised premia priced at *pricing_vol* (homogeneity: * entry)."""
    legs = leg_specs(kind, config.strike_target_pct)
    r, t = config.risk_free_rate, config.cycle_length_years
    return [bs_price(1.0, mult, r, pricing_vol, t, opt) for (opt, _side, mult, _w) in legs]


def run_hero_lifecycle_mc(
    strategy: Strategy,
    config: MultiCycleMCConfig,
    *,
    kind: str | None = None,
    pricing_vol: float | None = None,
    holder_basis: bool = False,
    volatility_source: str = "calibrated: per-tenor ATM IV (snapshot)",
    risk_free_source: str = "observed (deribit interest_rate)",
    bootstrap_samples: int = 200,
) -> HeroMCResult:
    """Run the rolling-lifecycle diagnostic MC for one structure.

    Paths diffuse at ``config.volatility`` (the DIFFUSION vol); option premia are
    priced at ``pricing_vol`` (the PRICING vol; defaults to the diffusion vol).
    When they differ the run models the **variance risk premium** (sell at implied,
    realise at physical); when equal it is the **pure-implied fair-value** anchor.

    *kind* overrides the structure kind (needed for strike_ladder, whose legs
    classify as covered_call); defaults to ``strategy.canonical.value``.
    """
    effective_kind = kind or strategy.canonical.value
    if effective_kind not in ALL_MC_KINDS:
        raise ValidationError(f"MC does not support {effective_kind!r}")
    pv = config.volatility if pricing_vol is None else pricing_vol
    vol_regime = "fair_value" if abs(pv - config.volatility) < 1e-12 else "vrp"
    unit_prems = unit_premiums_for(effective_kind, config, pv)
    fee = config.asym_fee_usd
    plan = _iter_chunks(config.n_paths, config.chunk_size, config.use_antithetic)

    parts: dict[str, list[np.ndarray]] = {
        "pnl": [], "hold": [], "overlay": [], "dd": [], "itm": [], "touch": [], "eac": [],
    }
    for chunk_index, _start, count in plan:
        paths = _generate_chunk_paths(config, chunk_index, count)
        ext = _extended_cycles_vectorized(
            effective_kind, paths, config, fee, unit_prems, holder_basis,
        )
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
        strategy, effective_kind, config, pnl, hold, overlay, dd, itm, touch, eac, fee,
        volatility_source, risk_free_source, pv, vol_regime, bootstrap_samples,
    )


def _bootstrap_ci(
    pnl: np.ndarray, eac: np.ndarray, b_samples: int, seed: int,
) -> dict[str, dict[str, float]]:
    """Vectorised bootstrap SE + 95% CI for every MC metric (Glasserman 1.1.3)."""
    n = pnl.shape[0]
    out: dict[str, dict[str, float]] = {}
    if n < 2 or b_samples < 2:
        return out
    rng = np.random.default_rng([int(seed), 20260730])
    idx = rng.integers(0, n, size=(b_samples, n))
    s = np.sort(pnl[idx], axis=1)                       # ascending, per resample
    k_es = max(1, int(np.ceil(0.025 * n)))
    k_var = min(n - 1, max(0, int(0.05 * n)))
    k_p95 = min(n - 1, int(0.95 * n))
    metrics = {
        "mean_pnl": s.mean(axis=1),
        "var_95_usd": -s[:, k_var],
        "es_975_usd": -s[:, :k_es].mean(axis=1),
        "prob_loss": (s < 0.0).mean(axis=1),
        "pnl_p5": s[:, k_var],
        "pnl_p95": s[:, k_p95],
    }
    finite = eac[np.isfinite(eac)]
    if finite.size >= 2:
        eidx = rng.integers(0, finite.size, size=(b_samples, finite.size))
        metrics["eac_mean"] = finite[eidx].mean(axis=1)
    for name, arr in metrics.items():
        out[name] = {
            "se": float(np.std(arr)),
            "ci_lo": float(np.percentile(arr, 2.5)),
            "ci_hi": float(np.percentile(arr, 97.5)),
        }
    return out


def _finalize_hero(
    strategy: Strategy,
    effective_kind: str,
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
    pricing_vol: float,
    vol_regime: str,
    bootstrap_samples: int,
) -> HeroMCResult:
    n = pnl.shape[0]
    capital = config.capital_base
    block = config.btc_quantity
    n_non_finite = int(np.count_nonzero(~np.isfinite(pnl)))
    metric_ci = _bootstrap_ci(pnl, eac, bootstrap_samples, config.seed)

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
    # CVaR (coherent) at 95/99 for the loss-budget frontier: mean loss beyond VaR_beta.
    cvar95 = float(np.mean(losses[losses >= float(np.percentile(losses, 95))])) if n else 0.0
    cvar99 = float(np.mean(losses[losses >= float(np.percentile(losses, 99))])) if n else 0.0

    valid_eac = eac[np.isfinite(eac)]
    mean_eac = float(np.mean(valid_eac)) if valid_eac.size else float("nan")
    eac5 = float(np.percentile(valid_eac, 5)) if valid_eac.size else float("nan")
    eac95 = float(np.percentile(valid_eac, 95)) if valid_eac.size else float("nan")

    std_pnl = float(np.std(pnl))
    mc_se = std_pnl / math.sqrt(n) if n else 0.0

    return HeroMCResult(
        strategy_id=strategy.strategy_id,
        strategy_kind=effective_kind,
        business_label=strategy.business_label,
        n_paths=n,
        n_cycles=config.n_cycles,
        model=config.model,
        seed=config.seed,
        initial_spot=config.initial_spot,
        volatility=config.volatility,
        volatility_source=volatility_source,
        diffusion_vol=config.volatility,
        pricing_vol=pricing_vol,
        vol_regime=vol_regime,
        metric_ci=metric_ci,
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
        cvar_95_usd=cvar95,
        cvar_99_usd=cvar99,
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
