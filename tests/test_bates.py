"""C9 · M3.1 — Bates (Heston SV + Merton jumps): CF + full-truncation-Euler simulation.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Bates reuses the M2 Heston variance
stream and the existing Merton jump block. No best/optimal claim (model selection is M3.2, still a
statistical model-fit choice, not an MS-25 strategy claim).

Oracles: the Bates CF satisfies the four CF invariants; lambda=0 collapses exactly to Heston;
COS-Bates matches Carr-Madan (independent method); the MC is a martingale and matches the COS/CF
price within k*SE; jumps produce excess kurtosis and (mu_j<0) extra left skew a pure-Heston lacks.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import kurtosis, skew

from pricing.cf.carr_madan import carr_madan_call
from pricing.cf.characteristic_functions import Bates, Heston, check_cf_sanity, numerical_cumulants
from pricing.cf.cos import cos_call
from strategy.multi_cycle_mc import MultiCycleMCConfig, _generate_chunk_paths, _simulate_paths_full

_B = Bates(r=0.0, q=0.0, v0=0.15, kappa=3.0, theta=0.2, sigma=1.2, rho=-0.3,
           lam=1.5, mu_j=-0.10, sigma_j=0.15)
_HP = {"heston_v0": 0.15, "heston_kappa": 3.0, "heston_theta": 0.2,
       "heston_vol_of_vol": 1.2, "heston_rho": -0.3}
_JP = {"jump_intensity": 1.5, "jump_mean": -0.10, "jump_std": 0.15}


def _bates_cfg(**kw: object) -> MultiCycleMCConfig:
    base = dict(n_paths=300_000, n_cycles=1, cycle_length_years=1.0, n_steps_per_cycle=150,
                initial_spot=60_000.0, drift=0.0, risk_free_rate=0.0, model="Bates",
                seed=42, use_antithetic=True, chunk_size=50_000, **_HP, **_JP)
    base.update(kw)
    return MultiCycleMCConfig(**base)  # type: ignore[arg-type]


# ── Bates CF ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("T", [0.1, 0.5, 1.0, 3.0])
def test_bates_cf_sanity(T: float) -> None:
    s = check_cf_sanity(_B, T)
    assert s.phi0_err < 1e-12 and s.max_modulus <= 1.0 + 1e-9
    assert s.conj_sym_err < 1e-10 and s.martingale_err < 1e-9


def test_bates_reduces_to_heston_when_lambda_zero() -> None:
    b0 = Bates(r=0.0, q=0.0, v0=0.15, kappa=3.0, theta=0.2, sigma=1.2, rho=-0.3,
               lam=0.0, mu_j=0.0, sigma_j=0.1)
    h = Heston(r=0.0, q=0.0, v0=0.15, kappa=3.0, theta=0.2, sigma=1.2, rho=-0.3)
    for K in (48_000.0, 60_000.0, 75_000.0):
        assert cos_call(b0, 60_000.0, K, 0.5, N=2048, L=16.0) == pytest.approx(
            cos_call(h, 60_000.0, K, 0.5, N=2048, L=16.0), abs=1e-10)


def test_bates_cumulants_match_numerical() -> None:
    ca = _B.cumulants(1.0)
    cn = numerical_cumulants(_B, 1.0)
    assert ca[0] == pytest.approx(cn[0], rel=1e-3, abs=1e-6)
    assert ca[1] == pytest.approx(cn[1], rel=1e-3, abs=1e-6)
    assert ca[2] > 0.0                              # jumps add positive c4 (kurtosis)


def test_cos_bates_matches_carr_madan() -> None:
    for K in (48_000.0, 60_000.0, 75_000.0):
        c = cos_call(_B, 60_000.0, K, 0.5, N=4096, L=18.0)
        cm = carr_madan_call(_B, 60_000.0, K, 0.5, alpha=1.5, v_max=800.0, n=16384)
        assert c == pytest.approx(cm, abs=1e-5)


# ── Bates MC ──────────────────────────────────────────────────────────────────


def test_bates_mc_martingale_and_reproducible() -> None:
    cfg = _bates_cfg(n_paths=200_000)
    st = _simulate_paths_full(cfg)[:, -1]
    assert st.mean() == pytest.approx(60_000.0, rel=2e-3)
    assert np.array_equal(_simulate_paths_full(cfg), _simulate_paths_full(cfg))


def test_bates_chunk_self_contained_with_jump_streams() -> None:
    cfg = _bates_cfg(n_paths=20_000)
    a = _generate_chunk_paths(cfg, chunk_index=1, m=5_000)
    assert np.array_equal(a, _generate_chunk_paths(cfg, chunk_index=1, m=5_000))
    assert not np.array_equal(a, _generate_chunk_paths(cfg, chunk_index=2, m=5_000))


def test_cos_matches_bates_mc_within_k_se() -> None:
    cfg = _bates_cfg(n_paths=300_000)
    st = _simulate_paths_full(cfg)[:, -1]
    for K in (54_000.0, 60_000.0, 66_000.0):
        payoff = np.maximum(st - K, 0.0)
        mc, se = float(payoff.mean()), float(payoff.std() / math.sqrt(payoff.size))
        cos = cos_call(_B, 60_000.0, K, 1.0, N=4096, L=18.0)
        assert abs(cos - mc) < 4.0 * se, f"K={K}: |COS-MC|={abs(cos - mc):.1f} vs 4*SE={4 * se:.1f}"


def test_bates_heavy_tail_and_jump_conditioned_skew() -> None:
    """Bates paths are heavy-tailed and left-skewed; negative jumps add left skew (isolated).

    Note: with a large SV vol-of-vol the leverage/SV already drives most kurtosis, so the clean
    demonstration of the JUMP contribution is mu_j<0 vs mu_j=0 (everything else identical), which
    isolates the jump-conditioned skew rather than confounding it with the SV variance.
    """
    lr_neg = np.log(_simulate_paths_full(_bates_cfg(n_paths=300_000, jump_mean=-0.10))[:, -1] / 60_000.0)
    lr_sym = np.log(_simulate_paths_full(_bates_cfg(n_paths=300_000, jump_mean=0.0))[:, -1] / 60_000.0)
    assert kurtosis(lr_neg) > 0.3                   # heavy tails (jumps + SV)
    assert skew(lr_neg) < 0.0                        # left-skewed
    assert skew(lr_neg) < skew(lr_sym)              # negative jumps add left skew (isolated)
