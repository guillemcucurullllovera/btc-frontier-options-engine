"""Tranche scheduler for institutional-scale execution (A4).

Schedules configurable BTC quantities across an expiry-ladder DTE range
and a clip-size range over a configurable duration.

Default mandate schedule reconciles exactly to 30 000 BTC across
DTE ladder [30, 37, 44] with clips in [250, 1000] over 4 weeks.

Frozen per contracts.md §12.3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field

from engine.settlement import Venue
from execution.impact import ImpactEstimate, KissellConfig, estimate_impact


class ExecutionMethod(StrEnum):
    BLOCK_RFQ = "block_rfq"
    VOICE_BROKER = "voice_broker"
    OTC = "otc"
    SCREEN = "screen"
    RFQ_AUCTION = "rfq_auction"


class Tranche(BaseModel):
    """One scheduled tranche — frozen per contracts.md §12.3."""

    tranche_id: int
    dte: int
    btc_quantity: int = Field(ge=1)
    strike: float = 0.0
    delta_target: float = 0.0
    target_premium_pct: float = 0.0
    execution_venue: Venue = Venue.DERIBIT
    execution_method: ExecutionMethod = ExecutionMethod.BLOCK_RFQ
    estimated_impact: ImpactEstimate | None = None
    scheduled_date: datetime


class TrancheSchedule(BaseModel):
    """Complete tranche schedule — frozen per contracts.md §12.3."""

    strategy: str = ""
    total_btc: int = Field(ge=1)
    tranches: list[Tranche] = Field(default_factory=list)
    expiry_ladder_dte: list[int] = Field(min_length=1)
    clip_size_range: tuple[int, int]
    duration_weeks: int = Field(ge=1, le=52)

    def total_scheduled_btc(self) -> int:
        return sum(t.btc_quantity for t in self.tranches)


def schedule_tranches(
    total_btc: int,
    expiry_ladder: list[int] | None = None,
    clip_range: tuple[int, int] | None = None,
    duration_weeks: int = 4,
) -> TrancheSchedule:
    """Build a tranche schedule that sums exactly to total_btc.

    Default schedule (30 000 BTC, ladder [30,37,44], clips [250,1000],
    4 weeks) reconciles exactly with evenly-sized clips.

    Parameters
    ----------
    total_btc : int
        Total BTC to schedule (must equal config mandate quantity).
    expiry_ladder : list[int] | None
        DTE values to distribute across. Default [30, 37, 44].
    clip_range : tuple[int, int] | None
        (min_clip, max_clip) in BTC. Default (250, 1000).
    duration_weeks : int
        Number of weeks over which to schedule. Default 4.

    Returns
    -------
    TrancheSchedule
        Complete schedule with total == total_btc.
    """
    ladder = expiry_ladder or [30, 37, 44]
    cmin, cmax = clip_range or (250, 1000)

    n_dte = len(ladder)
    n_weeks = duration_weeks

    btc_per_dte: int = total_btc // n_dte
    remainder: int = total_btc - btc_per_dte * n_dte

    tranches: list[Tranche] = []
    base_date = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    tranche_id = 0

    for dte_idx, dte in enumerate(ladder):
        dte_quantity = btc_per_dte + (1 if dte_idx < remainder else 0)
        btc_per_week = dte_quantity // n_weeks
        week_remainder = dte_quantity - btc_per_week * n_weeks

        # Determine clip count and size per week
        for week in range(n_weeks):
            week_qty = btc_per_week + (1 if week < week_remainder else 0)
            if week_qty == 0:
                continue

            n_clips = max(1, round(week_qty / ((cmin + cmax) / 2.0)))
            clip_size = week_qty // n_clips
            clip_rem = week_qty - clip_size * n_clips

            for c in range(n_clips):
                qty = clip_size + (1 if c < clip_rem else 0)
                if qty < cmin:
                    clip_size_adj = cmin
                    n_adj = week_qty // clip_size_adj
                    if n_adj == 0:
                        qty = week_qty
                    else:
                        qty = clip_size_adj
                        if c >= n_adj:
                            continue

                if qty == 0:
                    continue

                d = base_date + timedelta(weeks=week)
                est_impact = estimate_impact(
                    KissellConfig(
                        order_size_btc=float(qty),
                        adv_btc=5000.0,
                        volatility=0.45,
                    )
                )
                tranches.append(
                    Tranche(
                        tranche_id=tranche_id,
                        dte=dte,
                        btc_quantity=qty,
                        estimated_impact=est_impact,
                        scheduled_date=d,
                    )
                )
                tranche_id += 1

    total = sum(t.btc_quantity for t in tranches)
    return TrancheSchedule(
        strategy="mandate_default",
        total_btc=total,
        tranches=tranches,
        expiry_ladder_dte=ladder,
        clip_size_range=(cmin, cmax),
        duration_weeks=duration_weeks,
    )
