"""Penalized model selection over {BS, Heston, Bates, VG, CGMY} (C9 · M3.2).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Each model is calibrated to the SAME
whole-chain surface and scored by its residual quartet + AIC/BIC (parameter counts: BS=1, Heston=5,
Bates=8, VG=3, CGMY=4). Selection favours the most PARSIMONIOUS model whose residual is inside a
tolerance of the best fit — not merely the lowest-residual over-parameterised one (Hirsa §7.5;
Akaike/Schwarz information criteria formally penalise complexity).

This is STATISTICAL MODEL-FIT selection (which model reprices the observed market best), which is
legitimate and DISTINCT from strategy ranking — it is NOT an MS-25 "best strategy" claim.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt

from pricing.cf.characteristic_functions import (
    CGMY,
    GBM,
    Bates,
    CharModel,
    Heston,
    VarianceGamma,
)
from vol.calibrate import ModelBuilder, calibrate_generic
from vol.chain_surface import ChainSlice

FloatArr = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    n_params: int
    build: ModelBuilder
    lb: FloatArr
    ub: FloatArr
    seeds: Sequence[FloatArr]


def _bs_build(p: FloatArr) -> CharModel:
    return GBM(r=0.0, q=0.0, sigma=float(p[0]))


def _heston_build(p: FloatArr) -> CharModel:
    return Heston(r=0.0, q=0.0, v0=float(p[0]), kappa=float(p[1]), theta=float(p[2]),
                  sigma=float(p[3]), rho=float(p[4]))


def _bates_build(p: FloatArr) -> CharModel:
    return Bates(r=0.0, q=0.0, v0=float(p[0]), kappa=float(p[1]), theta=float(p[2]),
                 sigma=float(p[3]), rho=float(p[4]), lam=float(p[5]), mu_j=float(p[6]),
                 sigma_j=float(p[7]))


def _vg_build(p: FloatArr) -> CharModel:
    return VarianceGamma(r=0.0, q=0.0, sigma=float(p[0]), theta=float(p[1]), nu=float(p[2]))


def _cgmy_build(p: FloatArr) -> CharModel:
    return CGMY(r=0.0, q=0.0, C=float(p[0]), G=float(p[1]), M=float(p[2]), Y=float(p[3]))


def build_specs(atm_var: float) -> list[ModelSpec]:
    """The five model specs with bounds + deterministic grid-seed start points."""
    v = max(atm_var, 0.02)
    sv = math.sqrt(v)
    heston_seeds = [np.array([v, kappa, v, volvol, rho])
                    for kappa in (1.0, 3.0, 6.0) for volvol in (0.5, 1.5, 3.0) for rho in (-0.5, 0.0)]
    bates_seeds = [np.concatenate([h, [1.0, -0.10, 0.15]]) for h in heston_seeds[:6]]
    bates_seeds += [np.concatenate([h, [3.0, -0.05, 0.10]]) for h in heston_seeds[:3]]
    return [
        ModelSpec("BS", 1, _bs_build, np.array([0.05]), np.array([3.0]),
                  [np.array([sv * m]) for m in (0.8, 1.0, 1.3)]),
        ModelSpec("Heston", 5, _heston_build,
                  np.array([1e-3, 0.1, 1e-3, 1e-2, -0.95]), np.array([4.0, 20.0, 4.0, 20.0, 0.95]),
                  heston_seeds),
        ModelSpec("Bates", 8, _bates_build,
                  np.array([1e-3, 0.1, 1e-3, 1e-2, -0.95, 0.0, -0.6, 1e-3]),
                  np.array([4.0, 20.0, 4.0, 20.0, 0.95, 20.0, 0.6, 1.0]),
                  bates_seeds),
        ModelSpec("VG", 3, _vg_build,
                  np.array([0.05, -1.0, 1e-2]), np.array([2.0, 1.0, 3.0]),
                  [np.array([sv * 0.8, th, nu]) for th in (-0.3, -0.1, 0.0) for nu in (0.2, 0.6)]),
        ModelSpec("CGMY", 4, _cgmy_build,
                  np.array([1e-3, 0.5, 0.5, 0.05]), np.array([20.0, 60.0, 60.0, 1.8]),
                  [np.array([c, g, m, y]) for (c, g, m) in ((1.0, 5.0, 5.0), (0.5, 10.0, 10.0))
                   for y in (0.4, 0.8, 1.2)]),
    ]


@dataclass(frozen=True)
class ModelFit:
    name: str
    n_params: int
    params: list[float]
    rmse_usd: float
    aae_usd: float
    ape: float
    arpe: float
    rmse_iv: float
    aic: float
    bic: float
    n_options: int
    starts_obj_rel_spread: float


@dataclass(frozen=True)
class ModelSelection:
    fits: list[ModelFit]                 # sorted by BIC ascending
    selected_by_aic: str
    selected_by_bic: str
    selected_parsimonious: str           # fewest params within the ARPE tolerance of the best
    arpe_tolerance: float
    provenance: str = "CALIBRATED"


def _aic_bic(ssr_iv: float, n: int, k: int) -> tuple[float, float]:
    """Gaussian AIC/BIC from the residual sum of squares: n*ln(SSR/n) + {2k, k*ln n}."""
    ll_term = n * math.log(max(ssr_iv, 1e-30) / n)
    return ll_term + 2.0 * k, ll_term + k * math.log(n)


def calibrate_spec(spec: ModelSpec, slices: Sequence[ChainSlice],
                   t_floor: float = 14.0 / 365.0, N: int = 128, L: float = 14.0,
                   n_starts: int = 2, maxiter: int = 2500) -> ModelFit:
    g = calibrate_generic(spec.build, spec.lb, spec.ub, spec.seeds, slices,
                          t_floor=t_floor, N=N, L=L, n_starts=n_starts, maxiter=maxiter)
    aic, bic = _aic_bic(g.ssr_iv, g.n_options, spec.n_params)
    return ModelFit(
        name=spec.name, n_params=spec.n_params, params=[float(x) for x in g.params],
        rmse_usd=g.rmse_usd, aae_usd=g.aae_usd, ape=g.ape, arpe=g.arpe, rmse_iv=g.rmse_iv,
        aic=aic, bic=bic, n_options=g.n_options, starts_obj_rel_spread=g.starts_obj_rel_spread,
    )


def select_models(slices: Sequence[ChainSlice], t_floor: float = 14.0 / 365.0,
                  N: int = 128, L: float = 14.0, n_starts: int = 2, maxiter: int = 2500,
                  arpe_rel_margin: float = 0.15) -> ModelSelection:
    """Calibrate all five models and select the most parsimonious one within tolerance of the best."""
    usable = [sl for sl in slices if sl.k.size >= 5 and t_floor <= sl.T]
    if len(usable) < 2:
        raise ValueError("need >= 2 usable slices to run model selection")
    near = min(usable, key=lambda s: s.T)
    atm_var = float(np.interp(0.0, near.k, near.mark_iv) ** 2)

    specs = {s.name: s for s in build_specs(atm_var)}
    fits: list[ModelFit] = []
    heston_fit: ModelFit | None = None
    # BS/VG/CGMY are always far worse; a light budget suffices (their exact optimum is immaterial
    # to the Heston-vs-Bates conclusion, and CGMY's rugged landscape is otherwise very slow).
    for name in ("BS", "VG", "CGMY"):
        fits.append(calibrate_spec(specs[name], slices, t_floor, min(N, 96), L, n_starts,
                                   maxiter=min(maxiter, 900)))
    heston_fit = calibrate_spec(specs["Heston"], slices, t_floor, N, L, n_starts, maxiter)
    fits.append(heston_fit)

    # Bates ⊇ Heston (lambda=0 recovers it): warm-start from the Heston optimum across a jump-param
    # spread (incl. high intensity), so the 8-param fit converges to >= Heston quality — an 8-param
    # NM from cold starts under-converges to a spurious lambda~0 local minimum.
    hp = np.array(heston_fit.params)
    warm = [np.concatenate([hp, [lam, mu, sj]])
            for (lam, mu, sj) in ((0.5, -0.10, 0.15), (1.5, -0.05, 0.10),
                                  (3.0, -0.15, 0.20), (8.0, -0.06, 0.03), (0.2, 0.0, 0.10))]
    bates_spec = replace(specs["Bates"], seeds=warm)
    fits.append(calibrate_spec(bates_spec, slices, t_floor, N, L, n_starts=len(warm), maxiter=maxiter))

    fits.sort(key=lambda f: f.bic)
    parsimonious, tol = select_parsimonious(fits, arpe_rel_margin)
    return ModelSelection(
        fits=fits,
        selected_by_aic=min(fits, key=lambda f: f.aic).name,
        selected_by_bic=min(fits, key=lambda f: f.bic).name,
        selected_parsimonious=parsimonious,
        arpe_tolerance=tol,
    )


def select_parsimonious(fits: Sequence[ModelFit], arpe_rel_margin: float = 0.15) -> tuple[str, float]:
    """Most parsimonious (fewest-param) model whose ARPE is within the tolerance of the best fit.

    Guards against picking a marginally-better over-parameterised model (Hirsa §7.5): a simpler
    model whose residual is 'inside tolerance' of the best is preferred. Returns (name, tolerance).
    """
    best_arpe = min(f.arpe for f in fits)
    tol = best_arpe * (1.0 + arpe_rel_margin)
    within = [f for f in fits if f.arpe <= tol]
    return min(within, key=lambda f: (f.n_params, f.arpe)).name, tol


def selection_table(sel: ModelSelection) -> list[dict[str, object]]:
    """JSON-serialisable per-model rows (quartet + AIC/BIC), for the report/manifest."""
    return [
        {"model": f.name, "n_params": f.n_params, "rmse_usd": round(f.rmse_usd, 2),
         "aae_usd": round(f.aae_usd, 2), "ape_pct": round(f.ape * 100, 3),
         "arpe_pct": round(f.arpe * 100, 3), "rmse_iv_vp": round(f.rmse_iv * 100, 3),
         "aic": round(f.aic, 1), "bic": round(f.bic, 1),
         "obj_spread": round(f.starts_obj_rel_spread, 4)}
        for f in sel.fits
    ]
