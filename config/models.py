"""Configuration-boundary Pydantic models and Provenance enum.

Frozen per contracts.md §§4, 15, 16.  Pydantic is used at configuration,
ingestion, persistence and external-reporting boundaries only (AC-3).
Pure numerical internals use frozen typed dataclasses.

Phase 0 — models required for Phase-0 gates and test infrastructure.
Do not add A1-A5 implementation models here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── §4.1 Provenance ──────────────────────────────────────────────────────────


class Provenance(StrEnum):
    """Provenance tag for every value entering or leaving the engine.

    Frozen per contracts.md §4.1.  Must be assigned at ingestion and carried
    through to every output report.

    Stage 3 additions: OBSERVED_REPLAY (historical windows consumed as-is),
    OBSERVED_FALLBACK (explicitly-labelled fallback data source).
    """

    OBSERVED = "observed"  # Direct market observation (e.g. Deribit mark_iv)
    OBSERVED_REPLAY = "observed_replay"  # Observed historical window consumed as-is
    OBSERVED_FALLBACK = "observed_fallback"  # Explicitly-labelled fallback provider
    CALCULATED = "calculated"  # Deterministic computation from observed inputs
    MODEL_RECONSTRUCTED = "model_reconstructed"  # Inferred where observed data is missing (AC-5 §5)
    SIMULATED = "simulated"  # Monte Carlo or synthetic generation
    ASSUMED = "assumed"  # Uncalibrated placeholder
    BUSINESS_REQUIREMENT = "business_requirement"  # Configurable mandate parameter
    VENUE_SPECIFICATION = "venue_specification"  # Contract spec from official venue docs


# ── §4.2 Source origin labels ────────────────────────────────────────────────


class Origin(StrEnum):
    """Data origin labels per contracts.md §4.2."""

    DERIBIT = "deribit"
    DERIBIT_PUBLIC_API = "deribit_public_api"
    MASSIVE = "massive"
    CRYPTODATADOWNLOAD = "cryptodatadownload"
    CME = "cme"
    CME_PUBLIC_API = "cme_public_api"
    TEXTBOOK = "textbook"
    BUSINESS_CONFIG = "business_config"


# ── §16.1 BreakoutRule ──────────────────────────────────────────────────────


class BreakoutRule(BaseModel):
    """Definition of what constitutes a 'breakout' for stand_down_on_breakout policy.

    Frozen per contracts.md §16.1.
    """

    method: Literal["n_day_high", "dvol_spike", "realised_vol_spike"] = Field(
        default="n_day_high"
    )
    lookback_days: int = Field(ge=1, default=20)
    threshold_pct: float = Field(ge=0, le=100, default=10.0)
    # e.g. "spot exceeds 20-day high by 10%" triggers stand-down


# Developer-only default for offline testing — not serialised as model data
DEV_DEFAULT_VENUE: str = "deribit"

# ── §16.1 EngineConfig ──────────────────────────────────────────────────────


class EngineConfig(BaseModel):
    """Validated wrapper for config/params.yaml.

    All percentage fields are stored as their raw percent values (e.g. 2.5 = 2.5%).
    Use to_decimal_dict() to convert to the 0-1 decimal form expected
    by pricing functions.  Pure pricing functions never read params.yaml
    directly — this config layer injects decimal values (AC-4).

    Frozen per contracts.md §16.1.
    """

    # FRF-020 / AT-020: reject unknown/unconsumed keys so a configured research
    # design is exactly the executed design (no silently-ignored knobs).
    model_config = ConfigDict(extra="forbid")

    btc_quantity: int = Field(ge=1, description="Reference transaction quantity")
    reference_spot_usd: float = Field(gt=0, description="Working reference spot price (USD)")
    seller_discount_pct: float = Field(ge=0, le=100)
    target_option_yield_pct: float = Field(ge=0, le=100)
    combined_target_discount_pct: float = Field(ge=0, le=100)
    execution_fee_pct: float = Field(ge=0, le=100)
    call_delta_target: list[float] = Field(min_length=2, max_length=2)
    dte_target_days: list[int] = Field(min_length=2, max_length=2)
    strike_target_pct_above_spot: list[float] = Field(min_length=2, max_length=2)
    target_monthly_premium_pct: float = Field(ge=0, le=100)
    iv_working_band_pct: list[float] = Field(min_length=2, max_length=2)
    risk_free_rate_pct: float = Field(
        ge=-5.0,
        le=50.0,
        description="Risk-free rate in percent. Negative floor to accommodate ZIRP/VIP scenarios.",
    )
    tranche_btc: list[int] = Field(min_length=2, max_length=2)
    expiry_ladder_dte: list[int] = Field(min_length=1)

    # DVOL-triggered execution rules (distinct from iv_working_band_pct):
    #   iv_working_band_pct  — band where the overlay always operates.
    #   sell_when_dvol_above — ADDITIONAL conditional trigger for vol-opportunistic
    #                           execution (only sell when DVOL exceeds this threshold,
    #                           even within the working band).
    sell_when_dvol_above: float | None = None  # e.g. 55.0
    stand_down_on_breakout: bool | None = None
    breakout_definition: BreakoutRule = Field(default_factory=BreakoutRule)

    # ── Locked mandate policy (ratified Aug-2026): the +6% laddered covered call ──
    # Income overlay (NOT acquisition). "Safer" = +6% floor ladder, strikes
    # 6/10/14/18% OTM, 40% coverage (12,000 covered / 18,000 uncapped), QUARTERLY
    # cadence, IV-timed entry (harvest-when-rich). Provenance: BUSINESS_REQUIREMENT.
    # These carry sensible defaults so pre-existing EngineConfig(**minimal) call
    # sites (test_phase0, test_frontier_acceptance) still validate; params.yaml sets
    # them explicitly as the single source of truth.
    coverage_fraction_pct: float = Field(
        default=40.0,
        ge=0.0,
        le=100.0,
        description="Covered fraction of the block (40% = 12,000 of 30,000 BTC covered).",
    )
    ladder_strikes_pct_above_spot: list[float] = Field(
        default_factory=lambda: [6.0, 10.0, 14.0, 18.0],
        min_length=1,
        description="Asymmetric short-call ladder strikes as % OTM (the +6% floor ladder).",
    )
    cadence: Literal["monthly", "quarterly"] = Field(
        default="quarterly",
        description="Overlay entry/rebalance cadence (locked: quarterly).",
    )
    iv_timed_entry: bool = Field(
        default=True,
        description="Write only when IV is rich (harvest-when-rich); pairs with sell_when_dvol_above.",
    )

    # Unresolved decisions — truly pending, NOT defaulted (C-6, H-7, IDR-1, IDR-2, IDR-3):
    primary_venue: str | None = None  # TODO(decision_pending: D-3) — no default
    fee_base: Literal["reference_notional", "executed_volume"] | None = (
        None  # TODO(decision_pending: D-1)
    )
    reference_spot_source: str | None = None  # TODO(decision_pending: D-2) — no default
    # Developer-only convenience (not the resolved decision):
    # Default is the module-level DEV_DEFAULT_VENUE constant — not serialised as model data.
    dev_default_venue: str | None = Field(
        default=None,
        description="DEV ONLY — for offline testing; not the D-3 resolution",
    )

    # ── field validators ─────────────────────────────────────────────────

    # FRF-029 / AT-029: validators raise ValueError (NOT assert, which `python -O`
    # strips) so the invariants still hold under optimised bytecode.
    @field_validator("call_delta_target")
    @classmethod
    def deltas_in_0_1_range(cls, v: list[float]) -> list[float]:
        if not 0.0 < v[0] < 1.0:
            raise ValueError(f"First delta {v[0]} must be in (0, 1)")
        if not 0.0 < v[1] < 1.0:
            raise ValueError(f"Second delta {v[1]} must be in (0, 1)")
        if not v[0] <= v[1]:
            raise ValueError(f"Deltas {v} must be non-decreasing")
        return v

    @field_validator("risk_free_rate_pct")
    @classmethod
    def rate_sane(cls, v: float) -> float:
        if not -5.0 <= v <= 50.0:
            raise ValueError(f"Risk-free rate {v}% out of plausible range [-5%, 50%]")
        return v

    @field_validator("iv_working_band_pct")
    @classmethod
    def iv_band_sane(cls, v: list[float]) -> list[float]:
        if not 10.0 <= v[0] <= 200.0:
            raise ValueError(f"IV band lower bound {v[0]}% unreasonable")
        if not 10.0 <= v[1] <= 200.0:
            raise ValueError(f"IV band upper bound {v[1]}% unreasonable")
        if not v[0] <= v[1]:
            raise ValueError(f"IV band {v} lower must be <= upper")
        return v

    @field_validator("ladder_strikes_pct_above_spot")
    @classmethod
    def ladder_strikes_sane(cls, v: list[float]) -> list[float]:
        if any(not 0.0 < s < 100.0 for s in v):
            raise ValueError(f"Ladder strikes {v} must each be in (0, 100)%")
        if list(v) != sorted(v):
            raise ValueError(
                f"Ladder strikes {v} must be ascending (nearest floor first, e.g. 6/10/14/18)"
            )
        return v

    @field_validator("tranche_btc")
    @classmethod
    def tranches_within_quantity(cls, v: list[int], info: Any) -> list[int]:
        qty = info.data.get("btc_quantity")
        if qty is not None:
            if v[0] > qty:
                raise ValueError(f"Min tranche {v[0]} > total quantity {qty}")
            if v[1] > qty:
                raise ValueError(f"Max tranche {v[1]} > total quantity {qty}")
        if not v[0] <= v[1]:
            raise ValueError(f"Tranche min {v[0]} must be <= max {v[1]}")
        return v

    # ── model validators ─────────────────────────────────────────────────

    @model_validator(mode="after")
    def discount_consistency(self) -> EngineConfig:
        disc = self.seller_discount_pct
        ovl = self.target_option_yield_pct
        combined = self.combined_target_discount_pct
        if disc + ovl > combined + 1e-6:
            raise ValueError(
                f"seller_discount ({disc}%) + target_option_yield ({ovl}%) "
                f"exceeds combined_target_discount ({combined}%). "
                f"Asymmetrica fee ({self.execution_fee_pct}%) would further increase cost."
            )
        return self

    @model_validator(mode="after")
    def dte_ladder_overlap(self) -> EngineConfig:
        target_range = set(range(self.dte_target_days[0], self.dte_target_days[1] + 1))
        ladder = set(self.expiry_ladder_dte)
        overlap = target_range & ladder
        if not overlap:
            raise ValueError(
                f"expiry_ladder_dte {self.expiry_ladder_dte} has no overlap "
                f"with dte_target_days range {sorted(target_range)}"
            )
        return self

    @field_validator("primary_venue")
    @classmethod
    def primary_venue_must_be_resolved(cls, v: str | None, info: Any) -> str | None:
        """Null check deferred to load_validated_config()."""
        return v

    @field_validator("fee_base")
    @classmethod
    def fee_base_must_be_resolved(
        cls, v: Literal["reference_notional", "executed_volume"] | None, info: Any
    ) -> Literal["reference_notional", "executed_volume"] | None:
        """Null check deferred to load_validated_config()."""
        return v

    # ── utility ──────────────────────────────────────────────────────────

    def to_decimal_dict(self) -> dict[str, Any]:
        """Return dict with percentage values divided by 100 for pricing functions."""
        result: dict[str, Any] = {}
        for k, v in self.model_dump().items():
            if k.endswith("_pct") and isinstance(v, (int, float)):
                result[k] = v / 100.0
            else:
                result[k] = v
        return result
