#!/usr/bin/env python3
"""SVCJ convergence retry on a stationary recent sub-window (C10 · N3.2).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED; deck & canonical main untouched. The Phase-C returns-only
SVCJ MCMC did not converge on the full 8.5yr history (R-hat up to 9.4) — attributed to weak SV
identification + regime NON-STATIONARITY. N3.2 tests the non-stationarity leg: re-run the SAME sampler on
STATIONARY recent sub-windows (2yr / 3yr, ~constant-vol regime). Reports R-hat/ESS honestly; does NOT force
convergence. Writes docs/reports/c10_n3_svcj_retry.json.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vol.svcj_mcmc import svcj_mcmc

_SPOT = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c10_n3_svcj_retry.json"


def _run(y_pct: np.ndarray, label: str) -> dict[str, object]:
    post = svcj_mcmc(y_pct, n_iter=9000, n_chains=3, n_burn=3500, seed=20260731)
    worst = max(post.rhat.items(), key=lambda kv: kv[1])
    n_converged = sum(1 for r in post.rhat.values() if math.isfinite(r) and r < 1.1)
    print(f"[{label}] n={y_pct.size} converged(all R<1.1)={post.converged}  worst R-hat: "
          f"{worst[0]}={worst[1]:.2f}  ({n_converged}/10 params R<1.1)", flush=True)
    return {"label": label, "n_obs": int(y_pct.size), "converged_all": post.converged,
            "worst_rhat_param": worst[0], "worst_rhat": worst[1], "n_params_rhat_lt_1.1": n_converged,
            "rhat": post.rhat, "ess": {k: round(v, 1) for k, v in post.ess.items()},
            "rho_j_mean": post.post_mean["rho_j"], "rho_j_rhat": post.rhat["rho_j"],
            "theta_vol_annual": float(math.sqrt(max(post.post_mean["theta"], 0.0)) / 100 * math.sqrt(365) * 100)}


def main() -> int:
    close = np.array([r["close"] for r in json.loads(_SPOT.read_text())], dtype=np.float64)
    y_pct = 100.0 * np.log(close)
    results = [
        _run(y_pct, "full_2017_2026"),
        _run(y_pct[-1095:], "recent_3yr_stationary"),
        _run(y_pct[-730:], "recent_2yr_stationary"),
    ]
    any_conv = any(r["converged_all"] for r in results)
    verdict = ("CONVERGED on a stationary window" if any_conv else
               "STILL non-convergent even on stationary windows — returns-only SVCJ is weakly identified; "
               "the PF-based parameter-uncertainty (N3.3) is the operational fallback")
    out = {"results": results, "verdict": verdict,
           "note": ("Same sampler as Phase C. If even the stationary windows do not converge, the limit is "
                    "weak SV identification from RETURNS alone, not just non-stationarity -> use the PF "
                    "alternative (N3.3). rho_j (co-jump leverage) is the parameter to watch (best-converged).")}
    _OUT.write_text(json.dumps(out, indent=2))
    print(f"\nVERDICT: {verdict}\nwrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
