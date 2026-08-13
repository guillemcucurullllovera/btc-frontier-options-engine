"""EVT tail hardening — VaR back-testing + declustering + xi-monitor (C9 · M5.2).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Hardens the EVT/CVaR tail metrics:

  * ``kupiec_pof`` — Kupiec (1995) proportion-of-failures unconditional-coverage LR test (chi^2_1):
    is the realised VaR-exceedance rate consistent with 1 - confidence?
  * ``christoffersen_cc`` — Christoffersen (1998) conditional-coverage LR test (chi^2_2) = POF +
    an independence test (exceedances must not CLUSTER).
  * ``extremal_index`` / ``decluster`` — crypto jumps and vol cluster, so raw peaks-over-threshold
    over-counts; the Ferro-Segers (2003) intervals extremal index theta and runs-declustering give
    the independent cluster maxima the GPD assumes.
  * ``xi_monitor`` — flag a GPD shape xi >= 0.5 (infinite variance) / >= 1 (infinite mean) and
    threshold instability (from the M0.3 threshold-stability diagnostic).

References: Kupiec (1995); Christoffersen (1998); Ferro & Segers (2003); McNeil-Frey-Embrechts QRM Ch.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import numpy.typing as npt
from scipy.stats import chi2

from risk.tail import ThresholdStability

FloatArr = npt.NDArray[np.float64]
BoolArr = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class CoverageTest:
    n: int
    n_violations: int
    expected_rate: float          # 1 - confidence
    observed_rate: float
    lr_pof: float                 # Kupiec unconditional-coverage LR (chi^2_1)
    pof_pvalue: float
    lr_ind: float                 # Christoffersen independence LR (chi^2_1)
    lr_cc: float                  # conditional coverage LR = pof + ind (chi^2_2)
    cc_pvalue: float
    pof_reject: bool              # reject correct unconditional coverage at 5%
    cc_reject: bool               # reject correct conditional coverage at 5%


def _hits(returns: FloatArr, var_forecast: FloatArr | float, confidence: float) -> BoolArr:
    """Violation (hit) indicator: a loss exceeds the VaR forecast (VaR is a positive magnitude)."""
    r = np.asarray(returns, dtype=np.float64)
    v = np.broadcast_to(np.asarray(var_forecast, dtype=np.float64), r.shape)
    return np.asarray(-r > v, dtype=np.bool_)          # loss = -return > VaR


def var_backtest(returns: FloatArr, var_forecast: FloatArr | float, confidence: float = 0.95) -> CoverageTest:
    """Kupiec POF + Christoffersen conditional-coverage back-test of a VaR series."""
    hits = _hits(returns, var_forecast, confidence)
    n = int(hits.size)
    x = int(np.sum(hits))
    p = 1.0 - confidence
    obs = x / n if n else 0.0

    # Kupiec POF: LR = -2 ln[ (1-p)^{n-x} p^x / ((1-obs)^{n-x} obs^x) ].
    def _ll(rate: float) -> float:
        rate = min(max(rate, 1e-12), 1.0 - 1e-12)
        return (n - x) * math.log(1.0 - rate) + x * math.log(rate)
    lr_pof = -2.0 * (_ll(p) - _ll(obs)) if 0 < x < n else (-2.0 * (_ll(p) - _ll(obs)) if x in (0, n) else 0.0)
    lr_pof = max(lr_pof, 0.0)
    pof_p = float(chi2.sf(lr_pof, 1))

    # Christoffersen independence: first-order Markov on the hit sequence.
    lr_ind = _independence_lr(hits)
    lr_cc = lr_pof + lr_ind
    return CoverageTest(
        n=n, n_violations=x, expected_rate=p, observed_rate=obs,
        lr_pof=lr_pof, pof_pvalue=pof_p, lr_ind=lr_ind, lr_cc=lr_cc,
        cc_pvalue=float(chi2.sf(lr_cc, 2)),
        pof_reject=pof_p < 0.05, cc_reject=float(chi2.sf(lr_cc, 2)) < 0.05,
    )


def _independence_lr(hits: BoolArr) -> float:
    """Christoffersen (1998) first-order-Markov independence LR (chi^2_1); 0 if degenerate."""
    h = hits.astype(int)
    n00 = n01 = n10 = n11 = 0
    for a, b in pairwise(h):
        if a == 0 and b == 0:
            n00 += 1
        elif a == 0 and b == 1:
            n01 += 1
        elif a == 1 and b == 0:
            n10 += 1
        else:
            n11 += 1
    t = n00 + n01 + n10 + n11
    if t == 0 or (n01 + n11) == 0:
        return 0.0
    pi = (n01 + n11) / t
    pi0 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi1 = n11 / (n10 + n11) if (n10 + n11) else 0.0

    def _l(a: int, rate: float) -> float:
        rate = min(max(rate, 1e-12), 1.0 - 1e-12)
        return a * math.log(rate)
    ll_null = _l(n00 + n10, 1.0 - pi) + _l(n01 + n11, pi)
    ll_alt = _l(n00, 1.0 - pi0) + _l(n01, pi0) + _l(n10, 1.0 - pi1) + _l(n11, pi1)
    return max(-2.0 * (ll_null - ll_alt), 0.0)


# ── Extremal index + declustering ────────────────────────────────────────────


def extremal_index(losses: FloatArr, threshold_quantile: float = 0.95) -> float:
    """Ferro-Segers (2003) intervals estimator of the extremal index theta in (0,1].

    theta = 1 for independent extremes; theta < 1 signals clustering (crypto jumps/vol cluster).
    """
    x = np.asarray(losses, dtype=np.float64)
    u = float(np.percentile(x, 100.0 * threshold_quantile))
    idx = np.where(x > u)[0].astype(np.float64)
    if idx.size < 3:
        return 1.0
    s = np.diff(idx)                                    # inter-exceedance times
    n_c = s.size
    if float(np.max(s)) <= 2.0:
        theta = 2.0 * float(np.sum(s)) ** 2 / (n_c * float(np.sum(s * s)))
    else:
        theta = 2.0 * float(np.sum(s - 1.0)) ** 2 / (n_c * float(np.sum((s - 1.0) * (s - 2.0))))
    return float(min(max(theta, 0.0), 1.0))


@dataclass(frozen=True)
class DeclusterResult:
    cluster_maxima: FloatArr      # one representative (max) exceedance per cluster
    n_exceedances: int            # raw peaks over threshold
    n_clusters: int               # independent clusters (< n_exceedances if clustered)
    threshold: float
    extremal_index: float


def decluster(losses: FloatArr, threshold_quantile: float = 0.95, run_gap: int = 2) -> DeclusterResult:
    """Runs-declustering: exceedances separated by < run_gap non-exceedances share a cluster.

    Returns the cluster maxima (the independent extremes the GPD/POT assumes) plus the extremal index.
    """
    x = np.asarray(losses, dtype=np.float64)
    u = float(np.percentile(x, 100.0 * threshold_quantile))
    exc_idx = np.where(x > u)[0]
    if exc_idx.size == 0:
        return DeclusterResult(np.array([]), 0, 0, u, 1.0)
    clusters: list[list[int]] = [[int(exc_idx[0])]]
    for i in exc_idx[1:]:
        if i - clusters[-1][-1] <= run_gap:
            clusters[-1].append(int(i))
        else:
            clusters.append([int(i)])
    maxima = np.array([float(np.max(x[c])) for c in clusters], dtype=np.float64)
    return DeclusterResult(maxima, int(exc_idx.size), len(clusters), u,
                           extremal_index(losses, threshold_quantile))


# ── xi-monitor ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class XiMonitor:
    stable_xi: float
    xi_range: float
    heavy_tailed: bool            # xi >= 0.5 (infinite variance)
    infinite_mean: bool           # xi >= 1 (ES undefined)
    unstable: bool                # xi varies too much across thresholds
    warnings: list[str]


def xi_monitor(stability: ThresholdStability, xi_range_tol: float = 0.3) -> XiMonitor:
    """Flag heavy-tail / infinite-moment / instability conditions from the threshold-stability scan."""
    xi = stability.stable_xi
    rng = stability.xi_range
    warns: list[str] = []
    heavy = xi >= 0.5
    inf_mean = xi >= 1.0
    unstable = rng > xi_range_tol
    if inf_mean:
        warns.append(f"xi={xi:.2f} >= 1: ES/mean undefined (extreme heavy tail)")
    elif heavy:
        warns.append(f"xi={xi:.2f} >= 0.5: infinite variance (heavy tail)")
    if unstable:
        warns.append(f"xi varies {rng:.2f} across thresholds (> {xi_range_tol}): threshold-sensitive")
    return XiMonitor(xi, rng, heavy, inf_mean, unstable, warns)
