"""CSCV / PBO / DSR anti-overfitting harness applied to the recommended overlays.

DIAGNOSTIC / MODERATE. Reuses strategy/regimes.py (compute_cscv_pbo,
compute_oos_validation, classify_regime) — the validated Bailey et al. (2015)
CSCV/PBO/DSR harness — on the OBSERVED per-cycle P&L series recovered by
re-running the Phase-1 8-year multi-granularity backtest (run_backtest_multigran).

Structures under test:
  - The 5 fixed backtestable candidates (covered_call_4pct, long_btc_short_put_5pct,
    laddered_covered_call_4pct, collar_symm10, strike_ladder_uniform8).
  - The frontier objective-selected structure per regime is, in EVERY regime, a
    COLLAR (call+2..4% / put-12%). The only backtestable collar proxy is
    collar_symm10 (symmetric +/-10%) -> its verdict is the OOS evidence for the
    objective-selected pick, with the asymmetry-mismatch caveat recorded.

No future leakage: cycles are chronological; train precedes test; the harness
splits are on the ordered series. r=0, seed=42, observed Binance bars, IV proxy
identical across granularities (see run_backtest_multigran.py).

Honest blocker: the observed cycle ceiling is 69 (1d, 31d cadence). Bailey's CSCV
default requires n>=100. We therefore report BOTH:
  (a) the default-gate result (typed insufficient-data), and
  (b) a DIAGNOSTIC underpowered config (n_min = n, s scaled to <= n/2) that
      actually computes PBO/DSR, explicitly labelled UNDERPOWERED.
A statistically-powered PBO/DSR needs the GATED full-campaign Monte-Carlo cycle
set (14.4M/60M) or a longer/higher-frequency observed cycle series.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from strategy.backtest import backtest_strategy
from strategy.definitions import (
    build_collar,
    build_covered_call,
    build_long_btc_plus_short_put,
    build_strike_ladder,
)
from strategy.regimes import (
    classify_regime,
    compute_cscv_pbo,
    compute_oos_validation,
)
from strategy import deflated_sharpe as _ds

ROOT = Path("/home/francisco/btc/worktrees/c9-advanced-methods")
HIST = ROOT / "market_snapshots" / "binance_history"
OUT = ROOT / "strategy_figures" / "overfitting.json"
S0 = 63_401.86
SEED = 42
NOTIONAL = 30_000.0 * S0  # holder-inclusive notional


def load_bars(gran: str):
    bars = json.load(open(HIST / gran / "bars.json"))
    dates = [datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00")) for b in bars]
    close = np.array([float(b["close"]) for b in bars], dtype=float)
    return dates, close


def rolling_iv_daily(close_d, window=30):
    lr = np.diff(np.log(close_d))
    iv = np.full(len(close_d), 0.5)
    for i in range(window, len(close_d)):
        iv[i] = float(np.clip(np.std(lr[i - window:i]) * math.sqrt(365.0), 0.15, 2.0))
    iv[:window] = iv[window] if len(close_d) > window else 0.5
    return iv


def regime_segments(dates_d, close_d, window_days=90, min_span_days=35):
    labels = []
    for i in range(len(close_d)):
        lo = max(0, i - window_days + 1)
        labels.append(str(classify_regime(close_d[lo:i + 1], dates_d[lo:i + 1],
                                           window_days=window_days, vol_window=30)))
    segs, start = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            span = (dates_d[i - 1] - dates_d[start]).days
            if span >= min_span_days:
                segs.append({"label": labels[start], "start": dates_d[start],
                             "end": dates_d[i - 1]})
            start = i
    return segs


# fixed backtestable candidates: (id, builder, strike_pct_above, faithful, note)
def _laddered():
    return build_strike_ladder(base_quantity=30_000.0, entry_spot=S0,
                               dte_ladder=[31, 38, 45, 52], strike_uplift_pct=0.04,
                               premium_pct_of_spot=0.02)


STRATS = [
    ("covered_call_4pct", lambda: build_covered_call(quantity=30_000.0, entry_spot=S0),
     0.04, True, "Covered call short +4%. Faithful."),
    ("long_btc_short_put_5pct",
     lambda: build_long_btc_plus_short_put(quantity=30_000.0, entry_spot=S0),
     0.05, True, "Long 30k BTC + short put -5%. Faithful."),
    ("laddered_covered_call_4pct", _laddered, 0.04, True,
     "4x25% covered call, DTE ladder, strikes +4%. Faithful."),
    ("collar_symm10", lambda: build_collar(quantity=30_000.0, entry_spot=S0),
     0.10, False,
     "APPROX proxy for the objective-selected collar. Engine forces symmetric +/-10%; "
     "frontier pick is asymmetric call+2..4%/put-12%. OOS evidence is indicative, not exact."),
    ("strike_ladder_uniform8", _laddered, 0.08, False,
     "APPROX: engine collapses +4/8/12/16% dispersion to uniform +8%."),
]


def cycle_series(builder, spa, segs, gd, gc, giv, gts, dte=31):
    """Recover the chronological per-cycle net-P&L series across all regime segments."""
    cyc = []
    for seg in segs:
        lo = int(np.searchsorted(gts, seg["start"].timestamp(), side="left"))
        hi = int(np.searchsorted(gts, seg["end"].timestamp(), side="right"))
        if hi - lo < 3:
            continue
        try:
            r = backtest_strategy(builder(), list(gd[lo:hi]), gc[lo:hi], giv[lo:hi],
                                  risk_free_rate=0.0, dte_days=dte, strike_pct_above=spa, seed=SEED)
        except Exception:
            continue
        for c in r.cycles:
            cyc.append((c.start_date, float(c.net_pnl_usd)))
    cyc.sort(key=lambda x: x[0])  # chronological, no leakage
    dates = [c[0] for c in cyc]
    pnl = np.array([c[1] for c in cyc], dtype=float)
    return dates, pnl


def sharpe(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return None
    sd = float(np.std(x))
    return float(np.mean(x) / sd) if sd > 1e-12 else 0.0


def verdict(pbo, dsr):
    """Bailey: PBO>0.5 => overfit. DSR>0 => skill survives deflation."""
    if pbo is None or dsr is None:
        return "INDETERMINATE"
    if pbo <= 0.5 and dsr > 0.0:
        return "PASS" if pbo <= 0.2 else "PASS_WEAK"
    return "FAIL"


def main():
    dates_d, close_d = load_bars("1d")
    daily_iv = rolling_iv_daily(close_d)
    gts = np.array([d.timestamp() for d in dates_d])
    segs = regime_segments(dates_d, close_d)

    full_regime = str(classify_regime(close_d, dates_d, window_days=90, vol_window=30))

    per_structure = {}
    matrix_returns = {}  # for cross-sectional CSCV (aligned on segment total returns)

    for sid, builder, spa, faithful, note in STRATS:
        cdates, pnl = cycle_series(builder, spa, segs, dates_d, close_d, daily_iv, gts)
        n = len(pnl)
        ret = pnl / NOTIONAL  # per-cycle holder-inclusive return
        matrix_returns[sid] = (cdates, ret)

        # (a) DEFAULT GATE — honest Bailey config (n_min=100, s=16)
        default_res = compute_cscv_pbo(ret, s=16, n_min=100)

        # (b) DIAGNOSTIC underpowered — actually computes PBO/DSR on the short series
        s_diag = max(2, min(16, n // 4))
        diag_res = compute_cscv_pbo(ret, s=s_diag, n_min=2 * s_diag)

        # chronological 70/30 OOS split (train precedes test)
        split = int(n * 0.70)
        tr, te = ret[:split], ret[split:]
        train_result = {
            "sharpe": sharpe(tr), "returns": tr.tolist(),
            "train_period": (cdates[0], cdates[split - 1]) if split >= 1 else (datetime.min, datetime.min),
        }
        test_result = {
            "sharpe": sharpe(te), "returns": te.tolist(),
            "test_period": (cdates[split], cdates[-1]) if split < n else (datetime.min, datetime.min),
        }
        oos = compute_oos_validation(train_result, test_result,
                                     cscv_s=s_diag, cscv_n=2 * s_diag)

        per_structure[sid] = {
            "faithful": faithful,
            "note": note,
            "n_cycles": n,
            "return_series_provenance": "OBSERVED path P&L / MODEL_RECONSTRUCTED IV; net_pnl_usd/NOTIONAL",
            "median_return": float(np.median(ret)) if n else None,
            "mean_return": float(np.mean(ret)) if n else None,
            "std_return": float(np.std(ret)) if n else None,
            "sharpe_full": sharpe(ret),
            "default_gate_bailey": {
                "config": {"s": 16, "n_min": 100},
                **default_res,
            },
            "diagnostic_underpowered": {
                "config": {"s": s_diag, "n_min": 2 * s_diag},
                "WARNING": f"UNDERPOWERED: n={n} < Bailey n_min=100. Indicative only.",
                "pbo": diag_res.get("pbo_estimate"),
                "dsr": diag_res.get("deflated_sharpe_ratio"),
                "signal_to_noise": diag_res.get("signal_to_noise"),
                "is_insufficient_data": diag_res.get("is_insufficient_data"),
            },
            "chronological_oos": {
                "train_frac": 0.70,
                "train_sharpe": oos.train_sharpe,
                "test_sharpe": oos.test_sharpe,
                "cscv_performance_degradation": oos.performance_degradation,
                "pbo_estimate": oos.pbo_estimate,
                "deflated_sharpe_ratio": oos.deflated_sharpe_ratio,
                "signal_to_noise": oos.signal_to_noise,
                "is_insufficient_data": oos.is_insufficient_data,
                "insufficient_data_reason": oos.insufficient_data_reason,
            },
            "verdict_diagnostic": verdict(diag_res.get("pbo_estimate"),
                                          diag_res.get("deflated_sharpe_ratio")),
        }

    # ── cross-sectional CSCV (canonical Bailey: is the IS-best pick OOS-robust?) ──
    # Align all candidates on their COMMON per-cycle dates (collar/cc/short-put share
    # the 31d schedule; laddered/strike-ladder differ). Use the intersection.
    common = None
    for sid, (cds, _) in matrix_returns.items():
        keyset = set(d.isoformat() for d in cds)
        common = keyset if common is None else (common & keyset)
    common_sorted = sorted(common)
    rows, row_ids = [], []
    for sid, (cds, ret) in matrix_returns.items():
        idx = {d.isoformat(): r for d, r in zip(cds, ret)}
        rows.append([idx[d] for d in common_sorted])
        row_ids.append(sid)
    perf_matrix = np.array(rows, dtype=float)  # (n_strategies, n_common_cycles)
    # canonical CSCV-PBO wants (T_obs x N_configs) -> transpose
    _xsec = _ds.cscv_pbo(perf_matrix.T, S=min(16, max(perf_matrix.shape[1] // 2, 2)))
    xsec_pbo = _xsec.get("pbo")

    out = {
        "meta": {
            "title": "CSCV / PBO / DSR anti-overfitting on recommended overlays",
            "provenance": "DIAGNOSTIC / MODERATE. Reuses strategy/regimes.py Bailey (2015) "
                          "CSCV/PBO/DSR harness on OBSERVED per-cycle P&L from the Phase-1 "
                          "8-year multi-granularity backtest (1d, 31d cadence, r=0, seed=42).",
            "objective": "median P&L / CVaR95 s.t. CVaR95 <= loss cap (locked).",
            "no_leakage": "Cycles chronological; train precedes test; harness splits on ordered series.",
            "full_history_regime_classification": full_regime,
            "n_regime_segments": len(segs),
            "notional_usd": NOTIONAL,
        },
        "objective_selected_mapping": {
            "all_regimes_pick": "COLLAR (frontier: call+2..4% / put-12%, 28AUG26 tenor)",
            "backtest_proxy": "collar_symm10 (symmetric +/-10%)",
            "caveat": "Proxy asymmetry mismatch: put floor -10% vs spec -12%; call cap +10% "
                      "vs spec +2..4%. collar_symm10 verdict is INDICATIVE OOS evidence for "
                      "the objective-selected collar, not an exact reproduction.",
            "per_regime_objective_selected": {
                "risk_neutral": "collar(call+2%/put-12%)",
                "bear_current": "collar(call+2%/put-12%)",
                "stress": "collar(call+2%/put-12%)",
                "bull": "collar(call+4%/put-12%)",
                "sideways": "collar(call+2%/put-12%)",
            },
        },
        "per_structure": per_structure,
        "cross_sectional_cscv": {
            "method": "Bailey CSCV on aligned per-cycle return matrix across all 5 candidates; "
                      "PBO = P(IS-best config underperforms OOS). Common cycles only.",
            "n_common_cycles": len(common_sorted),
            "strategies": row_ids,
            "pbo_selection": xsec_pbo,
            "n_logit_splits": int(len(xsec_logits)),
            "WARNING": "UNDERPOWERED: common-cycle count below Bailey n_min=100.",
        },
        "blockers": {
            "observation_ceiling": "Observed cycle ceiling is 69 (1d, 31d cadence); 46 for laddered/"
                                   "strike-ladder. Below Bailey CSCV n_min=100. Default-gate PBO/DSR "
                                   "return typed insufficient-data; diagnostic config is UNDERPOWERED.",
            "powered_path": "A statistically-powered PBO/DSR requires the GATED full-campaign "
                            "Monte-Carlo cycle set (14.4M/60M paths) or a longer/higher-frequency "
                            "observed cycle series. This diagnostic pass does NOT clear that gate.",
            "objective_pick_asymmetry": "Objective-selected structure is an ASYMMETRIC collar; the "
                                        "backtest engine (single strike_pct_above) can only run the "
                                        "symmetric collar_symm10 proxy. Exact-strike OOS validation "
                                        "is BLOCKED on the multi-strike engine limitation.",
            "dsr_formula_note": "regimes.py DSR = (mean/std)*(1-PBO)*sqrt(n/365), the harness "
                                "convention (not the Lopez de Prado trial-count deflation). Reported "
                                "as the harness emits it; sign (>0) is the survival signal used.",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, default=str)

    print(f"WROTE {OUT}")
    print(f"\nfull-history regime: {full_regime} | segments: {len(segs)} | notional ${NOTIONAL:,.0f}")
    print(f"cross-sectional selection PBO: {xsec_pbo} (n_common={len(common_sorted)})\n")
    print(f"{'structure':30s} {'n':>4s} {'shrp':>6s} {'PBOdiag':>8s} {'DSRdiag':>9s} "
          f"{'degrad':>8s} {'verdict':>10s} {'default-gate':>14s}")
    for sid, r in per_structure.items():
        d = r["diagnostic_underpowered"]
        pbo = d["pbo"]
        dsr = d["dsr"]
        deg = r["chronological_oos"]["cscv_performance_degradation"]
        dg = "insuff" if r["default_gate_bailey"].get("is_insufficient_data") else "computed"
        print(f"{sid:30s} {r['n_cycles']:>4d} {r['sharpe_full']:>6.2f} "
              f"{(pbo if pbo is not None else float('nan')):>8.3f} "
              f"{(dsr if dsr is not None else float('nan')):>9.3f} "
              f"{(deg if deg is not None else float('nan')):>8.3f} "
              f"{r['verdict_diagnostic']:>10s} {dg:>14s}")


if __name__ == "__main__":
    main()
