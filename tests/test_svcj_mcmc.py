"""C9 · Phase C (M4.4b) — SVCJ Bayesian MCMC (Eraker-Johannes-Polson) validation.

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED; canonical main untouched. Validates the sampler by
EJP's own approach (Appendix C): simulate the discretised SVCJ with known parameters and check that the
posterior recovers them and tracks the latent volatility path. The core SV/jump structure is recovered
and the latent vol is tracked (corr ~0.75); as EJP note, kappa and the vol-jump size are weakly
identified from returns alone (wider posteriors / slower mixing) — reported honestly, not asserted tight.
"""

from __future__ import annotations

import numpy as np

from vol.svcj_mcmc import (
    SVCJParams,
    _rtruncnorm_pos,
    gelman_rubin,
    simulate_svcj,
    svcj_mcmc,
)

_TRUE = SVCJParams(mu=0.05, kappa=0.03, theta=4.0, sigma_v=0.5, rho=-0.4,
                   lam=0.04, mu_y=-1.5, sigma_y=3.0, mu_v=2.0, rho_j=-0.5)


def test_simulate_svcj_shapes_and_jump_rate() -> None:
    y, v, j = simulate_svcj(_TRUE, n=2000, seed=1)
    assert y.shape == (2001,) and v.shape == (2001,) and j.shape == (2000,)
    assert np.all(np.isfinite(y)) and np.all(v > 0)
    assert 0.02 < j.mean() < 0.07                          # ~lambda=0.04 arrivals


def test_truncnorm_positive() -> None:
    rng = np.random.default_rng(0)
    x = _rtruncnorm_pos(np.full(5000, -1.0), np.full(5000, 1.0), rng)
    assert np.all(x > 0.0)                                 # truncation respected even for negative mean


def test_gelman_rubin_discriminates() -> None:
    rng = np.random.default_rng(0)
    same = rng.standard_normal((3, 200)) * 0.1 + 5.0       # 3 chains, same target
    assert gelman_rubin(same) < 1.1
    split = np.vstack([rng.standard_normal(200) * 0.1 + c for c in (0.0, 3.0, 6.0)])  # divergent means
    assert gelman_rubin(split) > 1.3


def test_svcj_recovers_simulated_parameters_and_vol_path() -> None:
    """Simulate -> estimate -> the identifiable structure is recovered and the vol path is tracked."""
    y, v_true, _ = simulate_svcj(_TRUE, n=800, seed=3)
    post = svcj_mcmc(y, n_iter=2000, n_chains=2, n_burn=800, seed=5)

    assert all(np.isfinite(x) for x in post.post_mean.values())
    # latent volatility path recovered (annualised posterior mean vs the simulated truth)
    v_ann_true = np.sqrt(np.maximum(v_true, 0.0)) / 100.0 * np.sqrt(365.0)
    assert np.corrcoef(post.v_filtered, v_ann_true)[0, 1] > 0.6
    # well-identified structure: theta (vol level) covered; lambda brackets a sane rate; rho sign correct
    assert post.post_q05["theta"] < 4.0 < post.post_q95["theta"]
    assert post.post_q05["lambda"] < 0.04 < post.post_q95["lambda"]
    assert post.post_mean["rho"] < 0.0                     # leverage sign recovered
    assert 0.15 < post.post_mean["sigma_v"] < 0.9          # vol-of-vol in the right ballpark
    # diagnostics are populated
    assert set(post.rhat) == set(post.param_names)
    assert all(post.ess[n] > 0 for n in post.param_names)
