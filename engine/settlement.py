"""Settlement, venue, product and exercise models.

Frozen per contracts.md §5.  SettlementMechanism, SettlementCurrency, Venue,
ExerciseStyle and DeliveryPriceConvention are separate enums — never use
a combined enum (AC-1).

All models are Pydantic BaseModels because configuration, ingestion
and reporting boundaries use Pydantic (AC-3).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SettlementMechanism(StrEnum):
    """How the contract settles at expiry — frozen per contracts.md §5.1."""

    CASH = "cash"  # Cash-settled at expiry (Deribit inverse)
    FUTURES_DELIVERY_THEN_CASH = "futures_delivery_then_cash"  # Option→futures→cash (Deribit linear, CME)
    PHYSICAL_UNDERLYING = "physical_underlying"  # Actual BTC delivery (OTC only, if contract requires)


class SettlementCurrency(StrEnum):
    """Settlement currency — frozen per contracts.md §5.1."""

    BTC = "BTC"
    USDC = "USDC"
    USD = "USD"


class ExerciseStyle(StrEnum):
    """Exercise style — frozen per contracts.md §5.1."""

    EUROPEAN = "european"  # Exercise only at expiry
    AMERICAN = "american"  # Exercise at any time before expiry


class Venue(StrEnum):
    """Trading venue — frozen per contracts.md §5.1."""

    DERIBIT = "deribit"
    CME = "cme"
    OTC = "otc"


class DeliveryPriceConvention(StrEnum):
    """Delivery price convention — frozen per contracts.md §5.1."""

    TWAP_0730_0800_UTC = "twap_0730_0800"  # Deribit (line 187)
    BRR_1600_LONDON = "brr_1600_london"  # CME monthly (Ch. 350A)
    VWAP_0330_035959_LONDON = "vwap_0330_0400_london"  # CME weekly (Ch. 350A)
    NEGOTIATED = "negotiated"  # OTC bespoke


class SettlementSpec(BaseModel):
    """Separate settlement fields per AC-1. Never use a combined enum.

    Frozen per contracts.md §5.1.
    """

    venue: Venue
    product: str  # e.g. "inverse_option", "linear_option", "option_on_futures", "otc_option"
    settlement_mechanism: SettlementMechanism
    settlement_currency: SettlementCurrency
    exercise_style: ExerciseStyle
    contract_multiplier: float = Field(gt=0)  # e.g. 1 (Deribit), 5 (CME)
    delivery_price_convention: DeliveryPriceConvention
