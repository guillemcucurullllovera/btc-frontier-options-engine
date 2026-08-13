#!/usr/bin/env python3
"""Decision-grade SVJJ tail risk (SE/CI) for the mandate covered-call overlay — ENG3 · A5.

Wires the SVJJ (price + vol co-jump) tail model into the Monte Carlo for the LOCKED mandate structure
(30,000 BTC held; +6/10/14/18% laddered covered call at 40% coverage) and reports VaR/ES/CVaR with
bootstrap SE and 95% CI — the decision-grade tail panel the symmetric/GBM block cannot give. It also
runs a **matched-variance GBM** baseline (same S0, T, mean and terminal variance, NO jumps) so the tail
gap SVJJ - GBM is attributable purely to the jump-driven skew/kurtosis, and flags for each metric
whether that gap is STATISTICALLY RESOLVED given the Monte-Carlo error (|z| >= 1.96).

SIMULATED / diagnostic; physical-measure SVJJ; option premiums marked at the frozen Q_BATES anchor.
Canonical main untouched. Writes docs/reports/svjj_mc_tails.json.
Run: /home/francisco/btc/btc_engine_frontier/.venv/bin/python scripts/run_svjj_mc_tails.py
"""

from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import asdict

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pricing.cf.svjj import SVJJ, DoubleNormalJump, fit_double_normal
from risk.svjj_tails import compare_tails, tail_panel
from strategy.bates_risk import StructureDef, StructureLeg, structure_pnl
from strategy.svjj_sim import simulate_svjj_terminal
from vol.jumps import estimate_jump_params, lee_mykland, log_returns

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HIST = _ROOT / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_OUT = _ROOT / "docs" / "reports" / "svjj_mc_tails.json"

# Mandate (locked): 30,000 BTC held; +6/10/14/18% ladder; 40% coverage (12,000 covered).
S0 = 63_789.0                 # OBSERVED index, 2026-07-31 archive
BLOCK_BTC = 30_000.0
T = 30.0 / 365.0              # ~1-month covered-call cycle (deck tenor)
COVERAGE = 0.40
LADDER_PCTS = (6.0, 10.0, 14.0, 18.0)
N_PATHS, N_STEPS = 400_000, 30
LEVELS = (0.95, 0.99)
# Physical central scenario (recent-2yr matched, per c9_svjj_risk campaign): vol 0.46, drift 0.
CENTRAL_VOL, DRIFT = 0.46, 0.0
KAPPA, VOLVOL, RHO, MU_V = 8.37, 5.50, -0.403, 0.10     # Q SV structure + calibrated vol co-jump

_MANDATE = StructureDef("covered_ladder_40pct", True, tuple(
    StructureLeg("call", "SHORT", pct, 0.25) for pct in LADDER_PCTS))
_HOLD = StructureDef("unhedged_hold", True, ())


def _svjj_model(vol: float, drift: float, jump: DoubleNormalJump, lam: float, mu_v: float) -> SVJJ:
    v = vol * vol
    return SVJJ(mu=drift, v0=v, kappa=KAPPA, theta=v, sigma=VOLVOL, rho=RHO, lam=lam, jump=jump, mu_v=mu_v)


def _gbm_terminal_matched(target_logret: np.ndarray, n_paths: int, seed: int) -> np.ndarray:
    """GBM terminal spot matching the SVJJ terminal log-return MEAN and VARIANCE (no jumps).

    Isolates the higher-moment (skew/kurtosis) tail contribution: same first two moments, so any
    residual VaR/ES gap is the jump-driven tail alone. Antithetic, seeded.
    """
    m = float(np.mean(target_logret))
    sd = float(np.std(target_logret))
    rng = np.random.default_rng(seed)
    half = (n_paths + 1) // 2
    z = rng.normal(size=half)
    z = np.concatenate([z, -z])[:n_paths]          # antithetic
    return S0 * np.exp(m + sd * z)


def main() -> int:
    close = np.array([r["close"] for r in json.loads(_HIST.read_text())], dtype=np.float64)
    r = log_returns(close)
    det = lee_mykland(r, window=20, alpha=0.05)
    lam = float(estimate_jump_params(r, det, dt_years=1 / 365).lam_annual)
    jump = fit_double_normal(r[det.is_jump.astype(bool)])

    # SVJJ terminal (physical central scenario) — the tail-sensitive engine replacing GBM.
    st_svjj = simulate_svjj_terminal(_svjj_model(CENTRAL_VOL, DRIFT, jump, lam, MU_V),
                                     S0, T, N_PATHS, N_STEPS, seed=100)
    st_svjj2 = simulate_svjj_terminal(_svjj_model(CENTRAL_VOL, DRIFT, jump, lam, MU_V),
                                      S0, T, N_PATHS, N_STEPS, seed=100)
    seed_stable = bool(np.array_equal(st_svjj, st_svjj2))
    n_nonfinite = int(np.sum(~np.isfinite(st_svjj)))
    # matched-variance GBM baseline (independent seed for the gap-SE combine).
    st_gbm = _gbm_terminal_matched(np.log(st_svjj / S0), N_PATHS, seed=777)

    results: dict[str, object] = {}
    gaps_out: dict[str, object] = {}
    for sdef in (_HOLD, _MANDATE):
        pnl_svjj = structure_pnl(sdef, S0, st_svjj, T, coverage=COVERAGE) * BLOCK_BTC
        pnl_gbm = structure_pnl(sdef, S0, st_gbm, T, coverage=COVERAGE) * BLOCK_BTC
        panel_svjj = tail_panel(pnl_svjj, LEVELS, seed=20260813)
        panel_gbm = tail_panel(pnl_gbm, LEVELS, seed=20260814)
        gaps = compare_tails(panel_svjj, panel_gbm)
        results[sdef.name] = {
            "mean_pnl_svjj": float(np.mean(pnl_svjj)),
            "prob_loss_svjj": float(np.mean(pnl_svjj < 0.0)),
            "svjj_tail": [asdict(t) for t in panel_svjj],
            "gbm_matched_tail": [asdict(t) for t in panel_gbm],
        }
        gaps_out[sdef.name] = [asdict(g) for g in gaps]

    out = {
        "provenance": "SIMULATED (physical-measure SVJJ; option premiums frozen Q_BATES anchor)",
        "measure_note": ("Physical (P) tail. The RND crash-prob module gives the Q (market-implied) "
                         "leg; Q_crash - P_crash = the tail-risk premium the overlay harvests. "
                         "P and Q live in SEPARATE columns and are NEVER blended."),
        "config": {"S0": S0, "block_btc": BLOCK_BTC, "T_days": T * 365.0, "coverage": COVERAGE,
                   "ladder_pcts": list(LADDER_PCTS), "central_vol": CENTRAL_VOL, "drift": DRIFT,
                   "n_paths": N_PATHS, "n_steps": N_STEPS, "levels": list(LEVELS)},
        "jump_calibration": {"lambda_annual": lam, "p_up": jump.p_up, "mu_up": jump.mu_up,
                             "mu_dn": jump.mu_dn, "sig_up": jump.sig_up, "sig_dn": jump.sig_dn,
                             "mu_v_volcojump": MU_V},
        "seed_stable": seed_stable, "n_nonfinite": n_nonfinite,
        "structures": results, "svjj_minus_gbm_gaps": gaps_out,
        "baseline_note": ("GBM baseline is MATCHED to the SVJJ terminal mean+variance (no jumps), so a "
                          "resolved VaR/ES gap is the jump-driven skew/kurtosis tail alone — the tail a "
                          "naive Gaussian/GBM model misses."),
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(out, indent=2))

    print(f"SVJJ MC tails  S0=${S0:,.0f}  T={T*365:.0f}d  block={BLOCK_BTC:,.0f} BTC  "
          f"cov={COVERAGE:.0%}  n_paths={N_PATHS:,}  seed_stable={seed_stable}  nonfinite={n_nonfinite}")
    print(f"jumps: lambda={lam:.2f}/yr  p_up={jump.p_up:.2f}  mu_dn={jump.mu_dn:.3f}  mu_v={MU_V}")
    for name in (_HOLD.name, _MANDATE.name):
        res = results[name]                                        # type: ignore[assignment]
        print(f"\n{name}:  mean P&L ${res['mean_pnl_svjj']/1e6:,.1f}M  "        # type: ignore[index]
              f"P(loss)={res['prob_loss_svjj']*100:.1f}%")          # type: ignore[index]
        print(f"  {'metric':>7}{'lvl':>6}{'SVJJ ($M)':>12}{'SE':>7}{'95% CI ($M)':>22}"
              f"{'GBM ($M)':>11}{'gap z':>8}{'resolved':>10}")
        gmap = {(g['metric'], g['level']): g for g in gaps_out[name]}   # type: ignore[index]
        for t in res['svjj_tail']:                                  # type: ignore[index]
            g = gmap[(t['metric'], t['level'])]
            print(f"  {t['metric']:>7}{t['level']:>6.2f}{t['estimate']/1e6:>12.1f}{t['se']/1e6:>7.2f}"
                  f"   [{t['ci_lo']/1e6:>8.1f},{t['ci_hi']/1e6:>8.1f}]"
                  f"{g['b_estimate']/1e6:>11.1f}{g['gap_z']:>8.1f}{'YES' if g['resolved'] else 'no':>10}")
    print(f"\nwrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
