#!/usr/bin/env python3
"""Risk re-derivation with parameter uncertainty + campaign MC (C9 · overnight Phase D).

SIMULATED / diagnostic; MS-26-gated; holder-basis; frozen Q anchor untouched. Re-derives the
full-structure risk using the ENRICHED downside jumps (Phase B: full-history realized jumps, mean<0,
eta~1.4) and propagates PARAMETER uncertainty (bootstrap the realized jumps + draw the P-vol from the
estimator spread; the SVCJ posterior did not converge so it is used qualitatively, not sampled) so every
metric carries a [q05,q95] band ON TOP of the within-draw MC SE/CI. Campaign scale (~6M paths),
seed-stable, 0 non-finite. Reports how the VRP moves under the richer (downside) estimates.

Writes docs/reports/c9_risk_uncertainty.json.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from strategy.bates_risk import (
    STRUCTURES,
    ParamDraw,
    PhysicalRiskConfig,
    parameter_uncertainty_band,
    simulate_terminal,
    structure_vrp,
)
from vol.jumps import estimate_jump_params, lee_mykland, log_returns

_HIST = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c9_risk_uncertainty.json"

N_PATHS = 200_000
K_DRAWS = 30                                   # 30 x 200k = 6M paths (campaign scale)
SEED = 20260731


def _enriched_jumps() -> tuple[np.ndarray, float, float, float, float, float]:
    """Detect realized jumps on the full Binance daily history (alpha=0.05); return the jump returns."""
    close = np.array([r["close"] for r in json.loads(_HIST.read_text())], dtype=np.float64)
    r = log_returns(close)
    det = lee_mykland(r, window=20, alpha=0.05)
    jr = r[det.is_jump.astype(bool)]
    jp = estimate_jump_params(r, det, dt_years=1.0 / 365.0)
    return jr, jp.lam_annual, float(np.mean(jr)), float(np.std(jr)), jp.frac_downward, jp.eta_downward


def _param_draws(jr: np.ndarray, lam: float, n_years: float, rng: np.random.Generator) -> list[ParamDraw]:
    """Bootstrap the realized jumps + draw P-vol from the estimator spread (parameter uncertainty)."""
    draws = []
    n = jr.size
    for _ in range(K_DRAWS):
        boot = jr[rng.integers(0, n, size=n)]                 # bootstrap the jump-return sample
        lam_d = float(rng.poisson(max(lam * n_years, 1.0)) / n_years)   # Poisson count uncertainty
        # P-vol estimator spread (realized 0.68 / GARCH 0.77 / UKF 0.52 / PF 0.61 / SVCJ-theta 0.42):
        p_vol = float(np.clip(rng.normal(0.52, 0.10), 0.32, 0.82))
        draws.append(ParamDraw(p_vol=p_vol, jump_lam=lam_d,
                               jump_mean=float(np.mean(boot)), jump_std=float(np.std(boot))))
    return draws


def main() -> int:
    jr, lam, jmean, jstd, frac_down, eta = _enriched_jumps()
    n_years = 3269.0 / 365.0
    print(f"enriched jumps (full history, a=0.05): lam={lam:.2f}/yr mean={jmean:.4f} std={jstd:.4f} "
          f"frac_down={frac_down:.3f} eta={eta:.2f}", flush=True)

    base = PhysicalRiskConfig(n_paths=N_PATHS, n_steps=45, jump_lam=lam, jump_mean=jmean, jump_std=jstd)

    # --- VRP movement: M4.6 symmetric vs enriched downside jumps (same central vol) ----------------
    from dataclasses import replace
    st_sym = simulate_terminal(replace(base, jump_mean=0.0, jump_std=0.088, jump_lam=4.5, p_vol=0.50), "Bates")
    st_enr = simulate_terminal(replace(base, p_vol=0.50), "Bates")
    vrp_move = {}
    for name, sdef in STRUCTURES.items():
        vrp_move[name] = {"symmetric_m46": structure_vrp(sdef, base.S0, st_sym, base.T),
                          "enriched_downside": structure_vrp(sdef, base.S0, st_enr, base.T)}
    _lbsp = vrp_move["long_btc_plus_short_put"]
    print(f"VRP move (LBSP): sym {_lbsp['symmetric_m46']:.0f} -> enriched {_lbsp['enriched_downside']:.0f}",
          flush=True)

    # --- parameter-uncertainty band (campaign scale) ----------------------------------------------
    rng = np.random.default_rng(SEED)
    draws = _param_draws(jr, lam, n_years, rng)
    bands = parameter_uncertainty_band(base, draws, n_boot=80)

    # --- seed-stability check: identical draws -> identical central ------------------------------
    rng2 = np.random.default_rng(SEED)
    draws2 = _param_draws(jr, lam, n_years, rng2)
    bands2 = parameter_uncertainty_band(base, draws2, structures=("collar",), n_boot=80)
    seed_stable = all(abs(a.central - b.central) < 1e-9 for a, b in zip(
        [x for x in bands if x.structure == "collar"], bands2, strict=True))

    all_vals = [b.central for b in bands] + [b.q05 for b in bands] + [b.q95 for b in bands]
    n_finite_ok = all(math.isfinite(v) for v in all_vals)

    out = {
        "enriched_jumps": {"lam_annual": lam, "mean": jmean, "std": jstd,
                           "frac_downward": frac_down, "eta_downward": eta, "n_jumps": int(jr.size)},
        "n_paths_per_draw": N_PATHS, "k_draws": K_DRAWS, "total_paths": N_PATHS * K_DRAWS,
        "vrp_movement_symmetric_vs_enriched": vrp_move,
        "seed_stable": bool(seed_stable), "all_finite": bool(n_finite_ok),
        "bands": [{"structure": b.structure, "metric": b.metric, "central": b.central,
                   "q05": b.q05, "q95": b.q95, "mc_se_repr": b.mc_se_repr} for b in bands],
        "notes": ("Jumps bootstrapped from the full-history realized jumps (downside-loaded); P-vol drawn "
                  "N(0.52,0.10) over the estimator spread; SVCJ posterior non-convergent so used "
                  "qualitatively (rho_J<0 co-jump leverage), not sampled. Band = [q05,q95] across draws "
                  "ON TOP of within-draw MC SE."),
    }
    _OUT.write_text(json.dumps(out, indent=2))

    print(f"\nseed_stable={seed_stable}  all_finite={n_finite_ok}  total_paths={N_PATHS*K_DRAWS:,}")
    print(f"\n{'structure':26} {'metric':10} {'central':>10} {'q05':>10} {'q95':>10}")
    for b in bands:
        if b.metric in ("es975", "cvar95", "vrp_carry"):
            print(f"{b.structure:26} {b.metric:10} {b.central:10.0f} {b.q05:10.0f} {b.q95:10.0f}")
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
