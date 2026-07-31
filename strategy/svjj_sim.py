"""SVJJ physical-measure path simulation (QE variance + asymmetric price jump + vol co-jump).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED; canonical main untouched (C10 · N1). Reuses the
Andersen QE variance scheme and the reproducibility contract (SeedSequence.spawn substreams) of
``strategy/multi_cycle_mc.py``; extends the jump block to the ``DoubleNormalJump`` asymmetric price jump
plus a contemporaneous exponential VARIANCE co-jump xi^v ~ Exp(mu_v) (co-arriving with the SAME Poisson
process), matching the SVJJ characteristic function in ``pricing/cf/svjj.py`` (validated CF-vs-MC).
"""

from __future__ import annotations

import math

import numpy as np

from pricing.cf.svjj import SVJJ
from strategy.multi_cycle_mc import _antithetic_uniform, _diffusion_normals

_KMAX = 3            # exact compound-Poisson jump sum for N<=3 per step (P(N>3)~2e-7 at lambda*dt~0.01)


def simulate_svjj_terminal(model: SVJJ, S0: float, T: float, n_paths: int, n_steps: int,
                           seed: int, use_antithetic: bool = True) -> np.ndarray:
    """Terminal spot S_T under the SVJJ physical dynamics. Reproducible; jumps mean-compensated in drift."""
    ss = np.random.SeedSequence([seed, 0])
    diff, var, var_u, jc, jp, jv = ss.spawn(6)
    diff_g, var_g, varu_g = np.random.default_rng(diff), np.random.default_rng(var), np.random.default_rng(var_u)
    jc_g, jp_g, jv_g = np.random.default_rng(jc), np.random.default_rng(jp), np.random.default_rng(jv)

    m, dt = n_paths, T / n_steps
    kappa, theta, volvol, rho = model.kappa, model.theta, model.sigma, model.rho
    mu, lam, mu_v = model.mu, model.lam, model.mu_v
    psi_c = 1.5
    zs = _diffusion_normals(diff_g, m, n_steps, use_antithetic)
    zv = _diffusion_normals(var_g, m, n_steps, use_antithetic)
    uu = _antithetic_uniform(varu_g, m, n_steps, use_antithetic)

    # co-arriving jumps: N ~ Poisson(lambda dt); price jump = sum of N double-normal draws, vol jump =
    # sum of N Exp(mu_v) draws (exact for N<=_KMAX). Per-path i.i.d. (not antithetic), as in Bates.
    n_jumps = jc_g.poisson(lam * dt, size=(m, n_steps))
    price_jump = np.zeros((m, n_steps))
    vol_jump = np.zeros((m, n_steps))
    for k in range(1, _KMAX + 1):
        hit = (n_jumps >= k)
        price_jump += np.where(hit, model.jump.sample(jp_g, (m, n_steps)), 0.0)
        vol_jump += np.where(hit, jv_g.exponential(mu_v, size=(m, n_steps)), 0.0)
    jc_comp = lam * model.jump.kappa_price                      # price-jump drift compensator

    ekt = math.exp(-kappa * dt)
    K0 = -rho * kappa * theta * dt / volvol
    K1 = 0.5 * dt * (kappa * rho / volvol - 0.5) - rho / volvol
    K2 = 0.5 * dt * (kappa * rho / volvol - 0.5) + rho / volvol
    K3 = 0.5 * dt * (1.0 - rho * rho)
    K4 = K3

    logS = np.full(m, math.log(S0), dtype=np.float64)
    v = np.full(m, model.v0, dtype=np.float64)
    for t in range(n_steps):
        s2 = (v * volvol * volvol * ekt / kappa * (1.0 - ekt)
              + theta * volvol * volvol / (2.0 * kappa) * (1.0 - ekt) ** 2)
        mcond = theta + (v - theta) * ekt
        psi = s2 / np.maximum(mcond * mcond, 1e-300)
        inv_psi = 1.0 / np.maximum(psi, 1e-300)
        b2 = np.maximum(2.0 * inv_psi - 1.0 + np.sqrt(2.0 * inv_psi) * np.sqrt(np.maximum(2.0 * inv_psi - 1.0, 0.0)), 0.0)
        aq = mcond / (1.0 + b2)
        v_quad = aq * (np.sqrt(b2) + zv[:, t]) ** 2
        p = np.clip((psi - 1.0) / (psi + 1.0), 0.0, 1.0 - 1e-12)
        beta = (1.0 - p) / np.maximum(mcond, 1e-300)
        u = uu[:, t]
        v_exp = np.where(u <= p, 0.0, np.log(np.maximum((1.0 - p) / np.maximum(1.0 - u, 1e-300), 1e-300)) / beta)
        v_next = np.where(psi <= psi_c, v_quad, v_exp)

        logS += (mu * dt + K0 + K1 * v + K2 * v_next
                 + np.sqrt(np.maximum(K3 * v + K4 * v_next, 0.0)) * zs[:, t]
                 + price_jump[:, t] - jc_comp * dt)
        v = np.maximum(v_next + vol_jump[:, t], 0.0)            # contemporaneous variance co-jump
    return np.exp(logS)
