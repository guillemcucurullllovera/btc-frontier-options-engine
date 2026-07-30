"""Rough-Heston characteristic function via the fractional Riccati (C9 · M6.0a).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Statistical model-fit only (not an
MS-25 claim). Implements the El Euch-Rosenbaum (2018) rough-Heston CF, whose only difference from the
classical Heston CF is that the Riccati ODE becomes a FRACTIONAL Riccati of order alpha = H + 1/2:

    E[exp(i a X_T)] = exp( g1(a,T) + V0 g2(a,T) ),
        g1(a,T) = kappa*theta * I^1 h(a,T),   g2(a,T) = I^{1-alpha} h(a,T),
    D^alpha h = 1/2(-a^2 - i a) + (i a rho sigma - kappa) h + (sigma^2/2) h^2,   I^{1-alpha}h(a,0)=0,

with sigma the vol-of-vol, kappa the mean-reversion, theta the long-run variance, rho the correlation,
and H the Hurst exponent (H=1/2 => alpha=1 => classical Heston; H<1/2 => rough). The fractional Riccati
is solved by the fractional Adams-Bashforth-Moulton predictor-corrector (Diethelm-Ford-Freed 2002;
Jeng-Kilicman 2020, symmetry-12-00959), vectorised across the CF argument grid. The CF prices through
the M1 COS pricer on the observed forward (r=q=0, the Deribit/B3 convention).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.special import gamma as _gamma

from pricing.cf.characteristic_functions import Heston, numerical_cumulants

Complex = npt.NDArray[np.complex128]
CumTuple = tuple[float, float, float]


def solve_fractional_riccati(
    b_const: Complex, b_lin: Complex, b_quad: complex, alpha: float, T: float, n_steps: int,
) -> Complex:
    """Fractional Adams (predictor-corrector) for D^alpha h = b_const + b_lin h + b_quad h^2.

    Vectorised across the CF-argument grid (b_const, b_lin are (M,) complex; b_quad scalar). Returns
    the full history h of shape (n_steps+1, M) (needed for the fractional integrals I^1 and I^{1-alpha}).
    """
    dt = T / n_steps
    dta = dt ** alpha
    g_a = float(_gamma(alpha))
    g_a2 = float(_gamma(alpha + 2.0))
    m = b_const.shape[0]

    def F(h: Complex) -> Complex:
        return np.asarray(b_const + b_lin * h + b_quad * h * h, dtype=np.complex128)

    h = np.zeros((n_steps + 1, m), dtype=np.complex128)
    Fh = np.zeros((n_steps + 1, m), dtype=np.complex128)
    Fh[0] = F(h[0])                                   # F(0) = b_const
    kpow = np.arange(n_steps + 2, dtype=np.float64) ** alpha           # k^alpha cache
    kpow1 = np.arange(n_steps + 2, dtype=np.float64) ** (alpha + 1.0)  # k^(alpha+1) cache
    for n in range(1, n_steps + 1):
        # Predictor weights b_{j,n} = dt^a/a * ((n-j)^a - (n-j-1)^a), j=0..n-1 (k=n-j).
        k = np.arange(1, n + 1)
        bw = (dta / alpha) * (kpow[k] - kpow[k - 1])          # indexed by k=n-j
        pred = (bw[::-1][:, None] * Fh[:n]).sum(axis=0) / g_a  # sum_j b_{n-j} F_j
        hP = pred
        # Corrector a-weights.
        aw = np.empty(n, dtype=np.float64)
        aw[0] = kpow1[n - 1] - (n - 1 - alpha) * kpow[n]
        if n > 1:
            jj = np.arange(1, n)
            aw[1:] = kpow1[n - jj + 1] + kpow1[n - jj - 1] - 2.0 * kpow1[n - jj]
        corr = (aw[:, None] * Fh[:n]).sum(axis=0)
        h[n] = (dta / g_a2) * (F(hP) + corr)
        Fh[n] = F(h[n])
    return h


def _fractional_integral_at_T(h: Complex, beta: float, T: float, n_steps: int) -> Complex:
    """I^beta h(T) = 1/Gamma(beta) int_0^T (T-s)^{beta-1} h(s) ds, product-trapezoidal weights."""
    dt = T / n_steps
    dtb = dt ** beta
    g_b2 = float(_gamma(beta + 2.0))
    idx = np.arange(n_steps + 2, dtype=np.float64)
    ip1 = idx ** (beta + 1.0)
    w = np.empty(n_steps + 1, dtype=np.float64)
    w[0] = ip1[n_steps - 1] - (n_steps - 1 - beta) * (n_steps ** beta) if n_steps >= 1 else 0.0
    if n_steps > 1:
        jj = np.arange(1, n_steps)
        w[jj] = ip1[n_steps - jj + 1] + ip1[n_steps - jj - 1] - 2.0 * ip1[n_steps - jj]
    w[n_steps] = 1.0
    return np.asarray((dtb / g_b2) * (w[:, None] * h).sum(axis=0), dtype=np.complex128)


@dataclass(frozen=True)
class RoughHeston:
    r: float
    q: float
    v0: float
    kappa: float
    theta: float
    sigma: float        # vol-of-vol
    rho: float
    H: float            # Hurst exponent in (0, 1/2]; H=1/2 => classical Heston
    n_steps: int = 200  # fractional-Riccati grid resolution

    @property
    def alpha(self) -> float:
        return self.H + 0.5

    def cf(self, u: complex | Complex, T: float) -> Complex:
        uu = np.atleast_1d(np.asarray(u, dtype=np.complex128))
        # H = 1/2 is exactly classical Heston (alpha=1) — use the branch-safe closed form.
        if abs(self.alpha - 1.0) < 1e-12:
            return Heston(self.r, self.q, self.v0, self.kappa, self.theta, self.sigma, self.rho).cf(uu, T)

        alpha = self.alpha
        b_const = 0.5 * (-uu * uu - 1j * uu)
        b_lin = 1j * uu * self.rho * self.sigma - self.kappa
        b_quad = 0.5 * self.sigma * self.sigma
        # The fractional Riccati can overflow for the deep-tail (large |u|) arguments where the true
        # CF magnitude is ~0; solve under errstate and set any non-finite tail entry to 0 (|phi|->0).
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            h = solve_fractional_riccati(b_const, b_lin, complex(b_quad), alpha, T, self.n_steps)
            g1 = self.kappa * self.theta * _fractional_integral_at_T(h, 1.0, T, self.n_steps)
            g2 = _fractional_integral_at_T(h, 1.0 - alpha, T, self.n_steps)
            phi = np.exp(1j * uu * (self.r - self.q) * T + g1 + self.v0 * g2)
        # Non-finite entries are the deep real-u tail (|phi|->0); zero them. NOTE: do NOT clip |phi|<=1
        # — that bound holds only for REAL u; cumulants evaluate at imaginary u where the MGF exceeds 1.
        return np.asarray(np.where(np.isfinite(phi), phi, 0.0), dtype=np.complex128)

    def cumulants(self, T: float) -> CumTuple:
        c1, c2, _ = numerical_cumulants(self, T)
        return c1, c2, 0.0
