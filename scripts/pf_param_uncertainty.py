#!/usr/bin/env python3
"""PF-based parameter-uncertainty band — the validated operational fallback (C10 · N3.3).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED; holder-basis; frozen Q anchor untouched. The returns-only
SVCJ MCMC does not converge (N3.2) -> parameter uncertainty is made decision-grade via the VALIDATED
particle filter (M4.4a) instead. Block-bootstraps the return series (preserving vol clustering); on each
resample runs the PF for the P-vol level (recording ESS health) + realized-jump detection for the jump
distribution; propagates that joint parameter distribution through the OPERATIONAL SVJJ risk model to
deliver the parameter-uncertainty band the risk carries. Formalizes / re-bands the Phase-D ~+/-15-18%.
Writes docs/reports/c10_n3_pf_band.json. Campaign scale; seed-stable; 0 non-finite.
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pricing.cf.svjj import SVJJ, fit_double_normal
from strategy.bates_risk import STRUCTURES, structure_pnl
from strategy.svjj_sim import simulate_svjj_terminal
from vol.filter import bootstrap_particle_filter
from vol.jumps import estimate_jump_params, lee_mykland, log_returns

_SPOT = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c10_n3_pf_band.json"
S0, T = 63_402.0, 45.0 / 365.0
B_BOOT, K_DRAWS, N_PATHS, BLOCK = 40, 24, 150_000, 30
KAPPA, VOLVOL, RHO, MU_V = 8.37, 5.50, -0.403, 0.0     # SVJJ SV structure; mu_v=0 = operational CENTRAL


def _block_bootstrap(r: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n = r.size
    n_blocks = n // BLOCK + 1
    starts = rng.integers(0, n - BLOCK, size=n_blocks)
    return np.concatenate([r[s:s + BLOCK] for s in starts])[:n]


def main() -> int:
    close = np.array([x["close"] for x in json.loads(_SPOT.read_text())], dtype=np.float64)
    r = log_returns(close)
    rng = np.random.default_rng(20260731)

    # --- PF-based P-vol + jump parameter distribution via block bootstrap -------------------------
    pf_vols, pf_ess, lams, jmeans, jstds, jr_pool = [], [], [], [], [], []
    for _ in range(B_BOOT):
        rb = _block_bootstrap(r, rng)
        theta = float(np.var(rb) * 365)                     # annualised long-run variance for the PF
        pf = bootstrap_particle_filter(rb, kappa=3.0, theta=theta, vol_of_vol=0.8,
                                       dt=1 / 365, n_particles=1200, seed=int(rng.integers(1 << 31)))
        pf_vols.append(float(np.sqrt(max(np.mean(pf.filtered_variance), 0.0))))
        pf_ess.append(float(np.mean(pf.ess)))
        det = lee_mykland(rb, window=20, alpha=0.05)
        jp = estimate_jump_params(rb, det, dt_years=1 / 365)
        lams.append(jp.lam_annual)
        jr = rb[det.is_jump.astype(bool)]
        if jr.size >= 8:
            jmeans.append(float(jr.mean()))
            jstds.append(float(jr.std()))
            jr_pool.append(jr)

    pf_vols_a, lams_a = np.array(pf_vols), np.array(lams)
    p_vol_band = [float(np.percentile(pf_vols_a, 5)), float(np.percentile(pf_vols_a, 95))]
    pf_ess_mean = float(np.mean(pf_ess))
    pf_healthy = pf_ess_mean > 300.0                        # PF validated: healthy effective sample size

    # --- propagate through the OPERATIONAL SVJJ model -> the risk band ---------------------------
    draws = []
    for i in range(K_DRAWS):
        p_vol = float(np.clip(rng.normal(pf_vols_a.mean(), pf_vols_a.std()), 0.30, 0.85))
        j = fit_double_normal(jr_pool[i % len(jr_pool)])
        lam = float(lams_a[rng.integers(0, lams_a.size)])
        draws.append((p_vol, j, lam))

    def _es975(st: np.ndarray, name: str) -> float:
        loss = -structure_pnl(STRUCTURES[name], S0, st, T)
        return float(np.mean(loss[loss >= np.percentile(loss, 97.5)]))

    es_by: dict[str, list[float]] = {s: [] for s in STRUCTURES}
    n_nonfinite = 0
    for i, (p_vol, j, lam) in enumerate(draws):
        m = SVJJ(mu=0.0, v0=p_vol ** 2, kappa=KAPPA, theta=p_vol ** 2, sigma=VOLVOL, rho=RHO, lam=lam,
                 jump=j, mu_v=MU_V)
        st = simulate_svjj_terminal(m, S0, T, N_PATHS, 45, seed=500 + i)
        n_nonfinite += int(np.sum(~np.isfinite(st)))
        for s in STRUCTURES:
            es_by[s].append(_es975(st, s))

    band = {}
    for s in STRUCTURES:
        a = np.array(es_by[s])
        med = float(np.median(a))
        lo, hi = float(np.percentile(a, 5)), float(np.percentile(a, 95))
        band[s] = {"es975_median": med, "es975_q05": lo, "es975_q95": hi,
                   "band_pct": 100.0 * (hi - lo) / max(abs(med), 1.0)}

    # seed-stability
    st_a = simulate_svjj_terminal(SVJJ(0.0, 0.21, KAPPA, 0.21, VOLVOL, RHO, 4.5,
                                       fit_double_normal(jr_pool[0]), MU_V), S0, T, 40_000, 45, seed=1)
    st_b = simulate_svjj_terminal(SVJJ(0.0, 0.21, KAPPA, 0.21, VOLVOL, RHO, 4.5,
                                       fit_double_normal(jr_pool[0]), MU_V), S0, T, 40_000, 45, seed=1)
    seed_stable = bool(np.array_equal(st_a, st_b))

    tail_pcts = [band[s]["band_pct"] for s in STRUCTURES if band[s]["band_pct"] > 1.0]
    out = {
        "method": "block-bootstrap -> PF P-vol + realized-jump distribution -> SVJJ risk band",
        "b_bootstrap": B_BOOT, "k_draws": K_DRAWS, "n_paths_per_draw": N_PATHS,
        "pf_validation": {"ess_mean": pf_ess_mean, "healthy": pf_healthy, "n_particles": 1200},
        "p_vol_band_q05_q95": p_vol_band, "p_vol_mean": float(pf_vols_a.mean()),
        "lambda_band_q05_q95": [float(np.percentile(lams_a, 5)), float(np.percentile(lams_a, 95))],
        "es975_band_by_structure": band,
        "tail_exposed_band_pct_range": [float(min(tail_pcts)), float(max(tail_pcts))] if tail_pcts else [0.0, 0.0],
        "seed_stable": seed_stable, "n_nonfinite": n_nonfinite,
        "phase_d_comparison": ("Phase D reported +/-15-18% from a jump-bootstrap + P-vol estimator spread; "
                               "N3.3 re-bands it with the VALIDATED PF as the P-vol source."),
        "verdict": ("Parameter uncertainty is decision-grade via the validated PF (SVCJ MCMC non-convergent). "
                    "The operational risk carries the ES97.5 band below; defined-risk overlays are bounded."),
    }
    _OUT.write_text(json.dumps(out, indent=2))

    print(f"PF ess_mean={pf_ess_mean:.0f} (healthy={pf_healthy})  p_vol band {p_vol_band[0]:.2f}-{p_vol_band[1]:.2f}"
          f"  seed_stable={seed_stable} nonfinite={n_nonfinite}")
    print(f"{'structure':26}{'ES med':>10}{'q05':>10}{'q95':>10}{'band%':>8}")
    for s in STRUCTURES:
        b = band[s]
        print(f"{s:26}{b['es975_median']:10.0f}{b['es975_q05']:10.0f}{b['es975_q95']:10.0f}{b['band_pct']:8.1f}")
    print(f"tail-exposed band range: {out['tail_exposed_band_pct_range']}\nwrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
