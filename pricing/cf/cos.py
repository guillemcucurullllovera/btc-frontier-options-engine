"""COS Fourier-cosine pricer — the primary CF pricer (C9 · M1.2).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Fang & Oosterlee (2008),
"A Novel Pricing Method for European Options Based on Fourier-Cosine Series Expansions".

Convention: y = ln(S_T / K); the CF of y is phi_y(u) = e^{i u x} phi_R(u) with x = ln(S0/K)
and phi_R = model.cf (the log-return CF). The cosine coefficients of the payoff use the closed
forms chi_k (for e^y) and psi_k (for 1). Truncation [a,b] = c1 +/- L*sqrt(c2 + sqrt(c4)) from the
cumulants of y (Fang-Oosterlee Eq. 49); c4=0 fallback uses a larger L.

The CALL is priced as PUT + put-call parity: the call payoff coefficients suffer catastrophic
cancellation for large y (the e^y term), whereas the put integrand is bounded on [a,0]. Digitals
are exposed too (Vk = psi_k over the in-the-money region).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pricing.cf.characteristic_functions import CharModel

FloatArr = npt.NDArray[np.float64]


@dataclass(frozen=True)
class CosGrid:
    """The COS truncation range and node count actually used (for diagnostics/invariance)."""

    a: float
    b: float
    N: int
    L: float


def cos_truncation(model: CharModel, S0: float, K: float, T: float, L: float) -> tuple[float, float]:
    """[a,b] for y=ln(S_T/K): cumulants of y = (x + c1_R, c2_R, c4_R), x=ln(S0/K)."""
    c1, c2, c4 = model.cumulants(T)
    x = math.log(S0 / K)
    c1y = x + c1
    width = L * math.sqrt(abs(c2) + math.sqrt(max(c4, 0.0)))
    return c1y - width, c1y + width


def _chi(k: FloatArr, a: float, b: float, c: float, d: float) -> FloatArr:
    """chi_k(c,d) = ∫_c^d e^y cos(k*pi*(y-a)/(b-a)) dy  (Fang-Oosterlee closed form)."""
    w = k * math.pi / (b - a)
    fac = 1.0 / (1.0 + w * w)
    cos_d = np.cos(w * (d - a))
    cos_c = np.cos(w * (c - a))
    sin_d = np.sin(w * (d - a))
    sin_c = np.sin(w * (c - a))
    return fac * (cos_d * math.exp(d) - cos_c * math.exp(c)
                  + w * sin_d * math.exp(d) - w * sin_c * math.exp(c))


def _psi(k: FloatArr, a: float, b: float, c: float, d: float) -> FloatArr:
    """psi_k(c,d) = ∫_c^d cos(k*pi*(y-a)/(b-a)) dy; psi_0 = d-c."""
    w = k * math.pi / (b - a)
    out = np.empty_like(k)
    out[0] = d - c
    wk = w[1:]
    out[1:] = (np.sin(wk * (d - a)) - np.sin(wk * (c - a))) / wk
    return out


def _fk(model: CharModel, S0: float, K: float, T: float, a: float, b: float, N: int) -> FloatArr:
    """F_k = Re{ phi_R(w_k) * exp(i w_k (x - a)) }, w_k = k*pi/(b-a), x = ln(S0/K)."""
    k = np.arange(N, dtype=np.float64)
    w = k * math.pi / (b - a)
    x = math.log(S0 / K)
    phi = model.cf(w.astype(np.complex128), T)
    return np.real(phi * np.exp(1j * w * (x - a)))


def _weights(N: int) -> FloatArr:
    wts = np.ones(N, dtype=np.float64)
    wts[0] = 0.5                      # the primed sum halves the k=0 term
    return wts


def cos_put(model: CharModel, S0: float, K: float, T: float, N: int = 256, L: float = 12.0,
            a: float | None = None, b: float | None = None) -> float:
    """European PUT via COS. Returns the price in the model's currency (USD)."""
    if a is None or b is None:
        a, b = cos_truncation(model, S0, K, T, L)
    k = np.arange(N, dtype=np.float64)
    # Put payoff K(1 - e^y)^+ lives on y in [a, min(0,b)]; empty (a >= that) => worthless here.
    d = min(0.0, b)
    if a >= d:
        return 0.0
    Uk = (2.0 / (b - a)) * K * (_psi(k, a, b, a, d) - _chi(k, a, b, a, d))
    Fk = _fk(model, S0, K, T, a, b, N)
    disc = math.exp(-model.r * T)
    return float(disc * np.sum(_weights(N) * Fk * Uk))


def cos_call(model: CharModel, S0: float, K: float, T: float, N: int = 256, L: float = 12.0,
             a: float | None = None, b: float | None = None) -> float:
    """European CALL via PUT + put-call parity (avoids the call-coefficient cancellation)."""
    put = cos_put(model, S0, K, T, N, L, a, b)
    fwd = S0 * math.exp(-model.q * T) - K * math.exp(-model.r * T)
    return put + fwd


def cos_price(model: CharModel, S0: float, K: float, T: float, kind: str = "call",
              N: int = 256, L: float = 12.0,
              a: float | None = None, b: float | None = None) -> float:
    """European vanilla via COS (put priced directly; call by parity)."""
    if kind == "put":
        return cos_put(model, S0, K, T, N, L, a, b)
    if kind == "call":
        return cos_call(model, S0, K, T, N, L, a, b)
    raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")


def cos_digital(model: CharModel, S0: float, K: float, T: float, kind: str = "call",
                N: int = 256, L: float = 12.0,
                a: float | None = None, b: float | None = None) -> float:
    """Cash-or-nothing digital paying 1 unit if in the money at T (call: S_T>K)."""
    if a is None or b is None:
        a, b = cos_truncation(model, S0, K, T, L)
    k = np.arange(N, dtype=np.float64)
    if kind == "call":                              # pays on y in [max(0,a), b]
        lo = max(0.0, a)
        if lo >= b:
            return 0.0
        Uk = (2.0 / (b - a)) * _psi(k, a, b, lo, b)
    elif kind == "put":                             # pays on y in [a, min(0,b)]
        hi = min(0.0, b)
        if a >= hi:
            return 0.0
        Uk = (2.0 / (b - a)) * _psi(k, a, b, a, hi)
    else:
        raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")
    Fk = _fk(model, S0, K, T, a, b, N)
    return float(math.exp(-model.r * T) * np.sum(_weights(N) * Fk * Uk))


def cos_price_with_grid(model: CharModel, S0: float, K: float, T: float, kind: str = "call",
                        N: int = 256, L: float = 12.0) -> tuple[float, CosGrid]:
    """Price plus the (a,b,N,L) grid used — for numerical-invariance diagnostics."""
    a, b = cos_truncation(model, S0, K, T, L)
    return cos_price(model, S0, K, T, kind, N, L, a, b), CosGrid(a=a, b=b, N=N, L=L)
