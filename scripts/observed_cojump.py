#!/usr/bin/env python3
"""Observed co-jump identification -> free mu_v upgrade (C10 · N3.6).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED from OBSERVED data; deck & canonical main untouched. The
SVJJ vol-co-jump magnitude mu_v was the least-identified parameter (Phase C MCMC non-convergent -> N1
carried it as a pure sensitivity band). N3.6 identifies it DIRECTLY from free observed data: on days with a
Lee-Mykland spot jump (2021-2026 DVOL overlap), measure the contemporaneous DVOL move -> the empirical
(price-jump, vol-jump) joint distribution, an observed co-jump correlation rho_J, and a mu_v estimate.

IMPLIED-vs-INSTANTANEOUS CAVEAT (stated, not hidden): DVOL is a 30-DAY ATM IMPLIED vol; the SVJJ xi^v is an
INSTANTANEOUS variance jump. The 30d-implied response is a mean-reversion-DAMPED, risk-neutral proxy for the
instantaneous physical jump, not an identity. mu_v is therefore reported as a RANGE (damped-as-is lower
bound -> un-damped upper bound over a plausible vol mean-reversion) with the caveat explicit.

Writes docs/reports/c10_n3_6_cojump.json.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pricing.cf.svjj import SVJJ, fit_double_normal
from strategy.bates_risk import STRUCTURES, structure_pnl
from strategy.svjj_sim import simulate_svjj_terminal
from vol.jumps import lee_mykland, log_returns

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DVOL = _ROOT / "market_snapshots" / "deribit_dvol_history" / "dvol_daily.json"
_SPOT = _ROOT / "market_snapshots" / "binance_history" / "1d" / "bars.json"
_OUT = _ROOT / "docs" / "reports" / "c10_n3_6_cojump.json"
S0, T = 63_402.0, 45.0 / 365.0
CENTRAL_VOL, KAPPA, VOLVOL, RHO = 0.46, 8.37, 5.50, -0.403


def main() -> int:
    dvol = {x["date"]: float(x["dvol"]) for x in json.loads(_DVOL.read_text())}
    bars = json.loads(_SPOT.read_text())
    dates = [b["timestamp"][:10] for b in bars]
    close = np.array([b["close"] for b in bars], dtype=np.float64)
    r = log_returns(close)
    rdates = dates[1:]
    dv_t = np.array([dvol.get(d, np.nan) for d in rdates])                 # DVOL at day t
    dv_prev = np.array([dvol.get(dates[i], np.nan) for i in range(len(rdates))])  # DVOL at t-1
    ddvol = dv_t - dv_prev
    dvar = dv_t ** 2 - dv_prev ** 2                                        # implied-variance change

    det = lee_mykland(r, window=20, alpha=0.05)
    jd = det.is_jump & ~np.isnan(ddvol)
    sj, dd, dvar_j = r[jd], ddvol[jd], dvar[jd]
    n = int(jd.sum())

    rho_j = float(np.corrcoef(sj, dd)[0, 1])
    rho_j_se = float((1 - rho_j ** 2) / math.sqrt(max(n - 2, 1)))          # approx SE of a correlation
    down, up = sj < 0, sj > 0
    dvar_mean = float(np.mean(dvar_j))                                     # mean implied-variance jump

    # implied -> instantaneous mapping: 30d-forward-average of a decaying instantaneous jump captures a
    # fraction D(kappa,T)=(1-e^{-kappaT})/(kappaT). Un-damp over a plausible vol mean-reversion range.
    Tv = 30.0 / 365.0
    def _D(k: float) -> float:
        return (1 - math.exp(-k * Tv)) / (k * Tv)
    D_lo, D_hi = _D(40.0), _D(10.0)                                        # fast (kappa=40) .. slow (kappa=10)
    muv_lower = max(dvar_mean, 0.0)                                        # damped-as-is (lower bound)
    muv_upper = max(dvar_mean / D_lo, 0.0)                                 # most un-damped (upper)
    muv_central = max(dvar_mean / D_hi, 0.0)                               # mild un-damping (central)

    # --- re-run SVJJ risk across mu_v in {0, lower, central, upper} at central vol ---------------
    j_asym = fit_double_normal(r[det.is_jump.astype(bool)])
    lam = n / (r.size / 365.0)                                             # annual co-jump intensity (overlap-consistent)

    def _es(muv: float, seed: int) -> dict[str, float]:
        m = SVJJ(mu=0.0, v0=CENTRAL_VOL ** 2, kappa=KAPPA, theta=CENTRAL_VOL ** 2, sigma=VOLVOL, rho=RHO,
                 lam=4.47, jump=j_asym, mu_v=muv)
        st = simulate_svjj_terminal(m, S0, T, 300_000, 45, seed=seed)
        return {s: float(np.mean((-structure_pnl(STRUCTURES[s], S0, st, T))[
            (-structure_pnl(STRUCTURES[s], S0, st, T)) >= np.percentile(-structure_pnl(STRUCTURES[s], S0, st, T), 97.5)]))
            for s in STRUCTURES}

    es_mu0 = _es(0.0, 11)
    es_lower = _es(muv_lower, 12)
    es_central = _es(muv_central, 13)
    es_upper = _es(muv_upper, 14)
    firm = {s: {"es_no_cojump": es_mu0[s], "es_observed_central": es_central[s],
                "widen_central_pct": 100 * (es_central[s] / es_mu0[s] - 1),
                "widen_lower_pct": 100 * (es_lower[s] / es_mu0[s] - 1),
                "widen_upper_pct": 100 * (es_upper[s] / es_mu0[s] - 1)} for s in STRUCTURES}

    decision_grade = abs(rho_j) > 0.4 and abs(rho_j) > 2 * rho_j_se       # clean, significant co-jump sign
    out = {
        "overlap_days": int((~np.isnan(ddvol)).sum()), "n_spot_jump_days": n,
        "rho_j_observed": rho_j, "rho_j_se": rho_j_se,
        "dvol_change_on_jump_days_mean": float(np.mean(dd)),
        "dvol_change_down_jumps_mean": float(np.mean(dd[down])) if down.any() else None,
        "dvol_change_up_jumps_mean": float(np.mean(dd[up])) if up.any() else None,
        "n_down": int(down.sum()), "n_up": int(up.sum()),
        "implied_variance_jump_mean": dvar_mean,
        "muv_range_lower_central_upper": [muv_lower, muv_central, muv_upper],
        "muv_n1_assumed": 0.10, "damping_factor_range": [D_lo, D_hi],
        "co_jump_intensity_annual": float(lam),
        "risk_band_firming": firm,
        "decision_grade": bool(decision_grade),
        "implied_vs_instantaneous_caveat": ("DVOL is 30d ATM IMPLIED (risk-neutral); xi^v is INSTANTANEOUS "
                                            "variance (physical). The mapping un-damps the 30d-averaged implied "
                                            "response over a plausible vol mean-reversion (kappa 10-40/yr); it is "
                                            "a PROXY, not an identity. rho_J (sign/strength) is directly observed "
                                            "and decision-grade; the mu_v MAGNITUDE carries the mapping range."),
    }
    _OUT.write_text(json.dumps(out, indent=2))

    print(f"n_jump_days={n}  rho_J={rho_j:.3f} (SE {rho_j_se:.3f})  decision_grade={decision_grade}")
    print(f"DVOL chg jump-days mean +{np.mean(dd):.3f} (down +{np.mean(dd[down]):.3f} / up +{np.mean(dd[up]):.3f})")
    print(f"implied-var jump mean {dvar_mean:.3f} -> mu_v range [{muv_lower:.2f}, {muv_central:.2f}, {muv_upper:.2f}] "
          f"(N1 assumed 0.10)")
    print(f"\n{'structure':26}{'ES muv0':>10}{'ES obs':>10}{'central%':>9}{'lower%':>8}{'upper%':>8}")
    for s in STRUCTURES:
        f = firm[s]
        print(f"{s:26}{f['es_no_cojump']:10.0f}{f['es_observed_central']:10.0f}{f['widen_central_pct']:9.1f}"
              f"{f['widen_lower_pct']:8.1f}{f['widen_upper_pct']:8.1f}")
    print(f"wrote {_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
