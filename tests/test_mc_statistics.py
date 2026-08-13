"""C8 R3 — MC statistical validation battery (Tier-1 U1/U2/U3).

External-anchor checks on the C7/hero path generator, closing the "all oracles
in-house" risk (SR 11-7). No new dependencies (numpy + scipy.stats).

  U1  martingale/unbiasedness: E[e^{-rT} S_T] = S0 within k*SE (risk-neutral drift).
  U2  MC European price vs the analytical Black-Scholes price within k*SE.
  U3  KS / Anderson-Darling on simulated one-step log-returns vs the theoretical N.
"""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
import pytest
from scipy.stats import cramervonmises, kstest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pricing.black_scholes import price as bs_price
from strategy.multi_cycle_mc import MultiCycleMCConfig, _generate_chunk_paths

K_SE = 5.0          # tolerance in standard errors (5 sigma: ~1 in 3.5M false-positive)
SIGMA = 0.60
R = 0.03
T = 0.5


def _rn_config(n_paths: int, antithetic: bool = True, steps: int = 1) -> MultiCycleMCConfig:
    """Risk-neutral GBM config (drift = r) over a single horizon T."""
    return MultiCycleMCConfig(
        n_paths=n_paths, n_cycles=1, cycle_length_years=T, n_steps_per_cycle=steps,
        initial_spot=100.0, volatility=SIGMA, risk_free_rate=R, drift=R, model="GBM",
        seed=20260730, use_antithetic=antithetic, chunk_size=n_paths + 2,
    )


def _terminal(config: MultiCycleMCConfig) -> np.ndarray:
    return _generate_chunk_paths(config, 0, config.n_paths)[:, -1]


def test_u1_martingale_discounted_spot() -> None:
    cfg = _rn_config(400_000)
    st = _terminal(cfg)
    disc = math.exp(-R * T) * st
    mean = float(np.mean(disc))
    se = float(np.std(disc)) / math.sqrt(cfg.n_paths)
    assert abs(mean - cfg.initial_spot) <= K_SE * se  # E[e^{-rT} S_T] == S0


def test_u2_mc_european_call_vs_analytical() -> None:
    cfg = _rn_config(400_000)
    st = _terminal(cfg)
    s0, k = cfg.initial_spot, 110.0
    disc_payoff = math.exp(-R * T) * np.maximum(st - k, 0.0)
    mc = float(np.mean(disc_payoff))
    se = float(np.std(disc_payoff)) / math.sqrt(cfg.n_paths)
    analytic = bs_price(s0, k, R, SIGMA, T, "call")
    assert abs(mc - analytic) <= K_SE * se


def test_u2_mc_european_put_vs_analytical() -> None:
    cfg = _rn_config(400_000)
    st = _terminal(cfg)
    s0, k = cfg.initial_spot, 90.0
    disc_payoff = math.exp(-R * T) * np.maximum(k - st, 0.0)
    mc = float(np.mean(disc_payoff))
    se = float(np.std(disc_payoff)) / math.sqrt(cfg.n_paths)
    analytic = bs_price(s0, k, R, SIGMA, T, "put")
    assert abs(mc - analytic) <= K_SE * se


def test_u3_ks_and_ad_on_log_returns() -> None:
    # One-step GBM log-returns ~ N((r-sigma^2/2)dt, sigma^2 dt). Antithetic OFF (need iid).
    steps = 20
    cfg = _rn_config(20_000, antithetic=False, steps=steps)
    paths = _generate_chunk_paths(cfg, 0, cfg.n_paths)
    rets = np.log(paths[:, 1:] / paths[:, :-1]).ravel()
    dt = T / steps
    mu = (R - 0.5 * SIGMA * SIGMA) * dt
    sd = SIGMA * math.sqrt(dt)
    # KS on a large random subsample (KS is conservative on huge n).
    sub = np.random.default_rng(1).choice(rets, size=5_000, replace=False)
    _stat, pval = kstest((sub - mu) / sd, "norm")
    assert pval > 0.01
    # Cramer-von-Mises GoF (an EDF test in the Anderson-Darling family) as a cross-check.
    cvm = cramervonmises((sub - mu) / sd, "norm")
    assert cvm.pvalue > 0.01
    # Standardised moments are ~ normal.
    assert abs(float(np.mean((rets - mu) / sd))) < 0.02
    assert float(np.std((rets - mu) / sd)) == pytest.approx(1.0, abs=0.02)


def test_u1_martingale_merton_compensated() -> None:
    # The Merton jump compensator preserves the martingale (drift = r).
    cfg = MultiCycleMCConfig(
        n_paths=400_000, n_cycles=1, cycle_length_years=T, n_steps_per_cycle=10,
        initial_spot=100.0, volatility=SIGMA, risk_free_rate=R, drift=R, model="Merton",
        seed=99, use_antithetic=True, chunk_size=400_002,
    )
    st = _generate_chunk_paths(cfg, 0, cfg.n_paths)[:, -1]
    disc = math.exp(-R * T) * st
    se = float(np.std(disc)) / math.sqrt(cfg.n_paths)
    assert abs(float(np.mean(disc)) - cfg.initial_spot) <= K_SE * se
