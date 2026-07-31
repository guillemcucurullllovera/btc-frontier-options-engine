#!/usr/bin/env python3
"""Estimate the SVCJ model on the full Binance BTC daily history via MCMC (C9 · Phase C / M4.4b).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED from OBSERVED returns; frozen Q anchor untouched.
Runs the Eraker-Johannes-Polson SVCJ Gibbs/Metropolis sampler (vol/svcj_mcmc.py) on the 2017-2026 daily
log-returns and writes docs/reports/c9_svcj_mcmc.json: posterior means/quantiles, Gelman-Rubin R-hat,
ESS, acceptance rates, posterior-predictive return-residual checks, and the posterior jump/vol summary.
Convergence is reported honestly (some SV/jump params are weakly identified from returns alone).
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vol.svcj_mcmc import svcj_mcmc

_HIST = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c9_svcj_mcmc.json"


def main() -> int:
    rows = json.loads(_HIST.read_text())
    close = np.array([r["close"] for r in rows], dtype=np.float64)
    y_pct = 100.0 * np.log(close)                          # percent log-price levels (EJP scale)
    print(f"BTC daily: {y_pct.size} obs, realized daily vol%={np.std(np.diff(y_pct)):.2f}", flush=True)

    post = svcj_mcmc(y_pct, n_iter=9000, n_chains=3, n_burn=3500, seed=20260731)
    print(f"MCMC done. accept_v={post.accept_v:.2f} accept_rho={post.accept_rho:.2f} "
          f"converged(all Rhat<1.1)={post.converged}", flush=True)

    # posterior-predictive: standardised return residuals should be ~N(0,1)
    dy = np.diff(y_pct)
    v_daily = (post.v_filtered / math.sqrt(365.0) * 100.0) ** 2      # back to percent^2 daily variance
    resid = (dy - post.post_mean["mu"]) / np.sqrt(np.maximum(v_daily[:-1], 1e-8))
    ppc = {"resid_mean": float(np.mean(resid)), "resid_std": float(np.std(resid)),
           "resid_kurtosis": float(np.mean(((resid - resid.mean()) / resid.std()) ** 4)),
           "frac_days_jump_prob_gt_0.5": float(np.mean(post.jump_prob > 0.5))}

    # annualise the jump-return params for readability (mu_y is percent; keep as-is + note)
    summary = {
        "n_obs": int(y_pct.size), "n_iter": post.n_iter, "n_burn": post.n_burn, "n_chains": 3,
        "accept_v": post.accept_v, "accept_rho": post.accept_rho, "converged_all_rhat_lt_1.1": post.converged,
        "post_mean": post.post_mean, "post_sd": post.post_sd,
        "post_q05": post.post_q05, "post_q95": post.post_q95,
        "rhat": post.rhat, "ess": post.ess,
        "theta_vol_annual": float(math.sqrt(max(post.post_mean["theta"], 0.0)) / 100.0 * math.sqrt(365.0) * 100.0),
        "v_filtered_mean_annual": float(np.mean(post.v_filtered)),
        "mean_jump_prob": float(np.mean(post.jump_prob)),
        "lambda_annual": float(post.post_mean["lambda"] * 365.0),
        "posterior_predictive": ppc,
        "notes": ("y in percent log-returns (EJP scale); mu_y/sigma_y/mu_v in percent/percent^2. "
                  "theta_vol_annual = sqrt(theta[%^2]) * sqrt(365). Convergence: SV params (kappa, theta, "
                  "sigma_v) and vol-jump size are weakly identified from returns-only (EJP) -> higher R-hat."),
    }
    _OUT.write_text(json.dumps(summary, indent=2))
    print("\nparam      post_mean      q05      q95    Rhat     ESS", flush=True)
    for name in post.param_names:
        print(f"{name:9} {post.post_mean[name]:9.3f} {post.post_q05[name]:8.3f} {post.post_q95[name]:8.3f} "
              f"{post.rhat[name]:7.2f} {post.ess[name]:7.0f}", flush=True)
    print(f"\ntheta_vol_annual={summary['theta_vol_annual']:.2f}  lambda_annual={summary['lambda_annual']:.1f}/yr  "
          f"vol_path_annual_mean={summary['v_filtered_mean_annual']:.2f}", flush=True)
    print(f"PPC resid: mean={ppc['resid_mean']:.3f} std={ppc['resid_std']:.3f} kurt={ppc['resid_kurtosis']:.2f}", flush=True)
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
