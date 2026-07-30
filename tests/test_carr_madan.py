"""C9 · M1.3 — Carr-Madan FFT validation oracle.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. No calibration/live data.

Carr-Madan is an INDEPENDENT numerical method over the same model CF as COS. Oracles:
direct quadrature vs Black-Scholes (GBM) to ~machine eps; direct + FFT vs COS for Heston/VG at
high N; damping-alpha robustness. COS-vs-Carr-Madan agreement validates both against numerical error.
"""

from __future__ import annotations

import numpy as np
import pytest

from pricing.black_scholes import price as bs_price
from pricing.cf.carr_madan import carr_madan_call, carr_madan_call_grid, carr_madan_fft
from pricing.cf.characteristic_functions import GBM, Heston, VarianceGamma
from pricing.cf.cos import cos_call

_HESTON = Heston(r=0.0, q=0.0, v0=0.0175, kappa=1.5768, theta=0.0398, sigma=0.5751, rho=-0.5711)
_VG = VarianceGamma(r=0.1, q=0.0, sigma=0.12, theta=-0.14, nu=0.2)


def test_carr_madan_direct_matches_black_scholes() -> None:
    m = GBM(r=0.05, q=0.0, sigma=0.25)
    max_err = 0.0
    for T in (0.25, 1.0, 2.0):
        for K in (80.0, 100.0, 120.0):
            err = abs(carr_madan_call(m, 100.0, K, T, alpha=1.5) - bs_price(100.0, K, 0.05, 0.25, T, "call"))
            max_err = max(max_err, err)
    assert max_err < 1e-10, f"max |CM-BS| = {max_err:.2e}"


def test_carr_madan_direct_matches_cos_heston() -> None:
    """Two independent CF methods (Carr-Madan quadrature vs COS) agree for Heston."""
    max_err = 0.0
    for K in (70.0, 85.0, 100.0, 115.0, 130.0):
        cm = carr_madan_call(_HESTON, 100.0, K, 1.0, alpha=1.5, v_max=600.0, n=16384)
        co = cos_call(_HESTON, 100.0, K, 1.0, N=2048, L=16.0)
        max_err = max(max_err, abs(cm - co))
    assert max_err < 1e-5, f"max |CM-COS Heston| = {max_err:.2e}"


def test_carr_madan_direct_matches_cos_vg() -> None:
    max_err = 0.0
    for K in (80.0, 90.0, 100.0, 110.0):
        cm = carr_madan_call(_VG, 100.0, K, 1.0, alpha=1.5, v_max=600.0, n=16384)
        co = cos_call(_VG, 100.0, K, 1.0, N=1024, L=12.0)
        max_err = max(max_err, abs(cm - co))
    assert max_err < 1e-5, f"max |CM-COS VG| = {max_err:.2e}"


def test_carr_madan_fft_matches_cos_at_grid_nodes() -> None:
    """The classic FFT (Simpson-weighted) matches COS at its own strike nodes (high N)."""
    strikes, calls = carr_madan_fft(_HESTON, 100.0, 1.0, alpha=1.5, N=8192, eta=0.2)
    max_err = 0.0
    for target in (80.0, 100.0, 120.0):
        idx = int(np.argmin(np.abs(strikes - target)))
        K = float(strikes[idx])
        co = cos_call(_HESTON, 100.0, K, 1.0, N=2048, L=16.0)
        max_err = max(max_err, abs(calls[idx] - co))
    assert max_err < 1e-5, f"max |FFT-COS| = {max_err:.2e}"


def test_carr_madan_fft_matches_direct_quadrature() -> None:
    """FFT and direct quadrature (same method, two implementations) agree at grid nodes."""
    strikes, calls = carr_madan_fft(_HESTON, 100.0, 1.0, alpha=1.5, N=8192, eta=0.2)
    idx = int(np.argmin(np.abs(strikes - 100.0)))
    K = float(strikes[idx])
    direct = carr_madan_call(_HESTON, 100.0, K, 1.0, alpha=1.5, v_max=600.0, n=16384)
    assert calls[idx] == pytest.approx(direct, abs=1e-5)


def test_carr_madan_alpha_robustness() -> None:
    """The damped-call price is invariant to the damping alpha in [1.0, 1.5] (calls)."""
    prices = [carr_madan_call(_HESTON, 100.0, 100.0, 1.0, alpha=a, v_max=600.0, n=16384)
              for a in (1.0, 1.25, 1.5)]
    assert max(prices) - min(prices) < 1e-5


def test_carr_madan_grid_helper_vectorised() -> None:
    ks = np.array([90.0, 100.0, 110.0])
    grid = carr_madan_call_grid(_VG, 100.0, ks, 1.0, alpha=1.5, v_max=600.0, n=16384)
    for i, K in enumerate(ks):
        assert grid[i] == pytest.approx(cos_call(_VG, 100.0, float(K), 1.0, N=1024, L=12.0), abs=1e-5)
