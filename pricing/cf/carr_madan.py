"""Carr-Madan FFT pricer — the CF validation oracle (C9 · M1.3).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Carr & Madan (1999), "Option
valuation using the fast Fourier transform". An INDEPENDENT numerical method over the same model
CF as COS, so COS-vs-Carr-Madan agreement validates both against numerical error.

Damped call transform (damping alpha ~ 1.0-1.5 for calls):
    psi(v) = e^{-rT} phi_T(v - (alpha+1) i) / (alpha^2 + alpha - v^2 + i(2 alpha + 1) v)
    C(k)   = e^{-alpha k} / pi * ∫_0^inf Re{ e^{-i v k} psi(v) } dv,   k = ln K,
where phi_T(u) = E[e^{i u ln S_T}] = e^{i u ln S0} * phi_R(u) is the log-PRICE CF.

Two entry points: ``carr_madan_call`` (direct quadrature, accurate at a single strike, used as the
oracle) and ``carr_madan_fft`` (the classic FFT over a log-strike grid, with lambda*eta = 2pi/N).
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from pricing.cf.characteristic_functions import CharModel

Complex = npt.NDArray[np.complex128]
FloatArr = npt.NDArray[np.float64]


def _phi_logprice(model: CharModel, u: Complex, S0: float, T: float) -> Complex:
    """Log-PRICE CF phi_T(u) = e^{i u ln S0} * phi_R(u)."""
    return np.asarray(np.exp(1j * u * math.log(S0)) * model.cf(u, T), dtype=np.complex128)


def _psi(model: CharModel, v: FloatArr, S0: float, T: float, alpha: float) -> Complex:
    """Carr-Madan damped-call Fourier transform psi(v)."""
    u = (v - (alpha + 1.0) * 1j).astype(np.complex128)
    numer = math.exp(-model.r * T) * _phi_logprice(model, u, S0, T)
    denom = alpha * alpha + alpha - v * v + 1j * (2.0 * alpha + 1.0) * v
    return np.asarray(numer / denom, dtype=np.complex128)


def carr_madan_call(model: CharModel, S0: float, K: float, T: float,
                    alpha: float = 1.5, v_max: float = 400.0, n: int = 8192) -> float:
    """Single-strike European call via direct quadrature of the Carr-Madan integral (oracle)."""
    dv = v_max / n
    v = (np.arange(n, dtype=np.float64) + 0.5) * dv        # midpoint rule (avoids v=0 pole handling)
    k = math.log(K)
    integrand = np.real(np.exp(-1j * v * k) * _psi(model, v, S0, T, alpha))
    integral = float(np.sum(integrand) * dv)
    return math.exp(-alpha * k) / math.pi * integral


def carr_madan_fft(model: CharModel, S0: float, T: float, alpha: float = 1.5,
                   N: int = 4096, eta: float = 0.25) -> tuple[FloatArr, FloatArr]:
    """Classic Carr-Madan FFT: returns (strikes, call_prices) on the log-strike grid.

    lambda * eta = 2 pi / N; strikes are centred (b = N lambda / 2) around the forward log-strike.
    Simpson weights improve the quadrature accuracy.
    """
    lam = 2.0 * math.pi / (N * eta)
    b = N * lam / 2.0
    j = np.arange(N, dtype=np.float64)
    v = eta * j
    # Simpson weights (0-indexed): eta/3 * [3 + (-1)^{j+1} - delta_{j0}] => pattern 1,4,2,4,...,4.
    simpson = 3.0 + (-1.0) ** (j + 1.0)
    simpson[0] -= 1.0
    weights = eta / 3.0 * simpson
    psi = _psi(model, v, S0, T, alpha)
    fft_in = np.exp(1j * b * v) * psi * weights
    fft_out = np.fft.fft(fft_in)
    k = -b + lam * j
    call = np.exp(-alpha * k) / math.pi * np.real(fft_out)
    return np.exp(k), call


def carr_madan_call_grid(model: CharModel, S0: float, strikes: FloatArr, T: float,
                         alpha: float = 1.5, v_max: float = 400.0, n: int = 8192) -> FloatArr:
    """Direct-quadrature call prices at an explicit array of strikes (oracle, vectorised)."""
    return np.array([carr_madan_call(model, S0, float(K), T, alpha, v_max, n) for K in strikes],
                    dtype=np.float64)
