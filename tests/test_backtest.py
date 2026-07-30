"""C9 · M5.2 — EVT tail hardening: VaR back-testing + declustering + xi-monitor.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched.

Oracles: a correctly-specified VaR passes Kupiec/Christoffersen and a too-low one is rejected;
clustered violations are caught by the independence test; the extremal index is ~1 for iid extremes
and < 1 for a clustered process; declustering reduces a clustered exceedance count; the xi-monitor
flags a heavy (xi >= 0.5) tail.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import genpareto

from risk.backtest import (
    decluster,
    extremal_index,
    var_backtest,
    xi_monitor,
)
from risk.tail import gpd_threshold_stability


def test_kupiec_accepts_correct_rejects_misspecified() -> None:
    r = np.random.default_rng(3).normal(0.0, 1.0, 5000)
    var95 = float(np.percentile(-r, 95.0))
    ok = var_backtest(r, var95, confidence=0.95)
    assert ok.observed_rate == 0.05
    assert not ok.pof_reject and ok.pof_pvalue > 0.05     # correct coverage not rejected
    bad = var_backtest(r, float(np.percentile(-r, 90.0)), confidence=0.95)   # too-low VaR
    assert bad.observed_rate > 0.09
    assert bad.pof_reject and bad.pof_pvalue < 0.01        # over-violations => rejected


def test_christoffersen_detects_clustered_violations() -> None:
    """Same total violation rate but CLUSTERED => POF may pass while conditional coverage rejects."""
    n = 3000
    r = np.zeros(n)
    var = 5.0
    # 150 violations (5%) in 5 consecutive bursts of 30 (clustered).
    for start in (100, 700, 1400, 2100, 2700):
        r[start:start + 30] = -10.0                        # big losses > VaR
    ct = var_backtest(r, var, confidence=0.95)
    assert abs(ct.observed_rate - 0.05) < 0.005            # correct unconditional rate
    assert ct.lr_ind > 5.0                                  # strong dependence in the hit sequence
    assert ct.cc_reject                                     # conditional coverage rejected (clustering)


def test_extremal_index_iid_vs_clustered() -> None:
    rng = np.random.default_rng(11)
    iid = rng.normal(0.0, 1.0, 10_000)
    mv = np.array([iid[max(0, i - 4):i + 1].max() for i in range(10_000)])   # moving-max clusters
    assert extremal_index(iid, 0.95) > 0.8                 # ~1 for independent extremes
    assert extremal_index(mv, 0.95) < 0.5                  # << 1 for clustered extremes


def test_declustering_reduces_clustered_exceedance_count() -> None:
    rng = np.random.default_rng(11)
    iid = rng.normal(0.0, 1.0, 10_000)
    mv = np.array([iid[max(0, i - 4):i + 1].max() for i in range(10_000)])
    d_iid = decluster(iid, 0.95, run_gap=2)
    d_mv = decluster(mv, 0.95, run_gap=2)
    assert d_iid.n_clusters > 0.85 * d_iid.n_exceedances   # iid: clusters ~ exceedances
    assert d_mv.n_clusters < 0.5 * d_mv.n_exceedances       # clustered: far fewer clusters
    assert d_mv.cluster_maxima.size == d_mv.n_clusters


def test_xi_monitor_flags_heavy_tail() -> None:
    rng = np.random.default_rng(21)
    heavy = np.concatenate([rng.normal(0, 1, 60_000),
                            3.0 + genpareto.rvs(0.6, scale=2.0, size=12_000, random_state=rng)])
    xm = xi_monitor(gpd_threshold_stability(-heavy, confidence=0.99))
    assert xm.stable_xi > 0.4
    assert xm.heavy_tailed                                  # xi >= 0.5 flagged
    assert not xm.infinite_mean                             # xi < 1
    assert len(xm.warnings) >= 1


def test_light_tail_not_flagged() -> None:
    """A thin (normal) tail is not flagged heavy/infinite by the xi-monitor."""
    r = np.random.default_rng(5).normal(0.0, 1e6, 120_000)
    xm = xi_monitor(gpd_threshold_stability(r, confidence=0.975))
    assert not xm.heavy_tailed and not xm.infinite_mean     # xi < 0.5 for a normal tail
