"""Heston calibration to the live Deribit smile (C9 · M2.1).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Fits a single global Heston
parameter set to the whole-chain surface (M0 ingest) off a frozen snapshot. Heston is stood up +
validated here; it does NOT become the production scenario engine (that is M5) and model selection
(Heston vs alternatives) is M3 — so NO best/optimal claim is made.

Objective — bid-ask-weighted least squares in IV/relative space (so BTC's wide, low-vega wings do
not dominate a price-space fit). The IV residual is approximated to first order without a
per-iteration implied-vol inversion via the vega-weighted price residual:

    (P_model - P_market) / vega  ~=  (iv_model - iv_market),

weighted by w = 1 / max(ask_iv - bid_iv, floor) (tighter quotes matter more). Optional Tikhonov
regularisation anchors the fit to a prior snapshot's params (re-calibration stability).

Marking convention (M0 · B3): every option is priced with the M1 COS pricer on the OBSERVED
per-expiry forward with r = q = 0 (Deribit convention), and compared to the market via Black-76 on
the same forward. Parameter bounds (positivity, |rho|<1) keep the fit arbitrage-free by
construction; Feller (2*kappa*theta >= volvol^2) is REPORTED, not enforced — BTC violates it.

Optimizer: fixed grid-seed -> Nelder-Mead (bounded) from >=3 starts (multi-start); the starts must
agree (same optimum). Calibrated params are provenance-tagged CALIBRATED in the result manifest.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize

from pricing.black76 import greeks_black76, price_black76
from pricing.cf.characteristic_functions import CharModel, Heston
from vol.chain_surface import ChainSlice

FloatArr = npt.NDArray[np.float64]
ModelBuilder = Callable[[FloatArr], CharModel]

# Parameter order: (v0, kappa, theta, vol_of_vol, rho).
_LB = np.array([1e-3, 0.1, 1e-3, 1e-2, -0.95])
_UB = np.array([4.0, 20.0, 4.0, 20.0, 0.95])
_TIKHONOV_SCALE = np.array([0.3, 3.0, 0.3, 1.0, 0.5])   # per-param scale for the prior anchor


@dataclass(frozen=True)
class HestonCalParams:
    v0: float
    kappa: float
    theta: float
    vol_of_vol: float
    rho: float

    @property
    def feller_ratio(self) -> float:
        return 2.0 * self.kappa * self.theta / (self.vol_of_vol ** 2)

    @property
    def feller_ok(self) -> bool:
        return self.feller_ratio >= 1.0

    def as_array(self) -> FloatArr:
        return np.array([self.v0, self.kappa, self.theta, self.vol_of_vol, self.rho])


@dataclass(frozen=True)
class CalibrationResult:
    params: HestonCalParams
    # MaMaMoMaMa error quartet (price space) + the IV-space fit metric.
    rmse_usd: float              # sqrt(mean(dP^2)) in USD (compare to MaMaMoMaMa ~9 USD at BTC~$6-10k)
    aae_usd: float               # mean(|dP|) in USD
    ape: float                   # aggregate percentage error sum|dP|/sum(P_market)
    arpe: float                  # average relative price error mean(|dP|/P) over the priced core (~3-4%)
    rmse_iv: float               # RMSE of (iv_model - iv_market) in vol points (the IV-space fit)
    n_options: int
    n_iterations: int
    n_starts: int
    starts_obj_rel_spread: float   # (max/min - 1) of the multi-start objectives — the "same optimum" check
    starts_param_spread: float     # L-inf param spread of the optima (Heston identifiability diagnostic)
    weighted_objective: float
    feller_ratio: float
    feller_ok: bool
    snapshot_dir: str
    provenance: str = "CALIBRATED"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    pending_decision_refs: tuple[str, ...] = ("MS-26", "MS-25")


# ── Vectorised undiscounted Heston call prices on a forward (z = ln(S_T/F)) ───


def _model_call_slice(model: CharModel, F: float, strikes: FloatArr, T: float,
                      N: int = 192, L: float = 14.0) -> FloatArr:
    """Undiscounted (r=q=0) call prices on forward F for all strikes (vectorised over K).

    Model-agnostic: any CharModel priced on the forward via the z=ln(S_T/F) COS convention.
    """
    c1, c2, c4 = model.cumulants(T)                       # cumulants of z = ln(S_T/F) = R
    width = L * math.sqrt(abs(c2) + math.sqrt(max(c4, 0.0)))
    a, b = c1 - width, c1 + width
    k = np.arange(N, dtype=np.float64)
    w = k * math.pi / (b - a)
    A = np.real(model.cf(w.astype(np.complex128), T) * np.exp(-1j * w * a))
    A[0] *= 0.5                                           # primed sum

    km = np.log(strikes / F)                              # log-moneyness per strike
    lo = np.maximum(a, km)                                # payoff support [lo, b]
    inv = 1.0 / (1.0 + w * w)
    # chi_k(lo_i, b) and psi_k(lo_i, b) as (N, S) matrices.
    cb, sb = np.cos(w * (b - a)), np.sin(w * (b - a))
    term_b = math.exp(b) * (cb + w * sb)                 # (N,)
    wl = np.outer(w, (lo - a))                            # (N, S)
    term_c = np.exp(lo)[None, :] * (np.cos(wl) + w[:, None] * np.sin(wl))
    chi = inv[:, None] * (term_b[:, None] - term_c)       # (N, S)
    psi = np.empty_like(chi)
    psi[0] = b - lo                                       # k=0
    psi[1:] = (sb[1:, None] - np.sin(wl[1:])) / w[1:, None]
    Vmat = (2.0 / (b - a)) * (F * chi - strikes[None, :] * psi)   # payoff coeffs (N, S)
    return np.asarray(A @ Vmat, dtype=np.float64)


def _heston_build(p: FloatArr) -> Heston:
    return Heston(r=0.0, q=0.0, v0=float(p[0]), kappa=float(p[1]), theta=float(p[2]),
                  sigma=float(p[3]), rho=float(p[4]))


def _heston_call_slice(p: FloatArr, F: float, strikes: FloatArr, T: float,
                       N: int = 192, L: float = 14.0) -> FloatArr:
    """Undiscounted (r=q=0) Heston call prices on forward F (back-compat wrapper)."""
    return _model_call_slice(_heston_build(p), F, strikes, T, N, L)


# ── Market-side prep (computed once) ─────────────────────────────────────────


@dataclass(frozen=True)
class _MarketSlice:
    F: float
    T: float
    strikes: FloatArr
    kinds: tuple[str, ...]
    mark_iv: FloatArr
    p_market: FloatArr           # OTM market price (Black-76 on F at mark_iv, r=0)
    vega: FloatArr
    weight: FloatArr             # 1 / max(spread, floor)


def _prep_market(slices: Sequence[ChainSlice], spread_floor: float = 5e-3) -> list[_MarketSlice]:
    out: list[_MarketSlice] = []
    for sl in slices:
        n = sl.strikes.size
        pm = np.empty(n)
        vega = np.empty(n)
        for i in range(n):
            K = float(sl.strikes[i])
            iv = float(sl.mark_iv[i])
            kind = sl.kinds[i]
            pm[i] = price_black76(sl.forward, K, 0.0, iv, sl.T, kind)
            vega[i] = greeks_black76(sl.forward, K, 0.0, iv, sl.T, kind).vega
        spread = np.where(np.isfinite(sl.ask_iv - sl.bid_iv), sl.ask_iv - sl.bid_iv, np.nan)
        weight = 1.0 / np.maximum(np.nan_to_num(spread, nan=0.05), spread_floor)
        out.append(_MarketSlice(sl.forward, sl.T, sl.strikes, sl.kinds, sl.mark_iv,
                                pm, np.maximum(vega, 1e-8), weight))
    return out


def _iv_residuals(build: ModelBuilder, p: FloatArr, market: list[_MarketSlice],
                  N: int, L: float) -> FloatArr:
    """Vega-weighted IV-space residuals across the whole surface (flattened), for any model."""
    model = build(p)
    parts: list[FloatArr] = []
    for ms in market:
        call = _model_call_slice(model, ms.F, ms.strikes, ms.T, N, L)
        # OTM model price: put = call - (F - K) (undiscounted r=0 parity) where kind == 'put'.
        is_put = np.array([kd == "put" for kd in ms.kinds])
        p_model = np.where(is_put, call - (ms.F - ms.strikes), call)
        parts.append(ms.weight * (p_model - ms.p_market) / ms.vega)
    return np.concatenate(parts)


# ── Grid-seeded, bounded Nelder-Mead multi-start calibration (model-agnostic) ─


def _heston_seed_grid(atm_var: float) -> list[FloatArr]:
    """Diverse Heston start points seeded around the ATM variance (deterministic)."""
    v = max(atm_var, 0.02)
    return [np.array([v, kappa, v, volvol, rho])
            for kappa in (1.0, 3.0, 6.0) for volvol in (0.5, 1.5, 3.0) for rho in (-0.5, 0.0)]


def _objective(p: FloatArr, build: ModelBuilder, market: list[_MarketSlice], N: int, L: float,
               prior: FloatArr | None, tikhonov: float, scale: FloatArr) -> float:
    try:
        res = _iv_residuals(build, p, market, N, L)
        obj = float(np.mean(res * res))
    except (ValueError, FloatingPointError):
        return 1e12
    if not math.isfinite(obj):        # VG/CGMY invalid regions (martingale/gamma poles) -> reject
        return 1e12
    if prior is not None and tikhonov > 0.0:
        obj += tikhonov * float(np.sum(((p - prior) / scale) ** 2))
    return obj


@dataclass(frozen=True)
class GenericCalResult:
    """Raw model-agnostic calibration result (mapped to CalibrationResult for Heston)."""

    params: FloatArr
    rmse_usd: float
    aae_usd: float
    ape: float
    arpe: float
    rmse_iv: float
    ssr_iv: float                # sum of squared IV residuals (for AIC/BIC)
    n_options: int
    n_iterations: int
    n_starts: int
    obj: float
    starts_obj_rel_spread: float
    starts_param_spread: float


def calibrate_generic(
    build: ModelBuilder, lb: FloatArr, ub: FloatArr, seeds: Sequence[FloatArr],
    slices: Sequence[ChainSlice], t_floor: float = 14.0 / 365.0, N: int = 192, L: float = 14.0,
    n_starts: int = 3, prior: FloatArr | None = None, tikhonov: float = 0.0, maxiter: int = 6000,
) -> GenericCalResult:
    """Calibrate any model (via ``build``) to the surface with grid-seed -> bounded Nelder-Mead."""
    usable = [sl for sl in slices if sl.k.size >= 5 and t_floor <= sl.T]
    if len(usable) < 2:
        raise ValueError("need >= 2 usable slices with >= 5 strikes to calibrate")
    market = _prep_market(usable)
    scale = np.maximum(np.abs(ub - lb), 1e-6)

    seed_scores = sorted(seeds, key=lambda s: _objective(s, build, market, N, L, None, 0.0, scale))
    starts = seed_scores[:max(n_starts, 1)]

    results: list[tuple[FloatArr, float, int]] = []
    for x0 in starts:
        x0c = np.minimum(np.maximum(x0, lb), ub)
        sol = minimize(_objective, x0c, args=(build, market, N, L, prior, tikhonov, scale),
                       method="Nelder-Mead", bounds=list(zip(lb, ub, strict=True)),
                       options={"xatol": 1e-5, "fatol": 1e-10, "maxiter": maxiter})
        results.append((np.asarray(sol.x, dtype=np.float64), float(sol.fun), int(sol.nit)))

    results.sort(key=lambda r: r[1])
    best_p, best_obj, best_nit = results[0]
    objs = np.array([r[1] for r in results])
    obj_spread = float(objs.max() / objs.min() - 1.0) if objs.min() > 0 else 0.0
    opt = np.array([r[0] for r in results])
    param_spread = float(np.max(np.max(np.abs(opt - opt[0]) / scale, axis=1))) if len(opt) > 1 else 0.0

    stats = _fit_stats(build, best_p, market, N, L)
    return GenericCalResult(
        params=best_p, rmse_usd=stats["rmse_usd"], aae_usd=stats["aae_usd"], ape=stats["ape"],
        arpe=stats["arpe"], rmse_iv=stats["rmse_iv"], ssr_iv=stats["ssr_iv"],
        n_options=int(sum(ms.strikes.size for ms in market)), n_iterations=best_nit,
        n_starts=len(starts), obj=best_obj, starts_obj_rel_spread=obj_spread,
        starts_param_spread=param_spread,
    )


def calibrate_heston(
    slices: Sequence[ChainSlice], snapshot_dir: str = "",
    prior: HestonCalParams | None = None, tikhonov: float = 0.0,
    n_starts: int = 3, N: int = 192, L: float = 14.0, t_floor: float = 14.0 / 365.0,
) -> CalibrationResult:
    """Calibrate a global Heston to the surface; returns a CALIBRATED-labelled result.

    ``t_floor`` excludes sub-2-week expiries: their extreme, fast-moving smiles create local minima
    that break multi-start agreement (a standard Heston-calibration stabilisation, like the SSVI
    t_floor). Weekly+ expiries yield a well-identified fit (all starts reach the same optimum).
    """
    usable = [sl for sl in slices if sl.k.size >= 5 and t_floor <= sl.T]
    if len(usable) < 2:
        raise ValueError("need >= 2 usable slices with >= 5 strikes for Heston calibration")
    near = min(usable, key=lambda s: s.T)
    atm_var = float(np.interp(0.0, near.k, near.mark_iv) ** 2)
    prior_arr = prior.as_array() if prior is not None else None

    g = calibrate_generic(_heston_build, _LB, _UB, _heston_seed_grid(atm_var), slices,
                          t_floor=t_floor, N=N, L=L, n_starts=n_starts,
                          prior=prior_arr, tikhonov=tikhonov)
    params = HestonCalParams(*(float(x) for x in g.params))
    return CalibrationResult(
        params=params, rmse_usd=g.rmse_usd, aae_usd=g.aae_usd, ape=g.ape, arpe=g.arpe,
        rmse_iv=g.rmse_iv, n_options=g.n_options, n_iterations=g.n_iterations, n_starts=g.n_starts,
        starts_obj_rel_spread=g.starts_obj_rel_spread, starts_param_spread=g.starts_param_spread,
        weighted_objective=g.obj, feller_ratio=params.feller_ratio, feller_ok=params.feller_ok,
        snapshot_dir=snapshot_dir,
    )


def calibration_manifest(result: CalibrationResult) -> dict[str, object]:
    """CALIBRATED-labelled manifest of the fit (JSON-serialisable) for persistence/provenance."""
    p = result.params
    return {
        "provenance": result.provenance,
        "timestamp": result.timestamp.isoformat(),
        "snapshot_dir": result.snapshot_dir,
        "model": "Heston",
        "params": {"v0": p.v0, "kappa": p.kappa, "theta": p.theta,
                   "vol_of_vol": p.vol_of_vol, "rho": p.rho},
        "feller_ratio": result.feller_ratio,
        "feller_ok": result.feller_ok,
        "fit": {"rmse_usd": result.rmse_usd, "aae_usd": result.aae_usd,
                "ape": result.ape, "arpe": result.arpe, "rmse_iv": result.rmse_iv},
        "n_options": result.n_options,
        "optimizer": {"method": "grid-seed -> Nelder-Mead (bounded)", "n_starts": result.n_starts,
                      "n_iterations": result.n_iterations,
                      "starts_obj_rel_spread": result.starts_obj_rel_spread,
                      "starts_param_spread": result.starts_param_spread},
        "pending_decision_refs": list(result.pending_decision_refs),
    }


def _fit_stats(build: ModelBuilder, p: FloatArr, market: list[_MarketSlice],
               N: int, L: float) -> dict[str, float]:
    """The MaMaMoMaMa error quartet (RMSE/AAE/APE/ARPE, USD price) + IV-space RMSE + SSR(IV).

    ARPE averages the per-option relative error; deep-OTM options with a near-zero price are floored
    at 0.1% of the forward so a single ~$0 wing quote cannot blow the metric up (documented).
    """
    model = build(p)
    dP: list[float] = []
    Pm: list[float] = []
    dIV: list[float] = []
    floors: list[float] = []
    for ms in market:
        call = _model_call_slice(model, ms.F, ms.strikes, ms.T, N, L)
        is_put = np.array([kd == "put" for kd in ms.kinds])
        p_model = np.where(is_put, call - (ms.F - ms.strikes), call)
        diff = p_model - ms.p_market
        dP.extend(np.abs(diff).tolist())
        Pm.extend(ms.p_market.tolist())
        dIV.extend((diff / ms.vega).tolist())            # first-order IV error
        floors.extend((1e-3 * ms.F * np.ones_like(ms.p_market)).tolist())
    dP_a, Pm_a, dIV_a, fl = (np.array(x) for x in (dP, Pm, dIV, floors))
    return {
        "rmse_usd": float(np.sqrt(np.mean(dP_a ** 2))),
        "aae_usd": float(np.mean(dP_a)),
        "ape": float(np.sum(dP_a) / max(np.sum(Pm_a), 1e-8)),
        "arpe": float(np.mean(dP_a / np.maximum(Pm_a, fl))),
        "rmse_iv": float(np.sqrt(np.mean(dIV_a ** 2))),
        "ssr_iv": float(np.sum(dIV_a ** 2)),
    }
