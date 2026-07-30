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

from dataclasses import dataclass

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
