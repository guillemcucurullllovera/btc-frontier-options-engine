"""C9 · M6.0a — rough-Heston CF via the fractional Riccati.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Statistical model-fit only.

Oracles: H=1/2 is EXACTLY the classical Heston (branch-safe closed form); as H->1/2 the fractional
solution converges to it; the fractional-Adams solver converges in the step count; the CF satisfies
the four invariants; and the model reproduces the qualitative rough-vol signature — a steeper
short-dated skew for rougher (smaller-H) surfaces. (Carr-Madan is NOT a usable oracle here: its
damping shift exceeds the rough-Heston analyticity strip — documented.)
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.optimize import brentq

from pricing.black76 import price_black76
from pricing.cf.characteristic_functions import Heston, check_cf_sanity
from pricing.cf.cos import cos_call
from pricing.cf.rough_heston import RoughHeston

_V0, _KAPPA, _THETA, _SIGMA, _RHO = 0.15, 1.5, 0.20, 0.6, -0.3


def _rh(H: float, n_steps: int = 200) -> RoughHeston:
    return RoughHeston(0.0, 0.0, _V0, _KAPPA, _THETA, _SIGMA, _RHO, H, n_steps)


def _heston() -> Heston:
    return Heston(0.0, 0.0, _V0, _KAPPA, _THETA, _SIGMA, _RHO)


def test_rough_reduces_to_heston_at_half() -> None:
    """H = 1/2 (alpha = 1) is exactly the classical Heston CF (branch-safe closed form)."""
    rh = _rh(0.5)
    h = _heston()
    u = np.array([0.5, 1.0, 3.0, -2.0], dtype=np.complex128)
    assert np.max(np.abs(rh.cf(u, 1.0) - h.cf(u, 1.0))) == 0.0


def test_rough_converges_to_heston_as_H_to_half() -> None:
    """As H -> 1/2 the fractional-Riccati CF converges to the classical Heston CF."""
    h = _heston()
    u = np.array([1.0 + 0j, 2.0, 5.0])
    ref = h.cf(u, 1.0)
    errs = [float(np.max(np.abs(_rh(H, 300).cf(u, 1.0) - ref)))
            for H in (0.49, 0.499, 0.4999)]
    assert errs[0] > errs[1] > errs[2]                 # monotone convergence
    assert errs[2] < 1e-5


def test_rough_cf_sanity() -> None:
    """phi(0)=1; |phi|<=1 (real u); conj symmetry; martingale phi(-i)=e^{(r-q)T} for a rough model."""
    s = check_cf_sanity(_rh(0.1, 200), 1.0, u_max=50.0, n=201)
    assert s.phi0_err < 1e-12
    assert s.max_modulus <= 1.0 + 1e-6
    assert s.conj_sym_err < 1e-9
    assert s.martingale_err < 1e-8


def test_fractional_riccati_solver_converges_in_steps() -> None:
    """The fractional-Adams CF converges as the step count grows (solver consistency)."""
    u = np.array([1.0 + 0j])
    ref = _rh(0.15, 800).cf(u, 1.0)[0]
    errs = [abs(_rh(0.15, N).cf(u, 1.0)[0] - ref) for N in (50, 100, 200, 400)]
    assert errs == sorted(errs, reverse=True)          # error decreases with N
    assert errs[-1] < 1e-5


def test_rough_cos_price_n_invariant_and_positive() -> None:
    rh = _rh(0.2, 150)
    prices = [cos_call(rh, 100.0, 100.0, 0.5, N=Nc, L=12.0) for Nc in (128, 256, 512)]
    assert all(p > 0.0 for p in prices)
    assert max(prices) - min(prices) < 1e-4            # COS N-invariance holds for the rough model


def _iv(S0: float, K: float, T: float, kind: str, model: RoughHeston) -> float:
    px = cos_call(model, S0, K, T, N=256, L=16.0)
    if kind == "put":
        px = px - (S0 - K * math.exp(-model.r * T))    # put via parity
    return float(brentq(lambda s: price_black76(S0, K, 0.0, s, T, kind) - px, 0.01, 4.0, xtol=1e-7))


def test_rough_skew_steepens_with_roughness() -> None:
    """The rough-vol signature: a rougher (smaller-H) surface has a STEEPER short-dated skew."""
    T = 0.05
    skews = []
    for H in (0.49, 0.30, 0.10):
        m = _rh(H, 200)
        iv_dn = _iv(100.0, 97.0, T, "put", m)
        iv_up = _iv(100.0, 103.0, T, "call", m)
        skews.append(iv_dn - iv_up)
    assert skews[2] > skews[1] > skews[0]              # rougher => steeper skew
    assert skews[2] > 1.5 * skews[0]


def test_rough_cumulants_finite() -> None:
    c1, c2, c4 = _rh(0.2, 150).cumulants(0.5)
    assert math.isfinite(c1) and c2 > 0.0 and c4 == 0.0
    assert c1 == pytest.approx(0.0 - 0.5 * 0.15 * 0.5, abs=0.02)  # ~ -v0 T/2
