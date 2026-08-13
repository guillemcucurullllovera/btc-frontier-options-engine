"""EVT / GPD tail estimation for VaR and ES, with a Cornish-Fisher cross-check.

DIAGNOSTIC / SIMULATED only (consumes simulated P&L; MS-26 pending). Standardises
on ES (Expected Shortfall / CVaR) as the coherent tail measure; VaR is reported
alongside for reference.

Methods (all in loss terms: loss = -pnl, a loss is positive):
  * ``empirical_tail``     — order-statistic VaR + mean-beyond ES.
  * ``evt_gpd_tail``       — peaks-over-threshold: fit a Generalised Pareto to the
                             threshold exceedances (McNeil-Frey-Embrechts QRM Ch.5,
                             eqns 5.15-5.16) for VaR/ES in the far tail.
  * ``cornish_fisher_tail``— VaR/ES from the first four moments via the
                             Cornish-Fisher quantile expansion (cross-check).

References: McNeil, Frey & Embrechts, *Quantitative Risk Management* Ch.5.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
from scipy.stats import genpareto, kurtosis, norm, skew


@dataclass(frozen=True)
class TailEstimate:
    method: str            # "empirical" | "evt_gpd" | "cornish_fisher"
    confidence: float      # e.g. 0.975
    var: float             # VaR at *confidence*, loss magnitude (>=0 for a loss)
    es: float              # ES / CVaR at *confidence*, loss magnitude
    xi: float | None = None        # GPD shape (evt only)
    beta: float | None = None      # GPD scale (evt only)
    threshold: float | None = None
    n_exceedances: int | None = None
    provenance: str = "SIMULATED"
    # C9 · M0.3: sampling uncertainty (seeded nonparametric bootstrap; None until computed).
    var_se: float | None = None
    es_se: float | None = None
    var_ci: tuple[float, float] | None = None   # (lo, hi) at ci_level
    es_ci: tuple[float, float] | None = None
    ci_level: float | None = None
    n_boot: int | None = None


def _losses(pnl: np.ndarray) -> np.ndarray:
    return -np.asarray(pnl, dtype=np.float64)


def empirical_tail(pnl: np.ndarray, confidence: float = 0.975) -> TailEstimate:
    """Empirical VaR (quantile) + ES (mean of losses beyond VaR)."""
    losses = _losses(pnl)
    var = float(np.percentile(losses, 100.0 * confidence))
    tail = losses[losses >= var]
    es = float(np.mean(tail)) if tail.size else var
    return TailEstimate("empirical", confidence, var, es)


def evt_gpd_tail(
    pnl: np.ndarray, confidence: float = 0.975, threshold_quantile: float = 0.90,
) -> TailEstimate:
    """Peaks-over-threshold VaR/ES via a Generalised Pareto fit to the loss tail.

    McNeil QRM 5.15-5.16, for shape xi < 1:
      VaR_a = u + (b/xi) * ( ((N/Nu)*(1-a))^(-xi) - 1 )
      ES_a  = VaR_a/(1-xi) + (b - xi*u)/(1-xi)
    Falls back to the empirical tail if too few exceedances to fit.
    """
    losses = _losses(pnl)
    n = losses.size
    u = float(np.percentile(losses, 100.0 * threshold_quantile))
    exceed = losses[losses > u] - u
    nu = exceed.size
    if nu < 50:
        return empirical_tail(pnl, confidence)
    xi, _loc, beta = genpareto.fit(exceed, floc=0.0)
    xi = float(xi)
    beta = float(beta)
    ratio = (n / nu) * (1.0 - confidence)
    if beta <= 0 or ratio <= 0:
        return empirical_tail(pnl, confidence)
    # xi -> 0 is the exponential limit; xi >= 1 is a heavy tail with no finite mean (ES = inf).
    var = u + beta * (-np.log(ratio)) if abs(xi) < 1e-8 else u + (beta / xi) * (ratio ** (-xi) - 1.0)
    es = var / (1.0 - xi) + (beta - xi * u) / (1.0 - xi) if xi < 1.0 else float("inf")
    return TailEstimate("evt_gpd", confidence, float(var), float(es),
                        xi=xi, beta=beta, threshold=u, n_exceedances=nu)


def _cf_z(p: float, s: float, k_excess: float) -> float:
    """Cornish-Fisher adjusted standard quantile at probability p."""
    z = float(norm.ppf(p))
    return (
        z
        + (z * z - 1.0) / 6.0 * s
        + (z ** 3 - 3.0 * z) / 24.0 * k_excess
        - (2.0 * z ** 3 - 5.0 * z) / 36.0 * s * s
    )


def cornish_fisher_tail(
    pnl: np.ndarray, confidence: float = 0.975, es_grid: int = 256,
) -> TailEstimate:
    """VaR/ES from the first four moments via the Cornish-Fisher expansion.

    VaR is the CF quantile of the loss distribution; ES is the mean of the CF
    quantile function over the tail (numerically integrated).
    """
    losses = _losses(pnl)
    mean = float(np.mean(losses))
    std = float(np.std(losses))
    s = float(skew(losses))
    k_excess = float(kurtosis(losses, fisher=True))
    var = mean + std * _cf_z(confidence, s, k_excess)
    ps = np.linspace(confidence, 1.0, es_grid + 1)[:-1]
    ps = np.clip(ps, 1e-6, 1.0 - 1e-9)
    q = np.array([mean + std * _cf_z(float(p), s, k_excess) for p in ps])
    es = float(np.mean(q))
    return TailEstimate("cornish_fisher", confidence, float(var), es)


def compare_tail_methods(
    pnl: np.ndarray, confidence: float = 0.975,
) -> dict[str, TailEstimate]:
    """All three tail estimates for one P&L sample (ES is the headline, coherent, measure)."""
    return {
        "empirical": empirical_tail(pnl, confidence),
        "evt_gpd": evt_gpd_tail(pnl, confidence),
        "cornish_fisher": cornish_fisher_tail(pnl, confidence),
    }


# ── C9 · M0.3: sampling uncertainty (SE/CI) on tail metrics ──────────────────


_ESTIMATORS: dict[str, Callable[[np.ndarray, float], TailEstimate]] = {
    "empirical": empirical_tail,
    "evt_gpd": evt_gpd_tail,
    "cornish_fisher": cornish_fisher_tail,
}


def with_bootstrap_ci(
    pnl: np.ndarray, method: str = "evt_gpd", confidence: float = 0.975,
    n_boot: int = 400, ci_level: float = 0.95, seed: int = 20260730,
) -> TailEstimate:
    """Point estimate + seeded nonparametric-bootstrap SE and percentile CI for VaR & ES.

    A tail metric with no stated uncertainty is not decision-grade (SR 11-7). The bootstrap
    is seeded for reproducibility; EVT refits the GPD on each resample. Returns the full-sample
    estimate enriched with ``var_se``/``es_se``/``var_ci``/``es_ci``.
    """
    if method not in _ESTIMATORS:
        raise ValueError(f"unknown tail method {method!r}; use one of {list(_ESTIMATORS)}")
    estimator = _ESTIMATORS[method]
    base = estimator(np.asarray(pnl, dtype=np.float64), confidence)

    rng = np.random.default_rng(seed)
    n = int(np.asarray(pnl).size)
    vars_: list[float] = []
    ess: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        est = estimator(np.asarray(pnl, dtype=np.float64)[idx], confidence)
        if np.isfinite(est.var) and np.isfinite(est.es):
            vars_.append(est.var)
            ess.append(est.es)
    if len(vars_) < 2:
        return base
    va = np.array(vars_)
    ea = np.array(ess)
    lo_q = 100.0 * (1.0 - ci_level) / 2.0
    hi_q = 100.0 * (1.0 + ci_level) / 2.0
    return replace(
        base,
        var_se=float(np.std(va, ddof=1)),
        es_se=float(np.std(ea, ddof=1)),
        var_ci=(float(np.percentile(va, lo_q)), float(np.percentile(va, hi_q))),
        es_ci=(float(np.percentile(ea, lo_q)), float(np.percentile(ea, hi_q))),
        ci_level=ci_level,
        n_boot=len(vars_),
    )


@dataclass(frozen=True)
class ThresholdPoint:
    threshold_quantile: float
    threshold: float
    n_exceedances: int
    xi: float
    beta: float
    var: float
    es: float
    xi_se: float          # GPD MLE asymptotic SE of xi: (1+xi)/sqrt(Nu)


@dataclass(frozen=True)
class ThresholdStability:
    points: list[ThresholdPoint]
    stable_quantile: float          # recommended threshold quantile (flattest xi region)
    stable_xi: float
    confidence: float

    @property
    def xi_range(self) -> float:
        xs = [p.xi for p in self.points]
        return max(xs) - min(xs) if xs else 0.0


def gpd_threshold_stability(
    pnl: np.ndarray, confidence: float = 0.975,
    quantiles: tuple[float, ...] = (0.80, 0.85, 0.875, 0.90, 0.925, 0.95, 0.975),
    min_exceedances: int = 50,
) -> ThresholdStability:
    """GPD shape-stability diagnostic across candidate thresholds (replaces the hard-coded 90%).

    Fits a GPD at each threshold quantile and reports (xi, beta, VaR, ES, xi_SE). The GPD is
    reliable in the range where the shape xi is stable (McNeil-Frey-Embrechts, QRM §5.3.1). The
    recommended threshold is the interior quantile whose neighbouring xi estimates vary least,
    so the 90% default is justified/overridden by evidence rather than assumed.
    """
    losses = _losses(pnl)
    n = losses.size
    pts: list[ThresholdPoint] = []
    for q in quantiles:
        u = float(np.percentile(losses, 100.0 * q))
        exceed = losses[losses > u] - u
        nu = exceed.size
        if nu < min_exceedances:
            continue
        xi, _loc, beta = genpareto.fit(exceed, floc=0.0)
        xi = float(xi)
        beta = float(beta)
        ratio = (n / nu) * (1.0 - confidence)
        if beta <= 0 or ratio <= 0:
            continue
        var = u + beta * (-np.log(ratio)) if abs(xi) < 1e-8 else u + (beta / xi) * (ratio ** (-xi) - 1.0)
        es = var / (1.0 - xi) + (beta - xi * u) / (1.0 - xi) if xi < 1.0 else float("inf")
        xi_se = (1.0 + xi) / np.sqrt(nu)  # GPD MLE asymptotic SE of the shape parameter
        pts.append(ThresholdPoint(
            threshold_quantile=q, threshold=u, n_exceedances=nu, xi=xi, beta=beta,
            var=float(var), es=float(es), xi_se=float(xi_se),
        ))
    if not pts:
        raise ValueError("no threshold had enough exceedances to fit a GPD")

    # Recommend the interior threshold with the smallest local xi variation (flattest region).
    if len(pts) >= 3:
        best_i = 1
        best_var = float("inf")
        for i in range(1, len(pts) - 1):
            local = abs(pts[i + 1].xi - pts[i].xi) + abs(pts[i].xi - pts[i - 1].xi)
            if local < best_var:
                best_var = local
                best_i = i
        stable = pts[best_i]
    else:
        stable = pts[len(pts) // 2]
    return ThresholdStability(
        points=pts, stable_quantile=stable.threshold_quantile, stable_xi=stable.xi,
        confidence=confidence,
    )
