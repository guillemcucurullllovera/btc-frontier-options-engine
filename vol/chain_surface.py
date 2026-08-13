"""Full live-chain ingest -> arbitrage-free SVI/SSVI surface + static no-arb gate (C9 · M0.2).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Prerequisite for all
calibration (M2+): today the engine ingests only per-tenor ATM IV; this ingests the
WHOLE listed chain (every liquid strike x expiry) into per-expiry smile slices in
total-variance / log-moneyness space off the OBSERVED per-expiry forward (B3 convention:
Deribit IV uses the forward, not the index).

Pipeline
--------
1. ``ingest_chain_slices`` — whole-chain -> slices; one OTM IV per strike (put below F,
   call at/above F), forward F = median ``underlying_price`` for the expiry.
2. ``static_no_arb_gate`` — Hirsa §7.8 checks on the RAW chain (in undiscounted r=0 call
   prices via Black-76 on F): call-price monotonicity, slope in [-1,0], butterfly convexity,
   and calendar (total variance non-decreasing in T). Diagnostic report, not a hard fail.
3. ``fit_svi_surface`` / ``fit_ssvi_surface`` — calibrate; reprice-the-chain IV RMSE;
   butterfly (per slice / SSVI conditions) + calendar on the FITTED surface.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise

import numpy as np
import numpy.typing as npt

from engine.data_models import BookSummary, OptionInstrument
from pricing.black76 import greeks_black76, price_black76
from vol.chain import parse_instrument_name
from vol.svi import (
    SsviParams,
    SviParams,
    calendar_arb_free,
    calibrate_ssvi,
    calibrate_svi_slice,
    ssvi_butterfly_free,
    svi_butterfly_free,
)

FloatArr = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ChainSlice:
    """One expiry's liquid smile in log-moneyness/total-variance space (OTM IVs)."""

    expiry: datetime
    label: str
    T: float                 # years
    forward: float           # observed per-expiry forward (USD)
    strikes: FloatArr        # sorted ascending
    k: FloatArr              # log-moneyness ln(K/F)
    mark_iv: FloatArr        # decimal, OTM per strike
    bid_iv: FloatArr         # decimal (NaN where unavailable)
    ask_iv: FloatArr
    kinds: tuple[str, ...]   # "call"/"put" of the OTM option used per strike

    @property
    def total_variance(self) -> FloatArr:
        return np.asarray(self.mark_iv * self.mark_iv * self.T, dtype=np.float64)

    @property
    def weights(self) -> FloatArr:
        spread = np.where(np.isfinite(self.ask_iv - self.bid_iv), self.ask_iv - self.bid_iv, np.nan)
        w = 1.0 / np.maximum(np.nan_to_num(spread, nan=0.05), 1e-3)
        return np.asarray(w, dtype=np.float64)


def _is_liquid(bs: BookSummary) -> bool:
    return (bs.mark_iv > 0.0 and bs.bid_price is not None
            and bs.ask_price is not None and bs.open_interest > 0.0)


def ingest_chain_slices(
    instruments: Sequence[OptionInstrument],
    book_summaries: Sequence[BookSummary],
    reference: datetime,
    min_strikes: int = 5,
) -> list[ChainSlice]:
    """Ingest the whole liquid chain into per-expiry OTM smile slices (sorted by T)."""
    book = {b.instrument_name: b for b in book_summaries}
    by_exp: dict[datetime, list[tuple[OptionInstrument, BookSummary]]] = defaultdict(list)
    for inst in instruments:
        bs = book.get(inst.instrument_name)
        if bs is not None and _is_liquid(bs):
            by_exp[inst.expiration_timestamp].append((inst, bs))

    slices: list[ChainSlice] = []
    for exp, rows in by_exp.items():
        T = (exp - reference).total_seconds() / (365.0 * 86400.0)
        if T <= 0:
            continue
        fwds = np.array([bs.underlying_price for _, bs in rows if bs.underlying_price > 0],
                        dtype=np.float64)
        if fwds.size == 0:
            continue
        F = float(np.median(fwds))

        # One OTM option per strike: put for K<F, call for K>=F. Prefer the exact OTM kind.
        by_strike: dict[float, dict[str, BookSummary]] = defaultdict(dict)
        for inst, bs in rows:
            by_strike[inst.strike][inst.option_type] = bs
        picked: list[tuple[float, str, BookSummary]] = []
        for K, kinds in by_strike.items():
            want = "put" if K < F else "call"
            bs = kinds.get(want) or next(iter(kinds.values()))
            kind = want if want in kinds else next(iter(kinds))
            picked.append((K, kind, bs))
        if len(picked) < min_strikes:
            continue
        picked.sort(key=lambda x: x[0])

        strikes = np.array([p[0] for p in picked], dtype=np.float64)
        mark_iv = np.array([p[2].mark_iv for p in picked], dtype=np.float64)
        bid_iv = np.array([p[2].bid_iv if p[2].bid_iv is not None else np.nan for p in picked],
                          dtype=np.float64)
        ask_iv = np.array([p[2].ask_iv if p[2].ask_iv is not None else np.nan for p in picked],
                          dtype=np.float64)
        slices.append(ChainSlice(
            expiry=exp, label=exp.strftime("%d%b%y").upper(), T=T, forward=F,
            strikes=strikes, k=np.log(strikes / F), mark_iv=mark_iv,
            bid_iv=bid_iv, ask_iv=ask_iv, kinds=tuple(p[1] for p in picked),
        ))
    slices.sort(key=lambda s: s.T)
    return slices


def slices_from_book_summaries(
    book_summaries: Sequence[BookSummary],
    reference: datetime | None = None,
    min_strikes: int = 5,
) -> list[ChainSlice]:
    """Ingest slices from book summaries alone (strike/expiry/kind parsed from the name).

    Used where the full instrument list is not threaded through (e.g. ``fit_surface``).
    Expiry is taken at 08:00 UTC (Deribit settlement); T off ``reference`` (default: the
    first book's timestamp). Same OTM-per-strike selection as ``ingest_chain_slices``.
    """
    if not book_summaries:
        return []
    ref = reference or book_summaries[0].timestamp
    by_exp: dict[datetime, list[tuple[float, str, BookSummary]]] = defaultdict(list)
    for bs in book_summaries:
        if not _is_liquid(bs):
            continue
        parsed = parse_instrument_name(bs.instrument_name)
        if parsed is None:
            continue
        exp_dt = datetime(parsed.expiry.year, parsed.expiry.month, parsed.expiry.day, 8, 0, tzinfo=UTC)
        by_exp[exp_dt].append((parsed.strike, parsed.kind, bs))

    slices: list[ChainSlice] = []
    for exp, rows in by_exp.items():
        T = (exp - ref).total_seconds() / (365.0 * 86400.0)
        if T <= 0:
            continue
        fwds = np.array([bs.underlying_price for _, _, bs in rows if bs.underlying_price > 0],
                        dtype=np.float64)
        if fwds.size == 0:
            continue
        F = float(np.median(fwds))
        by_strike: dict[float, dict[str, BookSummary]] = defaultdict(dict)
        for K, kind, bs in rows:
            by_strike[K][kind] = bs
        picked: list[tuple[float, str, BookSummary]] = []
        for K, kinds in by_strike.items():
            want = "put" if K < F else "call"
            bs = kinds.get(want) or next(iter(kinds.values()))
            kind = want if want in kinds else next(iter(kinds))
            picked.append((K, kind, bs))
        if len(picked) < min_strikes:
            continue
        picked.sort(key=lambda x: x[0])
        strikes = np.array([p[0] for p in picked], dtype=np.float64)
        slices.append(ChainSlice(
            expiry=exp, label=exp.strftime("%d%b%y").upper(), T=T, forward=F,
            strikes=strikes, k=np.log(strikes / F),
            mark_iv=np.array([p[2].mark_iv for p in picked], dtype=np.float64),
            bid_iv=np.array([p[2].bid_iv if p[2].bid_iv is not None else np.nan for p in picked],
                            dtype=np.float64),
            ask_iv=np.array([p[2].ask_iv if p[2].ask_iv is not None else np.nan for p in picked],
                            dtype=np.float64),
            kinds=tuple(p[1] for p in picked),
        ))
    slices.sort(key=lambda s: s.T)
    return slices


# ── Static no-arbitrage gate on the RAW chain (Hirsa §7.8) ──────────────────


@dataclass(frozen=True)
class SliceArbReport:
    label: str
    T: float
    n_strikes: int
    monotonicity_violations: int      # call price rising in K
    slope_violations: int             # dC/dK outside [-1, 0]
    convexity_violations: int         # negative butterfly (non-convex call curve)
    worst_convexity: float            # most-negative second divided difference (price)


@dataclass(frozen=True)
class StaticNoArbReport:
    slices: list[SliceArbReport]
    calendar_violations: int          # adjacent-expiry total-variance decreases on the k-grid
    worst_calendar: float             # most-negative w_next - w_prev
    n_slices: int

    @property
    def is_clean(self) -> bool:
        per_slice = all(
            s.monotonicity_violations == 0 and s.slope_violations == 0
            and s.convexity_violations == 0 for s in self.slices
        )
        return per_slice and self.calendar_violations == 0

    @property
    def total_violations(self) -> int:
        return sum(s.monotonicity_violations + s.slope_violations + s.convexity_violations
                   for s in self.slices) + self.calendar_violations


def _call_prices_undiscounted(sl: ChainSlice) -> FloatArr:
    """Undiscounted (r=0) call price at each strike from the OTM IV, via Black-76 + parity."""
    calls = np.empty(sl.strikes.size, dtype=np.float64)
    for i, (K, kind, iv) in enumerate(zip(sl.strikes, sl.kinds, sl.mark_iv, strict=True)):
        px = price_black76(sl.forward, float(K), 0.0, float(iv), sl.T, kind)
        # Put-call parity on the forward, r=0: C = P + (F - K).
        calls[i] = px if kind == "call" else px + (sl.forward - float(K))
    return calls


def static_no_arb_gate(
    slices: Sequence[ChainSlice], k_grid: FloatArr | None = None, tol: float = 1e-6,
) -> StaticNoArbReport:
    """Raw-chain static no-arbitrage checks (monotonicity / slope / convexity / calendar)."""
    if k_grid is None:
        k_grid = np.linspace(-0.5, 0.5, 51)
    reports: list[SliceArbReport] = []
    tv_by_slice: list[tuple[float, FloatArr]] = []
    for sl in slices:
        C = _call_prices_undiscounted(sl)
        K = sl.strikes
        dC = np.diff(C)
        dK = np.diff(K)
        slope = dC / dK
        mono = int(np.sum(dC > tol * sl.forward))                 # call price must fall in K
        slope_bad = int(np.sum((slope > tol) | (slope < -1.0 - tol)))
        # Convexity: second divided difference >= 0 (butterfly).
        conv = np.diff(slope) / ((K[2:] - K[:-2]) / 2.0)
        conv_bad = int(np.sum(conv < -tol))
        worst_conv = float(np.min(conv)) if conv.size else 0.0
        reports.append(SliceArbReport(
            label=sl.label, T=sl.T, n_strikes=int(K.size),
            monotonicity_violations=mono, slope_violations=slope_bad,
            convexity_violations=conv_bad, worst_convexity=worst_conv,
        ))
        # Total variance on the common k-grid (flat extrapolation beyond listed range).
        w = np.interp(k_grid, sl.k, sl.total_variance)
        tv_by_slice.append((sl.T, w))

    _, worst_cal = calendar_arb_free(tv_by_slice, k_grid)
    cal_bad = 0
    ordered = sorted(tv_by_slice, key=lambda x: x[0])
    for (_, w0), (_, w1) in pairwise(ordered):
        cal_bad += int(np.sum(w1 - w0 < -tol))
    return StaticNoArbReport(
        slices=reports, calendar_violations=cal_bad, worst_calendar=worst_cal,
        n_slices=len(slices),
    )


# ── SVI / SSVI surface fits ─────────────────────────────────────────────────


@dataclass(frozen=True)
class SviSliceFit:
    label: str
    T: float
    params: SviParams
    iv_rmse: float                 # reprice-the-chain: RMSE of fitted vs observed IV (vol pts)
    n_strikes: int
    butterfly_free: bool
    min_g: float


@dataclass(frozen=True)
class SviSurfaceFit:
    slices: list[SviSliceFit]
    calendar_free: bool
    worst_calendar: float
    overall_iv_rmse: float
    method: str = "svi"

    @property
    def butterfly_free(self) -> bool:
        return all(s.butterfly_free for s in self.slices)


def _vega_price_weights(sl: ChainSlice) -> FloatArr:
    """Per-strike weight vega_i/max(P_i,floor) × quote-quality (A1 §2C price-relative objective).

    Combined with an IV-space SVI fit this is the cheap first-order equivalent of Gatheral
    §5.2's price-relative objective vega·Δσ/max(P,floor): it steers the fit toward near-ATM
    price fidelity (which the ARPE gate scores) instead of the wing-dominated total-variance
    LSQ. The quote-quality factor (1/half-IV-spread, already in ``sl.weights``) makes the
    tightest, most-reliable quotes bind hardest.
    """
    floor = 1e-3 * sl.forward
    vega = np.empty(sl.k.size, dtype=np.float64)
    price = np.empty(sl.k.size, dtype=np.float64)
    for j, (K, kind, iv) in enumerate(zip(sl.strikes, sl.kinds, sl.mark_iv, strict=True)):
        g = greeks_black76(sl.forward, float(K), 0.0, float(iv), sl.T, kind)
        vega[j] = g.vega
        price[j] = price_black76(sl.forward, float(K), 0.0, float(iv), sl.T, kind)
    quote_q = sl.weights                      # 1/half-IV-spread (nan-safe, see ChainSlice)
    w = quote_q * vega / np.maximum(price, floor)
    return np.asarray(np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0), dtype=np.float64)


def fit_svi_surface(
    slices: Sequence[ChainSlice], objective: str = "total_variance",
) -> SviSurfaceFit:
    """Per-slice raw-SVI calibration + butterfly (per slice) + calendar (across slices).

    ``objective`` selects the slice calibration metric (A1 §2C):
      * ``"total_variance"`` (default, back-compat) — quote-quality-weighted total-variance LSQ.
      * ``"vega_price"`` — vega/price-weighted IV-space fit (Gatheral §5.2 price-relative
        objective, first-order form); aligns the calibration with the price-space ARPE gate.
    """
    if objective not in ("total_variance", "vega_price"):
        raise ValueError(f"objective must be 'total_variance' or 'vega_price', got {objective!r}")
    fits: list[SviSliceFit] = []
    sq_err = 0.0
    n_tot = 0
    tv_by_slice: list[tuple[float, FloatArr]] = []
    k_grid = np.linspace(-0.6, 0.6, 121)
    for sl in slices:
        if sl.k.size < 5:
            continue
        if objective == "vega_price":
            params, _ = calibrate_svi_slice(
                sl.k, sl.total_variance, sl.T, _vega_price_weights(sl), space="iv")
        else:
            params, _ = calibrate_svi_slice(sl.k, sl.total_variance, sl.T, sl.weights)
        fitted_iv = params.iv(sl.k)
        resid = fitted_iv - sl.mark_iv
        iv_rmse = float(np.sqrt(np.mean(resid * resid)))
        free, min_g = svi_butterfly_free(params)
        fits.append(SviSliceFit(
            label=sl.label, T=sl.T, params=params, iv_rmse=iv_rmse,
            n_strikes=int(sl.k.size), butterfly_free=free, min_g=min_g,
        ))
        sq_err += float(np.sum(resid * resid))
        n_tot += int(sl.k.size)
        tv_by_slice.append((sl.T, params.total_variance(k_grid)))

    cal_free, worst_cal = calendar_arb_free(tv_by_slice, k_grid)
    overall = float(np.sqrt(sq_err / max(n_tot, 1)))
    return SviSurfaceFit(
        slices=fits, calendar_free=cal_free, worst_calendar=worst_cal,
        overall_iv_rmse=overall,
    )


@dataclass(frozen=True)
class SsviSurfaceFit:
    params: SsviParams
    thetas: list[float]                # ATM total variance per slice (monotone-enforced)
    labels: list[str]
    overall_iv_rmse: float
    butterfly_free: bool
    worst_butterfly_margin: float
    calendar_free: bool                # monotone theta by construction
    atm_theta_was_monotone: bool
    method: str = "ssvi"
    per_slice_iv_rmse: list[float] = field(default_factory=list)


def _atm_total_variance(sl: ChainSlice) -> float:
    """ATM (k=0) total variance from the slice, via interpolation of total variance in k."""
    return float(np.interp(0.0, sl.k, sl.total_variance))


def fit_ssvi_surface(slices: Sequence[ChainSlice], t_floor: float = 7.0 / 365.0) -> SsviSurfaceFit:
    """Global SSVI fit; monotone ATM total-variance term structure => calendar arb-free.

    ``t_floor`` excludes ultra-near-expiry (0-DTE/intraday) slices: SSVI is a smooth
    whole-surface model whose power-law phi(theta)=eta*theta^-gamma diverges as theta->0,
    so sub-week expiries (microstructure/pin-risk dominated, not used for 30-60 DTE
    calibration) are dropped from the smooth fit. Per-slice SVI still covers them.
    """
    usable = [sl for sl in slices if sl.k.size >= 5 and t_floor <= sl.T]
    if len(usable) < 2:
        raise ValueError("SSVI needs >=2 usable slices at/above t_floor")
    theta_raw = np.array([_atm_total_variance(sl) for sl in usable], dtype=np.float64)
    theta_mono = np.maximum.accumulate(theta_raw)          # enforce non-decreasing (calendar)
    was_monotone = bool(np.all(np.diff(theta_raw) >= -1e-12))

    ks = [sl.k for sl in usable]
    ws = [sl.total_variance for sl in usable]
    wts = [sl.weights for sl in usable]
    params, _ = calibrate_ssvi(ks, ws, theta_mono, wts)

    per_slice_rmse: list[float] = []
    sq_err = 0.0
    n_tot = 0
    for sl, th in zip(usable, theta_mono, strict=True):
        w_fit = params.total_variance(sl.k, float(th))
        fitted_iv = np.sqrt(np.maximum(w_fit, 1e-12) / sl.T)
        resid = fitted_iv - sl.mark_iv
        per_slice_rmse.append(float(np.sqrt(np.mean(resid * resid))))
        sq_err += float(np.sum(resid * resid))
        n_tot += int(sl.k.size)

    bf_free, worst_margin = ssvi_butterfly_free(params, theta_mono)
    return SsviSurfaceFit(
        params=params, thetas=[float(x) for x in theta_mono],
        labels=[sl.label for sl in usable],
        overall_iv_rmse=float(np.sqrt(sq_err / max(n_tot, 1))),
        butterfly_free=bf_free, worst_butterfly_margin=worst_margin,
        calendar_free=True, atm_theta_was_monotone=was_monotone,
        per_slice_iv_rmse=per_slice_rmse,
    )
