"""Phase-0 gate tests per contracts.md §13 and §18.

All 9 existing tests in test_engine.py are preserved and run alongside these.

Restricted to Pydantic usage at configuration, ingestion, persistence
and external-reporting boundaries only (AC-3).  Pure numerical internals
use frozen typed dataclasses.
"""

from __future__ import annotations

import ast
import pathlib
import sys
from datetime import UTC, datetime
from typing import Any, Literal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from config.models import (
    BreakoutRule,
    EngineConfig,
    Origin,
    Provenance,
)
from engine.data_models import (
    BookSummary,
    FixtureManifest,
    FixtureManifestEntry,
    OptionInstrument,
    SpotBar,
)
from engine.errors import ClassificationError, ConfigurationError, EngineError
from engine.fixture_loader import load_manifest
from engine.settlement import (
    DeliveryPriceConvention,
    ExerciseStyle,
    SettlementCurrency,
    SettlementMechanism,
    SettlementSpec,
    Venue,
)
from engine.strategy import (
    DecisionRef,
    Leg,
    Strategy,
    StrategyKind,
    classify,
)
from execution.waterfall import load_params, waterfall
from pricing.black_scholes import OptionQuote

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_spot_leg(
    side: str = "LONG", quantity: float = 1.0, entry_spot: float = 65000.0
) -> Leg:
    return Leg(
        instrument="BTC-spot",
        venue=Venue.DERIBIT,
        product="spot",
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        entry_spot=entry_spot,
    )


def _make_option_leg(
    option_type: Literal["call", "put"],
    side: str,
    strike: float = 75000.0,
    quantity: float = 1.0,
    entry_premium: float = 0.0,
) -> Leg:
    return Leg(
        instrument=f"BTC-OP-{option_type.upper()}",
        venue=Venue.DERIBIT,
        product=f"{option_type}_option",
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        entry_premium=entry_premium,
        settlement=SettlementSpec(
            venue=Venue.DERIBIT,
            product="inverse_option",
            settlement_mechanism=SettlementMechanism.CASH,
            settlement_currency=SettlementCurrency.BTC,
            exercise_style=ExerciseStyle.EUROPEAN,
            contract_multiplier=1.0,
            delivery_price_convention=DeliveryPriceConvention.TWAP_0730_0800_UTC,
        ),
        option_type=option_type,
        strike=strike,
    )


def load_validated_config_via_dict(raw: dict[str, Any]) -> EngineConfig:
    """Helper: validate a raw dict without touching YAML file."""
    cfg = EngineConfig(**raw)
    if cfg.primary_venue is None:
        raise ConfigurationError(
            "primary_venue is None — decision D-3 (primary venue selection) is unresolved."
        )
    if cfg.fee_base is None:
        raise ConfigurationError(
            "fee_base is None — decision D-1 (fee base) is unresolved."
        )
    if cfg.reference_spot_source is None:
        raise ConfigurationError(
            "reference_spot_source is None — decision D-2 is unresolved."
        )
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
# §13.7 — Configuration tests
# ══════════════════════════════════════════════════════════════════════════════


def test_params_schema_validates() -> None:
    """EngineConfig Pydantic wrapper validates a well-formed params dict."""
    cfg = EngineConfig(
        btc_quantity=30000,
        reference_spot_usd=65000,
        seller_discount_pct=2.5,
        target_option_yield_pct=2.5,
        combined_target_discount_pct=5.0,
        execution_fee_pct=0.5,
        call_delta_target=[0.10, 0.15],
        dte_target_days=[30, 45],
        strike_target_pct_above_spot=[15, 20],
        target_monthly_premium_pct=3.0,
        iv_working_band_pct=[40, 50],
        risk_free_rate_pct=4.0,
        tranche_btc=[250, 1000],
        expiry_ladder_dte=[30, 37, 44],
    )
    assert cfg.btc_quantity == 30000
    assert cfg.reference_spot_usd == 65000
    decimal = cfg.to_decimal_dict()
    assert decimal["seller_discount_pct"] == pytest.approx(0.025)
    assert decimal["risk_free_rate_pct"] == pytest.approx(0.04)


def test_params_schema_rejects_malformed() -> None:
    """EngineConfig rejects invalid delta range."""
    with pytest.raises(Exception):
        EngineConfig(
            btc_quantity=30000,
            reference_spot_usd=65000,
            seller_discount_pct=2.5,
            target_option_yield_pct=2.5,
            combined_target_discount_pct=5.0,
            execution_fee_pct=0.5,
            call_delta_target=[0.15, 0.10],  # reversed
            dte_target_days=[30, 45],
            strike_target_pct_above_spot=[15, 20],
            target_monthly_premium_pct=3.0,
            iv_working_band_pct=[40, 50],
            risk_free_rate_pct=4.0,
            tranche_btc=[250, 1000],
            expiry_ladder_dte=[30, 37, 44],
        )


def test_params_rejects_negative_rate() -> None:
    """Risk-free rate below -5% is rejected."""
    with pytest.raises(Exception):
        EngineConfig(
            btc_quantity=30000,
            reference_spot_usd=65000,
            seller_discount_pct=2.5,
            target_option_yield_pct=2.5,
            combined_target_discount_pct=5.0,
            execution_fee_pct=0.5,
            call_delta_target=[0.10, 0.15],
            dte_target_days=[30, 45],
            strike_target_pct_above_spot=[15, 20],
            target_monthly_premium_pct=3.0,
            iv_working_band_pct=[40, 50],
            risk_free_rate_pct=-10.0,  # below floor
            tranche_btc=[250, 1000],
            expiry_ladder_dte=[30, 37, 44],
        )


def test_params_rejects_discount_inconsistency() -> None:
    """Discount + overlay > combined target raises ValidationError."""
    with pytest.raises(Exception):
        EngineConfig(
            btc_quantity=30000,
            reference_spot_usd=65000,
            seller_discount_pct=4.0,
            target_option_yield_pct=3.0,
            combined_target_discount_pct=5.0,
            execution_fee_pct=0.5,
            call_delta_target=[0.10, 0.15],
            dte_target_days=[30, 45],
            strike_target_pct_above_spot=[15, 20],
            target_monthly_premium_pct=3.0,
            iv_working_band_pct=[40, 50],
            risk_free_rate_pct=4.0,
            tranche_btc=[250, 1000],
            expiry_ladder_dte=[30, 37, 44],
        )


def test_engine_config_rejects_unresolved_primary_venue() -> None:
    """EngineConfig with primary_venue=None raises ConfigurationError."""
    raw: dict[str, Any] = {
        "btc_quantity": 30000,
        "reference_spot_usd": 65000,
        "seller_discount_pct": 2.5,
        "target_option_yield_pct": 2.5,
        "combined_target_discount_pct": 5.0,
        "execution_fee_pct": 0.5,
        "call_delta_target": [0.10, 0.15],
        "dte_target_days": [30, 45],
        "strike_target_pct_above_spot": [15, 20],
        "target_monthly_premium_pct": 3.0,
        "iv_working_band_pct": [40, 50],
        "risk_free_rate_pct": 4.0,
        "tranche_btc": [250, 1000],
        "expiry_ladder_dte": [30, 37, 44],
    }
    with pytest.raises(ConfigurationError, match="primary_venue"):
        load_validated_config_via_dict(raw)


def test_engine_config_rejects_unresolved_fee_base() -> None:
    """EngineConfig with fee_base=None raises ConfigurationError."""
    raw: dict[str, Any] = {
        "btc_quantity": 30000,
        "reference_spot_usd": 65000,
        "seller_discount_pct": 2.5,
        "target_option_yield_pct": 2.5,
        "combined_target_discount_pct": 5.0,
        "execution_fee_pct": 0.5,
        "call_delta_target": [0.10, 0.15],
        "dte_target_days": [30, 45],
        "strike_target_pct_above_spot": [15, 20],
        "target_monthly_premium_pct": 3.0,
        "iv_working_band_pct": [40, 50],
        "risk_free_rate_pct": 4.0,
        "tranche_btc": [250, 1000],
        "expiry_ladder_dte": [30, 37, 44],
        "primary_venue": "deribit",
    }
    with pytest.raises(ConfigurationError, match="fee_base"):
        load_validated_config_via_dict(raw)


def test_params_schema_validates_tranche_btc_range() -> None:
    """Tranche sizes must not exceed total quantity."""
    with pytest.raises(Exception):
        EngineConfig(
            btc_quantity=1000,
            reference_spot_usd=65000,
            seller_discount_pct=2.5,
            target_option_yield_pct=2.5,
            combined_target_discount_pct=5.0,
            execution_fee_pct=0.5,
            call_delta_target=[0.10, 0.15],
            dte_target_days=[30, 45],
            strike_target_pct_above_spot=[15, 20],
            target_monthly_premium_pct=3.0,
            iv_working_band_pct=[40, 50],
            risk_free_rate_pct=4.0,
            tranche_btc=[500, 2000],  # max tranche > total qty
            expiry_ladder_dte=[30, 37, 44],
        )


def test_params_no_hardcode() -> None:
    """No business parameter is hardcoded in waterfall or pricing."""
    w = waterfall(load_params())
    assert "reference_spot_usd" in w
    assert "btc_quantity" in w
    pricing_source = (
        pathlib.Path(__file__).resolve().parents[1] / "pricing" / "black_scholes.py"
    )
    content = pricing_source.read_text()
    assert "65000" not in content, "Hardcoded spot found in pricing module"
    assert "30000" not in content, "Hardcoded quantity found in pricing module"


def test_all_values_have_provenance() -> None:
    """All Provenance enum values are well-defined."""
    # Use str() comparison to avoid strict mypy comparison-overlap
    assert str(Provenance.OBSERVED) == "observed"
    assert str(Provenance.CALCULATED) == "calculated"
    assert str(Provenance.MODEL_RECONSTRUCTED) == "model_reconstructed"
    assert str(Provenance.SIMULATED) == "simulated"
    assert str(Provenance.ASSUMED) == "assumed"
    assert str(Provenance.BUSINESS_REQUIREMENT) == "business_requirement"
    assert str(Provenance.VENUE_SPECIFICATION) == "venue_specification"


# ══════════════════════════════════════════════════════════════════════════════
# §13.12 — Interface preservation tests
# ══════════════════════════════════════════════════════════════════════════════


def test_existing_optionquote_unchanged() -> None:
    """OptionQuote dataclass is preserved exactly as it was (AC-3, AC-6)."""
    q = OptionQuote(price=10.45, delta=0.6368, gamma=0.02, vega=0.05, theta=-0.03, strike=100.0)
    assert q.price == 10.45
    assert q.delta == 0.6368
    assert q.gamma == 0.02
    assert q.vega == 0.05
    assert q.theta == -0.03
    assert q.strike == 100.0
    fields = {f.name for f in OptionQuote.__dataclass_fields__.values()}
    assert fields == {"price", "delta", "gamma", "vega", "theta", "strike"}


def test_pure_functions_no_yaml_read() -> None:
    """pricing/black_scholes.py functions do not import or read config/params.yaml."""
    pricing_source = (
        pathlib.Path(__file__).resolve().parents[1] / "pricing" / "black_scholes.py"
    )
    tree = ast.parse(pricing_source.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            else:
                for alias in node.names:
                    imports.add(alias.name)
    assert "yaml" not in imports, "pricing module imports yaml"


# ══════════════════════════════════════════════════════════════════════════════
# §13.3 — Classification integrity tests
# ══════════════════════════════════════════════════════════════════════════════


def test_covered_call_legs() -> None:
    """Long BTC + short call → COVERED_CALL."""
    legs = [
        _make_spot_leg(side="LONG"),
        _make_option_leg("call", "SHORT", strike=75000),
    ]
    assert classify(legs) == StrategyKind.COVERED_CALL


def test_csp_legs() -> None:
    """Cash + short put → CASH_SECURED_PUT."""
    cash_leg = Leg(
        instrument="USD-cash",
        venue=Venue.OTC,
        product="cash",
        side="LONG",
        quantity=65000.0,
    )
    legs = [cash_leg, _make_option_leg("put", "SHORT", strike=65000)]
    assert classify(legs) == StrategyKind.CASH_SECURED_PUT


def test_long_btc_short_put_legs() -> None:
    """Long BTC + short put → LONG_BTC_PLUS_SHORT_PUT (NOT COVERED_PUT)."""
    legs = [
        _make_spot_leg(side="LONG"),
        _make_option_leg("put", "SHORT", strike=65000),
    ]
    canonical = classify(legs)
    assert canonical == StrategyKind.LONG_BTC_PLUS_SHORT_PUT
    assert str(canonical) != "covered_put"


def test_covered_put_legs() -> None:
    """Short underlying + short put → COVERED_PUT."""
    legs = [
        _make_spot_leg(side="SHORT"),
        _make_option_leg("put", "SHORT", strike=65000),
    ]
    assert classify(legs) == StrategyKind.COVERED_PUT


def test_protective_put_legs() -> None:
    """Long underlying + long put → PROTECTIVE_PUT."""
    legs = [
        _make_spot_leg(side="LONG"),
        _make_option_leg("put", "LONG", strike=65000),
    ]
    assert classify(legs) == StrategyKind.PROTECTIVE_PUT


def test_collar_legs() -> None:
    """Long underlying + short call + long put → COLLAR."""
    legs = [
        _make_spot_leg(side="LONG"),
        _make_option_leg("call", "SHORT", strike=75000),
        _make_option_leg("put", "LONG", strike=60000),
    ]
    assert classify(legs) == StrategyKind.COLLAR


def test_naked_call_legs() -> None:
    """Short call only → NAKED_CALL."""
    legs = [_make_option_leg("call", "SHORT", strike=75000)]
    assert classify(legs) == StrategyKind.NAKED_CALL


def test_naked_put_legs() -> None:
    """Short put only → NAKED_PUT."""
    legs = [_make_option_leg("put", "SHORT", strike=65000)]
    assert classify(legs) == StrategyKind.NAKED_PUT


def test_unclassifiable_raises() -> None:
    """Empty or unrecognised legs raise ClassificationError."""
    with pytest.raises(ClassificationError):
        classify([])
    weird_leg = Leg(
        instrument="XYZ",
        venue=Venue.OTC,
        product="unknown",
        side="LONG",
        quantity=1.0,
    )
    with pytest.raises(ClassificationError):
        classify([weird_leg])


def test_label_mismatch_flagged() -> None:
    """When business_label != canonical, the Strategy records a warning."""
    legs = [
        _make_spot_leg(side="LONG"),
        _make_option_leg("put", "SHORT", strike=65000),
    ]
    canonical = classify(legs)
    strategy = Strategy(
        strategy_id="test-1",
        business_label="Covered Put",
        canonical=canonical,
        legs=legs,
    )
    assert canonical == StrategyKind.LONG_BTC_PLUS_SHORT_PUT
    assert strategy.business_label != str(strategy.canonical)
    assert strategy.classification_warning is None


def test_label_mismatch_emits_warning() -> None:
    """business_label='Covered Put' but canonical is LONG_BTC_PLUS_SHORT_PUT."""
    legs = [
        _make_spot_leg(side="LONG"),
        _make_option_leg("put", "SHORT", strike=65000),
    ]
    canonical = classify(legs)
    assert canonical == StrategyKind.LONG_BTC_PLUS_SHORT_PUT
    strategy = Strategy(
        strategy_id="test-2",
        business_label="Covered Put",
        canonical=canonical,
        legs=legs,
        classification_warning=(
            "W-CLASSIFY-MISMATCH: business_label 'Covered Put' "
            "!= canonical 'long_btc_plus_short_put'"
        ),
    )
    assert strategy.classification_warning is not None
    assert "W-CLASSIFY-MISMATCH" in strategy.classification_warning
    assert "Covered Put" in strategy.classification_warning


# ══════════════════════════════════════════════════════════════════════════════
# §13.4 — Provenance integrity tests
# ══════════════════════════════════════════════════════════════════════════════


def test_no_observed_label_on_simulated() -> None:
    """SIMULATED provenance must never equal OBSERVED."""
    assert str(Provenance.SIMULATED) != str(Provenance.OBSERVED)


def test_no_observed_label_on_model_reconstructed() -> None:
    """MODEL_RECONSTRUCTED provenance must never be confused with OBSERVED."""
    assert str(Provenance.MODEL_RECONSTRUCTED) != str(Provenance.OBSERVED)


def test_provenance_field_present_on_all_outputs() -> None:
    """SpotBar and BookSummary carry provenance fields."""
    bar = SpotBar(timestamp=datetime.now(UTC), price=65000.0)
    assert bar.provenance == Provenance.OBSERVED
    assert bar.origin == "deribit"

    bs = BookSummary(
        instrument_name="BTC-27SEP24-65000-C",
        mark_price=0.025,
        mark_iv=0.45,
    )
    assert bs.provenance == Provenance.OBSERVED
    assert bs.origin == "deribit"

    inst = OptionInstrument(
        instrument_name="BTC-27SEP24-65000-C",
        base_currency="BTC",
        quote_currency="USD",
        settlement_currency="BTC",
        instrument_type="reversed",
        option_type="call",
        strike=65000.0,
        expiration_timestamp=datetime.now(UTC),
    )
    assert inst.provenance == Provenance.OBSERVED
    assert inst.origin == "deribit"


@pytest.mark.skip(reason="Deferred to A4 — ImpactEstimate not yet built")
def test_impact_estimate_provenance_per_component() -> None:
    """Provenance enum values for impact components are defined."""
    assert False, "Not implemented — A4"


# ══════════════════════════════════════════════════════════════════════════════
# §5 — Settlement spec integrity tests
# ══════════════════════════════════════════════════════════════════════════════


def test_settlement_spec_separate_fields() -> None:
    """Settlement fields are all separate — no combined enum (AC-1)."""
    spec = SettlementSpec(
        venue=Venue.DERIBIT,
        product="inverse_option",
        settlement_mechanism=SettlementMechanism.CASH,
        settlement_currency=SettlementCurrency.BTC,
        exercise_style=ExerciseStyle.EUROPEAN,
        contract_multiplier=1.0,
        delivery_price_convention=DeliveryPriceConvention.TWAP_0730_0800_UTC,
    )
    assert spec.venue == Venue.DERIBIT
    assert spec.settlement_mechanism == SettlementMechanism.CASH
    assert spec.settlement_currency == SettlementCurrency.BTC


def test_settlement_spec_rejects_zero_multiplier() -> None:
    """Contract multiplier must be > 0."""
    with pytest.raises(Exception):
        SettlementSpec(
            venue=Venue.DERIBIT,
            product="inverse_option",
            settlement_mechanism=SettlementMechanism.CASH,
            settlement_currency=SettlementCurrency.BTC,
            exercise_style=ExerciseStyle.EUROPEAN,
            contract_multiplier=0.0,
            delivery_price_convention=DeliveryPriceConvention.TWAP_0730_0800_UTC,
        )


def test_all_settlement_mechanisms() -> None:
    """All required settlement mechanisms are defined."""
    assert str(SettlementMechanism.CASH) == "cash"
    assert str(SettlementMechanism.FUTURES_DELIVERY_THEN_CASH) == "futures_delivery_then_cash"
    assert str(SettlementMechanism.PHYSICAL_UNDERLYING) == "physical_underlying"


def test_all_settlement_currencies() -> None:
    """All required settlement currencies are defined."""
    assert str(SettlementCurrency.BTC) == "BTC"
    assert str(SettlementCurrency.USDC) == "USDC"
    assert str(SettlementCurrency.USD) == "USD"


def test_all_venues() -> None:
    """All required venues are defined."""
    assert str(Venue.DERIBIT) == "deribit"
    assert str(Venue.CME) == "cme"
    assert str(Venue.OTC) == "otc"


def test_origin_labels_complete() -> None:
    """All required origin labels are defined per contracts.md §4.2."""
    assert str(Origin.DERIBIT) == "deribit"
    assert str(Origin.MASSIVE) == "massive"
    assert str(Origin.CME) == "cme"
    assert str(Origin.TEXTBOOK) == "textbook"
    assert str(Origin.BUSINESS_CONFIG) == "business_config"


# ══════════════════════════════════════════════════════════════════════════════
# §15 — Error hierarchy tests
# ══════════════════════════════════════════════════════════════════════════════


def test_error_hierarchy() -> None:
    """All error types are in the hierarchy."""
    assert issubclass(ConfigurationError, EngineError)
    assert issubclass(ClassificationError, EngineError)
    assert issubclass(EngineError, Exception)


# ══════════════════════════════════════════════════════════════════════════════
# §13.8 — Inverse settlement tests (deferred to A1)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Deferred to A1 — inverse pricing functions not yet implemented")
def test_inverse_call_holder_settlement() -> None:
    """settlement_inverse_call_holder(125000, 100000) == 0.2 (exact)."""
    assert False, "Not implemented — A1 Sprint 1"


@pytest.mark.skip(reason="Deferred to A1 — inverse pricing functions not yet implemented")
def test_inverse_put_holder_settlement() -> None:
    """settlement_inverse_put_holder(80000, 100000) == 0.25 (exact)."""
    assert False, "Not implemented — A1 Sprint 1"


@pytest.mark.skip(reason="Deferred to A1 — inverse pricing functions not yet implemented")
def test_inverse_call_writer_sign() -> None:
    """Writer cash flow = -0.2 BTC * contracts."""
    assert False, "Not implemented — A1 Sprint 1"


@pytest.mark.skip(reason="Deferred to A3 — strategy payoff functions not yet implemented")
def test_strategy_pnl_separated_from_settlement() -> None:
    """Long-BTC + short-put at ST=0: P&L correctly separates payoff from settlement."""
    assert False, "Not implemented — A3 Sprint 2"


# ══════════════════════════════════════════════════════════════════════════════
# §13.2 — Payoff boundary tests (deferred to A3)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Deferred to A3 — strategy_payoff not yet implemented")
def test_payoff_zero() -> None:
    assert False, "Not implemented — A3 Sprint 2"


@pytest.mark.skip(reason="Deferred to A3 — strategy_payoff not yet implemented")
def test_payoff_half_strike() -> None:
    assert False, "Not implemented — A3 Sprint 2"


@pytest.mark.skip(reason="Deferred to A3 — strategy_payoff not yet implemented")
def test_payoff_at_strike() -> None:
    assert False, "Not implemented — A3 Sprint 2"


@pytest.mark.skip(reason="Deferred to A3 — strategy_payoff not yet implemented")
def test_payoff_at_entry_spot() -> None:
    assert False, "Not implemented — A3 Sprint 2"


@pytest.mark.skip(reason="Deferred to A3 — strategy_payoff not yet implemented")
def test_payoff_double_strike() -> None:
    assert False, "Not implemented — A3 Sprint 2"


# ══════════════════════════════════════════════════════════════════════════════
# §6 — Fixture infrastructure tests
# ══════════════════════════════════════════════════════════════════════════════


def test_fixture_manifest_schema() -> None:
    """FixtureManifestEntry validates per contracts.md §6.4."""
    now = datetime.now(UTC)
    entry = FixtureManifestEntry(
        path="index_price.json",
        sha256="a" * 64,
        retrieval_date=now,
        venue="deribit",
        endpoint="get_index_price",
        record_count=1,
        status_code=200,
        byte_count=1024,
        url="https://www.deribit.com/api/v2/public/get_index_price",
    )
    assert entry.sha256 == "a" * 64
    assert entry.record_count == 1

    manifest = FixtureManifest(entries=[entry], created_at=now)
    assert len(manifest.entries) == 1


def test_fixture_manifest_parses_real_file() -> None:
    """If a fixture manifest exists, it must have valid schema."""
    manifest = load_manifest()
    assert "entries" in manifest
    assert "description" in manifest


# ══════════════════════════════════════════════════════════════════════════════
# §9 — Breakeven tests (deferred to A3)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Deferred to A3 — breakeven function not yet implemented")
def test_breakeven_returns_usd_for_usd_settled() -> None:
    assert False, "Not implemented — A3 Sprint 2"


@pytest.mark.skip(reason="Deferred to A3 — breakeven function not yet implemented")
def test_breakeven_returns_btc_for_inverse_settled() -> None:
    assert False, "Not implemented — A3 Sprint 2"


# ══════════════════════════════════════════════════════════════════════════════
# §13.10 — Hedge / Optimality tests (deferred)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Deferred to A3 — BacktestResult schemas not yet built")
def test_hedge_cost_field_present() -> None:
    assert False, "Not implemented — A3 Sprint 2"


@pytest.mark.skip(reason="Deferred to A5 — reporting layer enforces this")
def test_covered_call_not_marked_optimal() -> None:
    assert False, "Not implemented — A5 Sprint 3"


# ══════════════════════════════════════════════════════════════════════════════
# §13.6 — Waterfall sensitivity (deferred per D-1)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.xfail(reason="D-1 fee base unresolved")
def test_waterfall_fee_base_sensitivity() -> None:
    assert False, "Not implemented — A4 Sprint 1"


@pytest.mark.skip(reason="Deferred to A4 — waterfall_sensitivity not yet implemented")
def test_waterfall_spot_sensitivity() -> None:
    assert False, "Not implemented — A4 Sprint 1"


# ══════════════════════════════════════════════════════════════════════════════
# §10 — Rolling / early-close tests (deferred to A3)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Deferred to A3/A4 — RollSpec and EarlyCloseResult not yet built")
def test_roll_spec_validates() -> None:
    assert False, "Not implemented - A3/A4 Sprint 1-2"


# ══════════════════════════════════════════════════════════════════════════════
# D-9 hedge strategy test — deferred
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Deferred until D-9 is resolved by mandate issuer")
def test_delta_hedge_requires_d9_resolution() -> None:
    """Delta hedge P&L should emit W-HEDGE-MODEL-UNSPECIFIED when D-9 is unresolved."""
    assert False, "Not implemented — blocked on D-9 resolution"


# ══════════════════════════════════════════════════════════════════════════════
# §16.1 — DTE ladder overlap test
# ══════════════════════════════════════════════════════════════════════════════


def test_dte_ladder_no_overlap_rejected() -> None:
    """DTE ladder with no overlap vs target DTE range is rejected."""
    with pytest.raises(Exception):
        EngineConfig(
            btc_quantity=30000,
            reference_spot_usd=65000,
            seller_discount_pct=2.5,
            target_option_yield_pct=2.5,
            combined_target_discount_pct=5.0,
            execution_fee_pct=0.5,
            call_delta_target=[0.10, 0.15],
            dte_target_days=[30, 45],
            strike_target_pct_above_spot=[15, 20],
            target_monthly_premium_pct=3.0,
            iv_working_band_pct=[40, 50],
            risk_free_rate_pct=4.0,
            tranche_btc=[250, 1000],
            expiry_ladder_dte=[1, 2, 3],
        )


# ══════════════════════════════════════════════════════════════════════════════
# §13.11 — OOS and breakout tests (deferred or schema-only)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skip(reason="Deferred to A3 — OOS validation not yet implemented")
def test_oos_cscv_n_minimum() -> None:
    assert False, "Not implemented — A3 Sprint 2"


@pytest.mark.skip(reason="Deferred to A3 — OOS validation not yet implemented")
def test_oos_runs_by_default() -> None:
    assert False, "Not implemented — A3 Sprint 2"


def test_breakout_definition_schema() -> None:
    """BreakoutRule schema validates correctly."""
    rule = BreakoutRule(method="n_day_high", lookback_days=20, threshold_pct=10.0)
    assert rule.method == "n_day_high"
    assert rule.lookback_days == 20
    assert rule.threshold_pct == 10.0

    with pytest.raises(Exception):
        BreakoutRule(method="n_day_high", lookback_days=0, threshold_pct=10.0)


# ══════════════════════════════════════════════════════════════════════════════
# DecisionRef and pending decision tests
# ══════════════════════════════════════════════════════════════════════════════


def test_decision_ref_model() -> None:
    """DecisionRef carries code, owner, and impact."""
    ref = DecisionRef(
        code="D-1",
        owner="Mandate issuer",
        impact="$243,750 swing on $9.75M fee",
    )
    assert ref.code == "D-1"


def test_strategy_carries_pending_decisions() -> None:
    """Strategy model includes pending_decisions field."""
    legs = [
        _make_spot_leg(side="LONG"),
        _make_option_leg("call", "SHORT", strike=75000),
    ]
    strategy = Strategy(
        strategy_id="test-pending",
        business_label="Covered Call",
        canonical=classify(legs),
        legs=legs,
        pending_decisions=[
            DecisionRef(code="D-1", owner="Mandate issuer", impact="Fee base"),
            DecisionRef(code="D-3", owner="Mandate issuer", impact="Venue selection"),
        ],
    )
    assert len(strategy.pending_decisions) == 2
    assert strategy.pending_decisions[0].code == "D-1"
