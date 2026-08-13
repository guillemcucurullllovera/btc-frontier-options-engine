"""Live option-chain analysis for the C8 strategy grid.

Pure functions over frozen-snapshot Deribit instruments + book summaries:

  * ``parse_instrument_name``  — decompose ``BTC-28AUG26-59000-P``.
  * ``select_expiries``        — nearest liquid listed expiries around target
                                 day counts (e.g. 30/45/60d), with the distinct
                                 set and any collapse surfaced explicitly.
  * ``snap_to_listed_strike``  — snap a requested strike to the nearest listed
                                 Deribit strike at an expiry/kind.
  * ``iv_for``                 — per-(strike,expiry) IV: the exact listed
                                 instrument's OBSERVED mark_iv, else a
                                 MODEL_RECONSTRUCTED same-expiry smile
                                 interpolation in strike space.

"Liquid" (per the C8 brief §2.2) = populated book summary: mark_iv > 0, both
bid and ask present, and non-zero open interest.  Strike-space smile fallback
is used (rather than the delta-parameterised vol/surface.iv_at) because grid
strikes are snapped to listed strikes and a missing strike is interpolated
across the same expiry's listed smile; this is labelled MODEL_RECONSTRUCTED.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import numpy as np
from scipy.interpolate import PchipInterpolator

from config.models import Provenance
from engine.data_models import BookSummary, OptionInstrument
from engine.errors import DataError


class ChainError(DataError):
    """Option-chain analysis or lookup error."""


@dataclass(frozen=True)
class ParsedInstrument:
    base: str
    expiry: date
    strike: float
    kind: str  # "call" or "put"


@dataclass(frozen=True)
class ExpiryLiquidity:
    """Liquidity summary for a single listed expiry."""

    expiry: datetime
    label: str  # e.g. "28AUG26"
    days_to_expiry: float  # calendar days from the reference instant
    n_instruments: int
    n_liquid: int
    total_open_interest: float
    is_liquid: bool


@dataclass(frozen=True)
class TargetSelection:
    target_days: float
    selected: ExpiryLiquidity


@dataclass(frozen=True)
class ExpirySelection:
    reference: datetime
    targets: list[TargetSelection]
    distinct: list[ExpiryLiquidity]
    collapsed: bool
    notes: list[str]


@dataclass(frozen=True)
class IVLookup:
    iv: float  # annualised, decimal
    provenance: Provenance
    source: str  # instrument_name (OBSERVED) or "smile_interpolation_strike_space"
    strike: float
    expiry: datetime
    kind: str


# ── Instrument-name parsing ────────────────────────────────────────────────


def parse_instrument_name(name: str) -> ParsedInstrument | None:
    """Parse a Deribit option instrument name, e.g. ``BTC-28AUG26-59000-P``.

    Returns None for non-option names (perpetuals, futures, malformed).
    """
    parts = name.split("-")
    if len(parts) != 4:
        return None
    base, date_str, strike_str, suffix = parts
    if suffix == "C":
        kind = "call"
    elif suffix == "P":
        kind = "put"
    else:
        return None
    try:
        expiry = datetime.strptime(date_str, "%d%b%y").date()
        strike = float(strike_str)
    except ValueError:
        return None
    return ParsedInstrument(base=base, expiry=expiry, strike=strike, kind=kind)


# ── Liquidity + expiry selection ───────────────────────────────────────────


def _is_liquid_book(bs: BookSummary) -> bool:
    return (
        bs.mark_iv > 0.0
        and bs.bid_price is not None
        and bs.ask_price is not None
        and bs.open_interest > 0.0
    )


def _expiry_label(expiry: datetime) -> str:
    return expiry.strftime("%d%b%y").upper()


def expiry_liquidities(
    instruments: Sequence[OptionInstrument],
    book_summaries: Sequence[BookSummary],
    reference: datetime,
    min_liquid: int = 1,
) -> list[ExpiryLiquidity]:
    """Summarise per-expiry liquidity, sorted ascending by expiry.

    Includes past and future expiries; callers filter as needed.
    """
    book = {b.instrument_name: b for b in book_summaries}
    groups: dict[datetime, list[OptionInstrument]] = {}
    for inst in instruments:
        groups.setdefault(inst.expiration_timestamp, []).append(inst)

    out: list[ExpiryLiquidity] = []
    for expiry, insts in groups.items():
        n_liquid = 0
        total_oi = 0.0
        for inst in insts:
            bs = book.get(inst.instrument_name)
            if bs is not None and _is_liquid_book(bs):
                n_liquid += 1
                total_oi += bs.open_interest
        out.append(
            ExpiryLiquidity(
                expiry=expiry,
                label=_expiry_label(expiry),
                days_to_expiry=(expiry - reference).total_seconds() / 86400.0,
                n_instruments=len(insts),
                n_liquid=n_liquid,
                total_open_interest=total_oi,
                is_liquid=n_liquid >= min_liquid,
            )
        )
    out.sort(key=lambda e: e.expiry)
    return out


def select_expiries(
    instruments: Sequence[OptionInstrument],
    book_summaries: Sequence[BookSummary],
    reference: datetime,
    targets_days: Sequence[float] = (30.0, 45.0, 60.0),
    min_liquid: int = 1,
) -> ExpirySelection:
    """Select the nearest liquid listed expiry to each target day-count.

    Only future, liquid expiries are candidates.  Ties break toward higher open
    interest then the sooner expiry (a proxy for "standard" monthly/weekly
    listings).  The distinct selected set and any target collapse (two targets
    resolving to the same listed expiry, e.g. when the chain lists no ~45d/~60d
    expiry) are reported explicitly — never silently deduped.
    """
    candidates = [
        e
        for e in expiry_liquidities(instruments, book_summaries, reference, min_liquid)
        if e.days_to_expiry > 0.0 and e.is_liquid
    ]
    if not candidates:
        raise ChainError("No future liquid listed expiries available for selection")

    targets: list[TargetSelection] = []
    for target in targets_days:
        selected = min(
            candidates,
            key=lambda e: (
                abs(e.days_to_expiry - target),
                -e.total_open_interest,
                e.days_to_expiry,
            ),
        )
        targets.append(TargetSelection(target_days=target, selected=selected))

    distinct: list[ExpiryLiquidity] = []
    seen: set[datetime] = set()
    for t in targets:
        if t.selected.expiry not in seen:
            seen.add(t.selected.expiry)
            distinct.append(t.selected)

    collapsed = len(distinct) < len(targets)

    # Surface collapses: which targets share a listed expiry.
    by_expiry: dict[str, list[float]] = {}
    for t in targets:
        by_expiry.setdefault(t.selected.label, []).append(t.target_days)
    notes: list[str] = []
    for label, tgts in by_expiry.items():
        if len(tgts) > 1:
            tgt_str = " and ".join(f"{int(x) if x.is_integer() else x}d" for x in tgts)
            days = next(t.selected.days_to_expiry for t in targets if t.selected.label == label)
            notes.append(
                f"Targets {tgt_str} both resolve to {label} ({days:.1f}d): "
                f"no distinct liquid listed expiry near the collapsed target(s)."
            )
    return ExpirySelection(
        reference=reference,
        targets=targets,
        distinct=distinct,
        collapsed=collapsed,
        notes=notes,
    )


# ── Strike snapping ────────────────────────────────────────────────────────


def snap_to_listed_strike(
    instruments: Sequence[OptionInstrument],
    expiry: datetime,
    kind: str,
    requested_strike: float,
) -> tuple[float, str]:
    """Snap *requested_strike* to the nearest listed Deribit strike.

    Returns (listed_strike, instrument_name).  Raises ChainError if no
    instrument is listed at the given expiry/kind.
    """
    matches = [
        i
        for i in instruments
        if i.expiration_timestamp == expiry and i.option_type == kind
    ]
    if not matches:
        raise ChainError(
            f"No listed {kind} instruments at expiry {_expiry_label(expiry)}"
        )
    best = min(matches, key=lambda i: (abs(i.strike - requested_strike), i.strike))
    return best.strike, best.instrument_name


# ── Per-(strike,expiry) IV lookup ──────────────────────────────────────────


def _listed_smile(
    instruments: Sequence[OptionInstrument],
    book_summaries: Sequence[BookSummary],
    expiry: datetime,
    kind: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (strikes, ivs) for the liquid listed smile at expiry/kind."""
    book = {b.instrument_name: b for b in book_summaries}
    pairs: list[tuple[float, float]] = []
    for inst in instruments:
        if inst.expiration_timestamp != expiry or inst.option_type != kind:
            continue
        bs = book.get(inst.instrument_name)
        if bs is not None and bs.mark_iv > 0.0:
            pairs.append((inst.strike, bs.mark_iv))
    pairs.sort(key=lambda p: p[0])
    strikes = np.array([p[0] for p in pairs], dtype=np.float64)
    ivs = np.array([p[1] for p in pairs], dtype=np.float64)
    return strikes, ivs


def iv_for(
    strike: float,
    expiry: datetime,
    kind: str,
    instruments: Sequence[OptionInstrument],
    book_summaries: Sequence[BookSummary],
) -> IVLookup:
    """Per-(strike,expiry) implied vol for one grid cell.

    Direct listed OBSERVED mark_iv when the exact strike is listed and priced;
    otherwise MODEL_RECONSTRUCTED interpolation across the same expiry's listed
    smile in strike space (flat extrapolation beyond the listed range).
    """
    book = {b.instrument_name: b for b in book_summaries}
    for inst in instruments:
        if (
            inst.expiration_timestamp == expiry
            and inst.option_type == kind
            and inst.strike == strike
        ):
            bs = book.get(inst.instrument_name)
            if bs is not None and bs.mark_iv > 0.0:
                return IVLookup(
                    iv=bs.mark_iv,
                    provenance=Provenance.OBSERVED,
                    source=inst.instrument_name,
                    strike=strike,
                    expiry=expiry,
                    kind=kind,
                )
            break  # listed but unpriced → fall through to smile interpolation

    strikes, ivs = _listed_smile(instruments, book_summaries, expiry, kind)
    if strikes.size < 2:
        raise ChainError(
            f"Cannot interpolate IV at {_expiry_label(expiry)} {kind} {strike}: "
            f"fewer than two liquid listed strikes"
        )
    if strike <= float(strikes[0]):
        iv = float(ivs[0])
    elif strike >= float(strikes[-1]):
        iv = float(ivs[-1])
    else:
        interp = PchipInterpolator(strikes, ivs, extrapolate=False)
        iv = float(interp(float(strike)))
    return IVLookup(
        iv=iv,
        provenance=Provenance.MODEL_RECONSTRUCTED,
        source="smile_interpolation_strike_space",
        strike=strike,
        expiry=expiry,
        kind=kind,
    )


def now_utc() -> datetime:
    """Timezone-aware current instant (UTC) — for reference-time defaults."""
    return datetime.now(UTC)
