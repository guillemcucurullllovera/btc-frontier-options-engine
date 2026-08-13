"""D3 lever quantification harness.

TRACK 1 (structure levers): regime-segmented over full Binance 1d history
(2017->2026), MODEL_RECONSTRUCTED realised-vol IV proxy (identical method to
run_backtest_multigran) -> apples-to-apples with the multigran baseline. Isolates
STRUCTURE effects on MaxDD / CVaR / P(win) / P(exercise) / income.

TRACK 2 (IV-timing / VRP / dynamic coverage): continuous 2021-03->2026-07 window
priced off OBSERVED Deribit DVOL. Isolates the variance-risk-premium edge and the
timing/coverage levers.
"""
import json, math
from datetime import datetime
import numpy as np

from strategy.backtest_multileg import backtest_strategy_multileg
from strategy.definitions_multileg import (build_laddered_cc, build_financed_collar,
    build_put_spread_collar, build_protective_ladder, build_cc_spread, build_symmetric_collar)
from strategy.regimes import classify_regime

ROOT = "/home/francisco/btc/worktrees/c9-advanced-methods"
S0 = 63_401.86
SEED = 42

def load_bars(gran):
    bars = json.load(open(f"{ROOT}/market_snapshots/binance_history/{gran}/bars.json"))
    dates = [datetime.fromisoformat(b["timestamp"].replace("Z","+00:00")) for b in bars]
    close = np.array([float(b["close"]) for b in bars])
    return dates, close

def rolling_iv(close, window=30):
    lr = np.diff(np.log(close)); iv = np.full(len(close), 0.5)
    for i in range(window, len(close)):
        iv[i] = float(np.clip(np.std(lr[i-window:i])*math.sqrt(365.0), 0.15, 2.0))
    iv[:window] = iv[window]
    return iv

def regime_segments(dates_d, close_d, window_days=90, min_span_days=35):
    labels = []
    for i in range(len(close_d)):
        lo = max(0, i-window_days+1)
        labels.append(str(classify_regime(close_d[lo:i+1], dates_d[lo:i+1],
                                           window_days=window_days, vol_window=30)))
    segs, start = [], 0
    for i in range(1, len(labels)+1):
        if i == len(labels) or labels[i] != labels[start]:
            span = (dates_d[i-1]-dates_d[start]).days
            if span >= min_span_days:
                segs.append({"label": labels[start], "start": dates_d[start], "end": dates_d[i-1]})
            start = i
    return segs

def tail_stats(pnls):
    a = np.array(pnls, float); n=len(a)
    if n==0: return {}
    s=np.sort(a); k=max(1,int(math.ceil(0.05*n)))
    return {"n_cycles":n, "median_pnl_usd":float(np.median(a)), "mean_pnl_usd":float(np.mean(a)),
            "p_profit":float(np.mean(a>0)), "cvar95_pnl_usd":float(np.mean(s[:k])),
            "worst_cycle_usd":float(s[0]), "std_pnl_usd":float(np.std(a))}

def aggregate(runs):
    pnls, dds, seg_ret, itmf, prem = [], [], [], [], []
    for r,_ in runs:
        pnls.extend([c.net_pnl_usd for c in r.cycles])
        dds.append(r.max_drawdown_pct); seg_ret.append(r.total_pnl_pct)
        itmf.append(r.itm_frequency)
        prem.extend([c.premium_received_usd for c in r.cycles])
    if not runs: return {}
    st = tail_stats(pnls)
    st["n_segments"]=len(runs); st["max_drawdown_pct"]=float(max(dds)) if dds else 0.0
    sr=np.array(seg_ret,float); srs=np.sort(sr); k=max(1,int(math.ceil(0.05*len(srs))))
    st["segRet_median"]=float(np.median(sr)); st["segRet_p_profit"]=float(np.mean(sr>0))
    st["segRet_cvar95"]=float(np.mean(srs[:k]))
    st["itm_frequency_mean"]=float(np.mean(itmf)) if itmf else 0.0   # P(exercise) proxy
    st["mean_premium_per_cycle_usd"]=float(np.mean([p for p in prem if p!=0.0])) if any(prem) else 0.0
    return st

def run_segmented(builder, dates_d, close_d, iv_d, segs, **kw):
    gts=np.array([d.timestamp() for d in dates_d]); runs=[]
    for seg in segs:
        lo=int(np.searchsorted(gts, seg["start"].timestamp(), "left"))
        hi=int(np.searchsorted(gts, seg["end"].timestamp(), "right"))
        if hi-lo < 3: continue
        sub_d=dates_d[lo:hi]; sub_c=close_d[lo:hi]; sub_iv=iv_d[lo:hi]
        try:
            r=backtest_strategy_multileg(builder(), list(sub_d), sub_c, sub_iv,
                                         ref_spot=S0, risk_free_rate=0.0, dte_days=31, seed=SEED, **kw)
            runs.append((r, float(sub_c[0])))
        except Exception as e:
            print("  seg fail", seg["label"], e)
    return aggregate(runs)

# ══════════════════════════ TRACK 1 ══════════════════════════
print("Loading 1d history...")
dates_d, close_d = load_bars("1d")
iv_d = rolling_iv(close_d)
print("Segmenting regimes...")
segs = regime_segments(dates_d, close_d)
print(f"  {len(segs)} segments")

CONFIGS = {
 "baseline_ladder40_asym":      lambda: build_laddered_cc(entry_spot=S0, coverage=0.40),
 "ladder100_uniform4_reconcile":lambda: build_laddered_cc(entry_spot=S0, coverage=1.00,
                                    ladder_pcts=[0.04,0.04,0.04,0.04]),
 "financed_collar_c5_p10":      lambda: build_financed_collar(entry_spot=S0, coverage=0.40, call_pct=0.05, put_pct=0.10),
 "financed_collar_c4_p10":      lambda: build_financed_collar(entry_spot=S0, coverage=0.40, call_pct=0.04, put_pct=0.10),
 "collar_c5_p10_fullput":       lambda: build_financed_collar(entry_spot=S0, coverage=0.40, call_pct=0.05, put_pct=0.10, put_coverage=1.00),
 "symmetric_collar100_c10_p10": lambda: build_symmetric_collar(entry_spot=S0, coverage=1.00, call_pct=0.10, put_pct=0.10),
 "collar100_c5_p12":            lambda: build_symmetric_collar(entry_spot=S0, coverage=1.00, call_pct=0.05, put_pct=0.12),
 "put_spread_collar_c5_p10_20": lambda: build_put_spread_collar(entry_spot=S0, coverage=0.40),
 "protective_ladder_p10":       lambda: build_protective_ladder(entry_spot=S0, coverage=0.40, put_pct=0.10),
 "protective_ladder_p10_fullput":lambda:build_protective_ladder(entry_spot=S0, coverage=0.40, put_pct=0.10, put_coverage=1.00),
 "protective_ladder_p12":       lambda: build_protective_ladder(entry_spot=S0, coverage=0.40, put_pct=0.12),
 "cc_spread_s4_l9":             lambda: build_cc_spread(entry_spot=S0, coverage=0.40, short_pct=0.04, long_pct=0.09),
 # strike-floor lever (higher floor = less income, more retained upside, higher P(win))
 "ladder40_floor5":             lambda: build_laddered_cc(entry_spot=S0, coverage=0.40, ladder_pcts=[0.05,0.0833,0.1167,0.15]),
 "ladder40_floor6":             lambda: build_laddered_cc(entry_spot=S0, coverage=0.40, ladder_pcts=[0.06,0.10,0.14,0.18]),
 # coverage lever
 "ladder25_asym":               lambda: build_laddered_cc(entry_spot=S0, coverage=0.25),
 "ladder60_asym":               lambda: build_laddered_cc(entry_spot=S0, coverage=0.60),
}

track1 = {}
for name, b in CONFIGS.items():
    print("T1:", name)
    track1[name] = run_segmented(b, dates_d, close_d, iv_d, segs)

# ══════════════════════════ TRACK 2 (DVOL) ══════════════════════════
print("Loading DVOL...")
dvol_raw = json.load(open(f"{ROOT}/market_snapshots/deribit_dvol_history/dvol_daily.json"))
dvol_map = {d["date"]: float(d["dvol"]) for d in dvol_raw}
# align DVOL to daily bars from 2021-03-24
mask = np.array([d.strftime("%Y-%m-%d") in dvol_map for d in dates_d])
idx0 = int(np.argmax(mask))  # first date with DVOL
d2_dates = dates_d[idx0:]; d2_close = close_d[idx0:]
dvol_series = np.array([dvol_map.get(d.strftime("%Y-%m-%d"), np.nan) for d in d2_dates])
# forward-fill any missing
for i in range(len(dvol_series)):
    if np.isnan(dvol_series[i]): dvol_series[i] = dvol_series[i-1] if i>0 else 0.5
realized_2021 = rolling_iv(d2_close)

# --- (2a) Direct VRP: DVOL implied vs SUBSEQUENT 30d realized ---
fut_rv = np.full(len(d2_close), np.nan)
lr = np.diff(np.log(d2_close))
for i in range(len(d2_close)-31):
    fut_rv[i] = float(np.std(lr[i:i+30])*math.sqrt(365.0))
valid = ~np.isnan(fut_rv)
vrp = dvol_series[valid] - fut_rv[valid]   # implied - realized
vrp_stats = {"n_obs": int(valid.sum()),
             "mean_implied_dvol": float(np.mean(dvol_series[valid])),
             "mean_realized_fwd30": float(np.mean(fut_rv[valid])),
             "mean_vrp_impl_minus_real": float(np.mean(vrp)),
             "median_vrp": float(np.median(vrp)),
             "pct_days_vrp_positive": float(np.mean(vrp>0)),
             "vrp_p25": float(np.percentile(vrp,25)), "vrp_p75": float(np.percentile(vrp,75))}

# --- (2b) baseline ladder priced at DVOL (captures VRP) vs at realized proxy ---
def run_continuous(builder, dates, close, path_iv, price_iv=None, **kw):
    r = backtest_strategy_multileg(builder(), list(dates), close, path_iv, ref_spot=S0,
                                   price_iv_history=price_iv, risk_free_rate=0.0, dte_days=31, seed=SEED, **kw)
    pnls=[c.net_pnl_usd for c in r.cycles]; prem=[c.premium_received_usd for c in r.cycles]
    a=np.array(pnls,float); s=np.sort(a); k=max(1,int(math.ceil(0.05*len(s))))
    return {"n_cycles":len(pnls), "total_pnl_usd":r.total_pnl_usd, "total_pnl_pct":r.total_pnl_pct,
            "median_pnl_usd":float(np.median(a)), "mean_pnl_usd":float(np.mean(a)),
            "p_profit":float(np.mean(a>0)), "cvar95_pnl_usd":float(np.mean(s[:k])),
            "max_drawdown_pct":r.max_drawdown_pct, "itm_frequency":r.itm_frequency,
            "mean_premium_per_cycle_usd":float(np.mean([p for p in prem if p!=0])) if any(prem) else 0.0,
            "total_premium_usd":r.total_premium_usd}

lad = lambda: build_laddered_cc(entry_spot=S0, coverage=0.40)
track2 = {"vrp_direct": vrp_stats,
          "window": [d2_dates[0].isoformat(), d2_dates[-1].isoformat()],
          "ladder_priced_realizedproxy": run_continuous(lad, d2_dates, d2_close, realized_2021, price_iv=realized_2021),
          "ladder_priced_DVOL_implied":  run_continuous(lad, d2_dates, d2_close, realized_2021, price_iv=dvol_series),
}
# --- (2c) IV-gate: sell only when DVOL percentile >= thr (priced at DVOL) ---
for thr in [0.50, 0.60, 0.70]:
    track2[f"ladder_ivgate_p{int(thr*100)}"] = run_continuous(
        lad, d2_dates, d2_close, realized_2021, price_iv=dvol_series,
        iv_gate=True, iv_gate_percentile=thr, iv_gate_lookback=252)

# --- (2d) dynamic coverage: scale 25%..60% with DVOL percentile ---
# coverage_fn maps IV percentile -> multiplier on the base 40% legs.
# base legs are 40%; multiplier m gives effective coverage 0.40*m. To span 25-60%,
# m in [0.625, 1.50]; linear in percentile.
def cov_dyn(pct):
    return 0.625 + (1.50-0.625)*pct
track2["ladder_dyncov_25_60"] = run_continuous(
    lad, d2_dates, d2_close, realized_2021, price_iv=dvol_series, coverage_fn=cov_dyn)
# combined: IV-gate p60 + dynamic coverage (the recommended engine)
track2["ladder_gate60_dyncov"] = run_continuous(
    lad, d2_dates, d2_close, realized_2021, price_iv=dvol_series,
    iv_gate=True, iv_gate_percentile=0.60, coverage_fn=cov_dyn)
# recommended full: protective ladder (put on covered sleeve) + DVOL + gate60 + dyncov
prot = lambda: build_protective_ladder(entry_spot=S0, coverage=0.40, put_pct=0.10)
track2["RECOMMENDED_protective_gate60_dyncov"] = run_continuous(
    prot, d2_dates, d2_close, realized_2021, price_iv=dvol_series,
    iv_gate=True, iv_gate_percentile=0.60, coverage_fn=cov_dyn)
# stronger tail: put on FULL block (bigger floor, more out-of-pocket)
prot_full = lambda: build_protective_ladder(entry_spot=S0, coverage=0.40, put_pct=0.10, put_coverage=1.00)
track2["protective_fullput_gate60_dyncov"] = run_continuous(
    prot_full, d2_dates, d2_close, realized_2021, price_iv=dvol_series,
    iv_gate=True, iv_gate_percentile=0.60, coverage_fn=cov_dyn)
# and the plain protective ladder over 2021 for reference (DVOL priced, no timing)
track2["protective_ladder_2021_DVOL"] = run_continuous(
    prot, d2_dates, d2_close, realized_2021, price_iv=dvol_series)

out = {"track1_structure_regime_segmented": track1,
       "track2_ivtiming_vrp_2021": track2,
       "n_segments": len(segs)}
open("/tmp/claude-1000/-home-francisco-btc/a2aa536f-79d8-4821-9ff1-48081b91aec7/scratchpad/levers_out.json","w").write(json.dumps(out, indent=2, default=str))

# ── console digest ──
print("\n===== TRACK 1 (structure, regime-segmented, full history) =====")
print(f"{'config':32s} {'segRetMed':>9s} {'segPprof':>8s} {'cycMed$M':>9s} {'cycMean$M':>9s} {'Pwin':>5s} {'CVaR95$M':>9s} {'maxDD':>6s} {'Pexer':>6s} {'prem/cyc$M':>10s}")
for name, s in track1.items():
    if not s: continue
    print(f"{name:32s} {s['segRet_median']:>9.2f} {s['segRet_p_profit']:>8.2f} "
          f"{s['median_pnl_usd']/1e6:>9.1f} {s['mean_pnl_usd']/1e6:>9.1f} {s['p_profit']:>5.2f} "
          f"{s['cvar95_pnl_usd']/1e6:>9.1f} {s['max_drawdown_pct']:>6.2f} {s['itm_frequency_mean']:>6.2f} "
          f"{s['mean_premium_per_cycle_usd']/1e6:>10.2f}")

print("\n===== TRACK 2 (IV-timing / VRP, 2021-> DVOL) =====")
v=vrp_stats
print(f"VRP direct: implied DVOL {v['mean_implied_dvol']*100:.1f}% vs fwd-30d realized {v['mean_realized_fwd30']*100:.1f}%"
      f" -> mean VRP {v['mean_vrp_impl_minus_real']*100:.2f} vol pts; positive {v['pct_days_vrp_positive']*100:.0f}% of days (n={v['n_obs']})")
print(f"{'config':40s} {'ncyc':>4s} {'totPnL$M':>9s} {'cycMed$M':>9s} {'cycMean$M':>9s} {'Pwin':>5s} {'CVaR95$M':>9s} {'maxDD':>6s} {'Pexer':>6s} {'prem/cyc$M':>10s}")
for name, s in track2.items():
    if not isinstance(s, dict) or "n_cycles" not in s: continue
    print(f"{name:40s} {s['n_cycles']:>4d} {s['total_pnl_usd']/1e6:>9.1f} {s['median_pnl_usd']/1e6:>9.2f} "
          f"{s['mean_pnl_usd']/1e6:>9.2f} {s['p_profit']:>5.2f} {s['cvar95_pnl_usd']/1e6:>9.1f} "
          f"{s['max_drawdown_pct']:>6.2f} {s['itm_frequency']:>6.2f} {s['mean_premium_per_cycle_usd']/1e6:>10.2f}")
print("\nWROTE levers_out.json")
