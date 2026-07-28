"""Tranche scheduler for institutional-scale execution (A4).

Schedules configurable BTC quantities across an expiry-ladder DTE range
and a clip-size range over a configurable duration.

Exact reconciliation: total_scheduled_btc() MUST equal the requested total_btc.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field

from engine.errors import ValidationError
from engine.settlement import Venue
from execution.impact import ImpactEstimate, KissellConfig, estimate_impact


class ExecutionMethod(StrEnum):
    BLOCK_RFQ = "block_rfq"
    VOICE_BROKER = "voice_broker"
    OTC = "otc"
    SCREEN = "screen"
    RFQ_AUCTION = "rfq_auction"


class Tranche(BaseModel):
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
    adv_btc: float = 25000.0,
    volatility: float = 0.45,
) -> TrancheSchedule:
    """Build a tranche schedule that sums exactly to total_btc.

    The schedule is built by iterating through (dte, week) slots and
    assigning clips from the clip_range until total_btc is consumed.
    Any remainder is distributed as residual clips.

    total_scheduled_btc() is guaranteed to equal the requested total_btc.
    """
    ladder = list(expiry_ladder) if expiry_ladder else [30, 37, 44]
    cmin, cmax = clip_range if clip_range else (250, 1000)

    if not ladder:
        raise ValidationError("expiry_ladder must be non-empty")
    if cmin <= 0 or cmax <= 0 or cmin > cmax:
        raise ValidationError(f"Invalid clip_range ({cmin}, {cmax})")

    n_dte = len(ladder)
    n_weeks = duration_weeks
    num_slots = n_dte * n_weeks

    base_clip = max(cmin, min(cmax, total_btc // num_slots))
    base_clip = max(cmin, base_clip)

    remaining = total_btc

    tranches: list[Tranche] = []
    base_date = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    tranche_id = 0

    for dte in ladder:
        for week in range(n_weeks):
            if remaining <= 0:
                break
            clip = min(base_clip, remaining)
            if clip < cmin and remaining >= cmin:
                clip = cmin
            if clip > remaining:
                clip = remaining
            if clip <= 0:
                continue

            est_impact = estimate_impact(
                KissellConfig(order_size_btc=float(clip), adv_btc=adv_btc, volatility=volatility)
            )
            d = base_date + timedelta(weeks=week)
            tranches.append(Tranche(
                tranche_id=tranche_id,
                dte=dte,
                btc_quantity=clip,
                estimated_impact=est_impact,
                scheduled_date=d,
            ))
            tranche_id += 1
            remaining -= clip

    while remaining > 0:
        for dte in ladder:
            if remaining <= 0:
                break
            for week in range(n_weeks):
                if remaining <= 0:
                    break
                residual_clip = min(cmin, remaining)
                if residual_clip <= 0:
                    continue
                est_impact = estimate_impact(
                    KissellConfig(order_size_btc=float(residual_clip), adv_btc=adv_btc, volatility=volatility)
                )
                d = base_date + timedelta(weeks=week)
                tranches.append(Tranche(
                    tranche_id=tranche_id,
                    dte=dte,
                    btc_quantity=residual_clip,
                    estimated_impact=est_impact,
                    scheduled_date=d,
                ))
                tranche_id += 1
                remaining -= residual_clip

    total = sum(t.btc_quantity for t in tranches)
    return TrancheSchedule(
        strategy="mandate_default",
        total_btc=total,
        tranches=tranches,
        expiry_ladder_dte=ladder,
        clip_size_range=(cmin, cmax),
        duration_weeks=duration_weeks,
    )
