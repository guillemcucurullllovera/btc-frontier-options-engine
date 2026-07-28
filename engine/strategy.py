"""Position leg, strategy classification, and strategy models.

Frozen per contracts.md §§2, 9.

Key invariants:
  - StrategyKind is derived purely from position legs, never from titles or labels.
  - Leg.quantity is unsigned (≥ 0); economic effect derives from Leg.side.
  - When business_label ≠ canonical, both are stored and a warning is emitted.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from engine.settlement import SettlementSpec, Venue


class StrategyKind(StrEnum):
    """Canonical strategy classification — derived purely from position legs.

    COVERED_PUT requires short underlying + short put (AGENTS.md line 61).
    It must not be assigned to long BTC + short put.

    Frozen per contracts.md §2.2.
    """

    COVERED_CALL = "covered_call"  # long underlying + short call
    CASH_SECURED_PUT = "cash_secured_put"  # cash collateral + short put
    LONG_BTC_PLUS_SHORT_PUT = "long_btc_plus_short_put"  # long underlying + short put
    COVERED_PUT = "covered_put"  # short underlying + short put (NOT long BTC + short put)
    PROTECTIVE_PUT = "protective_put"  # long underlying + long put
    CALL_SPREAD = "call_spread"  # long/short calls at different strikes
    COLLAR = "collar"  # long underlying + short call + long put
    PARTIAL_OVERLAY = "partial_overlay"  # long underlying + short call on fraction of position
    NAKED_CALL = "naked_call"  # short call, no underlying
    NAKED_PUT = "naked_put"  # short put, no underlying
    BESPOKE = "bespoke"  # any unrecognised combination


class Leg(BaseModel):
    """One leg of a strategy. Quantity is unsigned (≥ 0); economic effect from side.

    Frozen per contracts.md §9.1.
    """

    instrument: str  # e.g. "BTC-spot", "BTC-27SEP24-65000-C"
    venue: Venue
    product: str  # e.g. "spot", "call_option", "put_option"
    side: Literal["LONG", "SHORT"]
    quantity: float = Field(ge=0)  # Unsigned; economic effect from side
    entry_premium: float = Field(
        default=0.0,
        description=(
            "Per-contract premium PAID by the leg owner (positive) or RECEIVED "
            "(negative entry_premium means leg owner received premium, e.g. a short option)."
        ),
    )
    settlement: SettlementSpec | None = None  # None for spot legs
    entry_spot: float | None = None  # Spot price at leg initiation (underlying legs)
    option_type: Literal["call", "put"] | None = None  # Type for option legs
    strike: float | None = None  # Strike for option legs
    expiry_timestamp: datetime | None = None  # datetime for option legs


class DecisionRef(BaseModel):
    """Structured reference to an unresolved decision — frozen per contracts.md §9.2."""

    code: str  # e.g. "D-1"
    owner: str  # e.g. "Mandate issuer"
    impact: str  # e.g. "$243,750 swing on $9.75M fee"


class Strategy(BaseModel):
    """A complete strategy composed of position legs.

    Frozen per contracts.md §9.2.
    """

    strategy_id: str
    business_label: str  # Source label from mandate/client (may differ from canonical)
    canonical: StrategyKind  # Algorithmically derived from legs
    legs: list[Leg]
    classification_warning: str | None = None  # Non-None if business_label ≠ canonical
    pending_decisions: list[DecisionRef] = Field(default_factory=list)
    structural_max_loss: float = Field(
        default=0.0,
        description="Maximum possible loss under worst-case spot movement (USD)",
    )


# ── Classification function ──────────────────────────────────────────────


def classify(legs: list[Leg]) -> StrategyKind:
    """Derive the canonical StrategyKind from position legs only.

    Never classify from titles, filenames or source labels.
    Frozen per contracts.md §2.2.

    Raises ClassificationError if legs are incompatible or unclassifiable.
    """
    from engine.errors import ClassificationError

    if not legs:
        raise ClassificationError("Cannot classify an empty leg list.")

    # Separate leg types
    spot_long = [leg for leg in legs if leg.product == "spot" and leg.side == "LONG"]
    spot_short = [leg for leg in legs if leg.product == "spot" and leg.side == "SHORT"]
    call_long = [leg for leg in legs if leg.option_type == "call" and leg.side == "LONG"]
    call_short = [leg for leg in legs if leg.option_type == "call" and leg.side == "SHORT"]
    put_long = [leg for leg in legs if leg.option_type == "put" and leg.side == "LONG"]
    put_short = [leg for leg in legs if leg.option_type == "put" and leg.side == "SHORT"]

    has_spot = bool(spot_long)
    has_spot_short = bool(spot_short)
    has_call_short = bool(call_short)
    has_put_short = bool(put_short)
    has_put_long = bool(put_long)
    has_call_long = bool(call_long)

    # Cash is modelled as a leg with product="cash"
    has_cash = any(leg.product == "cash" for leg in legs)

    # Covered call: long underlying + short call
    if has_spot and has_call_short and not spot_short and not put_long and not put_short and not call_long:
        return StrategyKind.COVERED_CALL

    # Cash-secured put: cash collateral + short put
    if has_cash and has_put_short and not has_spot and not has_call_short and not has_call_long and not has_put_long:
        return StrategyKind.CASH_SECURED_PUT

    # Covered put: short underlying + short put
    if has_spot_short and has_put_short and not spot_long and not call_short and not call_long and not put_long:
        return StrategyKind.COVERED_PUT

    # Long BTC + short put
    if has_spot and has_put_short and not spot_short and not call_short and not call_long and not put_long:
        return StrategyKind.LONG_BTC_PLUS_SHORT_PUT

    # Protective put: long underlying + long put
    if has_spot and has_put_long and not spot_short and not call_short and not call_long and not put_short:
        return StrategyKind.PROTECTIVE_PUT

    # Call spread: long/short calls at different strikes, no underlying
    if (call_long or call_short) and ((call_long and call_short) or (len(call_long) + len(call_short) >= 2)) and not has_spot and not has_put_short and not has_put_long:
        return StrategyKind.CALL_SPREAD

    # Collar: long underlying + short call + long put
    if has_spot and has_call_short and has_put_long and not spot_short and not call_long and not put_short:
        return StrategyKind.COLLAR

    # Partial overlay: long underlying + short call on fraction (qualified by metadata, falls back to covered call)
    if has_spot and has_call_short and not spot_short and not put_long and not put_short and not call_long:
        return StrategyKind.PARTIAL_OVERLAY

    # Naked call: short call, no underlying
    if has_call_short and not has_spot and not has_put_short and not has_put_long and not call_long:
        return StrategyKind.NAKED_CALL

    # Naked put: short put, no underlying
    if has_put_short and not has_spot and not has_call_short and not has_call_long and not put_long:
        return StrategyKind.NAKED_PUT

    raise ClassificationError(
        f"Could not classify legs into a known StrategyKind. "
        f"Legs provided: {[(leg.product, leg.side, leg.option_type) for leg in legs]}"
    )
