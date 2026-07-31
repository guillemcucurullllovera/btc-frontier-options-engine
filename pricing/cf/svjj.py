"""Asymmetric price-vol co-jump SV model (SVJJ) — CF via the M1 spine (C10 · N1).

SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED jumps; canonical main untouched. Extends the Bates block
to a faithful DOWNSIDE tail:

  * PRICE jump: a separate up/down lognormal mixture (double-normal on the log-jump) — chosen over Kou by
    fit (AIC -51 vs -33 on the full-history realized jumps; it matches the empirical std 0.137 AND the
    extreme quantile q0.1% ~ -0.48 vs observed worst -0.50, where Kou over-extrapolates to -0.84). Captures
    the downside SIZE asymmetry (tightly-clustered up-jumps ~+10%, wider/heavier down-jumps).
  * VOL co-jump: a contemporaneous exponential variance jump xi^v ~ Exp(mu_v) arriving with the SAME
    Poisson(lambda) as the price jump -> volatility spikes coincide with the (down-skewed) price jumps,
    i.e. the rho_J<0 leverage effect (Phase C robust signal).

CF (affine / Duffie-Pan-Singleton): phi(u,T) = exp(iu mu T + C_H + D_H v0 + A_J), with the Heston C_H, D_H
closed-form and the jump contribution A_J = lambda * int_0^T [phi_price(u) * phi_volj(D_H(tau)) - 1] dtau
(phi_volj(D)=1/(1-mu_v D) for the exp vol-jump), integrated by Gauss-Legendre quadrature since D_H(tau)
is closed-form. Reductions: lambda=0 -> Heston exactly; mu_v=0 -> asymmetric-jump Bates (factorised).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pricing.cf.characteristic_functions import Heston, numerical_cumulants

Complex = npt.NDArray[np.complex128]
CumTuple = tuple[float, float, float]

# Gauss-Legendre nodes/weights on [0,1] for the A_J time-integral (128-pt: accurate + fast).
_GL_X, _GL_W = np.polynomial.legendre.leggauss(128)
_GL_X = 0.5 * (_GL_X + 1.0)              # map [-1,1] -> [0,1]
_GL_W = 0.5 * _GL_W


@dataclass(frozen=True)
class DoubleNormalJump:
    """Separate up/down lognormal price-jump mixture (double-normal on the log-jump size)."""
    p_up: float          # P(jump drawn from the up component)
    mu_up: float
    sig_up: float
    mu_dn: float
    sig_dn: float
    provenance: str = "P-ESTIMATED"

    def transform(self, u: Complex) -> Complex:
        """phi_price(u) = E[exp(iu J)] for the mixture (closed form)."""
        up = np.exp(1j * u * self.mu_up - 0.5 * self.sig_up ** 2 * u * u)
        dn = np.exp(1j * u * self.mu_dn - 0.5 * self.sig_dn ** 2 * u * u)
        return np.asarray(self.p_up * up + (1.0 - self.p_up) * dn, dtype=np.complex128)

    @property
    def kappa_price(self) -> float:
        """Price-jump compensator E[e^J]-1 = phi_price(-i)-1."""
        up = math.exp(self.mu_up + 0.5 * self.sig_up ** 2)
        dn = math.exp(self.mu_dn + 0.5 * self.sig_dn ** 2)
        return float(self.p_up * up + (1.0 - self.p_up) * dn - 1.0)

    def sample(self, rng: np.random.Generator, shape: tuple[int, ...]) -> npt.NDArray[np.float64]:
        up = rng.random(shape) < self.p_up
        return np.where(up, rng.normal(self.mu_up, self.sig_up, shape),
                        rng.normal(self.mu_dn, self.sig_dn, shape))


def fit_double_normal(jump_returns: npt.NDArray[np.float64]) -> DoubleNormalJump:
    """MLE fit of the up/down lognormal mixture to observed (P-measure) realized-jump log-returns."""
    from scipy.optimize import minimize
    jr = np.asarray(jump_returns, dtype=np.float64)

    def nll(par: npt.NDArray[np.float64]) -> float:
        p, mu_u, su, mu_d, sd = par
        if not (0.02 < p < 0.98 and su > 1e-3 and sd > 1e-3):
            return 1e12
        pdf = (p * np.exp(-0.5 * ((jr - mu_u) / su) ** 2) / (su * math.sqrt(2 * math.pi))
               + (1 - p) * np.exp(-0.5 * ((jr - mu_d) / sd) ** 2) / (sd * math.sqrt(2 * math.pi)))
        return float(-np.sum(np.log(np.maximum(pdf, 1e-300))))

    x0 = np.array([0.5, 0.10, 0.04, -0.09, 0.13])
    sol = minimize(nll, x0, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-9, "maxiter": 8000})
    p, mu_u, su, mu_d, sd = (float(x) for x in sol.x)
    # convention: the "up" component is the one with the larger mean (keeps mu_up>mu_dn).
    if mu_u < mu_d:
        p, mu_u, su, mu_d, sd = 1.0 - p, mu_d, sd, mu_u, su
    return DoubleNormalJump(p_up=p, mu_up=mu_u, sig_up=abs(su), mu_dn=mu_d, sig_dn=abs(sd))


def _heston_D(u: Complex, tau: float, kappa: float, sigma: float, rho: float) -> Complex:
    """Heston D(tau) (the v0 coefficient of the Riccati), closed form (little-trap g)."""
    b = kappa - 1j * rho * sigma * u
    d = np.sqrt(b * b + sigma * sigma * (u * u + 1j * u))
    g = (b - d) / (b + d)
    exp_dt = np.exp(-d * tau)
    return np.asarray(((b - d) / (sigma * sigma)) * (1.0 - exp_dt) / (1.0 - g * exp_dt), dtype=np.complex128)


@dataclass(frozen=True)
class SVJJ:
    """Heston SV + asymmetric price jump + contemporaneous exponential vol co-jump."""
    mu: float            # physical (or r-q) drift of log-price
    v0: float
    kappa: float
    theta: float
    sigma: float         # vol-of-vol
    rho: float
    lam: float           # co-jump intensity (per year)
    jump: DoubleNormalJump
    mu_v: float          # mean of the exponential variance co-jump xi^v ~ Exp(mu_v)
    provenance: str = "P-ESTIMATED"

    @property
    def r(self) -> float:                 # CharModel protocol: mu plays the r-q drift role here
        return self.mu

    @property
    def q(self) -> float:
        return 0.0

    @property
    def _heston(self) -> Heston:
        # r-q carries the physical drift mu (Heston C/D are drift-free; drift added as iu*mu*T).
        return Heston(self.mu, 0.0, self.v0, self.kappa, self.theta, self.sigma, self.rho)

    def cf(self, u: complex | Complex, T: float) -> Complex:
        uu = np.atleast_1d(np.asarray(u, dtype=np.complex128))
        base = self._heston.cf(uu, T)                        # exp(iu mu T + C_H + D_H v0)
        if self.lam <= 0.0:
            return np.asarray(base, dtype=np.complex128)
        phi_p = self.jump.transform(uu)                      # (M,)
        # A_J = lambda * int_0^T [phi_price * phi_volj(D(tau)) - 1] dtau  -  iu*lambda*kappa_price*T
        taus = _GL_X * T                                     # (Q,) quadrature nodes in [0,T]
        integ = np.zeros_like(uu)
        for xq, wq in zip(taus, _GL_W * T, strict=True):
            D = _heston_D(uu, float(xq), self.kappa, self.sigma, self.rho)
            phi_volj = 1.0 / (1.0 - self.mu_v * D)           # exp vol-jump transform E[e^{D xi^v}]
            integ = integ + wq * (phi_p * phi_volj - 1.0)
        a_j = self.lam * integ - 1j * uu * self.lam * self.jump.kappa_price * T
        with np.errstate(over="ignore", invalid="ignore"):
            phi = base * np.exp(a_j)
        return np.asarray(np.where(np.isfinite(phi), phi, 0.0), dtype=np.complex128)

    def cumulants(self, T: float) -> CumTuple:
        c1, c2, _ = numerical_cumulants(self, T)
        return c1, c2, 0.0
