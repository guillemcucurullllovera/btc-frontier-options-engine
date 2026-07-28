"""Market-data and fixture models.

Frozen per contracts.md §§4, 6.  All market-data models carry provenance
and origin fields.  Fixture manifests enable replayable offline testing.

Phase 0 — provenance and fixture schemas.
Do not add A1-A5 result schemas here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from config.models import Provenance

# ── §6.4 Fixture manifest ────────────────────────────────────────────────────


class FixtureManifestEntry(BaseModel):
    """One entry in the fixture manifest — frozen per contracts.md §6.4."""

    path: str  # Relative path under tests/fixtures/
    sha256: str  # Hex digest
    retrieval_date: datetime
    venue: str  # "deribit", "massive", etc.
    endpoint: str  # e.g. "get_book_summary_by_currency"
    record_count: int
    status_code: int | None = None
    byte_count: int | None = None
    url: str | None = None  # URL or method used for retrieval


class FixtureManifest(BaseModel):
    """Complete fixture manifest — frozen per contracts.md §6.4."""

    entries: list[FixtureManifestEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    description: str = "Replayable Deribit public API fixtures"


# ── §6.1 Live market data (Deribit) ──────────────────────────────────────────


class SpotBar(BaseModel):
    """Deribit spot index observation — frozen per contracts.md §6.1."""

    timestamp: datetime
    price: float  # USD
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"


class DvolBar(BaseModel):
    """Deribit DVOL index bar — frozen per contracts.md §6.1."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float  # annualised, decimal
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"


class BookSummary(BaseModel):
    """Per-instrument order-book summary — frozen per contracts.md §6.1."""

    instrument_name: str
    mark_price: float
    mark_iv: float  # annualised, decimal
    bid_price: float | None = None
    bid_iv: float | None = None
    ask_price: float | None = None
    ask_iv: float | None = None
    open_interest: float = 0.0
    underlying_price: float = 0.0
    interest_rate: float = Field(
        default=0.0,
        description="Decimal, continuous compounding (consistent with contracts.md §3.1)",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"


class OptionInstrument(BaseModel):
    """Deribit option instrument metadata — frozen per contracts.md §6.1."""

    instrument_name: str
    base_currency: str  # "BTC"
    quote_currency: str  # "USD"
    settlement_currency: str  # "BTC" or "USDC"
    instrument_type: str  # "reversed" or "linear"
    option_type: str  # "call" or "put"
    strike: float  # USD
    expiration_timestamp: datetime
    contract_size: float = 1.0
    min_trade_amount: float = 0.1
    block_trade_min_trade_amount: float = 25.0
    tick_size: float = 0.0001
    maker_commission: float = 0.0
    taker_commission: float = 0.0
    block_trade_commission: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"


# ── §6.3 Historical data ─────────────────────────────────────────────────────


class HistoricalSpotBar(BaseModel):
    """Historical BTC spot bar — frozen per contracts.md §6.3."""

    symbol: str  # e.g. "btc_usd"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float  # BTC
    vwap: float | None = None
    transactions: int | None = None
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "massive"  # or "cryptodatadownload"


class HistoricalOptionBar(BaseModel):
    """Historical option OHLCV bar — frozen per contracts.md §6.3."""

    instrument_name: str
    timestamp: datetime
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    open_interest: float = 0.0
    mark_iv: float | None = None
    mark_iv_provenance: Provenance = Field(
        default=Provenance.MODEL_RECONSTRUCTED,
        description="OBSERVED for Deribit book_summary; MODEL_RECONSTRUCTED for CDD/VWAP-derived",
    )
    provenance: Provenance = Provenance.OBSERVED  # OBSERVED or MODEL_RECONSTRUCTED
    origin: str = "cryptodatadownload"  # "cryptodatadownload" or "deribit" or "model_reconstructed"


# ── §6.5 Missing-data provenance rule ─────────────────────────────────────────
# Documented here; enforced at the data-ingestion layer by A2.
# Where observed historical option chains are missing:
#   1. Premium is reconstructed from DVOL + spot using BS ATM at the relevant tenor.
#   2. DVOL is a single 30-day index, not a term structure.
#   3. Provenance is MODEL_RECONSTRUCTED, origin is "model_reconstructed".
#   4. Must never present model-reconstructed values as observed.
