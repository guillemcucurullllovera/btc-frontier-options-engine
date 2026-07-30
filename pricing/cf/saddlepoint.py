"""Lugannani-Rice saddlepoint pricer for the deep-OTM wings COS cannot resolve (C9 · M1.4).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Rogers & Zane (1999),
"Saddlepoint approximations to option prices"; Lugannani & Rice (1980). Hirsa §2.5.

COS truncates the density to [a,b]; far past the truncation the cosine series returns tiny,
oscillating, sometimes NEGATIVE prices. The saddlepoint method instead works directly with the
cumulant generating function K(t) = ln E[e^{t X}], X = ln(S_T/S_0), and is accurate precisely in
the tails. The call decomposes into two tail probabilities:

    C = S0 e^{-qT} Q1(X>k) - K e^{-rT} Q0(X>k),   k = ln(K/S0),

where Q0 is the physical tail (LR on K) and Q1 is the share/Esscher-tilted tail (LR on the
t->t+1 tilted CGF). Both use the same saddlepoint t* solving K'(t*)=k.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

from pricing.cf.characteristic_functions import CharModel


def cgf(model: CharModel, t: float, T: float) -> float:
    """Cumulant generating function K(t) = ln E[e^{t X}] = ln phi_R(-i t).

    Returns +inf outside the analyticity strip (the MGF explodes); overflow there is expected
    and silenced — callers gate on math.isfinite to detect the strip edge.
    """
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        val = model.cf(np.array([-1j * t], dtype=np.complex128), T)[0]
        if not np.isfinite(val) or val.real <= 0.0:
            return math.inf
        return float(np.log(val).real)


def _cgf_derivs(model: CharModel, t: float, T: float, h: float = 1e-4) -> tuple[float, float, float]:
    """(K, K', K'') at t by central differences of the CGF."""
    k0 = cgf(model, t, T)
    kp = cgf(model, t + h, T)
    km = cgf(model, t - h, T)
    return k0, (kp - km) / (2.0 * h), (kp - 2.0 * k0 + km) / (h * h)


def _kprime(model: CharModel, t: float, T: float, h: float = 1e-4) -> float:
    return (cgf(model, t + h, T) - cgf(model, t - h, T)) / (2.0 * h)


def _strip_edge(model: CharModel, T: float, direction: float,
                step: float = 0.1, t_cap: float = 40.0) -> float:
    """March out from 0 in `direction` (+/-1) to the analyticity-strip edge.

    The CGF is finite and STRICTLY CONVEX (K''>0) inside the strip; at the strip edge the MGF
    explodes (K''-> inf / non-finite). Returns the last t where the CGF is finite and convex,
    pulled in by one step for a safe brentq bracket.
    """
    last_good = 0.0
    t = 0.0
    while abs(t) < t_cap:
        t_next = t + direction * step
        k0 = cgf(model, t_next, T)
        if not math.isfinite(k0):
            break
        _, _, kpp = _cgf_derivs(model, t_next, T)
        if not math.isfinite(kpp) or kpp <= 0.0:
            break
        last_good = t_next
        t = t_next
    return last_good - direction * step        # pull in one step for safety


def _solve_saddlepoint(model: CharModel, k: float, T: float) -> float:
    """Solve K'(t*) = k inside the analyticity strip; raises if k is beyond the attainable range."""
    hi = _strip_edge(model, T, +1.0)
    lo = _strip_edge(model, T, -1.0)
    if hi <= lo:
        raise ValueError("degenerate analyticity strip")

    def f(t: float) -> float:
        return _kprime(model, t, T) - k

    flo, fhi = f(lo), f(hi)
    if not (math.isfinite(flo) and math.isfinite(fhi)) or flo * fhi > 0:
        raise ValueError("no saddlepoint bracket (k outside the attainable range)")
    return float(brentq(f, lo, hi, xtol=1e-12, rtol=1e-12))


def _lr_upper_tail(w: float, u: float) -> float:
    """Lugannani-Rice upper-tail P(X>k): 1 - Phi(w) - phi(w)(1/w - 1/u); w=0 limit handled."""
    if abs(w) < 1e-7:
        # Continuity limit at the mean (t*->0): P ~ 1/2 - (1/sqrt(2pi))(K'''/(6 K''^{3/2}))... use 0.5.
        return 0.5
    return float(1.0 - norm.cdf(w) - norm.pdf(w) * (1.0 / w - 1.0 / u))


@dataclass(frozen=True)
class SaddlepointResult:
    price: float
    t_star: float
    q0: float       # physical tail P(X>k)
    q1: float       # tilted (share-measure) tail
    valid: bool


def saddlepoint_call(model: CharModel, S0: float, K: float, T: float) -> SaddlepointResult:
    """Deep-OTM/ITM European call via the Rogers-Zane two-tail Lugannani-Rice approximation."""
    k = math.log(K / S0)
    try:
        t0 = _solve_saddlepoint(model, k, T)
        _, _, kpp0 = _cgf_derivs(model, t0, T)
        Kt0 = cgf(model, t0, T)
        K1 = cgf(model, 1.0, T)             # = (r-q)T for a martingale model
        if kpp0 <= 0:
            return SaddlepointResult(float("nan"), t0, float("nan"), float("nan"), False)

        # Q0: physical tail, saddlepoint t0.
        w0 = math.copysign(math.sqrt(max(2.0 * (t0 * k - Kt0), 0.0)), t0)
        u0 = t0 * math.sqrt(kpp0)
        q0 = _lr_upper_tail(w0, u0)

        # Q1: Esscher-tilted (share) measure; tilted CGF K1t(s)=K(s+1)-K(1), saddlepoint s*=t0-1.
        s1 = t0 - 1.0
        arg1 = 2.0 * (s1 * k - (Kt0 - K1))
        w1 = math.copysign(math.sqrt(max(arg1, 0.0)), s1)
        u1 = s1 * math.sqrt(kpp0)
        q1 = _lr_upper_tail(w1, u1)

        price = S0 * math.exp(-model.q * T) * q1 - K * math.exp(-model.r * T) * q0
        valid = math.isfinite(price) and price >= -1e-10
        return SaddlepointResult(max(price, 0.0), t0, q0, q1, valid)
    except (ValueError, ZeroDivisionError, FloatingPointError):
        return SaddlepointResult(float("nan"), float("nan"), float("nan"), float("nan"), False)


def saddlepoint_price(model: CharModel, S0: float, K: float, T: float, kind: str = "call") -> float:
    """Saddlepoint vanilla price; put via put-call parity off the call."""
    res = saddlepoint_call(model, S0, K, T)
    if kind == "call":
        return res.price
    if kind == "put":
        return res.price - (S0 * math.exp(-model.q * T) - K * math.exp(-model.r * T))
    raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")


@dataclass(frozen=True)
class WingPrice:
    price: float
    method: str            # "cos" | "saddlepoint" | "none"
    L_used: float | None


def wing_price(model: CharModel, S0: float, K: float, T: float, kind: str = "call",
               N: int = 1024, L_ladder: tuple[float, ...] = (12.0, 16.0, 20.0, 24.0)) -> WingPrice:
    """Route a strike to the reliable pricer: COS with escalating L, else the saddlepoint tail.

    COS (with a large-enough L) is the accurate pricer wherever its density truncation covers the
    strike; past the breakdown it returns a non-positive/garbage price, so we fall back to the
    saddlepoint (accurate for GBM/Levy tails; an order-of-magnitude wing estimate under Heston).
    """
    from pricing.cf.cos import cos_price
    best: WingPrice | None = None
    for L in L_ladder:
        px = cos_price(model, S0, K, T, kind, N=N, L=L)
        if math.isfinite(px) and px > 0.0:
            best = WingPrice(px, "cos", L)          # keep the largest-L positive price
    if best is not None:
        return best
    sp = saddlepoint_price(model, S0, K, T, kind)
    if math.isfinite(sp) and sp >= 0.0:
        return WingPrice(sp, "saddlepoint", None)
    return WingPrice(0.0, "none", None)


def cos_breakdown_strike(model: CharModel, S0: float, T: float, kind: str = "call",
                         N: int = 256, L: float = 12.0,
                         k_grid: tuple[float, ...] | None = None) -> float:
    """The first strike (scanning OTM) where COS at (N,L) returns a non-positive price.

    Documents the COS deep-OTM breakdown boundary for a given (N,L). Returns +inf if COS stays
    positive across the scan (no breakdown observed).
    """
    from pricing.cf.cos import cos_price
    if k_grid is None:
        k_grid = tuple(float(x) for x in np.geomspace(1.05, 30.0, 60))
    for mult in k_grid:
        K = S0 * mult if kind == "call" else S0 / mult
        if cos_price(model, S0, K, T, kind, N=N, L=L) <= 0.0:
            return K
    return math.inf
