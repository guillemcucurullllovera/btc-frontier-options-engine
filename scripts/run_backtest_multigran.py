"""8-year multi-granularity holder-inclusive backtest, segmented by regime.

DIAGNOSTIC. Observed price bars (Binance BTCUSDT). Options repriced at a
MODEL_RECONSTRUCTED IV proxy (rolling 30d realised vol from the DAILY series,
annualised sqrt(365), clipped [0.15,2.0], forward-filled onto every granularity
so option prices are IDENTICAL across granularities -> the granularity effect is
isolated to PATH mechanics, not confounded by microstructure-inflated IV).

r=0 (calibration). Primary tenor 31d; 59d secondary on 1d only.
Holder-inclusive: every overlay P&L = long 30,000 BTC + option legs.

Multi-strike structures (collar asymmetric strikes, call spreads, strike-ladder
dispersion, protective ladder) are only PARTIALLY representable: backtest_strategy
overrides every leg strike with a single direction-aware strike_pct_above
(calls entry*(1+p), puts entry*(1-p)). Blockers reported honestly.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from strategy.backtest import backtest_strategy, backtest_unhedged_observed
from strategy.definitions import (
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_strike_ladder,
    build_unhedged_baseline,
)
from strategy.regimes import classify_regime

ROOT = Path("/home/francisco/btc/worktrees/c9-advanced-methods")
HIST = ROOT / "market_snapshots" / "binance_history"
OUT = ROOT / "strategy_figures" / "backtest_multigran.json"
S0 = 63_401.86
SEED = 42


def load_bars(gran: str):
    bars = json.load(open(HIST / gran / "bars.json"))
    dates = [datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00")) for b in bars]
    close = np.array([float(b["close"]) for b in bars], dtype=float)
    return dates, close


def rolling_iv_daily(dates_d, close_d, window=30):
    """Rolling realised vol on daily series -> annualised IV proxy."""
    lr = np.diff(np.log(close_d))
    iv = np.full(len(close_d), 0.5)
    for i in range(window, len(close_d)):
        iv[i] = float(np.clip(np.std(lr[i - window : i]) * math.sqrt(365.0), 0.15, 2.0))
    iv[:window] = iv[window] if len(close_d) > window else 0.5
    return iv


def iv_forward_fill(target_dates, daily_dates, daily_iv):
    """Assign each target bar the most recent daily IV at or before it."""
    dd = np.array([d.timestamp() for d in daily_dates])
    td = np.array([d.timestamp() for d in target_dates])
    idx = np.searchsorted(dd, td, side="right") - 1
    idx = np.clip(idx, 0, len(daily_iv) - 1)
    return daily_iv[idx]


def regime_segments(dates_d, close_d, window_days=90, min_span_days=35):
    """Per-bar rolling regime label on the daily series; contiguous segments."""
    labels = []
    for i in range(len(close_d)):
        lo = max(0, i - window_days + 1)
        labels.append(str(classify_regime(close_d[lo : i + 1], dates_d[lo : i + 1],
                                           window_days=window_days, vol_window=30)))
    segs = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            span = (dates_d[i - 1] - dates_d[start]).days
            if span >= min_span_days:
                segs.append({"label": labels[start], "start": dates_d[start],
                             "end": dates_d[i - 1], "n_days": span})
            start = i
    return segs


def tail_stats(pnls):
    a = np.array(pnls, dtype=float)
    n = len(a)
    if n == 0:
        return {}
    a_sorted = np.sort(a)
    k = max(1, int(math.ceil(0.05 * n)))
    cvar95 = float(np.mean(a_sorted[:k]))  # mean of worst 5% (left tail P&L)
    return {
        "n_cycles": n,
        "median_pnl_usd": float(np.median(a)),
        "mean_pnl_usd": float(np.mean(a)),
        "p_profit": float(np.mean(a > 0)),
        "cvar95_pnl_usd": cvar95,
        "es95_loss_usd": float(-cvar95),
        "worst_cycle_usd": float(a_sorted[0]),
        "best_cycle_usd": float(a_sorted[-1]),
        "std_pnl_usd": float(np.std(a)),
    }


# ── strategy registry: (id, builder, strike_pct_above, faithful, note) ──
def _laddered():
    return build_strike_ladder(base_quantity=30_000.0, entry_spot=S0,
                               dte_ladder=[31, 38, 45, 52], strike_uplift_pct=0.04,
                               premium_pct_of_spot=0.02)

STRATS = [
    ("covered_call_4pct", lambda: build_covered_call(quantity=30_000.0, entry_spot=S0),
     0.04, True, "Covered call, short call +4% (listed 66k-equiv). Faithful."),
    ("long_btc_short_put_5pct",
     lambda: build_long_btc_plus_short_put(quantity=30_000.0, entry_spot=S0),
     0.05, True, "Long 30k BTC + short put -5%. Faithful."),
    ("laddered_covered_call_4pct", _laddered, 0.04, True,
     "4x25% covered call, entry/expiry ladder (31/38/45/52d), all strikes +4%. Faithful."),
    ("collar_symm10", lambda: build_collar(quantity=30_000.0, entry_spot=S0),
     0.10, False, "APPROX: spec collar is call +5%/put -10% (2 strike DOF). Engine forces "
     "symmetric +/-10%: put floor -10% matches spec, call cap +10% is LOOSER than the +5% spec."),
    ("strike_ladder_uniform8", _laddered, 0.08, False,
     "APPROX: spec strike ladder is +4/8/12/16% dispersion; engine collapses all call legs to a "
     "single uniform +8% strike. Only the DTE ladder (31/38/45/52d) is faithful."),
]

BLOCKED = {
    "covered_call_spread_4_9": "Both legs are calls (short +4%, long +9%). backtest_strategy sets "
    "every call leg to entry*(1+strike_pct_above) -> both legs collapse to the SAME strike -> a "
    "zero-width, economically degenerate spread. Not representable via the single strike_pct_above knob.",
    "protective_ladder_call4_put10": "Requires short calls at +4% AND a long put floor at -10% "
    "SIMULTANEOUSLY. The single direction-aware strike_pct_above cannot set call and put offsets "
    "independently (it would force call +p and put -p). Not representable.",
}


def run_one(strat_builder, spa, dates, spot, iv, dte):
    strat = strat_builder()
    return backtest_strategy(strat, dates, spot, iv, risk_free_rate=0.0,
                             dte_days=dte, strike_pct_above=spa, seed=SEED)


def aggregate_segments(runs):
    """runs: list of (BacktestResult, seg_entry_spot). Pool cycle P&Ls and
    segment-level total returns. Benchmark (no cycles) still yields segment stats."""
    pnls, dds, eac_ratios, seg_ret_pct = [], [], [], []
    for r, s0 in runs:
        pnls.extend([c.net_pnl_usd for c in r.cycles])
        dds.append(r.max_drawdown_pct)
        seg_ret_pct.append(r.total_pnl_pct)
        eac = r.effective_acquisition_cost
        if eac is not None and eac.is_applicable and s0 > 0 and math.isfinite(eac.per_btc_usd):
            eac_ratios.append((eac.per_btc_usd / s0 - 1.0) * 100.0)
    if not runs:
        return {}
    stats = tail_stats(pnls)  # per-cycle P&L (empty for benchmark)
    stats["n_segments"] = len(runs)
    stats["max_drawdown_pct"] = float(max(dds)) if dds else 0.0
    stats["eac_vs_spot_pct_mean"] = float(np.mean(eac_ratios)) if eac_ratios else None
    # segment-level total return (%) — comparable across overlays and benchmark
    sr = np.array(seg_ret_pct, dtype=float)
    stats["segment_return_pct_median"] = float(np.median(sr))
    stats["segment_return_pct_mean"] = float(np.mean(sr))
    stats["segment_return_pct_p_profit"] = float(np.mean(sr > 0))
    srs = np.sort(sr)
    k = max(1, int(math.ceil(0.05 * len(srs))))
    stats["segment_return_pct_cvar95"] = float(np.mean(srs[:k]))
    return stats


def main():
    print("Loading granularities...")
    dates_d, close_d = load_bars("1d")
    dates_h, close_h = load_bars("1h")
    dates_m, close_m = load_bars("1m")
    daily_iv = rolling_iv_daily(dates_d, close_d)

    GRANS = {
        "1d": (dates_d, close_d, iv_forward_fill(dates_d, dates_d, daily_iv)),
        "1h": (dates_h, close_h, iv_forward_fill(dates_h, dates_d, daily_iv)),
        "1m": (dates_m, close_m, iv_forward_fill(dates_m, dates_d, daily_iv)),
    }
    coverage = {g: {"n_bars": len(v[0]), "start": v[0][0].isoformat(),
                    "end": v[0][-1].isoformat()} for g, v in GRANS.items()}

    print("Building regime segments (daily)...")
    segs = regime_segments(dates_d, close_d)
    seg_summary = {}
    for s in segs:
        seg_summary.setdefault(s["label"], {"count": 0, "total_days": 0})
        seg_summary[s["label"]]["count"] += 1
        seg_summary[s["label"]]["total_days"] += s["n_days"]

    results = {}
    # benchmark just_holding: pooled per regime & per granularity
    all_ids = ["just_holding"] + [s[0] for s in STRATS]

    for gran, (gd, gc, giv) in GRANS.items():
        gts = np.array([d.timestamp() for d in gd])
        print(f"=== granularity {gran} ({len(gd)} bars) ===")
        for sid in all_ids:
            results.setdefault(sid, {"by_granularity": {}})
        # organise segment runs per regime label
        runs_by_regime = {sid: {} for sid in all_ids}
        for seg in segs:
            a = seg["start"].timestamp()
            b = seg["end"].timestamp()
            lo = int(np.searchsorted(gts, a, side="left"))
            hi = int(np.searchsorted(gts, b, side="right"))
            sub_d = gd[lo:hi]
            if len(sub_d) < 3:
                continue
            sub_c = gc[lo:hi]
            sub_iv = giv[lo:hi]
            s0 = float(sub_c[0])
            lab = seg["label"]
            # need at least ~1 cycle worth of span; else backtest still runs (clipped)
            # just_holding
            try:
                r = backtest_unhedged_observed(build_unhedged_baseline(), list(sub_d), sub_c, sub_iv)
                runs_by_regime["just_holding"].setdefault(lab, []).append((r, s0))
            except Exception as e:
                pass
            for sid, builder, spa, faithful, note in STRATS:
                try:
                    r = run_one(builder, spa, list(sub_d), sub_c, sub_iv, 31)
                    runs_by_regime[sid].setdefault(lab, []).append((r, s0))
                except Exception as e:
                    pass
        # aggregate
        for sid in all_ids:
            by_regime = {}
            all_runs = []
            for lab, runs in runs_by_regime[sid].items():
                st = aggregate_segments(runs)
                if st:
                    by_regime[lab] = st
                all_runs.extend(runs)
            results[sid]["by_granularity"][gran] = {
                "by_regime": by_regime,
                "all_regimes": aggregate_segments(all_runs),
            }

    # annotate strategy metadata
    for sid, builder, spa, faithful, note in STRATS:
        results[sid]["faithful"] = faithful
        results[sid]["strike_pct_above"] = spa
        results[sid]["note"] = note
    results["just_holding"]["faithful"] = True
    results["just_holding"]["note"] = "Benchmark: buy 30k BTC at segment start, hold to segment end (observed)."

    # 59d secondary tenor, daily only, all regimes pooled
    tenor59 = {}
    gd, gc, giv = GRANS["1d"]
    gts = np.array([d.timestamp() for d in gd])
    for sid, builder, spa, faithful, note in STRATS:
        all_runs = []
        for seg in segs:
            lo = int(np.searchsorted(gts, seg["start"].timestamp(), side="left"))
            hi = int(np.searchsorted(gts, seg["end"].timestamp(), side="right"))
            if hi - lo < 3:
                continue
            try:
                strat = builder()
                r = backtest_strategy(strat, list(gd[lo:hi]), gc[lo:hi], giv[lo:hi],
                                      risk_free_rate=0.0, dte_days=59, strike_pct_above=spa, seed=SEED)
                all_runs.append((r, float(gc[lo])))
            except Exception:
                pass
        tenor59[sid] = aggregate_segments(all_runs)

    # granularity effect: covered_call_4pct on the COMMON recent window where all
    # three granularities overlap (2026-05-02 .. 2026-07-30), pooled over that window.
    common_start = max(GRANS["1m"][0][0], GRANS["1h"][0][0])
    common_end = min(GRANS["1m"][0][-1], GRANS["1d"][0][-1])
    gran_effect = {"window": [common_start.isoformat(), common_end.isoformat()],
                   "note": "Same calendar window, same IV path, same +4% strike/31d cadence; "
                           "differences are pure PATH/jump-capture effects of bar resolution.",
                   "per_strategy": {}}
    for sid, builder, spa in [("covered_call_4pct", lambda: build_covered_call(quantity=30_000.0, entry_spot=S0), 0.04),
                              ("long_btc_short_put_5pct", lambda: build_long_btc_plus_short_put(quantity=30_000.0, entry_spot=S0), 0.05)]:
        gran_effect["per_strategy"][sid] = {}
        for gran, (gd2, gc2, giv2) in GRANS.items():
            gts2 = np.array([d.timestamp() for d in gd2])
            lo = int(np.searchsorted(gts2, common_start.timestamp(), side="left"))
            hi = int(np.searchsorted(gts2, common_end.timestamp(), side="right"))
            if hi - lo < 3:
                continue
            try:
                r = run_one(builder, spa, list(gd2[lo:hi]), gc2[lo:hi], giv2[lo:hi], 31)
                st = aggregate_segments([(r, float(gc2[lo]))])
                st["itm_frequency"] = r.itm_frequency
                st["touch_frequency"] = r.touch_frequency
                gran_effect["per_strategy"][sid][gran] = st
            except Exception as e:
                gran_effect["per_strategy"][sid][gran] = {"error": str(e)}

    jump5m = json.load(open(ROOT / "market_snapshots" / "binance_5m_jumps" / "regime_stats.json"))

    out = {
        "meta": {
            "title": "8-year multi-granularity holder-inclusive backtest, regime-segmented",
            "provenance": "DIAGNOSTIC / MODERATE. Observed Binance BTCUSDT bars; options repriced "
                          "at MODEL_RECONSTRUCTED IV proxy (rolling 30d daily realised vol, "
                          "forward-filled across granularities). r=0. s0_calib=%.2f. seed=%d." % (S0, SEED),
            "holder_inclusive": "Every overlay P&L = long 30,000 BTC + option legs (spot P&L dominates).",
            "iv_proxy": "rolling 30-bar realised vol on DAILY close, annualised sqrt(365), clip[0.15,2.0], "
                        "forward-filled by timestamp onto 1h/1m so option prices are identical across "
                        "granularities (isolates path effect). NOT observed IV; ATM anchor 31d=0.3653.",
            "tenor_primary_dte": 31, "tenor_secondary_dte": 59,
            "objective": "risk-adjusted = median P&L / CVaR95 s.t. CVaR95 <= loss cap; frontier + selected point.",
        },
        "data_coverage": coverage,
        "blockers": {
            "binance_5m_jumps": "NO price bars present in market_snapshots/binance_5m_jumps/ (only "
                                "regime_stats.json with jump-intensity eta). A price-series backtest at "
                                "5m CANNOT be run. Jump-intensity stats reported below as context.",
            "1m_coverage": "1m series covers only 2026-05-02..2026-07-31 (~3 months), NOT the full "
                           "8-year history. 1m regime aggregates reflect only the recent window.",
            "multi_strike_engine_limit": "backtest_strategy applies ONE direction-aware strike_pct_above "
                                          "to all legs, overriding per-leg builder strikes. Asymmetric / "
                                          "multi-strike structures are only partially representable.",
            "blocked_structures": BLOCKED,
        },
        "jump_intensity_5m": jump5m,
        "regime_segments_daily": {"summary": seg_summary,
                                  "segments": [{"label": s["label"], "start": s["start"].isoformat(),
                                                "end": s["end"].isoformat(), "n_days": s["n_days"]} for s in segs]},
        "results": results,
        "tenor_59d_daily_all_regimes": tenor59,
        "granularity_effect": gran_effect,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"WROTE {OUT}")

    # brief console digest
    print("\n--- DIGEST (1d, all-regimes pooled, 31d) ---")
    for sid in all_ids:
        st = results[sid]["by_granularity"]["1d"]["all_regimes"]
        if st:
            ec = st.get('eac_vs_spot_pct_mean')
            print(f"{sid:28s} nseg={st['n_segments']:3d} ncyc={st.get('n_cycles',0):4d} "
                  f"segRet%med={st['segment_return_pct_median']:>7.1f} "
                  f"cycMed={st.get('median_pnl_usd',0):>13,.0f} "
                  f"CVaR95cyc={st.get('cvar95_pnl_usd',0):>14,.0f} "
                  f"dd={st.get('max_drawdown_pct',0):.2f} eac%={ec if ec is None else round(ec,1)}")


if __name__ == "__main__":
    main()
