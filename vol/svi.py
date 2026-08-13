"""Arbitrage-free SVI / SSVI volatility-surface calibration (C9 · M0.2).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. This is the
declared-but-unused ``"svi"``/``"ssvi"`` surface method, implemented in total-implied-
variance / log-moneyness space off the OBSERVED forward (consistent with the B3
marking convention: Deribit IV uses the forward, not the index).

Parameterisations
-----------------
Raw SVI (Gatheral 2004), per expiry slice, total variance w(k)=sigma^2(k)*T:
    w(k) = a + b*( rho*(k - m) + sqrt((k - m)^2 + s^2) )
    k = ln(K / F) log-moneyness; a level, b>=0 angle, rho in (-1,1) skew, m shift, s>0.

SSVI (Gatheral-Jacquier 2014), whole surface in one shape:
    w(k, theta) = (theta/2)*( 1 + rho*phi*k + sqrt((phi*k + rho)^2 + (1 - rho^2)) )
    theta = ATM total variance at T (a monotone term structure => calendar arb-free);
    phi = phi(theta) power-law: phi(theta) = eta * theta^(-gamma).

No-arbitrage gates
------------------
* Butterfly (density >= 0): raw SVI via the Gatheral-Jacquier g(k) >= 0 on a dense grid
  (with analytic w', w''); SSVI via theta*phi*(1+|rho|) < 4 and theta*phi^2*(1+|rho|) <= 4.
* Calendar: total variance non-decreasing in T at each fixed k (checked across slices).

References: Gatheral & Jacquier, "Arbitrage-free SVI volatility surfaces" (2014),
Quantitative Finance 14(1); Hirsa, *Computational Methods in Finance* §7.7-7.8.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import numpy.typing as npt
from scipy.optimize import least_squares

FloatArr = npt.NDArray[np.float64]


# ── Raw SVI ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SviParams:
    """Raw-SVI slice parameters (Gatheral) at a single expiry T (years)."""

    a: float
    b: float
    rho: float
    m: float
    s: float
    T: float

    def total_variance(self, k: FloatArr | float) -> FloatArr:
        kk = np.asarray(k, dtype=np.float64)
        u = kk - self.m
        return np.asarray(self.a + self.b * (self.rho * u + np.sqrt(u * u + self.s * self.s)),
                          dtype=np.float64)

    def iv(self, k: FloatArr | float) -> FloatArr:
        w = np.maximum(self.total_variance(k), 1e-12)
        return np.asarray(np.sqrt(w / self.T), dtype=np.float64)


def svi_total_variance(k: FloatArr, a: float, b: float, rho: float, m: float, s: float) -> FloatArr:
    u = k - m
    return np.asarray(a + b * (rho * u + np.sqrt(u * u + s * s)), dtype=np.float64)


def _svi_w_derivs(k: FloatArr, p: SviParams) -> tuple[FloatArr, FloatArr, FloatArr]:
    """Analytic (w, w', w'') for the raw-SVI slice. w'' = b*s^2/D^3 >= 0."""
    u = k - p.m
    D = np.sqrt(u * u + p.s * p.s)
    w = p.a + p.b * (p.rho * u + D)
    w1 = p.b * (p.rho + u / D)
    w2 = p.b * (p.s * p.s) / (D * D * D)
    return w, w1, w2


def svi_g(k: FloatArr, p: SviParams) -> FloatArr:
    """Gatheral-Jacquier g(k): the slice is butterfly-arb-free iff g(k) >= 0 (and w>0)."""
    w, w1, w2 = _svi_w_derivs(k, p)
    w = np.maximum(w, 1e-12)
    term1 = (1.0 - k * w1 / (2.0 * w)) ** 2
    term2 = (w1 * w1 / 4.0) * (1.0 / w + 0.25)
    return np.asarray(term1 - term2 + w2 / 2.0, dtype=np.float64)


def svi_butterfly_free(
    p: SviParams, k_grid: FloatArr | None = None, tol: float = -1e-8,
) -> tuple[bool, float]:
    """Return (is_free, min_g). Butterfly-arb-free iff min_g >= tol and w>0 on the grid."""
    if k_grid is None:
        k_grid = np.linspace(-1.5, 1.5, 601)
    w = p.total_variance(k_grid)
    if float(np.min(w)) <= 0.0:
        return False, float(np.min(w))
    g = svi_g(k_grid, p)
    min_g = float(np.min(g))
    return (min_g >= tol), min_g


def calibrate_svi_slice(
    k: FloatArr, w_obs: FloatArr, T: float, weights: FloatArr | None = None,
    n_starts: int = 6, space: str = "total_variance",
) -> tuple[SviParams, float]:
    """Least-squares raw-SVI fit to observed total variances w_obs at log-moneyness k.

    Returns (params, rmse_total_variance). Bounds keep b>=0, |rho|<1, s>0; the fit is
    multi-started for robustness. Butterfly-freeness is NOT forced here (raw LSQ) — it is
    reported separately via ``svi_butterfly_free`` so violations are surfaced, not hidden.

    ``space`` selects the residual metric (Gatheral 2014 §5.2 calibrates to *prices*, not
    total variance):
      * ``"total_variance"`` (default, back-compat) — resid = sqrt(wts)·(w_fit - w_obs).
        Total variance is O(σ²T), large in the wings, so this over-weights deep-OTM fit and
        under-weights near-ATM price fidelity — the exact mismatch A1 §2C flags.
      * ``"iv"`` — resid = sqrt(wts)·(iv_fit - iv_obs), iv = sqrt(w/T). Combined with a
        vega/price weight (passed via ``weights``) this is the cheap first-order equivalent
        of Gatheral's price-relative objective vega·Δσ/max(P,floor) (A1 §2C), aligning the fit
        metric with the price-space ARPE the reprice gate scores.
    """
    if space not in ("total_variance", "iv"):
        raise ValueError(f"space must be 'total_variance' or 'iv', got {space!r}")
    k = np.asarray(k, dtype=np.float64)
    w_obs = np.asarray(w_obs, dtype=np.float64)
    if k.size < 5:
        raise ValueError(f"SVI slice needs >=5 points; got {k.size}")
    wts = np.ones_like(w_obs) if weights is None else np.asarray(weights, dtype=np.float64)
    sw = np.sqrt(np.maximum(wts, 0.0))
    iv_obs = np.sqrt(np.maximum(w_obs, 1e-12) / T)

    w_atm = float(np.interp(0.0, k, w_obs)) if k.min() <= 0 <= k.max() else float(np.median(w_obs))
    kspan = max(float(k.max() - k.min()), 1e-3)

    # bounds: a, b, rho, m, s
    lb = np.array([-abs(w_atm) - 1e-6, 0.0, -0.999, k.min() - kspan, 1e-4])
    ub = np.array([max(w_obs.max(), 1e-6) + 1e-6, 10.0, 0.999, k.max() + kspan, 2.0 * kspan + 1.0])

    def resid(theta: FloatArr) -> FloatArr:
        a, b, rho, m, s = theta
        w = svi_total_variance(k, a, b, rho, m, s)
        if space == "iv":
            iv_fit = np.sqrt(np.maximum(w, 1e-12) / T)
            return sw * (iv_fit - iv_obs)
        return sw * (w - w_obs)

    starts = [
        np.array([w_atm * 0.5, 0.1, -0.3, 0.0, 0.1]),
        np.array([w_atm * 0.8, 0.04, -0.5, 0.0, 0.2]),
        np.array([max(w_obs.min(), 0.0), 0.2, 0.0, 0.0, 0.3]),
        np.array([w_atm * 0.5, 0.1, 0.3, -0.05, 0.15]),
        np.array([w_atm * 0.9, 0.02, -0.7, 0.05, 0.05]),
        np.array([w_atm, 0.15, -0.2, 0.0, kspan / 2.0]),
    ][:n_starts]

    best: tuple[SviParams, float] | None = None
    for x0 in starts:
        x0c = np.minimum(np.maximum(x0, lb), ub)
        try:
            sol = least_squares(resid, x0c, bounds=(lb, ub), method="trf", max_nfev=4000)
        except Exception:
            continue
        rmse = float(np.sqrt(np.mean((resid(sol.x) / np.maximum(sw, 1e-12)) ** 2)))
        if best is None or rmse < best[1]:
            a, b, rho, m, s = (float(v) for v in sol.x)
            best = (SviParams(a, b, rho, m, s, T), rmse)
    if best is None:
        raise ValueError("SVI calibration failed for all starts")
    return best


# ── SSVI ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SsviParams:
    """SSVI surface parameters with a power-law phi(theta) = eta*theta^(-gamma)."""

    rho: float
    eta: float
    gamma: float

    def phi(self, theta: float) -> float:
        return float(self.eta * theta ** (-self.gamma))

    def total_variance(self, k: FloatArr | float, theta: float) -> FloatArr:
        kk = np.asarray(k, dtype=np.float64)
        ph = self.phi(theta)
        x = ph * kk + self.rho
        return np.asarray(
            0.5 * theta * (1.0 + self.rho * ph * kk + np.sqrt(x * x + (1.0 - self.rho * self.rho))),
            dtype=np.float64,
        )


def ssvi_butterfly_free(p: SsviParams, thetas: FloatArr) -> tuple[bool, float]:
    """Gatheral-Jacquier Thm 4.2: theta*phi*(1+|rho|)<4 AND theta*phi^2*(1+|rho|)<=4.

    Returns (is_free, worst_margin) — worst_margin = 4 - max(lhs); >=0 means arb-free.
    """
    worst = math.inf
    ok = True
    for th in np.asarray(thetas, dtype=np.float64):
        ph = p.phi(float(th))
        c1 = th * ph * (1.0 + abs(p.rho))
        c2 = th * ph * ph * (1.0 + abs(p.rho))
        worst = min(worst, 4.0 - c1, 4.0 - c2)
        if not (c1 < 4.0 and c2 <= 4.0):
            ok = False
    return ok, float(worst)


def calibrate_ssvi(
    ks: list[FloatArr], w_obs: list[FloatArr], thetas: FloatArr,
    weights: list[FloatArr] | None = None, n_starts: int = 5,
) -> tuple[SsviParams, float]:
    """Global SSVI fit over all slices given the ATM total-variance term structure thetas.

    thetas[i] is theta_t at slice i (ATM total variance, monotone => calendar arb-free by
    construction). Returns (params, rmse_total_variance) aggregated across the whole chain.
    """
    thetas = np.asarray(thetas, dtype=np.float64)
    if weights is None:
        weights = [np.ones_like(w) for w in w_obs]

    def resid(theta_vec: FloatArr) -> FloatArr:
        rho, eta, gamma = theta_vec
        p = SsviParams(rho, eta, gamma)
        parts: list[FloatArr] = []
        for kk, wo, wt, th in zip(ks, w_obs, weights, thetas, strict=True):
            w = p.total_variance(kk, float(th))
            parts.append(np.sqrt(np.maximum(wt, 0.0)) * (w - wo))
        return np.concatenate(parts)

    lb = np.array([-0.999, 1e-3, 0.0])
    ub = np.array([0.999, 10.0, 0.9])
    starts = [
        np.array([-0.5, 1.0, 0.3]),
        np.array([-0.3, 0.5, 0.5]),
        np.array([0.0, 2.0, 0.2]),
        np.array([-0.7, 1.5, 0.4]),
        np.array([-0.1, 0.8, 0.1]),
    ][:n_starts]

    best: tuple[SsviParams, float] | None = None
    n_pts = sum(int(k.size) for k in ks)
    for x0 in starts:
        x0c = np.minimum(np.maximum(x0, lb), ub)
        try:
            sol = least_squares(resid, x0c, bounds=(lb, ub), method="trf", max_nfev=6000)
        except Exception:
            continue
        rmse = float(np.sqrt(np.sum(resid(sol.x) ** 2) / max(n_pts, 1)))
        if best is None or rmse < best[1]:
            rho, eta, gamma = (float(v) for v in sol.x)
            best = (SsviParams(rho, eta, gamma), rmse)
    if best is None:
        raise ValueError("SSVI calibration failed for all starts")
    return best


# ── Calendar no-arbitrage across fitted slices ──────────────────────────────


def calendar_arb_free(
    total_variance_by_slice: list[tuple[float, FloatArr]], k_grid: FloatArr, tol: float = -1e-6,
) -> tuple[bool, float]:
    """Total variance must be non-decreasing in T at each fixed k (no calendar arbitrage).

    ``total_variance_by_slice`` = [(T, w(k_grid)), ...]; returns (is_free, worst_decrease)
    where worst_decrease = min over adjacent slices of (w_next - w_prev) on k_grid.
    """
    ordered = sorted(total_variance_by_slice, key=lambda x: x[0])
    worst = math.inf
    for (_, w0), (_, w1) in pairwise(ordered):
        worst = min(worst, float(np.min(w1 - w0)))
    if worst == math.inf:
        return True, 0.0
    return (worst >= tol), worst
