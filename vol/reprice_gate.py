"""Price-space repricing accuracy + validation gate for the arb-free SVI surface (D2 · Aug-2026).

SIMULATED / diagnostic PROTOTYPE — NEW file, canonical main untouched. Addresses the
c8_study_S0_register.md T0-4 open item ("surface fit_rmse never asserted") by turning the
already-built SVI/SSVI surface (``vol.svi`` / ``vol.chain_surface``) into a *price-space*
reprice-the-chain gate the engine can assert on.

WHY THIS EXISTS
---------------
``vol.chain_surface`` already fits an arbitrage-free SVI/SSVI surface and reports an *IV-space*
RMSE (vol points). It never reports a *price-space* ARPE, and there is no assertion that the
surface actually reprices the live chain. The deck's headline "pricing accuracy" is an ARPE
(average relative PRICE error), so the honest, deck-facing number must be computed in price space,
apples-to-apples with the parametric-model ARPE (Bates ~5.55%, Heston 8.08%).

TWO DISTINCT ACCURACY NOTIONS (keep them separate in any claim)
---------------------------------------------------------------
(a) Reprice the actual traded ladder strikes off the OBSERVED per-strike Deribit smile.
    Near-exact by construction — the only residual is the smile-interpolation error at those
    strikes. This is NOT a model-accuracy claim; it is "we price the ladder off the live market."
(b) A single surface/model repriced across the WHOLE chain: the genuine model-accuracy ARPE.
    A per-slice arb-free SVI surface reaches this best.

THE HONEST ≤2% RESULT (measured on the OBSERVED fixture chain, ref 2026-07-30)
-----------------------------------------------------------------------------
ARPE is pathologically sensitive to near-worthless deep-OTM wings: on the fixture, |delta|<0.05
options carry a *median half bid-ask spread of ~14.5% of their own price* — there is no tradeable
"true price" to reprice to within 2%. Measuring on the LIQUID, TRADEABLE CORE (the strikes that
actually trade) is standard vol-desk practice and is the honest metric:

    |delta| in [0.10, 0.90] : SVI ARPE ~1.46%   (~80% of options within their own bid-ask spread)
    |delta| in [0.15, 0.85] : SVI ARPE ~1.28%
    |delta| in [0.05, 0.95] : SVI ARPE ~2.12%
    whole chain (14d+)      : SVI ARPE ~3.96%   (dragged up by untradeable wings)

The gate below therefore asserts ARPE on a declared delta band, and separately reports the
whole-chain number so nothing is hidden.

Marking convention (B3, consistent with vol.calibrate): every option priced/compared with
Black-76 on the OBSERVED per-expiry forward, r = q = 0 (Deribit convention).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

import numpy as np
import numpy.typing as npt

from engine.data_models import BookSummary
from pricing.black76 import greeks_black76, price_black76
from vol.chain import parse_instrument_name
from vol.chain_surface import ChainSlice, fit_svi_surface

FloatArr = npt.NDArray[np.float64]
BoolArr = npt.NDArray[np.bool_]

# IV(slice_index, slice) -> fitted IV array aligned to slice.strikes.
IvGetter = Callable[[int, ChainSlice], FloatArr]
# (expiry-label, round(strike,2), kind) -> USD half bid-ask spread.
SpreadMap = dict[tuple[str, float, str], float]


def spreads_from_book_summaries(book_summaries: Sequence[BookSummary]) -> SpreadMap:
    """USD half bid-ask spread per option, from the OBSERVED book-summary bid/ask *price*.

    Deribit book_summary quotes bid/ask in BTC; USD half-spread = (ask-bid)*underlying/2. Used
    when the slice's bid_iv/ask_iv are absent (this fixture only carries bid/ask price)."""
    out: SpreadMap = {}
    for bs in book_summaries:
        p = parse_instrument_name(bs.instrument_name)
        if p is None or bs.bid_price is None or bs.ask_price is None:
            continue
        if bs.ask_price <= bs.bid_price or bs.underlying_price <= 0:
            continue
        lbl = p.expiry.strftime("%d%b%y").upper()
        out[(lbl, round(p.strike, 2), p.kind)] = (bs.ask_price - bs.bid_price) * bs.underlying_price / 2.0
    return out


@dataclass(frozen=True)
class OptionReprice:
    label: str
    T_days: float
    k: float               # log-moneyness ln(K/F)
    strike: float
    kind: str
    delta: float           # Black-76 delta at the market mark_iv
    p_market: float        # USD, Black-76 on F at mark_iv
    p_model: float         # USD, Black-76 on F at the surface IV
    rel_price_err: float   # |p_model - p_market| / max(p_market, floor)
    iv_err: float          # |iv_model - iv_market|
    half_spread_usd: float # USD half bid-ask (nan if not two-sided)


@dataclass(frozen=True)
class RepriceReport:
    """Price-space reprice-the-chain report. Provenance: CALCULATED from an OBSERVED chain."""

    options: list[OptionReprice]
    delta_band: tuple[float, float]
    # headline metrics on the declared tradeable delta band:
    arpe_core: float
    median_rel_core: float
    iv_rmse_core: float
    within_spread_frac_core: float     # fraction repriced within their own bid-ask
    n_core: int
    # full-chain (nothing hidden):
    arpe_all: float
    iv_rmse_all: float
    n_all: int
    provenance: str = "CALCULATED_FROM_OBSERVED"

    def region_table(self) -> list[dict[str, object]]:
        """ARPE / IV-RMSE by moneyness region and by tenor (for the report/figure)."""
        rows = self.options
        kk = np.array([o.k for o in rows])
        rel = np.array([o.rel_price_err for o in rows])
        iverr = np.array([o.iv_err for o in rows])
        Td = np.array([o.T_days for o in rows])
        out: list[dict[str, object]] = []

        def add(name: str, mask: BoolArr) -> None:
            if int(mask.sum()) == 0:
                return
            out.append({
                "region": name, "n": int(mask.sum()),
                "arpe_pct": round(float(rel[mask].mean()) * 100, 3),
                "iv_rmse_vp": round(float(math.sqrt((iverr[mask] ** 2).mean())) * 100, 2),
            })

        add("ATM |k|<=0.10", np.abs(kk) <= 0.10)
        add("near 0.10-0.25", (np.abs(kk) > 0.10) & (np.abs(kk) <= 0.25))
        add("wings |k|>0.25", np.abs(kk) > 0.25)
        for lo, hi in [(14, 25), (25, 45), (45, 75), (75, 140), (140, 400)]:
            add(f"tenor {lo}-{hi}d", (Td >= lo) & (Td < hi))
        return out

    def per_tenor_core_table(
        self, delta_band: tuple[float, float] | None = None,
    ) -> list[dict[str, object]]:
        """CORE ARPE per EXPIRY, restricting to the tradeable delta band WITHIN each tenor.

        This is the honest per-tenor number (A1 §3): ``region_table``'s per-tenor ARPE is
        computed over the whole chain in that tenor (wing-dragged) and overstates the tradeable
        error. Here each expiry is bucketed separately and only its |delta|-in-band options are
        scored — the metric the ladder actually trades against, tenor by tenor.

        ``delta_band`` overrides the report's band (all options are retained on the report, so
        any band can be re-applied; A1's per-tenor table uses [0.15, 0.85]).
        """
        lo, hi = delta_band if delta_band is not None else self.delta_band
        by_label: dict[str, list[OptionReprice]] = {}
        for o in self.options:
            if lo <= abs(o.delta) <= hi:
                by_label.setdefault(o.label, []).append(o)
        rows: list[dict[str, object]] = []
        for label, opts in by_label.items():
            rel = np.array([o.rel_price_err for o in opts])
            rows.append({
                "label": label,
                "T_days": round(float(np.median([o.T_days for o in opts])), 1),
                "arpe_pct": round(float(rel.mean()) * 100, 3),
                "median_rel_pct": round(float(np.median(rel)) * 100, 3),
                "n": int(rel.size),
            })
        rows.sort(key=lambda r: r["T_days"])  # type: ignore[arg-type,return-value]
        return rows


def _floor(forward: float) -> float:
    """Deep-OTM price floor = 0.1% of forward (documented in vol.calibrate._fit_stats)."""
    return 1e-3 * forward


def price_reprice_report(
    slices: Sequence[ChainSlice],
    iv_getter: IvGetter,
    delta_band: tuple[float, float] = (0.10, 0.90),
    t_floor_days: float = 14.0,
    min_strikes: int = 5,
    spread_map: SpreadMap | None = None,
) -> RepriceReport:
    """Reprice every liquid option from a surface's IV and score it in PRICE space.

    ``iv_getter(i, slice)`` returns the surface's fitted IV per strike for slice ``i``. Options
    with |delta| inside ``delta_band`` form the "tradeable core" the headline ARPE is measured on;
    the whole-chain number is reported alongside. The within-spread fraction uses ``spread_map``
    (USD half-spread per option, see ``spreads_from_book_summaries``) when given, else the slice's
    bid_iv/ask_iv, else nan.
    """
    opts: list[OptionReprice] = []
    for i, sl in enumerate(slices):
        if t_floor_days / 365.0 > sl.T or sl.k.size < min_strikes:
            continue
        iv_fit = np.asarray(iv_getter(i, sl), dtype=np.float64)
        for j in range(sl.k.size):
            K = float(sl.strikes[j])
            kind = sl.kinds[j]
            iv_m = float(sl.mark_iv[j])
            iv_f = float(iv_fit[j])
            p_mkt = price_black76(sl.forward, K, 0.0, iv_m, sl.T, kind)
            p_mod = price_black76(sl.forward, K, 0.0, iv_f, sl.T, kind)
            dlt = greeks_black76(sl.forward, K, 0.0, iv_m, sl.T, kind).delta
            hs = float("nan")
            if spread_map is not None:
                hs = spread_map.get((sl.label, round(K, 2), kind), float("nan"))
            if not math.isfinite(hs):
                b_iv, a_iv = float(sl.bid_iv[j]), float(sl.ask_iv[j])
                if math.isfinite(b_iv) and math.isfinite(a_iv) and a_iv > b_iv > 0:
                    p_b = price_black76(sl.forward, K, 0.0, b_iv, sl.T, kind)
                    p_a = price_black76(sl.forward, K, 0.0, a_iv, sl.T, kind)
                    hs = abs(p_a - p_b) / 2.0
            opts.append(OptionReprice(
                label=sl.label, T_days=sl.T * 365.0, k=float(sl.k[j]), strike=K, kind=kind,
                delta=float(dlt), p_market=p_mkt, p_model=p_mod,
                rel_price_err=abs(p_mod - p_mkt) / max(p_mkt, _floor(sl.forward)),
                iv_err=abs(iv_f - iv_m), half_spread_usd=hs,
            ))

    rel = np.array([o.rel_price_err for o in opts])
    iverr = np.array([o.iv_err for o in opts])
    adl = np.array([abs(o.delta) for o in opts])
    resid = np.array([abs(o.p_model - o.p_market) for o in opts])
    hs_arr = np.array([o.half_spread_usd for o in opts])

    lo, hi = delta_band
    core = (adl >= lo) & (adl <= hi)
    core_q = core & np.isfinite(hs_arr)
    within = float(np.mean(resid[core_q] <= hs_arr[core_q])) if int(core_q.sum()) else float("nan")

    return RepriceReport(
        options=opts, delta_band=delta_band,
        arpe_core=float(rel[core].mean()) if int(core.sum()) else float("nan"),
        median_rel_core=float(np.median(rel[core])) if int(core.sum()) else float("nan"),
        iv_rmse_core=float(math.sqrt((iverr[core] ** 2).mean())) if int(core.sum()) else float("nan"),
        within_spread_frac_core=within, n_core=int(core.sum()),
        arpe_all=float(rel.mean()) if rel.size else float("nan"),
        iv_rmse_all=float(math.sqrt((iverr ** 2).mean())) if iverr.size else float("nan"),
        n_all=int(rel.size),
    )


def svi_iv_getter(
    slices: Sequence[ChainSlice], objective: str = "total_variance",
) -> IvGetter:
    """Fit a per-slice arb-free SVI surface and return an IvGetter over it.

    Slices with no SVI fit (too few strikes) fall back to their own observed IV (zero error there),
    so they never spuriously help or hurt the ARPE — they are simply not scored as model error.

    ``objective`` is forwarded to ``fit_svi_surface`` (``"total_variance"`` default, or
    ``"vega_price"`` for the Gatheral §5.2 price-relative slice fit — A1 §2C).
    """
    fit = fit_svi_surface(slices, objective=objective)
    by_label = {s.label: s for s in fit.slices}

    def getter(i: int, sl: ChainSlice) -> FloatArr:
        f = by_label.get(sl.label)
        if f is None:
            return sl.mark_iv
        return f.params.iv(sl.k)

    return getter


# ── Validation gate (T0-4): assert the surface reprices the live chain ──────────


class RepriceGateError(AssertionError):
    """Raised when the fitted surface fails to reprice the observed chain within tolerance."""


@dataclass(frozen=True)
class RepriceGateResult:
    passed: bool
    arpe_core: float
    arpe_max: float
    within_spread_frac_core: float
    within_spread_min: float
    delta_band: tuple[float, float]
    n_core: int
    messages: tuple[str, ...] = field(default_factory=tuple)


def assert_reprice_gate(
    report: RepriceReport,
    arpe_max: float = 0.02,
    within_spread_min: float = 0.70,
    raise_on_fail: bool = False,
) -> RepriceGateResult:
    """Engine validation gate: the surface must reprice the tradeable core within tolerance.

    Default thresholds encode the honest deck claim:
      * ARPE on the declared delta band <= 2% (the "~98% pricing accuracy" claim), AND
      * >= 70% of core options repriced within their OWN bid-ask spread.

    Set ``raise_on_fail=True`` to hard-fail (for CI). The whole-chain ARPE is reported by the
    ``RepriceReport`` and is intentionally NOT gated (untradeable wings are not a fair target).
    """
    msgs: list[str] = []
    ok_arpe = report.arpe_core <= arpe_max
    if not ok_arpe:
        msgs.append(f"core ARPE {report.arpe_core * 100:.3f}% > {arpe_max * 100:.2f}% "
                    f"on delta band {report.delta_band}")
    ok_ws = (not math.isfinite(report.within_spread_frac_core)
             or report.within_spread_frac_core >= within_spread_min)
    if not ok_ws:
        msgs.append(f"within-spread {report.within_spread_frac_core * 100:.1f}% < "
                    f"{within_spread_min * 100:.0f}%")
    passed = ok_arpe and ok_ws
    if not passed and raise_on_fail:
        raise RepriceGateError("; ".join(msgs))
    return RepriceGateResult(
        passed=passed, arpe_core=report.arpe_core, arpe_max=arpe_max,
        within_spread_frac_core=report.within_spread_frac_core,
        within_spread_min=within_spread_min, delta_band=report.delta_band,
        n_core=report.n_core, messages=tuple(msgs),
    )


@dataclass(frozen=True)
class PerTenorGateResult:
    """Per-tenor reprice-gate outcome (A1 §3E). ``passed`` reflects the TRADED tenor bucket.

    ``traded_arpe`` is the core ARPE on the ladder tenor (hard-gated); ``warnings`` lists any
    OTHER tenor whose core ARPE exceeds ``arpe_max`` (surfaced, not hard-failed — non-traded
    tenors are diagnostics, e.g. the 57d liquidity anomaly A1 §3D)."""

    passed: bool
    traded_tenor_days: tuple[float, float]
    traded_arpe: float          # nan if no expiry falls in the traded window
    arpe_max: float
    delta_band: tuple[float, float]
    per_tenor: tuple[dict[str, object], ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    messages: tuple[str, ...] = field(default_factory=tuple)


def assert_per_tenor_gate(
    report: RepriceReport,
    arpe_max: float = 0.02,
    traded_tenor_days: tuple[float, float] = (25.0, 45.0),
    delta_band: tuple[float, float] | None = None,
    raise_on_fail: bool = False,
) -> PerTenorGateResult:
    """Per-tenor reprice gate (A1 §3B): HARD-assert the traded ~1-month bucket, WARN the rest.

    The default ``assert_reprice_gate`` gates only the tenor-AGGREGATED core ARPE, which passes
    at ~1.46% precisely because long-dated slices (148-330d reprice to 0.3-0.8%) dominate. The
    tenor the ladder actually trades (~1 month) sits higher; this gate scores each expiry on its
    own tradeable core and binds on the traded bucket alone, so "enforced <=2%" means the number
    on the tenor we trade — not an aggregate average that hides it.

    Honesty rule (FOUNDATIONS §10 lock #6): if the traded bucket sits above ``arpe_max`` after
    a legitimate calibration change, DO NOT edit the threshold to a target — set the deck/gate
    threshold to the number ACTUALLY achieved and report it (~97.6% on the traded tenor). This
    function reports the measured ``traded_arpe`` regardless of pass/fail so nothing is hidden.
    """
    band = delta_band if delta_band is not None else report.delta_band
    table = report.per_tenor_core_table(delta_band=band)
    lo_d, hi_d = traded_tenor_days
    traded_rows = [r for r in table if lo_d <= cast(float, r["T_days"]) < hi_d]
    if traded_rows:
        # n-weighted core ARPE across expiries in the traded window (usually exactly one).
        n_tot = sum(cast(int, r["n"]) for r in traded_rows)
        traded_arpe = sum(
            cast(float, r["arpe_pct"]) / 100.0 * cast(int, r["n"]) for r in traded_rows
        ) / max(n_tot, 1)
    else:
        traded_arpe = float("nan")

    msgs: list[str] = []
    if not traded_rows:
        msgs.append(f"no expiry in the traded window {traded_tenor_days}d — gate is vacuous")
        passed = False
    else:
        passed = traded_arpe <= arpe_max
        if not passed:
            msgs.append(
                f"traded-tenor core ARPE {traded_arpe * 100:.3f}% > {arpe_max * 100:.2f}% "
                f"on {traded_tenor_days}d, band {band}")

    warnings: list[str] = []
    for r in table:
        if lo_d <= float(r["T_days"]) < hi_d:  # type: ignore[arg-type]
            continue
        if float(r["arpe_pct"]) > arpe_max * 100.0:  # type: ignore[arg-type]
            warnings.append(
                f"{r['label']} ({r['T_days']}d): core ARPE {r['arpe_pct']}% > "
                f"{arpe_max * 100:.2f}% (non-traded, diagnostic)")

    if not passed and raise_on_fail:
        raise RepriceGateError("; ".join(msgs))
    return PerTenorGateResult(
        passed=passed, traded_tenor_days=traded_tenor_days, traded_arpe=traded_arpe,
        arpe_max=arpe_max, delta_band=band, per_tenor=tuple(table),
        warnings=tuple(warnings), messages=tuple(msgs),
    )


if __name__ == "__main__":  # pragma: no cover - manual diagnostic on the fixture
    import pathlib
    from datetime import UTC, datetime

    from vol.chain_surface import ingest_chain_slices
    from vol.snapshot import load_snapshot

    fix = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    snap = load_snapshot(fix)
    sl = ingest_chain_slices(snap.instruments, snap.book_summaries, datetime(2026, 7, 30, tzinfo=UTC))
    smap = spreads_from_book_summaries(snap.book_summaries)
    for obj in ("total_variance", "vega_price"):
        rep = price_reprice_report(
            sl, svi_iv_getter(sl, objective=obj), delta_band=(0.10, 0.90), spread_map=smap)
        print(f"\n=== SVI surface reprice — objective={obj} (OBSERVED fixture, ref 2026-07-30) ===")
        print(f"  tradeable core |delta| in {rep.delta_band}:  ARPE={rep.arpe_core*100:.3f}%  "
              f"median={rep.median_rel_core*100:.3f}%  IV_RMSE={rep.iv_rmse_core*100:.2f}vp  "
              f"within-spread={rep.within_spread_frac_core*100:.1f}%  n={rep.n_core}")
        print(f"  whole chain (14d+):  ARPE={rep.arpe_all*100:.3f}%  "
              f"IV_RMSE={rep.iv_rmse_all*100:.2f}vp  n={rep.n_all}")
        gate = assert_reprice_gate(rep, arpe_max=0.02)
        print(f"  AGGREGATE GATE(arpe<=2%): {'PASS' if gate.passed else 'FAIL'}  {gate.messages}")
        pt = assert_per_tenor_gate(rep, arpe_max=0.02, delta_band=(0.15, 0.85))
        print(f"  PER-TENOR core ARPE (band {pt.delta_band}):")
        for r in pt.per_tenor:
            print("     ", r)
        print(f"  TRADED-TENOR GATE {pt.traded_tenor_days}d: "
              f"{'PASS' if pt.passed else 'FAIL'}  traded_arpe="
              f"{pt.traded_arpe*100:.3f}%  {pt.messages}")
        for w in pt.warnings:
            print("      WARN:", w)
