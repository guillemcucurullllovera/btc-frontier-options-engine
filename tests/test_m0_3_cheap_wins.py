"""C9 · M0.3 — cheap correctness wins: GARCH MLE SE, tail/CVaR SE-CI, GPD threshold
stability, MC control variates.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched.

Independent oracles: injected-GPD known shape for the threshold diagnostic; the analytic
GBM expected-P&L for the control-variate mean; 1/sqrt(n) SE scaling for the GARCH SE.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import genpareto

from risk.cvar_frontier import ru_cvar, ru_cvar_ci
from risk.tail import (
    ThresholdStability,
    gpd_threshold_stability,
    with_bootstrap_ci,
)
from strategy.definitions import (
    build_long_btc_plus_short_put,
    build_unhedged_baseline,
)
from strategy.monte_carlo import (
    MonteCarloConfig,
    run_monte_carlo,
)
from vol.garch import GarchEstimator

# ── GARCH MLE standard errors (Fisher + sandwich) ─────────────────────────────


def _garch_series(n: int, seed: int, omega: float = 1e-6, alpha: float = 0.08,
                  beta: float = 0.90) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = [0.0]
    s2 = omega / max(1e-12, 1.0 - alpha - beta)
    for _ in range(n):
        s2 = omega + alpha * r[-1] ** 2 + beta * s2
        r.append(math.sqrt(s2) * rng.standard_normal())
    return np.array(r[1:], dtype=np.float64)


def test_garch_mle_se_populated_both_estimators() -> None:
    res = GarchEstimator(_garch_series(1500, seed=3)).fit()
    assert res.convergence
    for se in (res.param_std_errors, res.param_std_errors_fisher):
        assert {"omega", "alpha", "beta"} <= set(se)
        assert all(v > 0.0 and math.isfinite(v) for v in se.values())
    # Sandwich (robust) and Fisher (classical) differ but are the same order of magnitude.
    assert res.param_std_errors["beta"] != res.param_std_errors_fisher["beta"]
    ratio = res.param_std_errors["beta"] / res.param_std_errors_fisher["beta"]
    assert 0.25 < ratio < 4.0


def test_garch_se_shrinks_with_sample_size() -> None:
    """MLE SE ~ 1/sqrt(n): a 4x longer sample roughly halves the beta SE (oracle: asymptotics)."""
    se_small = GarchEstimator(_garch_series(600, seed=5)).fit().param_std_errors_fisher["beta"]
    se_big = GarchEstimator(_garch_series(2400, seed=5)).fit().param_std_errors_fisher["beta"]
    assert se_big < se_small
    assert se_big < 0.8 * se_small          # clearly shrinking (not exactly 0.5 in finite samples)


# ── Tail SE / CI (bootstrap) ──────────────────────────────────────────────────


def _loss_normal(n: int = 40_000, sigma: float = 1e6, seed: int = 11) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, sigma, n)


@pytest.mark.parametrize("method", ["empirical", "evt_gpd", "cornish_fisher"])
def test_tail_bootstrap_ci_brackets_point_estimate(method: str) -> None:
    pnl = _loss_normal()
    est = with_bootstrap_ci(pnl, method=method, confidence=0.975, n_boot=150, seed=99)
    assert est.var_se is not None and est.var_se > 0.0
    assert est.es_se is not None and est.es_se > 0.0
    assert est.var_ci is not None and est.var_ci[0] <= est.var <= est.var_ci[1]
    assert est.es_ci is not None and est.es_ci[0] <= est.es <= est.es_ci[1]
    assert est.es >= est.var                     # coherence preserved
    assert est.n_boot is not None and est.n_boot > 0


def test_tail_bootstrap_ci_reproducible() -> None:
    pnl = _loss_normal()
    a = with_bootstrap_ci(pnl, "evt_gpd", 0.975, n_boot=120, seed=2024)
    b = with_bootstrap_ci(pnl, "evt_gpd", 0.975, n_boot=120, seed=2024)
    assert a.var_se == b.var_se and a.es_se == b.es_se and a.var_ci == b.var_ci


# ── GPD threshold-stability diagnostic (replaces hard-coded 90%) ──────────────


def test_threshold_stability_recovers_known_shape() -> None:
    """Injected GPD tail (xi=0.3): the stability diagnostic's shape ~ true across thresholds."""
    rng = np.random.default_rng(21)
    body = rng.normal(0, 1.0, 150_000)
    xi_true = 0.30
    tail = 3.0 + genpareto.rvs(xi_true, loc=0.0, scale=2.0, size=30_000, random_state=rng)
    losses = np.concatenate([body, tail])
    ts = gpd_threshold_stability(-losses, confidence=0.99)
    assert isinstance(ts, ThresholdStability)
    assert len(ts.points) >= 3
    assert abs(ts.stable_xi - xi_true) < 0.1        # recovered near the true shape
    assert ts.xi_range < 0.25                        # shape reasonably stable across thresholds
    for p in ts.points:
        assert p.xi_se > 0.0 and p.n_exceedances >= 50


def test_threshold_stability_normal_is_bounded_tail() -> None:
    """A normal sample has a thin (bounded) tail: xi < 0 and stable."""
    ts = gpd_threshold_stability(_loss_normal(n=120_000), confidence=0.975)
    assert ts.stable_xi < 0.05                       # not heavy-tailed
    assert ts.xi_range < 0.2


# ── CVaR SE / CI ──────────────────────────────────────────────────────────────


def test_cvar_ci_brackets_point_and_reproducible() -> None:
    pnl = _loss_normal()
    var, cvar = ru_cvar(pnl, beta=0.95)
    est = ru_cvar_ci(pnl, beta=0.95, n_boot=150, seed=55)
    assert est.cvar == pytest.approx(cvar, rel=1e-12)   # point estimate unchanged
    assert est.var == pytest.approx(var, rel=1e-12)
    assert est.cvar_se > 0.0 and est.cvar_ci[0] <= cvar <= est.cvar_ci[1]
    again = ru_cvar_ci(pnl, beta=0.95, n_boot=150, seed=55)
    assert again.cvar_se == est.cvar_se and again.cvar_ci == est.cvar_ci


# ── MC control variates (reproducibility-preserving) ──────────────────────────


def test_control_variate_unhedged_matches_analytic_mean() -> None:
    """Unhedged holding P&L is linear in S_T => CV nails E[P&L]=S0*(e^{muT}-1) with R^2~1."""
    S0, mu, T = 65_000.0, 0.10, 30.0 / 365.0
    strat = build_unhedged_baseline(quantity=1.0, entry_spot=S0)
    cfg = MonteCarloConfig(n_paths=20_000, initial_spot=S0, drift=mu, volatility=0.45,
                           horizon_years=T, seed=42, model="GBM")
    mc = run_monte_carlo(strat, cfg)
    analytic = S0 * (math.exp(mu * T) - 1.0)
    assert mc.cv_controls == ["S_T"]
    assert mc.cv_variance_reduction > 0.999                 # exactly linear => full reduction
    assert mc.cv_expected_pnl == pytest.approx(analytic, abs=1.0)
    assert mc.cv_expected_pnl_se < mc.expected_pnl_se


def test_control_variate_reduces_variance_and_preserves_reproducibility() -> None:
    strat = build_long_btc_plus_short_put(quantity=1.0, entry_spot=65_000.0,
                                          strike=58_500.0, premium_received=1_500.0)
    cfg = MonteCarloConfig(n_paths=20_000, initial_spot=65_000.0, drift=0.10, volatility=0.45,
                           seed=42, model="GBM")
    a = run_monte_carlo(strat, cfg)
    b = run_monte_carlo(strat, cfg)
    # Reproducibility contract: identical paths (untouched RNG) AND identical CV output.
    assert a.pnl_distribution == b.pnl_distribution
    assert a.cv_expected_pnl == b.cv_expected_pnl
    # Payoff control included; long-BTC+short-put P&L is a function of (S_T, put payoff) => big cut.
    assert "payoff_put_58500" in a.cv_controls
    assert a.cv_variance_reduction > 0.5
    assert a.cv_expected_pnl_se < a.expected_pnl_se


def test_control_variate_is_unbiased_estimator() -> None:
    """CV mean sits within a few plain-MC SEs of the plain mean (unbiasedness sanity)."""
    strat = build_long_btc_plus_short_put(quantity=1.0, entry_spot=65_000.0,
                                          strike=58_500.0, premium_received=1_500.0)
    cfg = MonteCarloConfig(n_paths=30_000, initial_spot=65_000.0, drift=0.10, volatility=0.45,
                           seed=7, model="GBM")
    mc = run_monte_carlo(strat, cfg)
    assert mc.cv_controls  # non-empty
    assert abs(mc.cv_expected_pnl - mc.expected_pnl) < 5.0 * mc.expected_pnl_se


def test_control_variate_merton_uses_spot_only() -> None:
    """Under Merton the payoff-mean series is not used (mean not exact); S_T control stays exact."""
    strat = build_long_btc_plus_short_put(quantity=1.0, entry_spot=65_000.0,
                                          strike=58_500.0, premium_received=1_500.0)
    cfg = MonteCarloConfig(n_paths=15_000, initial_spot=65_000.0, drift=0.10, volatility=0.45,
                           seed=42, model="Merton")
    mc = run_monte_carlo(strat, cfg)
    assert mc.cv_controls == ["S_T"]                        # payoff controls omitted for Merton
    assert mc.cv_variance_reduction > 0.0
