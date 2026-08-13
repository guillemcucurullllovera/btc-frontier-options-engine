#!/usr/bin/env python3
"""Re-run the M4 physical-measure estimation on the rich Binance history (C9 · overnight Phase B).

The honest high-frequency jump revisit: estimate the physical jump/vol dynamics at DAILY (full 2017-2026
history), HOURLY, and 1-MINUTE frequencies, and report whether the downward jump asymmetry reappears at
high frequency vs the roughly-symmetric daily picture (M4.6, 2yr). Provenance P-ESTIMATED from OBSERVED
Binance BTCUSDT returns (basis caveat: an excellent BTC/USD *returns* proxy; frozen Q anchor untouched).

Writes docs/reports/c9_binance_reestimation.json. Intraday λ is inflated by microstructure (reported and
flagged); the economically meaningful signal is the jump-size ASYMMETRY (frac_downward, η), not raw λ.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vol.filter import bootstrap_particle_filter, sv_mle, unscented_kalman_sv
from vol.garch import GarchEstimator
from vol.jumps import (
    bipower_variation,
    estimate_jump_params,
    lee_mykland,
    log_returns,
    threshold_jumps,
)

_HIST = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c9_binance_reestimation.json"
_DT = {"1d": 1.0 / 365.0, "1h": 1.0 / (365.0 * 24.0), "1m": 1.0 / (365.0 * 24.0 * 60.0)}
_BARS_PER_YEAR = {"1d": 365.0, "1h": 365.0 * 24.0, "1m": 365.0 * 24.0 * 60.0}
_WINDOW = {"1d": 20, "1h": 48, "1m": 240}      # local-bipower vol window (bars) per frequency


def _closes(interval: str) -> np.ndarray:
    rows = json.loads((_HIST / interval / "bars.json").read_text())
    return np.array([x["close"] for x in rows], dtype=np.float64)


def _jumps(r: np.ndarray, interval: str) -> dict[str, object]:
    dt = _DT[interval]
    lm = lee_mykland(r, window=_WINDOW[interval], alpha=0.01)
    jp = estimate_jump_params(r, lm, dt_years=dt)
    th = threshold_jumps(r, c=4.0, window=_WINDOW[interval])
    jp_th = estimate_jump_params(r, th, dt_years=dt)
    bpv = bipower_variation(r)
    rv = float(np.sum(r ** 2))
    return {
        "n_obs": int(r.size),
        "realized_vol_annual": float(np.std(r) * math.sqrt(_BARS_PER_YEAR[interval])),
        "lm_lambda_annual": jp.lam_annual, "lm_n_jumps": jp.n_jumps,
        "lm_jump_mean": jp.jump_mean, "lm_jump_std": jp.jump_std,
        "lm_frac_downward": jp.frac_downward, "lm_eta_downward": jp.eta_downward,
        "thr_lambda_annual": jp_th.lam_annual, "thr_n_jumps": jp_th.n_jumps,
        "thr_frac_downward": jp_th.frac_downward, "thr_eta_downward": jp_th.eta_downward,
        "jump_variation_share": float(bpv.jump_variation / rv) if rv > 0 else 0.0,
    }


def _asymmetry(r: np.ndarray, alpha: float, window: int = 20) -> dict[str, float]:
    """Lee-Mykland jump asymmetry at a given detection level (daily, dt=1/365)."""
    jp = estimate_jump_params(r, lee_mykland(r, window=window, alpha=alpha), dt_years=1.0 / 365.0)
    return {"alpha": alpha, "n_jumps": float(jp.n_jumps), "lambda_annual": jp.lam_annual,
            "frac_downward": jp.frac_downward, "eta_downward": jp.eta_downward}


def main() -> int:
    result: dict[str, object] = {}

    # ---- DAILY: full estimation (jumps + GARCH + UKF/PF + Q-vs-P) --------------------------------
    rd = log_returns(_closes("1d"))
    print(f"[1d] n_returns={rd.size}", flush=True)

    # M4.6-comparability: SAME detector (alpha=0.05, window=20) on the full history vs the last 2yr.
    # Isolates SAMPLE LENGTH (not frequency) as the source of the downside asymmetry.
    daily_cmp = {"full_history_alpha05": _asymmetry(rd, 0.05),
                 "last_2yr_alpha05": _asymmetry(rd[-730:], 0.05)}
    print(f"[1d cmp] full η={daily_cmp['full_history_alpha05']['eta_downward']:.2f} "
          f"(n={daily_cmp['full_history_alpha05']['n_jumps']:.0f})  vs  "
          f"last2yr η={daily_cmp['last_2yr_alpha05']['eta_downward']:.2f} "
          f"(n={daily_cmp['last_2yr_alpha05']['n_jumps']:.0f})", flush=True)
    daily = _jumps(rd, "1d")
    g = GarchEstimator(rd).fit()
    # GarchParams.unconditional_vol is PER-BAR (daily here); annualise by sqrt(bars/year).
    daily_uncond_annual = g.params.unconditional_vol * math.sqrt(_BARS_PER_YEAR["1d"])
    daily["garch"] = {
        "alpha": g.params.alpha, "beta": g.params.beta, "omega": g.params.omega,
        "persistence": g.params.persistence,
        "uncond_vol_perbar": g.params.unconditional_vol,
        "uncond_vol_annual": daily_uncond_annual,
        "se_alpha_fisher": g.param_std_errors_fisher.get("alpha", float("nan")),
        "se_beta_fisher": g.param_std_errors_fisher.get("beta", float("nan")),
        "convergence": g.convergence,
    }
    ukf = unscented_kalman_sv(rd, kappa=3.0, theta=0.25, vol_of_vol=0.8, dt=_DT["1d"])
    daily["ukf_vol_annual"] = float(np.sqrt(max(np.mean(ukf.filtered_variance), 0.0)))
    svm = sv_mle(rd, dt=_DT["1d"])
    daily["sv_mle"] = {"kappa": svm.kappa, "theta": svm.theta, "vol_of_vol": svm.vol_of_vol,
                       "theta_vol_annual": float(math.sqrt(max(svm.theta, 0.0)))}
    pf = bootstrap_particle_filter(rd, kappa=svm.kappa, theta=svm.theta, vol_of_vol=svm.vol_of_vol,
                                   dt=_DT["1d"], n_particles=1500)
    daily["pf_vol_annual"] = float(np.sqrt(max(np.mean(pf.filtered_variance), 0.0)))
    daily["pf_ess_mean"] = float(np.mean(pf.ess))
    q_vol = 0.50
    daily["q_vs_p"] = {"q_vol": q_vol, "p_vol_garch_uncond_annual": daily_uncond_annual,
                       "ratio_q_over_p": q_vol / daily_uncond_annual if daily_uncond_annual > 0 else None,
                       "note": "Q=0.50 (M2/M3 frozen anchor); P annualised full-history GARCH unconditional."}
    daily["m46_comparison"] = daily_cmp
    result["1d"] = daily
    print(f"[1d] λ={daily['lm_lambda_annual']:.1f}/yr frac_down={daily['lm_frac_downward']:.2f} "
          f"η={daily['lm_eta_downward']:.2f} jumpvar={daily['jump_variation_share']:.3f} "
          f"GARCH uncondvol_annual={daily_uncond_annual:.2f}", flush=True)

    # ---- HOURLY: jumps + GARCH (intraday conditional vol) ----------------------------------------
    rh = log_returns(_closes("1h"))
    print(f"[1h] n_returns={rh.size}", flush=True)
    hourly = _jumps(rh, "1h")
    gh = GarchEstimator(rh).fit()
    hourly["garch"] = {"alpha": gh.params.alpha, "beta": gh.params.beta,
                       "persistence": gh.params.persistence,
                       "uncond_vol_perbar": gh.params.unconditional_vol,
                       "uncond_vol_annual": gh.params.unconditional_vol * math.sqrt(_BARS_PER_YEAR["1h"]),
                       "convergence": gh.convergence}
    result["1h"] = hourly
    print(f"[1h] λ={hourly['lm_lambda_annual']:.0f}/yr frac_down={hourly['lm_frac_downward']:.3f} "
          f"η={hourly['lm_eta_downward']:.2f} jumpvar={hourly['jump_variation_share']:.3f}", flush=True)

    # ---- 1-MINUTE: jumps only (asymmetry question; microstructure-inflated λ flagged) ------------
    rm = log_returns(_closes("1m"))
    print(f"[1m] n_returns={rm.size}", flush=True)
    minute = _jumps(rm, "1m")
    minute["microstructure_caveat"] = ("1m λ is inflated by microstructure noise (the test's FP rate x "
                                       "~130k obs); the meaningful signal is the jump-size asymmetry.")
    result["1m"] = minute
    print(f"[1m] λ={minute['lm_lambda_annual']:.0f}/yr frac_down={minute['lm_frac_downward']:.3f} "
          f"η={minute['lm_eta_downward']:.2f} jumpvar={minute['jump_variation_share']:.3f}", flush=True)

    _OUT.write_text(json.dumps(result, indent=2))
    print(f"\nwrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
