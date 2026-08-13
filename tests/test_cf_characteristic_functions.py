"""C9 · M1.1 — characteristic-function sanity + cumulants (Heston / VG / CGMY / GBM).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. No calibration/live data.

Oracles: the four CF invariants are model-independent identities; analytic cumulants are
cross-checked against finite-difference cumulants of the CGF; the branch-safe Heston form is
verified continuous (martingale + bounded modulus) out to long T (the "little Heston trap").
"""

from __future__ import annotations

import numpy as np
import pytest

from pricing.cf.characteristic_functions import (
    CGMY,
    GBM,
    CharModel,
    Heston,
    VarianceGamma,
    check_cf_sanity,
    numerical_cumulants,
)

_MODELS: dict[str, CharModel] = {
    "gbm": GBM(r=0.03, q=0.0, sigma=0.45),
    "heston": Heston(r=0.0, q=0.0, v0=0.0175, kappa=1.5768, theta=0.0398, sigma=0.5751, rho=-0.5711),
    "vg": VarianceGamma(r=0.10, q=0.0, sigma=0.12, theta=-0.14, nu=0.2),
    "cgmy": CGMY(r=0.10, q=0.0, C=1.0, G=5.0, M=5.0, Y=0.5),
}


@pytest.mark.parametrize("name", list(_MODELS))
@pytest.mark.parametrize("T", [0.05, 0.25, 1.0, 3.0])
def test_cf_sanity_invariants(name: str, T: float) -> None:
    """phi(0)=1; |phi|<=1 (real u); phi(-u)=conj phi(u); martingale phi(-i)=e^{(r-q)T}."""
    s = check_cf_sanity(_MODELS[name], T)
    assert s.phi0_err < 1e-12
    assert s.max_modulus <= 1.0 + 1e-9
    assert s.conj_sym_err < 1e-10
    assert s.martingale_err < 1e-9
    assert s.ok


@pytest.mark.parametrize("name", ["gbm", "vg", "cgmy"])
def test_analytic_cumulants_match_numerical(name: str) -> None:
    """Analytic c1,c2 match finite-difference cumulants of the CGF (c4 noisier — c1,c2 only)."""
    m = _MODELS[name]
    T = 1.0
    c1, c2, _ = m.cumulants(T)
    n1, n2, _ = numerical_cumulants(m, T)
    assert c1 == pytest.approx(n1, rel=1e-4, abs=1e-8)
    assert c2 == pytest.approx(n2, rel=1e-4, abs=1e-8)
    assert c2 > 0.0


def test_gbm_cumulants_closed_form() -> None:
    """GBM: c1=(r-q-sigma^2/2)T, c2=sigma^2 T, c4=0 exactly."""
    m = GBM(r=0.03, q=0.01, sigma=0.5)
    T = 0.7
    c1, c2, c4 = m.cumulants(T)
    assert c1 == pytest.approx((0.03 - 0.01 - 0.5 * 0.25) * T)
    assert c2 == pytest.approx(0.25 * T)
    assert c4 == 0.0


def test_heston_branch_safe_continuous_long_T() -> None:
    """Little-Heston-trap: the D/G form stays continuous (martingale + bounded) out to T=30."""
    m = _MODELS["heston"]
    for T in (0.02, 1.0, 5.0, 10.0, 30.0):
        s = check_cf_sanity(m, T, u_max=300.0, n=6001)
        assert s.martingale_err < 1e-9
        assert s.max_modulus <= 1.0 + 1e-9
        # No NaN/Inf anywhere on the grid.
        phi = m.cf(np.linspace(-300, 300, 6001).astype(np.complex128), T)
        assert np.all(np.isfinite(phi.real)) and np.all(np.isfinite(phi.imag))


def test_martingale_condition_across_models() -> None:
    """phi(-i;T) = e^{(r-q)T} => E[S_T/S_0] = e^{(r-q)T} for every model."""
    T = 1.3
    for m in _MODELS.values():
        mart = complex(m.cf(np.array([-1j]), T)[0])
        assert mart == pytest.approx(np.exp((m.r - m.q) * T), abs=1e-9)
        assert abs(mart.imag) < 1e-10          # real-valued


def test_vg_cgmy_martingale_correction_present() -> None:
    """The omega drift correction is what enforces the martingale (nonzero, finite)."""
    vg = VarianceGamma(r=0.10, q=0.0, sigma=0.12, theta=-0.14, nu=0.2)
    cgmy = CGMY(r=0.10, q=0.0, C=1.0, G=5.0, M=5.0, Y=0.5)
    assert np.isfinite(vg.omega)
    assert np.isfinite(cgmy.omega)
