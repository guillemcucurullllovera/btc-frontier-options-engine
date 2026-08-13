"""Faithful MULTI-LEG backtest — honours each leg's OWN strike (WP-D3 fix).

WHY THIS EXISTS
---------------
`strategy/backtest.py::backtest_strategy` computes the per-cycle strike from a
SINGLE direction-aware scalar `strike_pct_above` (calls -> spot*(1+p),
puts -> spot*(1-p)) at lines 505-514. That override discards each leg's own
strike set by the builders in `strategy/definitions.py`, so any structure whose
legs do not share ONE symmetric offset is mis-represented:

  * asymmetric strike ladder  (+4 / +6.67 / +9.33 / +12 %)  -> collapsed to uniform
  * collar  (call +5 % / put -10 %)                          -> forced symmetric +/-p
  * covered-call spread (short +4 % call / long +9 % call)   -> both legs same strike -> 0-width
  * protective ladder (short calls + long put floor)         -> cannot set 2 offsets

This module fixes that by carrying, per option leg, a **strike ratio**
`leg.strike / ref_spot` fixed at build time, and re-striking each cycle as
`entry_spot * ratio`. Every leg keeps its own moneyness, so collars, spreads,
protective ladders and the true asymmetric ladder backtest faithfully.

It is a faithful ADAPTATION of `backtest_strategy` (same ledger, same fee/impact/
settlement machinery, same no-look-ahead per-cycle re-strike). It ADDS two
strategy levers used by the D3 hedging study, both OFF by default so the default
call reproduces `backtest_strategy` on a faithful (single-offset) structure:

  * `iv_gate`      : sell the overlay ONLY when the entry IV percentile (trailing)
                     is >= threshold (IV-timed entry). Otherwise the cycle is a
                     pure hold of the spot leg (no premium, no options).
  * `vrp_forecast` : additional VRP gate — require entry implied minus a realised-
                     vol forecast > `vrp_min` (harvest only when implied is RICH;
                     Sinclair ch.4 / A3 D1).
  * `coverage_fn`  : per-cycle multiplier applied to every SHORT option leg's size
                     (dynamic coverage scaled with IV richness; use
                     `make_dynamic_coverage_fn` for the [0.25,0.60] panic-capped
                     map). Long hedge legs keep their built put_coverage.
  * `roll_enabled` : discretionary intra-cycle roll trigger (D4) — close a cycle
                     early and re-strike when a short leg is breached late in life.

PROTOTYPE — new file, does NOT modify production `backtest.py`. The equivalent
surgical production diff is documented in the D3 report.

Provenance of everything here is inherited from the inputs: OBSERVED spot path,
whatever `iv_history` you feed (MODEL_RECONSTRUCTED realised-vol proxy, or
OBSERVED DVOL implied), r as passed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Literal

import numpy as np

from engine.settlement import SettlementCurrency
from engine.settlement_engine import settle_leg
from engine.strategy import Leg, Strategy
from execution.fees import leg_trading_fee
from execution.impact import KissellConfig, estimate_impact
from strategy.backtest import (
    BacktestCycle,
    BacktestResult,
    RollPolicy,
    _btc_held,
    _cash_collateral,
    _clone_leg_strike,
    _delta_leg_at,
    _nearest_bar,
    _option_legs,
    _option_mtm_leg,
    _option_premium_currency,
    _price_leg_at,
    _total_option_qty,
    _validate_inputs,
)
from config.models import Provenance


# ─────────────────────────────────────────────────────────────────────────────
# Per-leg strike ratio — the whole point of the fix.
# ─────────────────────────────────────────────────────────────────────────────
def leg_strike_ratios(strategy: Strategy, ref_spot: float) -> dict[int, float]:
    """Map id(leg) -> (leg.strike / ref_spot) for every option leg.

    `ref_spot` is the spot at which the strategy was BUILT (so a builder that set
    call_strike = entry_spot*1.05 yields ratio 1.05, put_strike = entry_spot*0.90
    yields ratio 0.90). Each leg therefore re-strikes independently per cycle.
    """
    if ref_spot <= 0:
        raise ValueError("ref_spot must be positive")
    ratios: dict[int, float] = {}
    for leg in _option_legs(strategy):
        if leg.strike is not None:
            ratios[id(leg)] = leg.strike / ref_spot
    return ratios


def _leg_dte_map(opt_legs: list[Leg], dte_days: int) -> Callable[[Leg], int]:
    leg_expiries = [leg.expiry_timestamp for leg in opt_legs if leg.expiry_timestamp is not None]
    base_expiry = min(leg_expiries) if leg_expiries else None

    def _leg_dte(leg: Leg) -> int:
        if base_expiry is not None and leg.expiry_timestamp is not None:
            return dte_days + max(0, (leg.expiry_timestamp - base_expiry).days)
        return dte_days

    return _leg_dte


def _iv_percentile(iv_hist: np.ndarray, i: int, lookback: int) -> float:
    """Trailing percentile rank of iv_hist[i] within [i-lookback, i]."""
    lo = max(0, i - lookback)
    window = iv_hist[lo : i + 1]
    if len(window) < 5:
        return 0.5
    return float(np.mean(window <= iv_hist[i]))


def make_dynamic_coverage_fn(
    base_coverage: float = 0.40,
    lo: float = 0.25,
    hi: float = 0.60,
    cheap_pctile: float = 0.17,
    panic_pctile: float = 0.95,
) -> Callable[[float], float]:
    """A3 D2 dynamic-coverage map — DVOL percentile -> coverage MULTIPLIER.

    Implements the piecewise target-coverage curve in [lo, hi] around `base`,
    monotone in vol richness, with the Sinclair-4.3 PANIC CAP:

      pct < cheap_pctile               -> target = lo   (cheap vol: floor income,
                                                          bias further OTM)
      cheap_pctile <= pct < 0.50       -> linear lo -> base
      0.50 <= pct < panic_pctile       -> linear base -> hi   (write more when rich)
      pct >= panic_pctile              -> target CAPPED at base (do NOT push to hi:
                                          in a genuine panic realised overtakes
                                          implied and the VRP inverts)

    The returned callable yields `target / base` so it can be applied as a
    MULTIPLIER to option legs already built at `base_coverage` (the mandate 0.40
    sleeve). Anchoring base at the median (pct=0.50) makes the mean coverage ≈
    base for roughly uniform percentile occupancy. Coverage is the INCOME /
    participation dial, NOT a downside dial (FOUNDATIONS_SPEC §5).
    """
    if base_coverage <= 0:
        raise ValueError("base_coverage must be positive")

    def _fn(pct: float) -> float:
        p = float(min(max(pct, 0.0), 1.0))
        if p >= panic_pctile:
            target = base_coverage                       # panic cap
        elif p >= 0.50:
            span = max(panic_pctile - 0.50, 1e-9)
            target = base_coverage + (hi - base_coverage) * (p - 0.50) / span
        elif p >= cheap_pctile:
            span = max(0.50 - cheap_pctile, 1e-9)
            target = lo + (base_coverage - lo) * (p - cheap_pctile) / span
        else:
            target = lo                                  # cheap-vol floor
        return float(target / base_coverage)

    return _fn


def backtest_strategy_multileg(
    strategy: Strategy,
    dates: list[datetime],
    spot_prices: np.ndarray,
    iv_history: np.ndarray | None = None,
    *,
    ref_spot: float | None = None,
    risk_free_rate: float = 0.0,
    dte_days: int = 31,
    roll_policy: RollPolicy | None = None,
    seed: int = 42,
    spread_bps: float = 2.0,
    # ── D3 levers (all OFF by default → reproduces backtest_strategy) ──
    iv_gate: bool = False,
    iv_gate_percentile: float = 0.50,
    iv_gate_lookback: int = 252,
    coverage_fn: Callable[[float], float] | None = None,
    coverage_lookback: int = 252,
    price_iv_history: np.ndarray | None = None,
    # ── D1 VRP gate (require implied to be rich vs a realised-vol forecast) ──
    vrp_forecast: np.ndarray | None = None,
    vrp_min: float = 0.0,
    # ── D4 discretionary intra-cycle roll trigger (up-and-out / roll-down) ──
    roll_enabled: bool = False,
    roll_breach_pct: float = 0.0,
    roll_min_days_left: int = 7,
    # ── optional out-param: daily MTM equity curve (equity_out[i] <-> dates[i]) ──
    equity_out: list[float] | None = None,
) -> BacktestResult:
    """Leg-driven cycle backtest that honours each leg's OWN strike ratio.

    Parameters mirror `backtest_strategy` except `strike_pct_above` is REMOVED
    (each leg re-strikes from its own build-time ratio) and the two levers are
    added. `price_iv_history` (optional) prices the ENTRY premium off a different
    vol than the settlement path uses for MTM/percentiles — feed OBSERVED DVOL
    here to capture the variance-risk-premium while keeping the realised path for
    percentile/gating. If None, `iv_history` is used for pricing too.

    Ledger invariant preserved: dcash + d(btc*spot) + dcollateral == net_pnl.
    No look-ahead: strike, premium and gate all use data at/at-before entry.
    """
    _validate_inputs(dates, spot_prices, iv_history)
    if roll_policy is None:
        roll_policy = RollPolicy(policy_type="expiry")

    if ref_spot is None:
        # default: build reference = the spot leg's entry price, else first bar
        spot_entries = [leg.entry_spot for leg in strategy.legs
                        if leg.product == "spot" and leg.entry_spot]
        ref_spot = float(spot_entries[0]) if spot_entries else float(spot_prices[0])

    strike_ratios = leg_strike_ratios(strategy, ref_spot)
    opt_legs = _option_legs(strategy)
    _leg_dte = _leg_dte_map(opt_legs, dte_days)

    btc_held = _btc_held(strategy)
    cash_collateral_req = _cash_collateral(strategy)
    total_opt_qty = _total_option_qty(strategy)
    n_days = len(dates)
    initial_spot = float(spot_prices[0])
    adv_btc = total_opt_qty * 5.0 if total_opt_qty > 0 else 25_000.0

    price_iv = price_iv_history if price_iv_history is not None else iv_history

    capital_base = max(btc_held * initial_spot + cash_collateral_req,
                       total_opt_qty * initial_spot, 1.0)
    strategy_notional = capital_base

    # ledger
    cash_usd = -(btc_held * initial_spot)
    btc_inventory = btc_held
    collateral_usd = 0.0

    def _equity(spot: float) -> float:
        return cash_usd + btc_inventory * spot + collateral_usd

    cycles: list[BacktestCycle] = []
    equity_curve: list[float] = []

    total_premium_usd = 0.0
    total_premium_btc = 0.0
    total_venue_fees_usd = 0.0
    total_spread_usd = 0.0
    total_impact_usd = 0.0
    total_pnl_running = 0.0
    cumulative_premium_pct = 0.0
    run_residual = 0.0
    last_curve_idx = 0
    reference_qty = btc_held if btc_held > 0 else max(
        [leg.quantity for leg in opt_legs], default=1.0)
    spot_acq_impact_charged = False

    day_idx = 0
    cycle_idx = 0
    while day_idx < n_days - 1:
        entry_idx = day_idx
        entry_date = dates[entry_idx]
        entry_spot = float(spot_prices[entry_idx])
        entry_iv = float(iv_history[entry_idx]) if iv_history is not None else 0.45
        entry_price_iv = float(price_iv[entry_idx]) if price_iv is not None else entry_iv
        prev_cash, prev_btc, prev_coll = cash_usd, btc_inventory, collateral_usd
        equity_start = _equity(entry_spot)

        # ── lever 1: IV-timed entry gate (DVOL percentile) + VRP gate ──
        #   Feed iv_history = OBSERVED DVOL so the gate ranks RICHNESS, not the
        #   realised-vol level. The VRP gate additionally requires implied to be
        #   rich vs a realised-vol forecast (Sinclair ch.4 / A3 D1). No look-ahead:
        #   both use data at/at-before the entry bar.
        sell_overlay = True
        if iv_gate and iv_history is not None:
            pct = _iv_percentile(iv_history, entry_idx, iv_gate_lookback)
            sell_overlay = pct >= iv_gate_percentile
        if sell_overlay and vrp_forecast is not None:
            vrp = entry_iv - float(vrp_forecast[entry_idx])
            sell_overlay = vrp > vrp_min

        # ── lever 2: dynamic coverage multiplier (SHORT legs only) ──
        #   coverage_fn maps the DVOL percentile -> a multiplier on the built
        #   coverage sleeve (see make_dynamic_coverage_fn: [0.25, 0.60] around
        #   base 0.40, panic-capped). Long hedge legs (protective puts) are NOT
        #   scaled — the put floor is set by its own put_coverage, independent of
        #   income timing (A3 D2/D3).
        cov_factor = 1.0
        if coverage_fn is not None and iv_history is not None:
            pct = _iv_percentile(iv_history, entry_idx, coverage_lookback)
            cov_factor = float(coverage_fn(pct))

        # build per-cycle effective legs (re-struck + re-sized)
        leg_ctx: list[tuple[Leg, float, int, float]] = []
        cycle_end_idx = entry_idx
        if sell_overlay:
            for leg in opt_legs:
                if leg.strike is None or id(leg) not in strike_ratios:
                    continue
                cyc_strike = entry_spot * strike_ratios[id(leg)]
                # only SHORT legs are scaled by coverage; long hedge legs keep
                # their built size (put_coverage), so the floor is not shrunk when
                # income coverage is timed down/up.
                q = leg.quantity * cov_factor if leg.side == "SHORT" else leg.quantity
                eff_leg = leg.model_copy(update={"strike": cyc_strike, "quantity": q})
                exp_date = entry_date + timedelta(days=_leg_dte(leg))
                exp_idx = _nearest_bar(dates, exp_date, entry_idx)
                days_to_exp = max((dates[exp_idx] - entry_date).days, 1)
                T = days_to_exp / 365.0
                leg_ctx.append((eff_leg, cyc_strike, exp_idx, T))
                cycle_end_idx = max(cycle_end_idx, exp_idx)

        if not leg_ctx:  # pure-hold cycle (gated out, or no options)
            exp_date = entry_date + timedelta(days=dte_days)
            cycle_end_idx = _nearest_bar(dates, exp_date, entry_idx)
        cycle_end_idx = min(max(cycle_end_idx, entry_idx + 1), n_days - 1)

        # ── D4 discretionary roll trigger (up-and-out / roll-down) ──
        #   NEW capability, OFF by default. Client-authorised, advisory-only rule
        #   (FinIA non-discretionary posture): if a SHORT leg is breached by
        #   roll_breach_pct with < roll_min_days_left to that leg's expiry, close
        #   the whole cycle EARLY at that bar and re-strike next cycle from there.
        #   Settling early at the breach bar hands back the intrinsic — exactly the
        #   documented cost of the roll (RECONCILED_SPEC §5). Not automatic
        #   trading: this tests the VALUE of a pre-authorised roll rule.
        roll_event = None
        if roll_enabled and leg_ctx:
            roll_idx = None
            max_exp = max(e for (_l, _k, e, _T) in leg_ctx)
            for b in range(entry_idx + 1, min(max_exp, cycle_end_idx) + 1):
                sp_b = float(spot_prices[b])
                for (eff_leg, cyc_strike, exp_idx, _T) in leg_ctx:
                    if eff_leg.side != "SHORT" or b >= exp_idx:
                        continue
                    days_left = (dates[exp_idx] - dates[b]).days
                    if days_left >= roll_min_days_left:
                        continue
                    breached = (
                        (eff_leg.option_type == "call" and sp_b >= cyc_strike * (1.0 + roll_breach_pct))
                        or (eff_leg.option_type == "put" and sp_b <= cyc_strike * (1.0 - roll_breach_pct))
                    )
                    if breached:
                        roll_idx = b
                        break
                if roll_idx is not None:
                    break
            if roll_idx is not None:
                cycle_end_idx = roll_idx
                leg_ctx = [(l, k, min(e, roll_idx), T) for (l, k, e, T) in leg_ctx]
                roll_event = "roll_breach"

        end_spot = float(spot_prices[cycle_end_idx])
        end_date = dates[cycle_end_idx]

        # ── entry flows ──
        premium_usd = premium_btc = 0.0
        delta_at_entry = 0.0
        strike_report = 0.0
        venue_fee_usd = spread_usd = impact_usd = 0.0
        for (eff_leg, cyc_strike, _e, T) in leg_ctx:
            q = eff_leg.quantity
            mult = eff_leg.settlement.contract_multiplier if eff_leg.settlement else 1.0
            prem_per_ct = _price_leg_at(eff_leg, entry_spot, entry_price_iv, risk_free_rate, T, cyc_strike)
            prem_ccy = _option_premium_currency(eff_leg)
            sign = 1.0 if eff_leg.side == "SHORT" else -1.0
            if prem_ccy == "BTC":
                b = prem_per_ct * q * mult
                premium_btc += sign * b
                premium_usd += sign * b * entry_spot
            else:
                u = prem_per_ct * q * mult
                premium_usd += sign * u
                premium_btc += sign * (u / entry_spot if entry_spot > 0 else 0.0)
            delta_at_entry += _delta_leg_at(eff_leg, entry_spot, entry_price_iv, risk_free_rate, T, cyc_strike)
            strike_report = cyc_strike
            if eff_leg.settlement is not None:
                f_usd, _f_btc = leg_trading_fee(eff_leg.settlement, prem_per_ct, q * mult, entry_spot)
                venue_fee_usd += f_usd
            spread_usd += q * mult * entry_spot * spread_bps / 10000.0
            if q > 0:
                imp = estimate_impact(KissellConfig(order_size_btc=float(q * mult), adv_btc=adv_btc, volatility=entry_iv))
                impact_usd += q * mult * entry_spot * imp.market_impact_bp / 10000.0
        delta_at_entry += btc_inventory

        if not spot_acq_impact_charged and btc_held > 0:
            imp0 = estimate_impact(KissellConfig(order_size_btc=float(btc_held), adv_btc=adv_btc, volatility=entry_iv))
            impact_usd += btc_held * entry_spot * imp0.market_impact_bp / 10000.0
            spot_acq_impact_charged = True

        net_pnl = 0.0
        cash_usd += premium_usd; net_pnl += premium_usd
        cash_usd -= venue_fee_usd; net_pnl -= venue_fee_usd
        cash_usd -= spread_usd; net_pnl -= spread_usd
        cash_usd -= impact_usd; net_pnl -= impact_usd

        # CSP collateral (short put w/ cash leg) — reserved at strike notional
        reserved = 0.0
        if cash_collateral_req > 0:
            for (eff_leg, cyc_strike, _e, _T) in leg_ctx:
                if eff_leg.option_type == "put" and eff_leg.side == "SHORT":
                    mult = eff_leg.settlement.contract_multiplier if eff_leg.settlement else 1.0
                    reserved += eff_leg.quantity * mult * cyc_strike
            cash_usd -= reserved; collateral_usd += reserved

        # ── settlement (each leg at its own expiry bar) ──
        settlement_usd_total = 0.0
        delivery_fee_usd = 0.0
        is_itm_any = False
        realised_assignment = 0
        settle_bars: set[int] = set()
        for (eff_leg, cyc_strike, exp_idx, _T) in leg_ctx:
            settle_bars.add(exp_idx)
            leg_dp = float(spot_prices[exp_idx])
            sr = settle_leg(_clone_leg_strike(eff_leg, cyc_strike), leg_dp)
            holder_sign = 1.0 if eff_leg.side == "LONG" else -1.0
            if sr.settlement_currency == SettlementCurrency.BTC:
                s_usd = holder_sign * sr.settlement_amount * leg_dp
                delivery_fee_usd += sr.venue_delivery_fee * leg_dp
            else:
                s_usd = holder_sign * sr.settlement_amount
                delivery_fee_usd += sr.venue_delivery_fee
            settlement_usd_total += s_usd
            if sr.is_itm:
                is_itm_any = True
                if eff_leg.side == "SHORT":
                    realised_assignment = 1
        cash_usd += settlement_usd_total; net_pnl += settlement_usd_total
        cash_usd -= delivery_fee_usd; net_pnl -= delivery_fee_usd
        if reserved > 0:
            cash_usd += reserved; collateral_usd -= reserved

        spot_pnl = btc_inventory * (end_spot - entry_spot)
        net_pnl += spot_pnl

        equity_end = _equity(end_spot)
        run_residual += (equity_end - equity_start) - net_pnl

        # equity curve (MTM) for drawdown, over the cycle window
        booked_before = total_pnl_running
        start_credits = premium_usd - venue_fee_usd - spread_usd - impact_usd
        for bidx in range(last_curve_idx, cycle_end_idx + 1):
            sp = float(spot_prices[bidx])
            iv = float(iv_history[bidx]) if iv_history is not None else entry_iv
            ts = dates[bidx]
            option_mtm = 0.0
            for (eff_leg, cyc_strike, exp_idx, _T) in leg_ctx:
                if bidx >= exp_idx:
                    continue
                days_left = max((dates[exp_idx] - ts).days, 0.1)
                T_left = days_left / 365.0
                mult = eff_leg.settlement.contract_multiplier if eff_leg.settlement else 1.0
                option_mtm += _option_mtm_leg(eff_leg, cyc_strike, sp, iv, risk_free_rate, T_left, mult)
            equity_curve.append(capital_base + booked_before + start_credits
                                + btc_inventory * (sp - entry_spot) + option_mtm)
        last_curve_idx = cycle_end_idx + 1

        total_pnl_running += net_pnl
        total_premium_usd += premium_usd
        total_premium_btc += premium_btc
        total_venue_fees_usd += venue_fee_usd
        total_spread_usd += spread_usd
        total_impact_usd += impact_usd

        premium_pct = (100.0 * premium_usd / (entry_spot * reference_qty)
                       if entry_spot > 0 and reference_qty > 0 else 0.0)
        cumulative_premium_pct += premium_pct

        touched = False
        seg = spot_prices[entry_idx:cycle_end_idx + 1]
        for (eff_leg, cyc_strike, _e, _T) in leg_ctx:
            if eff_leg.option_type == "call" and bool(np.any(seg >= cyc_strike)):
                touched = True
            if eff_leg.option_type == "put" and bool(np.any(seg <= cyc_strike)):
                touched = True

        cycle_pct = (net_pnl / strategy_notional) * 100.0 if strategy_notional > 0 else 0.0
        cycles.append(BacktestCycle(
            cycle_num=cycle_idx, start_date=entry_date, end_date=end_date,
            dte=float((end_date - entry_date).days), entry_spot=entry_spot,
            strike=strike_report, delta_at_entry=delta_at_entry, entry_iv=entry_iv,
            premium_received_pct=premium_pct, premium_received_usd=premium_usd,
            premium_received_btc=premium_btc, premium_provenance=Provenance.MODEL_RECONSTRUCTED,
            expiry_spot=end_spot, expiry_delivery_price=end_spot, is_itm=is_itm_any,
            settlement_btc=0.0, settlement_usd=settlement_usd_total, net_pnl_usd=net_pnl,
            net_pnl_btc=net_pnl / entry_spot if entry_spot > 0 else 0.0, net_pnl_pct=cycle_pct,
            cumulative_premium_pct=cumulative_premium_pct, venue_fees_usd=venue_fee_usd,
            venue_fees_btc=0.0, spread_slippage_usd=spread_usd, impact_usd=impact_usd,
            delivery_fee_usd=delivery_fee_usd, impact_iv_giveup=0.0,
            cash_usd_start=prev_cash, cash_usd_end=cash_usd, btc_inventory_start=prev_btc,
            btc_inventory_end=btc_inventory, collateral_usd_start=prev_coll,
            collateral_usd_end=collateral_usd, realised_assignment=realised_assignment,
            unrealised_pnl_usd=spot_pnl, hedge_strategy="none", roll_event=roll_event,
            targeting_moneyness=(strike_report / entry_spot if entry_spot else 1.0),
            reconciliation_residual_usd=(equity_end - equity_start) - net_pnl,
            num_settlement_bars=max(1, len(settle_bars)), touch_frequency_hit=touched,
        ))
        day_idx = cycle_end_idx
        cycle_idx += 1
        if cycle_end_idx >= n_days - 1:
            break

    if equity_out is not None:
        # curve is contiguous from bar 0: equity_curve[i] corresponds to dates[i]
        equity_out.extend(equity_curve)

    total_pnl_pct = (total_pnl_running / strategy_notional) * 100.0 if strategy_notional > 0 else 0.0
    itm_frequency = (sum(1 for c in cycles if c.is_itm) / len(cycles)) if cycles else 0.0
    touch_frequency = (sum(1 for c in cycles if c.touch_frequency_hit) / len(cycles)) if cycles else 0.0

    max_drawdown_pct = 0.0
    peak = -1e30
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - eq) / peak)

    return BacktestResult(
        strategy_id=strategy.strategy_id,
        strategy_kind=str(strategy.canonical) if strategy.canonical else "",
        business_label=strategy.business_label if strategy.business_label else "",
        start_date=dates[0], end_date=dates[-1], cycles=cycles,
        total_pnl_usd=total_pnl_running, total_pnl_btc=total_pnl_running / initial_spot,
        total_pnl_pct=total_pnl_pct, total_premium_usd=total_premium_usd,
        total_premium_btc=total_premium_btc,
        total_fees_usd=total_venue_fees_usd + total_spread_usd + total_impact_usd,
        total_fees_btc=0.0, itm_frequency=itm_frequency, touch_frequency=touch_frequency,
        max_drawdown_pct=max_drawdown_pct, provenance=Provenance.CALCULATED,
        reconciliation_residual_usd=run_residual,
    )
