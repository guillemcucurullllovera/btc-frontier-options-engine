"""C9 · M1.6 — CF numerical-invariance + the CF-vs-MC rung of the validation ladder.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. No calibration/live data.

Invariance (a decision-grade price must not depend on solver knobs): COS is stable across the node
count N and truncation width L / range [a,b]; Carr-Madan is stable across the damping alpha and the
FFT (N, eta). The CF-vs-MC rung prices Heston with a small, clearly-labelled DIAGNOSTIC
full-truncation Euler Monte Carlo and checks the CF price lies within k*SE (allowing for the known
positive Euler discretisation bias; the Feller condition is violated so full-truncation is mandatory).
"""

from __future__ import annotations

import math

import numpy as np

from pricing.cf.carr_madan import carr_madan_call, carr_madan_fft
from pricing.cf.characteristic_functions import CGMY, Heston, VarianceGamma
from pricing.cf.cos import cos_call, cos_truncation

_HESTON = Heston(r=0.0, q=0.0, v0=0.0175, kappa=1.5768, theta=0.0398, sigma=0.5751, rho=-0.5711)
_VG = VarianceGamma(r=0.1, q=0.0, sigma=0.12, theta=-0.14, nu=0.2)
_CGMY = CGMY(r=0.1, q=0.0, C=1.0, G=5.0, M=5.0, Y=0.5)


# ── COS invariance across N, L, [a,b] ─────────────────────────────────────────


def test_cos_price_invariant_across_N() -> None:
    """Once resolved, the COS price does not depend on the node count N."""
    for model in (_HESTON, _VG, _CGMY):
        prices = [cos_call(model, 100.0, 100.0, 1.0, N=N, L=16.0) for N in (512, 1024, 2048, 4096)]
        assert max(prices) - min(prices) < 1e-6


def test_cos_price_invariant_across_L_when_converged() -> None:
    """For a light-tailed model the price is stable across the truncation width L."""
    prices = [cos_call(_VG, 100.0, 90.0, 1.0, N=2048, L=L) for L in (10.0, 12.0, 14.0, 16.0)]
    assert max(prices) - min(prices) < 1e-5


def test_cos_price_invariant_to_range_widening() -> None:
    """Widening [a,b] beyond the auto-range leaves the price unchanged (no truncation leakage)."""
    a, b = cos_truncation(_HESTON, 100.0, 100.0, 1.0, L=16.0)
    base = cos_call(_HESTON, 100.0, 100.0, 1.0, N=4096, L=16.0, a=a, b=b)
    wider = cos_call(_HESTON, 100.0, 100.0, 1.0, N=4096, L=16.0, a=a - 2.0, b=b + 2.0)
    assert abs(base - wider) < 1e-6


# ── Carr-Madan invariance across alpha and (N, eta) ──────────────────────────


def test_carr_madan_invariant_across_alpha() -> None:
    for K in (80.0, 100.0, 120.0):
        prices = [carr_madan_call(_HESTON, 100.0, K, 1.0, alpha=a, v_max=600.0, n=16384)
                  for a in (1.0, 1.25, 1.5, 2.0)]
        assert max(prices) - min(prices) < 1e-5


def test_carr_madan_fft_invariant_across_grid() -> None:
    """Different (N, eta) FFT grids agree at a common ATM strike (interp to K=100)."""
    vals = []
    for N, eta in ((4096, 0.25), (8192, 0.2), (16384, 0.1)):
        strikes, calls = carr_madan_fft(_HESTON, 100.0, 1.0, alpha=1.5, N=N, eta=eta)
        idx = int(np.argmin(np.abs(strikes - 100.0)))
        # Compare at the node's own strike via the direct quadrature (removes strike-grid offset).
        vals.append(carr_madan_call(_HESTON, 100.0, float(strikes[idx]), 1.0, alpha=1.5) - calls[idx])
    assert max(abs(v) for v in vals) < 1e-5


# ── CF vs MC rung (diagnostic full-truncation Euler Heston) ───────────────────


def _heston_mc_call(S0: float, K: float, T: float, model: Heston,
                    n_paths: int, n_steps: int, seed: int) -> tuple[float, float]:
    """DIAGNOSTIC full-truncation Euler Heston MC (Feller violated => full-truncation mandatory).

    Returns (discounted call estimate, standard error). Labelled diagnostic; not decision evidence.
    """
    rng = np.random.default_rng(seed)
    dt = T / n_steps
    logS = np.full(n_paths, math.log(S0))
    v = np.full(n_paths, model.v0)
    rho, sig, kappa, theta = model.rho, model.sigma, model.kappa, model.theta
    for _ in range(n_steps):
        z1 = rng.standard_normal(n_paths)
        z2 = rho * z1 + math.sqrt(1.0 - rho * rho) * rng.standard_normal(n_paths)
        vp = np.maximum(v, 0.0)                       # full truncation
        logS += (model.r - model.q - 0.5 * vp) * dt + np.sqrt(vp * dt) * z1
        v = v + kappa * (theta - vp) * dt + sig * np.sqrt(vp * dt) * z2
    payoff = np.maximum(np.exp(logS) - K, 0.0) * math.exp(-model.r * T)
    return float(np.mean(payoff)), float(np.std(payoff) / math.sqrt(n_paths))


def test_cos_matches_diagnostic_heston_mc_within_k_se() -> None:
    """COS/CF price lies within ~4*SE of a diagnostic full-truncation Euler MC (Euler bias noted)."""
    for K in (90.0, 100.0, 110.0):
        cos = cos_call(_HESTON, 100.0, K, 1.0, N=2048, L=16.0)
        mc, se = _heston_mc_call(100.0, K, 1.0, _HESTON, n_paths=300_000, n_steps=100, seed=42)
        assert abs(cos - mc) < 4.0 * se, f"K={K}: |COS-MC|={abs(cos - mc):.4f} vs 4*SE={4 * se:.4f}"


# ── Consolidated ladder: three independent methods agree ──────────────────────


def test_three_methods_agree_at_a_strike() -> None:
    """COS == Carr-Madan (direct) == Carr-Madan (FFT node) for Heston — the validation ladder."""
    strikes, calls = carr_madan_fft(_HESTON, 100.0, 1.0, alpha=1.5, N=8192, eta=0.2)
    idx = int(np.argmin(np.abs(strikes - 100.0)))
    K = float(strikes[idx])
    cos = cos_call(_HESTON, 100.0, K, 1.0, N=2048, L=16.0)
    cm_direct = carr_madan_call(_HESTON, 100.0, K, 1.0, alpha=1.5, v_max=600.0, n=16384)
    cm_fft = float(calls[idx])
    assert abs(cos - cm_direct) < 1e-5
    assert abs(cos - cm_fft) < 1e-5
