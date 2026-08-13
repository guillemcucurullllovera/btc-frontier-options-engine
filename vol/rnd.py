"""Breeden-Litzenberger risk-neutral density + market-implied crash probabilities (A5 / D4).

NEW isolated module; canonical main untouched (mirrors ``vol/reprice_gate.py``'s prototype style).
Extracts an **arbitrage-free risk-neutral density (RND)** and **market-implied crash probabilities**
for BTC directly from the OBSERVED Deribit surface, via Breeden-Litzenberger (1978) applied to a smooth
**arb-free SVI** call-price surface (``vol.svi`` / ``vol.chain_surface``).

Method (Rotunno, *Extracting Market-Implied Crash Probabilities via Breeden-Litzenberger*, §2.1):

    f^Q(K) = e^{rT} d2C(K,T)/dK2                         (density = curvature of call price in strike)

The improvement over Rotunno's quadratic-IV fit: we ride the repo's arb-free SVI surface, whose
butterfly gate g(k) >= 0 (``vol/svi.py:svi_butterfly_free``) is mathematically equivalent to a
non-negative RND -> the second derivative is convex-by-construction (density >= 0 with NO clipping),
which removes the multi-modal interpolation artifacts Rotunno flags as his own limitation (§7).

HONESTY LOCK (Rotunno §1, §2.2 -- FOUNDATIONS s10):  f^Q OVERSTATES the physical crash probability
because the pricing kernel M is larger in bad states (investors pay up for crash insurance):

    f^Q(S_T) = M(S_T) f^P(S_T) / E^P[M]

Therefore every crash number here is **MODELED-Q = "the market-implied / risk-neutral probability,
i.e. what the market CHARGES for downside", NOT "the probability BTC will crash."** The physical (P)
probability is the MC/historical engine's domain; the two measures live in SEPARATE columns and are
NEVER averaged. Their gap (Q_crash - P_crash) = the market's tail-risk premium (the VRP the overlay
harvests) -- reported by the caller, not blended here.

Marking convention (B3): Black-76 on the OBSERVED per-expiry forward, r = q = 0 (Deribit).
Provenance of every emitted value: CALCULATED_FROM_OBSERVED, MODELED-Q.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from scipy.integrate import cumulative_trapezoid
from scipy.stats import norm

from pricing.black76 import price_black76
from vol.chain_surface import ChainSlice, SviSliceFit, fit_svi_surface
from vol.svi import SviParams, svi_butterfly_free

FloatArr = npt.NDArray[np.float64]

# BTC-appropriate crash ladder (Rotunno uses -30% for equities; BTC routinely does -30% without a
# "crash", so we report a ladder). theta = S_T/S0 threshold; -30% => theta 0.70 is the headline.
CRASH_THRESHOLDS: tuple[float, ...] = (0.80, 0.70, 0.60, 0.50)   # -20 / -30 / -40 / -50%
_DENSITY_TOL = -1e-8            # SVI convexity guarantees f >= this; violation => surface it, don't clip
_MASS_BAND = (0.97, 1.03)      # pre-normalization integral must sit here (grid captures the density)
_ROUNDTRIP_ARPE_MAX = 0.05     # RND must reprice the OBSERVED core within this (key acceptance test)


def _thr_label(theta: float) -> str:
    return f"{round((theta - 1.0) * 100):+d}%"


def _bs_call_vec(F: float, K: FloatArr, iv: FloatArr, T: float) -> FloatArr:
    """Vectorized undiscounted (r=0) Black-76 CALL price on forward F. Matches ``price_black76``."""
    iv = np.maximum(iv, 1e-8)
    sqT = math.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * iv * iv * T) / (iv * sqT)
    d2 = d1 - iv * sqT
    return np.asarray(F * norm.cdf(d1) - K * norm.cdf(d2), dtype=np.float64)


@dataclass(frozen=True)
class RndSlice:
    """Per-expiry RND + crash/exercise probabilities. CALCULATED_FROM_OBSERVED, MODELED-Q."""

    label: str
    T_years: float
    T_days: float
    forward: float
    spot: float
    n_strikes: int
    obs_strike_lo: float          # deepest OBSERVED strike (USD) — below this, crash prob is EXTRAPOLATED
    obs_strike_hi: float
    obs_moneyness_lo: float        # obs_strike_lo / S0
    # gates
    butterfly_free: bool
    min_g: float
    min_density: float
    prenorm_mass: float
    svi_iv_rmse_vp: float
    atm_iv_svi: float
    atm_iv_observed: float
    # RND shape (MODELED-Q)
    rnd_mean: float
    rnd_std: float
    rnd_skew: float               # < 0 => market prices more downside than up (BTC: strongly negative)
    rnd_kurt: float               # excess kurtosis
    # crash / upside ladders (MODELED-Q); *_extrapolated flags a threshold beyond observed strikes
    crash_prob: dict[str, float]
    crash_extrapolated: dict[str, bool]
    upside_prob: dict[str, float]
    # market-implied assignment prob at the mandate ladder strikes (P(S_T > K))
    exercise_prob: dict[str, float]
    # acceptance test: does the RND reprice the OBSERVED chain?
    roundtrip_arpe_core: float
    roundtrip_n_core: int
    gates_pass: bool
    messages: tuple[str, ...] = field(default_factory=tuple)
    provenance: str = "CALCULATED_FROM_OBSERVED, MODELED-Q"


@dataclass(frozen=True)
class RndReport:
    spot: float
    n_slices: int
    slices: list[RndSlice]
    ladder_strikes_usd: tuple[float, ...]
    provenance: str = "CALCULATED_FROM_OBSERVED, MODELED-Q"

    def slice_for(self, label: str) -> RndSlice | None:
        return next((s for s in self.slices if s.label == label), None)


def _rnd_for_slice(
    sl: ChainSlice, fit: SviSliceFit, spot: float, ladder_strikes: Sequence[float],
    grid_lo: float, grid_hi: float, n_grid: int,
) -> RndSlice:
    p: SviParams = fit.params
    F = sl.forward
    S0 = spot

    # dense USD strike grid; moneyness k = ln(K/F); arb-free SVI IV; Black-76 calls; BL curvature.
    K = np.linspace(grid_lo * S0, grid_hi * S0, n_grid)
    k = np.log(K / F)
    iv = p.iv(k)
    C = _bs_call_vec(F, K, iv, sl.T)
    f = np.gradient(np.gradient(C, K), K)                 # d2C/dK2 ; e^{rT}=1 since r=0

    bf_free, min_g = svi_butterfly_free(p)
    min_density = float(np.min(f))
    msgs: list[str] = []
    if min_density < _DENSITY_TOL:
        msgs.append(f"RND negative (min f={min_density:.2e}) — SVI slice violated its butterfly gate")

    f = np.maximum(f, 0.0)
    prenorm_mass = float(np.trapezoid(f, K))
    if not (_MASS_BAND[0] <= prenorm_mass <= _MASS_BAND[1]):
        msgs.append(f"pre-norm mass {prenorm_mass:.4f} outside {_MASS_BAND} — extend K grid")
    f = f / max(prenorm_mass, 1e-300)
    cdf = np.concatenate([[0.0], cumulative_trapezoid(f, K)])

    # moments of the RND (MODELED-Q).
    mean = float(np.trapezoid(K * f, K))
    var = float(np.trapezoid((K - mean) ** 2 * f, K))
    std = math.sqrt(max(var, 0.0))
    skew = float(np.trapezoid(((K - mean) / std) ** 3 * f, K)) if std > 0 else 0.0
    kurt = float(np.trapezoid(((K - mean) / std) ** 4 * f, K)) - 3.0 if std > 0 else 0.0

    obs_lo, obs_hi = float(sl.strikes.min()), float(sl.strikes.max())
    crash_prob: dict[str, float] = {}
    crash_extrap: dict[str, bool] = {}
    upside_prob: dict[str, float] = {}
    for theta in CRASH_THRESHOLDS:
        lbl = _thr_label(theta)
        crash_prob[lbl] = float(np.interp(theta * S0, K, cdf))
        crash_extrap[lbl] = bool(theta * S0 < obs_lo)     # below deepest observed strike => extrapolated
        upside_prob[_thr_label(2.0 - theta)] = 1.0 - float(np.interp((2.0 - theta) * S0, K, cdf))

    exercise_prob = {f"{round(ks):d}": 1.0 - float(np.interp(ks, K, cdf)) for ks in ladder_strikes}

    # ── ACCEPTANCE TEST: reprice the OBSERVED chain from the RND (∫ f·payoff dS) vs the market mark ──
    rel_core: list[float] = []
    floor = 1e-3 * F
    for Ks, kind, iv_m, kk in zip(sl.strikes, sl.kinds, sl.mark_iv, sl.k, strict=True):
        payoff = np.maximum(K - Ks, 0.0) if kind == "call" else np.maximum(Ks - K, 0.0)
        p_rnd = float(np.trapezoid(payoff * f, K))
        p_mkt = price_black76(F, float(Ks), 0.0, float(iv_m), sl.T, kind)
        if abs(kk) <= math.log(1.0 / 0.6):                # tradeable-ish core (|k| within ~+/-51%)
            rel_core.append(abs(p_rnd - p_mkt) / max(p_mkt, floor))
    roundtrip_arpe = float(np.mean(rel_core)) if rel_core else float("nan")
    if math.isfinite(roundtrip_arpe) and roundtrip_arpe > _ROUNDTRIP_ARPE_MAX:
        msgs.append(f"round-trip ARPE {roundtrip_arpe*100:.2f}% > {_ROUNDTRIP_ARPE_MAX*100:.0f}% "
                    "— RND does not reprice the observed chain")

    atm_iv_svi = float(p.iv(0.0))
    atm_iv_obs = float(np.interp(0.0, sl.k, sl.mark_iv))

    gates_pass = (bf_free and min_density >= _DENSITY_TOL
                  and _MASS_BAND[0] <= prenorm_mass <= _MASS_BAND[1]
                  and (not math.isfinite(roundtrip_arpe) or roundtrip_arpe <= _ROUNDTRIP_ARPE_MAX))

    return RndSlice(
        label=sl.label, T_years=sl.T, T_days=sl.T * 365.0, forward=F, spot=S0,
        n_strikes=int(sl.k.size), obs_strike_lo=obs_lo, obs_strike_hi=obs_hi,
        obs_moneyness_lo=obs_lo / S0, butterfly_free=bf_free, min_g=min_g,
        min_density=min_density, prenorm_mass=prenorm_mass, svi_iv_rmse_vp=fit.iv_rmse * 100.0,
        atm_iv_svi=atm_iv_svi, atm_iv_observed=atm_iv_obs,
        rnd_mean=mean, rnd_std=std, rnd_skew=skew, rnd_kurt=kurt,
        crash_prob=crash_prob, crash_extrapolated=crash_extrap, upside_prob=upside_prob,
        exercise_prob=exercise_prob, roundtrip_arpe_core=roundtrip_arpe,
        roundtrip_n_core=len(rel_core), gates_pass=gates_pass, messages=tuple(msgs),
    )


def extract_rnd(
    slices: Sequence[ChainSlice], spot: float, ladder_strikes: Sequence[float] = (),
    t_floor_days: float = 14.0, min_strikes: int = 15,
    grid_lo: float = 0.10, grid_hi: float = 5.0, n_grid: int = 4000,
    objective: str = "total_variance",
) -> RndReport:
    """Extract the arb-free RND + crash/exercise probabilities per usable expiry slice.

    Only slices with ``T >= t_floor_days`` and ``>= min_strikes`` observed strikes are scored
    (the A5 floor: BL needs a wide, well-populated smile). ``spot`` is the crash-threshold
    reference S0 (use the OBSERVED index/spot, NOT the forward). ``ladder_strikes`` are the
    mandate's covered-call strikes (USD) for the market-implied P(exercise) cross-check.
    """
    fit = fit_svi_surface(slices, objective=objective)
    by_label = {s.label: s for s in fit.slices}
    out: list[RndSlice] = []
    for sl in slices:
        if t_floor_days > sl.T * 365.0 or sl.k.size < min_strikes:
            continue
        f = by_label.get(sl.label)
        if f is None:
            continue
        out.append(_rnd_for_slice(sl, f, spot, ladder_strikes, grid_lo, grid_hi, n_grid))
    out.sort(key=lambda s: s.T_years)
    return RndReport(spot=spot, n_slices=len(out), slices=out,
                     ladder_strikes_usd=tuple(float(k) for k in ladder_strikes))
