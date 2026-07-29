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
        ge=0.0,
        description=(
            "Per-contract premium MAGNITUDE (unsigned, ≥ 0) in the option's "
            "quoted currency. Economic direction derives from `side`, exactly "
            "like `quantity`: a LONG leg PAYS this premium (debit), a SHORT leg "
            "RECEIVES it (credit). See contracts.md §9.1 amendment A-2026-07-29 "
            "(FRF-018): the earlier signed convention (received = negative) is "
            "retired in favour of this unsigned-with-side convention."
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

    # FRF-019: legs with no recognisable position component (neither spot, cash
    # nor option) are invalid input — raise rather than silently label BESPOKE.
    has_any_option = bool(call_long or call_short or put_long or put_short)
    if not (has_spot or has_spot_short or has_cash or has_any_option):
        raise ClassificationError(
            "No recognisable position legs (spot/cash/option) to classify: "
            f"{[(leg.product, leg.side, leg.option_type) for leg in legs]}"
        )

    spot_long_qty = sum(leg.quantity for leg in spot_long)
    short_call_qty = sum(leg.quantity for leg in call_short)

    # Covered call vs partial overlay: long underlying + short call only.
    # FRF-019: PARTIAL_OVERLAY is reachable — the short-call quantity covers only
    # a fraction of the underlying (overlay ratio < 1).
    if has_spot and has_call_short and not spot_short and not put_long and not put_short and not call_long:
        if short_call_qty < spot_long_qty - 1e-9:
            return StrategyKind.PARTIAL_OVERLAY
        return StrategyKind.COVERED_CALL

    # Cash-secured put: cash collateral + short put (no underlying either side)
    if has_cash and has_put_short and not has_spot and not has_spot_short and not has_call_short and not has_call_long and not has_put_long:
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

    # Call spread: FRF-019 requires OPPOSITE sides (a long AND a short call) at
    # DISTINCT strikes, no underlying and no puts. Two same-direction calls do
    # NOT form a call spread.
    if (call_long and call_short and not has_spot and not has_spot_short
            and not has_put_short and not has_put_long):
        strikes_long = {leg.strike for leg in call_long}
        strikes_short = {leg.strike for leg in call_short}
        if strikes_long != strikes_short:
            return StrategyKind.CALL_SPREAD

    # Collar: long underlying + short call + long put
    if has_spot and has_call_short and has_put_long and not spot_short and not call_long and not put_short:
        return StrategyKind.COLLAR

    # Naked call: short call only, no underlying (either side)
    if has_call_short and not has_spot and not has_spot_short and not has_put_short and not has_put_long and not call_long:
        return StrategyKind.NAKED_CALL

    # Naked put: short put only, no underlying (either side)
    if has_put_short and not has_spot and not has_spot_short and not has_call_short and not has_call_long and not put_long:
        return StrategyKind.NAKED_PUT

    # FRF-019: any unrecognised COMBINATION of otherwise-valid legs is BESPOKE
    # (not a hard error). Empty / no-component input already raised above.
    return StrategyKind.BESPOKE
