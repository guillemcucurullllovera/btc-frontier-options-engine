"""Phase L — laddered / fractionated overlay analysis (ADDITIVE; SIMULATED).

Temporal fractionation: over a fixed horizon, run the overlay as N sequential
tranches, each re-struck at the then-current spot (N=1 is the one-shot baseline).
This is a MultiCycleMCConfig with n_cycles=N and cycle_length=H/N; the R1-R3
rolling-lifecycle MC and its economics are reused UNCHANGED — this module only
adds the fractionation-specific metrics via an independent per-path pass:

  * premium collected P_N (gross + net), per-BTC / %-spot / per-portfolio;
  * upside given up (short-call assignments) and upside participation
    (fraction of unhedged-BTC upside retained);
  * premium efficiency = net premium per unit of upside given up;
  * transaction-cost drag (N trades cost N x the per-trade Deribit fee);
  * risk metrics (prob-loss, VaR95, ES97.5, drawdown) with SE/CI, via the MC.

Honesty: a single sharp intra-cycle gap is still fully capped inside its tranche;
closer/shorter tranches raise assignment and transaction cost. No ranking (MS-25).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from engine.strategy import Strategy
from strategy.hero_lifecycle_mc import (
    leg_specs,
    run_hero_lifecycle_mc,
    unit_premiums_for,
)
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    _generate_chunk_paths,
    _iter_chunks,
)

HORIZON_DAYS: float = 56.0                 # ~57d (25SEP listed); divisible by {1,2,4}
N_TRANCHES: tuple[int, ...] = (1, 2, 4)
LADDER_STRUCTURES: tuple[str, ...] = ("covered_call", "collar")
DERIBIT_TAKER_COMMISSION: float = 0.0003   # 0.03% of underlying per option leg per trade
REGIME_BY_DRIFT: dict[float, str] = {-0.10: "trend_down", 0.0: "choppy_flat", 0.10: "trend_up"}


@dataclass(frozen=True)
class LadderMetrics:
    structure: str
    n_tranches: int
    tenor_days: float
    drift: float
    regime: str
    vol_regime: str            # "fair_value" | "vrp"
    # premium collected (gross short-leg + net structure), per-BTC / %spot / per-portfolio
    premium_collected_per_btc: float
    premium_collected_pct_spot: float
    premium_collected_per_portfolio: float
    net_premium_per_btc: float
    # upside trade-off
    upside_given_up_per_btc: float
    upside_participation: float
    premium_efficiency: float          # net premium / upside given up
    tcost_drag_per_btc: float
    # risk (from the MC; SIMULATED)
    prob_loss: float
    var95_usd: float
    es975_usd: float
    mean_max_drawdown_usd: float
    mean_pnl_usd: float
    itm_frequency: float
    touch_frequency: float
    var95_se: float
    es975_se: float
    prob_loss_se: float
    # reconciliation to the MC economics (must match hero.mean_overlay_gross_pnl_usd)
    net_overlay_per_btc: float


def ladder_config(
    structure_p: float, n: int, drift: float, diffusion_vol: float,
    s0: float, r: float, seed: int, paths: int,
) -> MultiCycleMCConfig:
    """MultiCycleMCConfig for N tranches over the fixed horizon (each tenor = H/N days)."""
    cycle_days = HORIZON_DAYS / n
    return MultiCycleMCConfig(
        n_paths=paths, n_cycles=n, cycle_length_years=cycle_days / 365.0,
        n_steps_per_cycle=max(round(cycle_days), 1), initial_spot=s0, volatility=diffusion_vol,
        risk_free_rate=r, drift=drift, model="GBM", seed=seed, strike_target_pct=structure_p,
        d12_interpretation="cash_settled", capital_base=s0 * 30_000.0, store_paths=False,
    )


def _ladder_pass(
    kind: str, paths: np.ndarray, config: MultiCycleMCConfig,
    unit_prems: list[float], commission: float,
) -> dict[str, np.ndarray]:
    """Independent per-path pass for the fractionation metrics (does not alter the MC)."""
    legs = leg_specs(kind, config.strike_target_pct)
    m = paths.shape[0]
    steps = config.n_steps_per_cycle
    total = config.total_steps
    qty = config.btc_quantity
    s0 = config.initial_spot
    prem_recv = np.zeros(m)
    prem_paid = np.zeros(m)
    call_payout = np.zeros(m)      # short-call assignments = upside given up
    net_overlay = np.zeros(m)
    tcost = np.zeros(m)
    for c in range(config.n_cycles):
        entry = paths[:, c * steps]
        exit_ = paths[:, min((c + 1) * steps, total)]
        for i, (opt, side, mult, w) in enumerate(legs):
            strike = entry * mult
            premium = entry * unit_prems[i]
            payout = np.maximum(exit_ - strike, 0.0) if opt == "call" else np.maximum(strike - exit_, 0.0)
            credit = 1.0 if side == "SHORT" else -1.0
            net_overlay = net_overlay + w * qty * credit * (premium - payout)
            if side == "SHORT":
                prem_recv = prem_recv + w * qty * premium
                if opt == "call":
                    call_payout = call_payout + w * qty * payout
            else:
                prem_paid = prem_paid + w * qty * premium
            tcost = tcost + commission * entry * w * qty
    holding_gain = qty * (paths[:, -1] - s0)
    return {
        "prem_recv": prem_recv, "prem_paid": prem_paid, "call_payout": call_payout,
        "net_overlay": net_overlay, "tcost": tcost, "holding_gain": holding_gain,
    }


def ladder_metrics(
    kind: str, builder: Callable[..., Strategy], config: MultiCycleMCConfig,
    pricing_vol: float, drift: float, vol_regime: str, commission: float = DERIBIT_TAKER_COMMISSION,
) -> LadderMetrics:
    """Compute the fractionation + risk metrics for one (structure, N, drift, regime, vol regime)."""
    unit_prems = unit_premiums_for(kind, config, pricing_vol)
    keys = ("prem_recv", "prem_paid", "call_payout", "net_overlay", "tcost", "holding_gain")
    acc: dict[str, list[np.ndarray]] = {k: [] for k in keys}
    for chunk_i, _s, cnt in _iter_chunks(config.n_paths, config.chunk_size, config.use_antithetic):
        out = _ladder_pass(kind, _generate_chunk_paths(config, chunk_i, cnt), config, unit_prems, commission)
        for key, arr in out.items():
            acc[key].append(arr)
    agg = {k: np.concatenate(v) for k, v in acc.items()}
    qty = config.btc_quantity
    s0 = config.initial_spot

    prem_recv = float(np.mean(agg["prem_recv"]))
    net_prem = prem_recv - float(np.mean(agg["prem_paid"]))
    upside_given_up = float(np.mean(agg["call_payout"]))
    # Upside participation on the AGGREGATE (ratio of sums over up-paths) — robust to the
    # spike-then-fall paths that make a per-path mean-of-ratios explode:
    #   participation = 1 - sum(call assignments | up) / sum(unhedged upside | up).
    up = agg["holding_gain"] > 0.0
    up_gain = float(np.sum(agg["holding_gain"][up]))
    participation = (1.0 - float(np.sum(agg["call_payout"][up])) / up_gain) if up_gain > 1e-9 else float("nan")
    efficiency = net_prem / upside_given_up if upside_given_up > 1e-9 else float("inf")

    risk = run_hero_lifecycle_mc(builder(), config, kind=kind, pricing_vol=pricing_vol,
                                 bootstrap_samples=150)
    ci = risk.metric_ci
    return LadderMetrics(
        structure=kind, n_tranches=config.n_cycles, tenor_days=HORIZON_DAYS / config.n_cycles,
        drift=drift, regime=REGIME_BY_DRIFT.get(drift, f"drift{drift:+.2f}"), vol_regime=vol_regime,
        premium_collected_per_btc=prem_recv / qty,
        premium_collected_pct_spot=100.0 * (prem_recv / qty) / s0,
        premium_collected_per_portfolio=prem_recv,
        net_premium_per_btc=net_prem / qty,
        upside_given_up_per_btc=upside_given_up / qty,
        upside_participation=participation,
        premium_efficiency=efficiency,
        tcost_drag_per_btc=float(np.mean(agg["tcost"])) / qty,
        prob_loss=risk.probability_of_loss, var95_usd=risk.var_95_usd,
        es975_usd=risk.expected_shortfall_975_usd, mean_max_drawdown_usd=risk.mean_max_drawdown_usd,
        mean_pnl_usd=risk.mean_outcome_usd, itm_frequency=risk.mean_itm_frequency,
        touch_frequency=risk.mean_touch_frequency,
        var95_se=ci.get("var_95_usd", {}).get("se", 0.0),
        es975_se=ci.get("es_975_usd", {}).get("se", 0.0),
        prob_loss_se=ci.get("prob_loss", {}).get("se", 0.0),
        net_overlay_per_btc=float(np.mean(agg["net_overlay"])) / qty,
    )
