"""Realised (historical) volatility — comparison-only for the C8 strategy grid.

Realised vol is computed from observed spot history and is kept strictly
distinct from implied vol (per-option Deribit mark_iv) and from the DVOL index.
It exists only as a labelled comparison marker; it is never a pricing input.

Estimator: close-to-close log-return standard deviation (sample, ddof=1),
annualised with sqrt(annualisation_days).  Per FRONTIER_ORCHESTRATION §6 and the
C8 builder brief §6, annualisation uses 365 calendar days by default.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from config.models import Provenance
from engine.data_models import HistoricalSpotBar

DEFAULT_ANNUALISATION_DAYS: float = 365.0


@dataclass(frozen=True)
class RealisedVol:
    """A realised-volatility observation over a trailing window.

    ``available`` is False when the window held fewer than two observations,
    in which case ``sigma_annual`` is not meaningful and must not be reported
    as a number.
    """

    window_days: int
    n_returns: int
    sigma_annual: float
    annualisation_days: float
    start: datetime | None
    end: datetime | None
    provenance: Provenance
    origin: str
    available: bool


def close_to_close_realised_vol(
    closes: Sequence[float],
    annualisation_days: float = DEFAULT_ANNUALISATION_DAYS,
) -> float:
    """Annualised close-to-close realised volatility from a price series.

    Uses log returns and the sample standard deviation (ddof=1).

    Raises ValueError if fewer than two prices are given or any price is
    non-positive (log return undefined).
    """
    if len(closes) < 2:
        raise ValueError("close_to_close_realised_vol requires at least two prices")
    if any(p <= 0 for p in closes):
        raise ValueError("close_to_close_realised_vol requires strictly positive prices")
    if annualisation_days <= 0:
        raise ValueError("annualisation_days must be positive")

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    n = len(log_returns)
    if n < 2:
        # A single return has no sample dispersion; treat as zero realised vol.
        return 0.0
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1)
    return math.sqrt(variance) * math.sqrt(annualisation_days)


def realised_vol_windows(
    bars: Sequence[HistoricalSpotBar],
    windows_days: Sequence[int],
    reference: datetime | None = None,
    annualisation_days: float = DEFAULT_ANNUALISATION_DAYS,
    provenance: Provenance = Provenance.OBSERVED,
    origin: str = "massive",
) -> list[RealisedVol]:
    """Realised vol over each trailing calendar-day window ending at *reference*.

    A window includes bars with ``reference - window_days < timestamp <= reference``.
    Windows with fewer than two observations are returned with ``available=False``
    rather than raising, so the caller can label them UNAVAILABLE.
    """
    ordered = sorted(bars, key=lambda b: b.timestamp)
    ref = reference or (ordered[-1].timestamp if ordered else None)
    results: list[RealisedVol] = []

    for w in windows_days:
        if ref is None:
            results.append(_unavailable(w, annualisation_days, provenance, origin))
            continue
        cutoff = ref - timedelta(days=w)
        window = [b for b in ordered if cutoff < b.timestamp <= ref]
        closes = [b.close for b in window]
        if len(closes) < 2:
            results.append(_unavailable(w, annualisation_days, provenance, origin))
            continue
        sigma = close_to_close_realised_vol(closes, annualisation_days)
        results.append(
            RealisedVol(
                window_days=w,
                n_returns=len(closes) - 1,
                sigma_annual=sigma,
                annualisation_days=annualisation_days,
                start=window[0].timestamp,
                end=window[-1].timestamp,
                provenance=provenance,
                origin=origin,
                available=True,
            )
        )
    return results


def _unavailable(
    window_days: int,
    annualisation_days: float,
    provenance: Provenance,
    origin: str,
) -> RealisedVol:
    return RealisedVol(
        window_days=window_days,
        n_returns=0,
        sigma_annual=0.0,
        annualisation_days=annualisation_days,
        start=None,
        end=None,
        provenance=provenance,
        origin=origin,
        available=False,
    )
