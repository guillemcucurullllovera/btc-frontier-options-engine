"""C9 · M2.2 / M2.3 — Heston full-truncation-Euler simulation + validation.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Small clearly-labelled diagnostic
MC (not decision evidence). BTC violates Feller (2*kappa*theta < volvol^2), so full-truncation is
mandatory; QE/Andersen is the optional unbiased upgrade.

Validation: reproducibility (SeedSequence.spawn substream contract), the risk-neutral martingale
E[e^{-rT} S_T] = S0, CF-vs-MC within k*SE (independent COS oracle), and the two stylised facts a
constant-vol GBM cannot produce — volatility clustering (ACF of |returns| > 0) and the leverage
effect (returns negatively correlated with next-step vol when rho < 0).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pricing.cf.characteristic_functions import Heston
from pricing.cf.cos import cos_call
from strategy.multi_cycle_mc import (
    MultiCycleMCConfig,
    _generate_chunk_paths,
    _simulate_paths_full,
)

# BTC-like, Feller-VIOLATED Heston (2*kappa*theta < volvol^2).
_HP = {"heston_v0": 0.30, "heston_kappa": 1.5768, "heston_theta": 0.30,
       "heston_vol_of_vol": 0.9, "heston_rho": -0.4}


def _cfg(**kw: object) -> MultiCycleMCConfig:
    base = dict(n_paths=100_000, n_cycles=1, cycle_length_years=1.0, n_steps_per_cycle=120,
                initial_spot=60_000.0, drift=0.0, risk_free_rate=0.0, model="Heston",
                seed=42, use_antithetic=True, chunk_size=50_000, **_HP)
    base.update(kw)
    return MultiCycleMCConfig(**base)  # type: ignore[arg-type]


# ── reproducibility (substream contract) ──────────────────────────────────────


def test_heston_sim_reproducible_same_seed() -> None:
    cfg = _cfg(n_paths=20_000)
    assert np.array_equal(_simulate_paths_full(cfg), _simulate_paths_full(cfg))


def test_heston_chunk_is_self_contained() -> None:
    """A given chunk generates identically regardless of when it is drawn (resumable substreams)."""
    cfg = _cfg(n_paths=20_000)
    a = _generate_chunk_paths(cfg, chunk_index=2, m=5_000)
    b = _generate_chunk_paths(cfg, chunk_index=2, m=5_000)
    assert np.array_equal(a, b)
    # A different chunk index draws a different (independent) stream.
    c = _generate_chunk_paths(cfg, chunk_index=3, m=5_000)
    assert not np.array_equal(a, c)


def test_full_truncation_keeps_paths_valid_under_feller_violation() -> None:
    """High vol-of-vol (Feller badly violated) still yields finite, strictly positive prices."""
    cfg = _cfg(n_paths=20_000, heston_vol_of_vol=2.5)   # Feller ratio ~ 0.15
    assert cfg.heston_feller_ratio < 1.0
    paths = _simulate_paths_full(cfg)
    assert np.all(np.isfinite(paths)) and np.all(paths > 0.0)


# ── martingale + CF-vs-MC ─────────────────────────────────────────────────────


def test_heston_martingale_risk_neutral() -> None:
    """E[e^{-rT} S_T] = S0 under the risk-neutral drift (r=q=0 => E[S_T]=S0)."""
    cfg = _cfg(n_paths=200_000, n_steps_per_cycle=150)
    st = _simulate_paths_full(cfg)[:, -1]
    assert st.mean() == pytest.approx(60_000.0, rel=2e-3)


def test_cos_matches_heston_mc_within_k_se() -> None:
    """COS/CF prices match the diagnostic full-truncation Euler MC within ~4*SE (Euler bias noted)."""
    cfg = _cfg(n_paths=300_000, n_steps_per_cycle=150)
    st = _simulate_paths_full(cfg)[:, -1]
    model = Heston(r=0.0, q=0.0, v0=_HP["heston_v0"], kappa=_HP["heston_kappa"],
                   theta=_HP["heston_theta"], sigma=_HP["heston_vol_of_vol"], rho=_HP["heston_rho"])
    for K in (54_000.0, 60_000.0, 66_000.0):
        payoff = np.maximum(st - K, 0.0)
        mc, se = float(payoff.mean()), float(payoff.std() / math.sqrt(payoff.size))
        cos = cos_call(model, 60_000.0, K, 1.0, N=2048, L=16.0)
        assert abs(cos - mc) < 4.0 * se, f"K={K}: |COS-MC|={abs(cos - mc):.1f} vs 4*SE={4 * se:.1f}"


# ── stylised facts: volatility clustering + leverage ──────────────────────────


def _log_returns(paths: np.ndarray) -> np.ndarray:
    return np.diff(np.log(paths), axis=1)


def _acf_abs_lag1(returns: np.ndarray) -> float:
    """Lag-1 autocorrelation of |returns|, averaged across paths (volatility clustering)."""
    a = np.abs(returns)
    a = a - a.mean(axis=1, keepdims=True)
    num = np.sum(a[:, :-1] * a[:, 1:], axis=1)
    den = np.sum(a * a, axis=1)
    return float(np.mean(num / np.maximum(den, 1e-30)))


def test_volatility_clustering_reproduced() -> None:
    """Heston paths show positive |return| autocorrelation; a constant-vol GBM does not."""
    cfg = _cfg(n_paths=4_000, n_steps_per_cycle=500, cycle_length_years=2.0, use_antithetic=False)
    heston_acf = _acf_abs_lag1(_log_returns(_simulate_paths_full(cfg)))
    gbm_cfg = MultiCycleMCConfig(n_paths=4_000, n_cycles=1, cycle_length_years=2.0,
                                 n_steps_per_cycle=500, initial_spot=60_000.0, drift=0.0,
                                 volatility=0.55, model="GBM", seed=7, use_antithetic=False)
    gbm_acf = _acf_abs_lag1(_log_returns(_simulate_paths_full(gbm_cfg)))
    assert heston_acf > 0.02                    # clustering present
    assert heston_acf > gbm_acf + 0.01          # and clearly above the constant-vol baseline


def test_leverage_effect_reproduced() -> None:
    """rho<0 => a negative return tends to precede a higher next-step |return| (leverage)."""
    cfg = _cfg(n_paths=6_000, n_steps_per_cycle=500, cycle_length_years=2.0, use_antithetic=False)
    r = _log_returns(_simulate_paths_full(cfg))
    # corr(return_t, |return_{t+1}|) < 0 under negative spot/vol correlation.
    x = r[:, :-1].ravel()
    y = np.abs(r[:, 1:]).ravel()
    corr = float(np.corrcoef(x, y)[0, 1])
    assert corr < 0.0
