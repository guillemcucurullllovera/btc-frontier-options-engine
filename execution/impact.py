"""Market impact, fee, and execution-cost models (A4).

I-Star model (Kissell Sec.4, eq. 4.6-4.7): I*_bp = a1 * (Q/ADV)^a2 * sig^a3
MI_bp = b1 * I* * POV^a4 + (1 - b1) * I*

Frozen per contracts.md Sec.12.1-12.2.

All provenance-labelled per component. Uncalibrated parameters carry
ASSUMED provenance.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from config.models import Provenance


class KissellConfig(BaseModel):
    """I-Star model parameters (Kissell Sec.4, eq. 4.6-4.7).

    Provenance: a1-a4, b1 are ASSUMED unless calibrated.
    order_size_btc, adv_btc, volatility are inputs that must carry their
    own provenance at the calling layer.
    """

    order_size_btc: float = Field(gt=0, description="Order size in BTC")
    adv_btc: float = Field(gt=0, description="Average daily volume in BTC")
    volatility: float = Field(
        gt=0, description="Annualised volatility (decimal, e.g. 0.45)"
    )
    a1: float = Field(
        default=100.0,
        gt=0,
        description="Scale coefficient (uncalibrated, provenance ASSUMED)",
    )
    a2: float = Field(
        default=0.5,
        description="Size exponent (uncalibrated, provenance ASSUMED)",
    )
    a3: float = Field(
        default=0.5,
        description="Volatility exponent (uncalibrated, provenance ASSUMED)",
    )
    b1: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Temporary/permanent split (uncalibrated, provenance ASSUMED)",
    )
    a4: float = Field(
        default=0.2,
        description="Participation-rate exponent (uncalibrated, provenance ASSUMED)",
    )
    pov: float = Field(
        default=0.10,
        gt=0,
        le=1,
        description="Default participation rate (10%)",
    )


class ImpactEstimate(BaseModel):
    """Per-clip market impact estimate with component-level provenance.

    Frozen per contracts.md §12.1 (H-13: component-level provenance).
    """

    order_size_btc: float
    adv_btc: float
    volatility: float

    i_star_bp: float = 0.0
    i_star_bp_provenance: Provenance = Provenance.ASSUMED

    market_impact_bp: float = 0.0
    market_impact_bp_provenance: Provenance = Provenance.ASSUMED

    temporary_impact_bp: float = 0.0
    permanent_impact_bp: float = 0.0

    square_root_eta: float = 0.0

    iv_giveup_vol_pts: float = 0.0
    iv_giveup_vol_pts_provenance: Provenance = Provenance.ASSUMED

    provenance: Provenance | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.provenance is None:
            object.__setattr__(self, "provenance", Provenance.CALCULATED)


def estimate_impact(config: KissellConfig) -> ImpactEstimate:
    """I-Star model (Kissell Sec.4, eq. 4.6-4.7).

    I*_bp = a1 * (Q / ADV)^a2 * sig^a3
    MI_bp = b1 * I* * POV^a4 + (1 - b1) * I*

    Square-root scaling eta = sqrt(Q / ADV)  (Sinclair Sec.6).
    IV give-up: default 1.0 vol pts (uncalibrated, provenance ASSUMED).
    """
    q_adv = config.order_size_btc / config.adv_btc
    i_star_bp = config.a1 * (q_adv ** config.a2) * (config.volatility ** config.a3)

    mi_bp = (
        config.b1 * i_star_bp * (config.pov ** config.a4)
        + (1.0 - config.b1) * i_star_bp
    )

    temp_bp = config.b1 * i_star_bp * (config.pov ** config.a4)
    perm_bp = (1.0 - config.b1) * i_star_bp

    square_root_eta = math.sqrt(q_adv)

    return ImpactEstimate(
        order_size_btc=config.order_size_btc,
        adv_btc=config.adv_btc,
        volatility=config.volatility,
        i_star_bp=i_star_bp,
        market_impact_bp=mi_bp,
        temporary_impact_bp=temp_bp,
        permanent_impact_bp=perm_bp,
        square_root_eta=square_root_eta,
        iv_giveup_vol_pts=1.0,
    )


class FeeBreakdown(BaseModel):
    """Fee decomposition with pending decision markers.

    Frozen per contracts.md §12.2.  fee_base is None pending D-1 resolution.
    """

    asym_fee_usd: float = 0.0
    asym_fee_btc_equiv: float = 0.0
    venue_trading_fee_btc: float = 0.0
    venue_delivery_fee_btc: float = 0.0
    block_trade_fee_btc: float = 0.0
    block_trade_fee_source: Literal[
        "standard_block", "block_rfq", "voice_broker"
    ] = "standard_block"
    bid_ask_cost_btc: float = 0.0
    total_fees_btc: float = 0.0
    impact_cost_estimate: ImpactEstimate | None = None

    fee_base: Literal["reference_notional", "executed_volume"] | None = None
    pending_decision_refs: list[str] = Field(default_factory=list)
