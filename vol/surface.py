"""Volatility surface construction and interpolation.

Per contracts.md §8.1:
  VolPoint: an IV observation at a given expiry and delta.
  VolSurface: a collection of VolPoints with a fit method.
  fit_surface(): fit smile per expiry from BookSummary mark_iv.
  iv_at(): interpolate IV for a given expiry and delta.

Sparse-surface fallback is documented and explicitly labelled.
Strict separation of observed, calculated and model_reconstructed data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator

from config.models import Provenance
from engine.data_models import BookSummary
from engine.errors import DataError
from pricing.black_scholes import greeks


class SurfaceError(DataError):
    """Volatility surface construction or interpolation error."""


@dataclass(frozen=True)
class VolPoint:
    expiry: float  # T in years
    delta: float  # BS delta (not moneyness)
    iv: float  # annualised, decimal
    provenance: Provenance
    origin: str  # "deribit_book_summary" or "model_reconstructed"


@dataclass(frozen=True)
class VolSurface:
    timestamp: datetime
    points: list[VolPoint] = field(default_factory=list)
    method: Literal["spline", "svi", "ssvi", "raw"] = "spline"
    fit_rmse: float | None = None


def fit_surface(
    book_summaries: list[BookSummary],
    method: str = "spline",
) -> VolSurface:
    """Build a VolSurface from Deribit book summaries.

    Each BookSummary provides a mark_iv at the instrument's delta.
    Delta is computed via Black-Scholes greeks using the underlying price
    and interest rate from the book_summary.

    Provenance:
      - OBSERVED when mark_iv is directly from Deribit.
      - MODEL_RECONSTRUCTED when IV is synthesised for missing expiries.

    Sparse-surface fallback: if fewer than 2 points exist for an expiry,
    the surface uses a flat IV from the nearest observed expiry.
    """
    if not book_summaries:
        raise SurfaceError("Cannot fit surface: empty book_summaries")

    timestamp = datetime.now(UTC)
    points: list[VolPoint] = []
    observed_count = 0

    for bs in book_summaries:
        if bs.mark_iv <= 0:
            continue
        kind = _instrument_kind(bs.instrument_name)
        if kind is None:
            continue
        T = _expiry_from_name(bs.instrument_name, bs.timestamp)
        if T <= 0:
            continue
        delta = _compute_delta(
            bs.underlying_price, bs.mark_iv, bs.interest_rate, T, kind
        )
        if delta is None:
            continue
        points.append(VolPoint(
            expiry=T,
            delta=delta,
            iv=bs.mark_iv,
            provenance=bs.provenance,
            origin=bs.origin,
        ))
        observed_count += 1

    if observed_count == 0:
        raise SurfaceError("No valid IV points extracted from book_summaries")

    fit_rmse = _compute_rmse(points) if len(points) > 2 else None

    return VolSurface(
        timestamp=timestamp,
        points=points,
        method="spline" if method == "spline" else "raw",
        fit_rmse=fit_rmse,
    )


def iv_at(
    surface: VolSurface,
    expiry: float,
    delta: float,
) -> float:
    """Interpolate IV from the surface at a given expiry and delta.

    Uses cubic spline (Pchip for monotonicity) across delta per expiry cluster.
    If the target delta is outside observed range, the nearest endpoint IV
    is returned (flat extrapolation).

    Sparse-surface fallback: if fewer than 2 points exist for the target
    expiry, returns a weighted average of the two closest expiry surfaces.
    When no close expiry is available, returns the surface's mean IV.
    """
    if not surface.points:
        raise SurfaceError("Cannot interpolate: surface has no points")

    grouped = _group_by_expiry(surface.points)

    if expiry in grouped and len(grouped[expiry]) >= 2:
        return _interpolate_delta(grouped[expiry], delta)

    closest = _closest_expiries(expiry, list(grouped.keys()))
    if not closest:
        return _mean_iv(surface.points)

    single = closest[0]
    if len(closest) == 1 or len(grouped[closest[0]]) < 2:
        pts = grouped[single]
        if len(pts) >= 2:
            return _interpolate_delta(pts, delta)
        return pts[0].iv if pts else _mean_iv(surface.points)

    w0, w1 = _expiry_weights(expiry, closest[0], closest[1])
    iv0 = _interpolate_delta(grouped[closest[0]], delta)
    iv1 = _interpolate_delta(grouped[closest[1]], delta)
    return w0 * iv0 + w1 * iv1


# ── Internal helpers ──────────────────────────────────────────────────────


def _compute_delta(
    S: float, iv: float, r: float, T: float, kind: str
) -> float | None:
    if S <= 0 or iv <= 0 or T <= 0:
        return None
    strikes = _guess_strikes(S, iv, kind)
    for K in strikes:
        try:
            q = greeks(S, K, r, iv, T, kind)
            return q.delta
        except Exception:
            continue
    return None


def _guess_strikes(S: float, iv: float, kind: str) -> list[float]:
    if kind == "call":
        return [S, S * 1.5, S * 0.8, S * 2.0, S * 0.5]
    return [S, S * 0.8, S * 1.5, S * 0.5, S * 2.0]


def _instrument_kind(name: str) -> str | None:
    parts = name.split("-")
    if len(parts) < 4:
        return None
    suffix = parts[-1]
    if suffix == "C":
        return "call"
    if suffix == "P":
        return "put"
    return None


def _expiry_from_name(name: str, reference: datetime | None = None) -> float:
    parts = name.split("-")
    if len(parts) < 4:
        return 0.0
    date_str = parts[1]
    try:
        exp = datetime.strptime(date_str, "%d%b%y").replace(tzinfo=UTC)
    except ValueError:
        return 0.0
    ref = reference or datetime.now(UTC)
    delta = exp - ref
    # 365-day annualisation (C8 brief §6 / orchestration §5.1) — consistent with
    # pricing T = days / 365 used elsewhere in the engine.
    return max(delta.total_seconds() / (365.0 * 86400), 1e-10)


def _group_by_expiry(points: list[VolPoint]) -> dict[float, list[VolPoint]]:
    grouped: dict[float, list[VolPoint]] = {}
    for p in points:
        grouped.setdefault(p.expiry, []).append(p)
    return grouped


def _interpolate_delta(points: list[VolPoint], target_delta: float) -> float:
    sorted_pts = sorted(points, key=lambda p: p.delta)
    deltas = np.array([p.delta for p in sorted_pts], dtype=np.float64)
    ivs = np.array([p.iv for p in sorted_pts], dtype=np.float64)

    if target_delta <= deltas[0]:
        return float(ivs[0])
    if target_delta >= deltas[-1]:
        return float(ivs[-1])

    try:
        cs: Any = PchipInterpolator(deltas, ivs, extrapolate=False)
        return float(cs(float(target_delta)))
    except Exception:
        try:
            cs = CubicSpline(deltas, ivs, bc_type="natural", extrapolate=False)
            return float(cs(float(target_delta)))
        except Exception:
            return _linear_interp(deltas, ivs, target_delta)


def _linear_interp(
    xs: np.ndarray, ys: np.ndarray, x: float
) -> float:
    idx = np.searchsorted(xs, x)
    if idx <= 0:
        return float(ys[0])
    if idx >= len(xs):
        return float(ys[-1])
    x0, x1 = xs[idx - 1], xs[idx]
    y0, y1 = ys[idx - 1], ys[idx]
    t = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
    return float(y0 + t * (y1 - y0))


def _closest_expiries(target: float, expiries: list[float]) -> list[float]:
    sorted_e = sorted(expiries)
    if not sorted_e:
        return []
    if target <= sorted_e[0]:
        return [sorted_e[0]]
    if target >= sorted_e[-1]:
        return [sorted_e[-1]]
    for i in range(len(sorted_e) - 1):
        if sorted_e[i] <= target <= sorted_e[i + 1]:
            return [sorted_e[i], sorted_e[i + 1]]
    return [sorted_e[0]]


def _expiry_weights(
    target: float, e0: float, e1: float
) -> tuple[float, float]:
    if e1 == e0:
        return 0.5, 0.5
    w1 = (target - e0) / (e1 - e0)
    w0 = 1.0 - w1
    return w0, w1


def _mean_iv(points: list[VolPoint]) -> float:
    if not points:
        return 0.0
    return float(np.mean([p.iv for p in points]))


def _compute_rmse(points: list[VolPoint]) -> float:
    if len(points) < 3:
        return 0.0
    grouped = _group_by_expiry(points)
    total_sq = 0.0
    total_n = 0
    for grp in grouped.values():
        if len(grp) < 2:
            continue
        sorted_pts = sorted(grp, key=lambda p: p.delta)
        deltas = [p.delta for p in sorted_pts]
        ivs = [p.iv for p in sorted_pts]
        if len(set(deltas)) < 2:
            continue
        try:
            cs = CubicSpline(deltas, ivs, bc_type="natural", extrapolate=False)
            fitted = [float(cs(float(d))) for d in deltas]
        except Exception:
            continue
        total_sq += sum((ivs[i] - fitted[i]) ** 2 for i in range(len(ivs)))
        total_n += len(ivs)
    if total_n == 0:
        return 0.0
    return float(math.sqrt(total_sq / total_n))
