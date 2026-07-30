"""Physical-measure realized-jump estimation from the BTC spot history (C9 · M4.3).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. This resolves the M3 finding that the
Bates *risk-neutral* jumps calibrate degenerate (lambda at bound, sigma_j ~ 0): the tail jump component
is instead identified from the OBSERVED spot return series by nonparametric realized-jump detectors,
which supersede the Q-degenerate jumps for tail risk.

Estimators (all on daily log-returns r_i):
  * ``bipower_variation`` — Barndorff-Nielsen & Shephard (2004): RV, BV, and the jump variation
    JV = max(RV-BV, 0); the relative jump measure RJ = JV/RV. BV is jump-robust, so RV-BV isolates jumps.
  * ``lee_mykland`` — Lee & Mykland (2008): L_i = r_i / sigma_hat_i with a local bipower vol; under no
    jump max|L_i| has a Gumbel law, giving a rigorous per-observation jump test.
  * ``threshold_jumps`` — |r_i| > c * local sigma (Mancini threshold), a simple robust cross-check.

Downward asymmetry (Xia-Li): BTC jumps skew down; eta_hat = mean|down jump| / mean|up jump| (>1 => the
tail is driven by downward jumps). Small-sample caveat: the live snapshot has only ~64 daily bars, so the
real-data jump statistics are noisy and reported as diagnostic; the detectors are validated on SIMULATED
data with known injected jumps (ground truth).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArr = npt.NDArray[np.float64]
BoolArr = npt.NDArray[np.bool_]

# E|Z| for Z~N(0,1); mu_1^-2 = pi/2 is the bipower scaling constant.
_MU1 = math.sqrt(2.0 / math.pi)


@dataclass(frozen=True)
class BipowerResult:
    realized_variance: float          # RV = sum r_i^2
    bipower_variation: float          # BV = (pi/2) sum |r_{i-1}||r_i|  (jump-robust)
    jump_variation: float             # JV = max(RV - BV, 0)
    relative_jump: float              # RJ = JV / RV in [0,1]


def log_returns(prices: FloatArr) -> FloatArr:
    p = np.asarray(prices, dtype=np.float64)
    if p.size < 2 or np.any(p <= 0):
        raise ValueError("log_returns needs >= 2 strictly positive prices")
    return np.diff(np.log(p))


def bipower_variation(returns: FloatArr) -> BipowerResult:
    """RV, BV, jump variation and relative jump measure (Barndorff-Nielsen-Shephard)."""
    r = np.asarray(returns, dtype=np.float64)
    rv = float(np.sum(r * r))
    bv = float((math.pi / 2.0) * np.sum(np.abs(r[:-1]) * np.abs(r[1:]))) if r.size > 1 else 0.0
    jv = max(rv - bv, 0.0)
    return BipowerResult(rv, bv, jv, jv / rv if rv > 0 else 0.0)


@dataclass(frozen=True)
class JumpDetection:
    jump_index: FloatArr              # indices (into returns) flagged as jumps
    is_jump: BoolArr                  # boolean mask over returns
    statistic: FloatArr              # L_i (Lee-Mykland) or |r|/sigma (threshold)
    threshold: float                  # critical value used
    n_jumps: int
    method: str


def _local_bipower_sigma(r: FloatArr, window: int) -> FloatArr:
    """Local instantaneous vol sigma_hat_i from a trailing bipower window (Lee-Mykland)."""
    n = r.size
    sigma = np.empty(n, dtype=np.float64)
    absr = np.abs(r)
    for i in range(n):
        lo = max(1, i - window + 1)
        # Bipower products |r_{j-1}||r_j| for j in [lo, i-1] (jump-robust local variance).
        prod = absr[lo:i] * absr[lo - 1:i - 1] if i - lo >= 1 else np.array([])
        if prod.size >= 1:
            sigma[i] = math.sqrt((1.0 / prod.size) * float(np.sum(prod)))
        else:
            sigma[i] = float(np.std(r[:i + 1])) if i >= 1 else absr[i]
    return np.maximum(sigma, 1e-12)


def lee_mykland(returns: FloatArr, window: int = 16, alpha: float = 0.01) -> JumpDetection:
    """Lee-Mykland (2008) jump test. Flags |L_i| beyond the Gumbel critical value at level alpha."""
    r = np.asarray(returns, dtype=np.float64)
    n = r.size
    sigma = _local_bipower_sigma(r, window)    # -> sigma_true * mu_1 (bipower scaling)
    L = _MU1 * r / sigma              # standardised: L_i ~ N(0,1) under no jump (mu_1*r/sigma_hat)
    # Gumbel centring/scaling for max|L| over n obs.
    c_n = (2.0 * math.log(n)) ** 0.5
    Cn = c_n - (math.log(math.pi) + math.log(math.log(n))) / (2.0 * c_n)
    Sn = 1.0 / c_n
    beta_star = -math.log(-math.log(1.0 - alpha))          # Gumbel quantile
    crit = Cn + beta_star * Sn
    is_jump = np.abs(L) > crit
    return JumpDetection(np.where(is_jump)[0].astype(np.float64), is_jump, L, float(crit),
                         int(np.sum(is_jump)), "lee_mykland")


def threshold_jumps(returns: FloatArr, c: float = 3.0, window: int = 16) -> JumpDetection:
    """Mancini threshold detector: |r_i| > c * local sigma_hat_i (bipower)."""
    r = np.asarray(returns, dtype=np.float64)
    sigma = _local_bipower_sigma(r, window)    # -> sigma_true * mu_1
    stat = _MU1 * np.abs(r) / sigma   # standardised |r_i| / sigma_true (units of sigma)
    is_jump = stat > c
    return JumpDetection(np.where(is_jump)[0].astype(np.float64), is_jump, stat, float(c),
                         int(np.sum(is_jump)), "threshold")


@dataclass(frozen=True)
class JumpParams:
    lam_annual: float                 # jump intensity (jumps per year)
    n_jumps: int
    jump_mean: float                  # mean detected jump log-return
    jump_std: float                   # std of detected jump log-returns
    frac_downward: float              # fraction of jumps that are negative
    eta_downward: float               # mean|down| / mean|up| (Xia-Li; >1 => downside-driven tail)
    dt_years: float
    provenance: str = "P-ESTIMATED"   # physical-measure, from observed returns


def estimate_jump_params(returns: FloatArr, detection: JumpDetection,
                         dt_years: float = 1.0 / 365.0) -> JumpParams:
    """Physical jump parameters from the detected jump returns."""
    r = np.asarray(returns, dtype=np.float64)
    mask = detection.is_jump.astype(bool)
    jr = r[mask]
    n = int(jr.size)
    lam = n / (r.size * dt_years) if r.size else 0.0
    if n == 0:
        return JumpParams(lam, 0, 0.0, 0.0, 0.0, 1.0, dt_years)
    down = jr[jr < 0]
    up = jr[jr > 0]
    mean_down = float(np.mean(np.abs(down))) if down.size else 0.0
    mean_up = float(np.mean(np.abs(up))) if up.size else 0.0
    eta = mean_down / mean_up if mean_up > 0 else (math.inf if mean_down > 0 else 1.0)
    return JumpParams(
        lam_annual=lam, n_jumps=n, jump_mean=float(np.mean(jr)), jump_std=float(np.std(jr)),
        frac_downward=float(down.size / n), eta_downward=eta, dt_years=dt_years,
    )


# ── Q-calibration identifiability guard (resolves the M3 degeneracy) ─────────


@dataclass(frozen=True)
class JumpIdentifiability:
    lam: float
    sigma_j: float
    lam_at_bound: bool                # lambda pinned near its upper bound
    sigma_j_below_floor: bool         # jump size collapsed to ~0
    degenerate: bool                  # unidentified => do NOT use as jump risk
    reason: str


def flag_jump_degeneracy(lam: float, sigma_j: float, lam_ub: float = 20.0,
                         sigma_j_floor: float = 0.02, lam_bound_frac: float = 0.9) -> JumpIdentifiability:
    """Flag an unidentified Bates Q-jump fit (lambda at bound and/or sigma_j collapsed).

    A degenerate jump fit reprices the surface via an over-flexible near-deterministic correction
    rather than genuine jump risk; it must NOT be propagated to the tail (use the P-identified jumps).
    """
    at_bound = lam >= lam_bound_frac * lam_ub
    below_floor = sigma_j < sigma_j_floor
    degen = at_bound or below_floor
    reasons = []
    if at_bound:
        reasons.append(f"lambda={lam:.1f} >= {lam_bound_frac:.0%} of bound {lam_ub}")
    if below_floor:
        reasons.append(f"sigma_j={sigma_j:.4f} < floor {sigma_j_floor}")
    return JumpIdentifiability(
        lam=lam, sigma_j=sigma_j, lam_at_bound=at_bound, sigma_j_below_floor=below_floor,
        degenerate=degen, reason="; ".join(reasons) if reasons else "identified",
    )
