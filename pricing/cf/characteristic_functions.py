"""Model characteristic functions + cumulants for the CF pricing spine (C9 · M1.1).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. NO calibration / live data
here — M1 validates the pricers against analytical / published / FFT / MC oracles; live-smile
calibration is M2.

Each model exposes the characteristic function of the log-return R = ln(S_T / S_0) under the
risk-neutral measure (drift r-q, martingale-corrected):

    phi(u; T) = E[ exp(i u R) ],   u possibly complex.

CF sanity contract (verified in tests): phi(0)=1; |phi(u)|<=1 for real u; phi(-u)=conj(phi(u))
for real u; martingale phi(-i; T) = exp((r-q)T) (i.e. E[S_T/S_0] = e^{(r-q)T}).

Heston uses the branch-safe "little Heston trap" D/G form (Albrecher-Mayer-Schoutens-Tistaert
2007; Gatheral): d via the principal square root (numpy => Re(d)>=0) and g = (b-d)/(b+d) (NOT
1/g), so the complex log stays off its branch cut and the integrand is continuous for long T.

References: Heston (1993); Albrecher et al. (2007); Fang & Oosterlee (2008); Madan-Carr-Chang
(VG, 1998); Carr-Geman-Madan-Yor (CGMY, 2002); Hirsa, *Computational Methods in Finance* Ch.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
from scipy.special import gamma as _gamma

Complex = npt.NDArray[np.complex128]
CumTuple = tuple[float, float, float]


@runtime_checkable
class CharModel(Protocol):
    """A log-return characteristic-function model: phi(u,T) and cumulants (c1,c2,c4)."""

    @property
    def r(self) -> float: ...
    @property
    def q(self) -> float: ...

    def cf(self, u: complex | Complex, T: float) -> Complex: ...
    def cumulants(self, T: float) -> CumTuple: ...


def _as_complex(u: complex | Complex) -> Complex:
    return np.asarray(u, dtype=np.complex128)


# ── Numerical cumulants (model-agnostic cross-check / fallback) ───────────────


def numerical_cumulants(model: CharModel, T: float, h: float = 1e-3) -> CumTuple:
    """(c1,c2,c4) from finite differences of the CGF K(w)=ln phi(-i w; T) at w=0.

    phi(-i w) = E[e^{w R}] is the MGF; K = ln MGF is the cumulant generating function, and
    c_n = K^{(n)}(0). Central stencils; c4 uses the 5-point 4th-difference (noisier — used only
    for the COS truncation width, not price precision).
    """
    def K(w: float) -> float:
        val = model.cf(np.array([-1j * w], dtype=np.complex128), T)[0]
        return float(np.log(val).real)

    c1 = (K(h) - K(-h)) / (2.0 * h)
    c2 = (K(h) - 2.0 * K(0.0) + K(-h)) / (h * h)
    c4 = (K(2 * h) - 4 * K(h) + 6 * K(0.0) - 4 * K(-h) + K(-2 * h)) / (h ** 4)
    return c1, c2, c4


# ── GBM (Black-Scholes) ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class GBM:
    r: float
    q: float
    sigma: float

    def cf(self, u: complex | Complex, T: float) -> Complex:
        u = _as_complex(u)
        mu = self.r - self.q - 0.5 * self.sigma * self.sigma
        return np.exp(1j * u * mu * T - 0.5 * self.sigma * self.sigma * u * u * T)

    def cumulants(self, T: float) -> CumTuple:
        mu = self.r - self.q - 0.5 * self.sigma * self.sigma
        return mu * T, self.sigma * self.sigma * T, 0.0


# ── Heston (stochastic volatility), branch-safe ──────────────────────────────


@dataclass(frozen=True)
class Heston:
    r: float
    q: float
    v0: float       # initial variance
    kappa: float    # mean-reversion speed
    theta: float    # long-run variance
    sigma: float    # vol-of-vol
    rho: float      # spot/vol correlation

    def cf(self, u: complex | Complex, T: float) -> Complex:
        u = _as_complex(u)
        kappa, theta, sig, rho, v0 = self.kappa, self.theta, self.sigma, self.rho, self.v0
        b = kappa - 1j * rho * sig * u                       # xi = kappa - i rho sigma u
        # d = sqrt(b^2 + sigma^2 (u^2 + i u)); numpy principal root => Re(d) >= 0.
        d = np.sqrt(b * b + sig * sig * (u * u + 1j * u))
        g = (b - d) / (b + d)                                # "little-trap" g2 (NOT 1/g)
        exp_dt = np.exp(-d * T)
        one_m_g_exp = 1.0 - g * exp_dt
        # C (drift-free) and D (v0 coefficient).
        C = (kappa * theta / (sig * sig)) * (
            (b - d) * T - 2.0 * np.log(one_m_g_exp / (1.0 - g))
        )
        D = ((b - d) / (sig * sig)) * (1.0 - exp_dt) / one_m_g_exp
        return np.exp(1j * u * (self.r - self.q) * T + C + D * v0)

    def cumulants(self, T: float) -> CumTuple:
        # c1, c2 numerically (robust); c4 = 0 with a larger COS L (per M1 brief) — the
        # closed-form Heston c4 is not needed and its transcription is error-prone.
        c1, c2, _ = numerical_cumulants(self, T)
        return c1, c2, 0.0


# ── Variance Gamma ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VarianceGamma:
    r: float
    q: float
    sigma: float    # diffusion vol of the time-changed BM
    theta: float    # drift of the BM
    nu: float       # variance rate of the Gamma subordinator

    @property
    def omega(self) -> float:
        """Martingale correction so phi(-i,T)=e^{(r-q)T}."""
        return float((1.0 / self.nu) * np.log(1.0 - self.theta * self.nu - 0.5 * self.sigma ** 2 * self.nu))

    def cf(self, u: complex | Complex, T: float) -> Complex:
        u = _as_complex(u)
        drift = 1j * u * (self.r - self.q + self.omega) * T
        bracket = 1.0 - 1j * u * self.theta * self.nu + 0.5 * self.sigma ** 2 * self.nu * u * u
        return np.exp(drift) * bracket ** (-T / self.nu)

    def cumulants(self, T: float) -> CumTuple:
        s2, th, nu = self.sigma ** 2, self.theta, self.nu
        c1 = (self.r - self.q + self.omega + th) * T
        c2 = (s2 + nu * th * th) * T
        c4 = 3.0 * (s2 * s2 * nu + 2.0 * th ** 4 * nu ** 3 + 4.0 * s2 * th * th * nu * nu) * T
        return c1, c2, c4


# ── CGMY ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CGMY:
    r: float
    q: float
    C: float
    G: float
    M: float
    Y: float        # in (0,2), Y != 1

    @property
    def omega(self) -> float:
        """Martingale correction so phi(-i,T)=e^{(r-q)T}."""
        gY = float(_gamma(-self.Y))
        return float(-self.C * gY * (
            (self.M - 1.0) ** self.Y - self.M ** self.Y
            + (self.G + 1.0) ** self.Y - self.G ** self.Y
        ))

    def cf(self, u: complex | Complex, T: float) -> Complex:
        u = _as_complex(u)
        gY = float(_gamma(-self.Y))
        expo = self.C * T * gY * (
            (self.M - 1j * u) ** self.Y - self.M ** self.Y
            + (self.G + 1j * u) ** self.Y - self.G ** self.Y
        )
        return np.asarray(np.exp(1j * u * (self.r - self.q + self.omega) * T + expo),
                          dtype=np.complex128)

    def cumulants(self, T: float) -> CumTuple:
        C, G, M, Y = self.C, self.G, self.M, self.Y
        c1 = (self.r - self.q + self.omega) * T + C * T * _gamma(1.0 - Y) * (M ** (Y - 1.0) - G ** (Y - 1.0))
        c2 = C * T * _gamma(2.0 - Y) * (M ** (Y - 2.0) + G ** (Y - 2.0))
        c4 = C * T * _gamma(4.0 - Y) * (M ** (Y - 4.0) + G ** (Y - 4.0))
        return float(c1), float(c2), float(c4)


# ── CF sanity checks (used by tests and as a runtime guard) ──────────────────


@dataclass(frozen=True)
class CfSanity:
    phi0_err: float           # |phi(0) - 1|
    max_modulus: float        # max |phi(u)| over the real-u grid (<= 1 + tol)
    conj_sym_err: float       # max |phi(-u) - conj(phi(u))|
    martingale_err: float     # |phi(-i) - e^{(r-q)T}|

    @property
    def ok(self) -> bool:
        return (self.phi0_err < 1e-12 and self.max_modulus <= 1.0 + 1e-9
                and self.conj_sym_err < 1e-10 and self.martingale_err < 1e-9)


def check_cf_sanity(model: CharModel, T: float, u_max: float = 200.0, n: int = 4001) -> CfSanity:
    """Evaluate the four CF invariants on a real-u grid plus the martingale point u=-i."""
    u = np.linspace(-u_max, u_max, n)
    phi = model.cf(u.astype(np.complex128), T)
    phi0 = model.cf(np.array([0.0 + 0j]), T)[0]
    phi_neg = model.cf((-u).astype(np.complex128), T)
    mart = model.cf(np.array([-1j]), T)[0]
    return CfSanity(
        phi0_err=float(abs(phi0 - 1.0)),
        max_modulus=float(np.max(np.abs(phi))),
        conj_sym_err=float(np.max(np.abs(phi_neg - np.conjugate(phi)))),
        martingale_err=float(abs(mart - np.exp((model.r - model.q) * T))),
    )
