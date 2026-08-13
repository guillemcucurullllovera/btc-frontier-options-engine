"""Extrapolation model-risk guard (C9 · M5.3).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Any price or greek whose IV is
EXTRAPOLATED beyond the listed strike range (deep-OTM wings, stressed scenario spots) or beyond the
listed expiries (rolled tenors) is a model-risk input, not an observed one. This guard classifies an
IV cell as OBSERVED (exact listed strike, priced), INTERPOLATED (within the listed strike range), or
EXTRAPOLATED (a wing/rolled-tenor flat-extrapolation) so every downstream number can be tagged.

Sits over the M0.2 whole-chain ingest / vol.chain listed-smile logic; the frozen anchor's listed
strikes/expiries define the observed grid.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from engine.data_models import BookSummary, OptionInstrument


@dataclass(frozen=True)
class IVCellFlag:
    strike: float
    expiry: datetime
    kind: str
    status: str                  # "OBSERVED" | "INTERPOLATED" | "EXTRAPOLATED" | "NO_MARKET"
    listed_min: float | None     # listed strike range at this expiry/kind
    listed_max: float | None
    expiry_listed: bool          # False => rolled tenor (extrapolated in time)

    @property
    def is_extrapolated(self) -> bool:
        return self.status in ("EXTRAPOLATED", "NO_MARKET") or not self.expiry_listed


def _listed_strikes(instruments: Sequence[OptionInstrument], books: Sequence[BookSummary],
                    expiry: datetime, kind: str) -> np.ndarray:
    """Sorted listed strikes with a priced (mark_iv>0) book at the given expiry/kind."""
    book = {b.instrument_name: b for b in books}
    strikes = [
        i.strike for i in instruments
        if i.expiration_timestamp == expiry and i.option_type == kind
        and (bs := book.get(i.instrument_name)) is not None and bs.mark_iv > 0.0
    ]
    return np.array(sorted(strikes), dtype=np.float64)


def classify_iv_cell(strike: float, expiry: datetime, kind: str,
                     instruments: Sequence[OptionInstrument], books: Sequence[BookSummary]) -> IVCellFlag:
    """Classify an IV query as OBSERVED / INTERPOLATED / EXTRAPOLATED / NO_MARKET."""
    listed_expiries = {i.expiration_timestamp for i in instruments if i.option_type == kind}
    expiry_listed = expiry in listed_expiries
    strikes = _listed_strikes(instruments, books, expiry, kind)
    if strikes.size == 0:
        return IVCellFlag(strike, expiry, kind, "NO_MARKET", None, None, expiry_listed)
    lo, hi = float(strikes[0]), float(strikes[-1])
    if strike < lo or strike > hi:
        status = "EXTRAPOLATED"                            # wing beyond the listed range
    elif np.any(np.isclose(strikes, strike)):
        status = "OBSERVED"                                # exact listed strike, priced
    else:
        status = "INTERPOLATED"                            # within the listed range
    return IVCellFlag(strike, expiry, kind, status, lo, hi, expiry_listed)


@dataclass(frozen=True)
class ExtrapolationReport:
    n_cells: int
    n_observed: int
    n_interpolated: int
    n_extrapolated: int          # includes rolled tenors + wings + no-market
    flags: list[IVCellFlag]

    @property
    def extrapolated_fraction(self) -> float:
        return self.n_extrapolated / self.n_cells if self.n_cells else 0.0

    @property
    def any_extrapolated(self) -> bool:
        return self.n_extrapolated > 0


def guard_cells(queries: Sequence[tuple[float, datetime, str]],
                instruments: Sequence[OptionInstrument], books: Sequence[BookSummary]) -> ExtrapolationReport:
    """Classify a batch of (strike, expiry, kind) queries; count observed/interp/extrapolated."""
    flags = [classify_iv_cell(k, e, kind, instruments, books) for (k, e, kind) in queries]
    n_ext = sum(1 for f in flags if f.is_extrapolated)
    n_obs = sum(1 for f in flags if f.status == "OBSERVED" and f.expiry_listed)
    n_int = sum(1 for f in flags if f.status == "INTERPOLATED" and f.expiry_listed)
    return ExtrapolationReport(len(flags), n_obs, n_int, n_ext, flags)


def guard_strike_grid(S0: float, expiry: datetime, kind: str, strike_pcts: Sequence[float],
                      instruments: Sequence[OptionInstrument],
                      books: Sequence[BookSummary]) -> ExtrapolationReport:
    """Flag which %OTM grid strikes fall in the extrapolated wings (beyond the listed strike range).

    The scenario/grid repricing uses each fixed %OTM strike's IV; strikes beyond the listed range are
    flat-extrapolated (model-risk), which this surfaces for review. (Sigma-shocked scenario spots do
    not change a fixed strike's IV cell — the strike, not the spot, sets the classification.)
    """
    queries = [(S0 * (1.0 + pct / 100.0), expiry, kind) for pct in strike_pcts]
    return guard_cells(queries, instruments, books)
