# BTC Engine Contracts — SOURCE-BACKED DRAFT

**Status:** Draft for Phase-0 gate review (A6 freeze prerequisite).  
**Date:** 2026-07-28  
**Replaces:** None (first version).  
**Next gate:** Phase-0 acceptance (Section 18).

---

## 1. Scope and authority hierarchy

### 1.1 Purpose

This document defines the architecture, interfaces and validation invariants for an engine whose exclusive purpose is to **compare — not prejudge** — the following structures:

- Covered call (long BTC + short call);
- Cash-secured put (cash collateral + short put);
- Long BTC plus short put (no canonical name substitution);
- Partial covered-call overlays;
- Staggered strikes and expiries;
- Rolling and early-close policies;
- Call spreads;
- Collars.

The engine must compute, for every candidate, **all** of:

- Expiry payoff, mark-to-market P&L, premium contribution, effective acquisition economics, ITM probability, touch probability, venue-specific exercise and settlement, missed-upside risk, downside exposure, hedge and rolling costs, bid/ask spread and fees, market impact and institutional tranching, historical backtest, Monte Carlo, stress test, out-of-sample validation, regime sensitivity.

### 1.2 Authority order (binding)

Where any two sources conflict, the higher-numbered document prevails:

| # | Document | Location |
|---|----------|----------|
| 1 | `authoritative_corrections.md` | `docs/requirements/authoritative_corrections.md` |
| 2 | Current official venue documentation | `private_reference_library/deribitfilesascopiedtxt.txt`, `pillar_4_venue_standards/deribit/api/` |
| 3 | `ceo_strategy_research_mandate.md` | `docs/requirements/ceo_strategy_research_mandate.md` |
| 4 | `AGENTS.md` | Root |
| 5 | `mandate_sanitized.md` | `docs/requirements/mandate_sanitized.md` |
| 6 | `BTC_30K_Build_Plan_Parallel_Agents.md` | `docs/requirements/BTC_30K_Build_Plan_Parallel_Agents.md` |
| 7 | Audits and pillar studies | `docs/reports/*` — evidence only, not executable specification |
| 8 | Textbooks (Hull, Haug, Gatheral, McNeil, Kissell, Harris, Sinclair, Bailey) | `_text_cache/Textbooks/` |

**Override rule (from authoritative_corrections.md §6):** Where an audit conflicts with this document, this document prevails. Where this document is silent, current official venue documentation prevails over textbooks.

### 1.3 Binding constraints

- Core pricing functions remain **pure and parameter-driven** (AC-4, AC-5).
- The existing `OptionQuote` frozen dataclass is **preserved** unless Section 7 explicitly approves an extension (AC-3, AC-6).
- Pydantic is used at **configuration, ingestion, persistence and external-reporting boundaries** only (AC-3). Pure numerical internals use frozen typed dataclasses.
- Strategy classification is derived **strictly from position legs** (AGENTS.md §"Strategy classification"). Source labels are preserved for comparison but never treated as canonical.
- Economic payoff, venue settlement and discretionary inventory actions are kept **separate** (AC-1, AC-8).
- Settlement mechanism, settlement currency, venue and product are **separate fields** (AC-1).
- Inverse-BTC formulas from the reconciled audit §10.8 are **not implemented directly** (AC-4, §4). Inverse settlement is re-derived from official Deribit specifications.
- The hypotheses listed in ceo_strategy_research_mandate.md §"Hypotheses" (10–15 delta, 30–45 DTE, 15–20% OTM, ~3% premium, high-IV selling, breakout stand-down) are treated as **testable claims**, not approved policies.
- The 2.5% seller discount, 2.5% overlay target, 0.5% fee and 30,000 BTC reference quantity are **configurable business requirements**.
- All values carry an explicit provenance label.

---

## 2. Terminology and canonical strategy classifications

### 2.1 Leg terminology

| Term | Definition |
|------|-----------|
| **Position leg** | `(instrument, side, quantity, entry_premium, settlement_terms)` — the atomic building block. |
| **Instrument** | `(venue, product, option_type, strike, expiry, multiplier, exercise_style, settlement_mechanism, settlement_currency, delivery_price_convention)`. |
| **Side** | `LONG` or `SHORT`. |
| **Quantity** | Number of contracts (positive integer for long, negative for short; or unsigned with side). |
| **Entry premium** | Premium received (short) or paid (long) per contract at leg initiation, in the quoted currency. |
| **Underlying leg** | For spot/futures legs the instrument identity is `(venue, product, side, quantity, entry_price)`. |

### 2.2 Canonical strategy classification

Classification is derived **algorithmically** from leg composition. The engine must never classify from titles, filenames, chart headings or source labels (AGENTS.md line 55–57).

```python
from enum import StrEnum

class StrategyKind(StrEnum):
    # Derivations:
    COVERED_CALL = "covered_call"            # long underlying + short call
    CASH_SECURED_PUT = "cash_secured_put"    # cash collateral + short put
    LONG_BTC_PLUS_SHORT_PUT = "long_btc_plus_short_put"  # long underlying + short put
    # WARNING: COVERED_PUT requires short underlying + short put (AGENTS.md line 61).
    COVERED_PUT = "covered_put"              # short underlying + short put
    PROTECTIVE_PUT = "protective_put"        # long underlying + long put
    CALL_SPREAD = "call_spread"              # long/short calls at different strikes
    COLLAR = "collar"                        # long underlying + short call + long put
    PARTIAL_OVERLAY = "partial_overlay"      # long underlying + short call on fraction of position
    NAKED_CALL = "naked_call"                # short call, no underlying
    NAKED_PUT = "naked_put"                  # short put, no underlying
    BESPOKE = "bespoke"                      # any unrecognised combination
```

### 2.3 Required dual-preservation rule

When the engine's algorithmic classification differs from a source business label:
- Store both as `canonical: StrategyKind` and `business_label: str`.
- In all reports emit both, with a warning when they differ.
- Flag the conflict as an `ERROR` level reporting event (Section 15).

---

## 3. Units, signs, numeraires and time conventions

### 3.1 Base conventions (all modules)

| Quantity | Unit | Convention | Source |
|----------|------|-----------|--------|
| Spot price (S) | USD per 1 BTC | Decimal | AGENTS.md line 24 |
| Strike (K) | USD | Same numeraire as spot | `pricing/black_scholes.py` |
| Risk-free rate (r) | Continuous, decimal | 0.04 = 4% | AGENTS.md line 24 |
| Volatility (σ) | Annualised, decimal | 0.45 = 45% | AGENTS.md line 24 |
| Time to expiry (T) | Years | dte_days / 365.0 | AGENTS.md line 24 |
| Option price (BS) | USD per unit | — | `pricing/black_scholes.py` line 16 |
| Premium percentage | % of spot | 100 × price / S | `premium_pct_at_delta()` |
| Delta | dPrice/dSpot | Call ∈ [0,1], Put ∈ [-1,0] | Haug §2.1 |
| Gamma | d²Price/dSpot² | Per 1 USD move | Hull §19 |
| Vega | dPrice/dσ | Per 1.00 (100%) absolute σ change; ÷100 for per-vol-point | docstring line 19 |
| Theta | dPrice/dT, annualised | Negative for long; ÷365 for per-day | docstring line 20 |
| Notional | USD | S × quantity | `waterfall.py` line 19 |
| Fees | % of reference notional | Configurable | `params.yaml` |

### 3.2 Sign convention

- **Buyer/ holder / long position:** positive quantity, premium paid (debit), delta positive for calls.
- **Writer / seller / short position:** negative quantity, premium received (credit), delta negative for short calls.
- **P&L:** positive = gain, negative = loss, all in base currency (USD).

### 3.3 Deribit inverse settlement — units and numeraire

**Source:** `deribitfilesascopiedtxt.txt` §"Inverse Options" lines 1–199; §"Inverse Option Contract Specifications" lines 58–274.

| Field | Value | Source line |
|-------|-------|-------------|
| Underlying | Deribit BTC Index | line 85 |
| Quoted currency | BTC | line 115 |
| Margin currency | BTC | line 121 |
| Settlement currency | BTC | line 203 |
| Contract multiplier | 1 BTC | line 135 |
| Delivery price | TWAP of Deribit BTC index, 07:30–08:00 UTC | line 187 |
| Exercise style | European, cash-settled, automatic at expiry | line 191 |
| Minimum tick | 0.0001 BTC ≤ 0.0050; 0.0005 BTC > 0.0050 | lines 239–241 |
| Minimum order | 0.1 contract | line 233 |
| Block minimum | 25 BTC notional | line 249 |
| Option trading fee | MIN(0.0003 BTC, 0.125 × OptionPrice) × Amount | lines 3572–3574 |
| Delivery fee | 0.015%, cap 12.5% of option value | line 3755 |

**Inverse call settlement (BTC):**
```
settlement_btc = max(delivery_price − strike, 0) / delivery_price  // per 1 contract
```
**Inverse put settlement (BTC):**
```
settlement_btc = max(strike − delivery_price, 0) / delivery_price  // per 1 contract
```
**Economic payoff in USD (for comparison purposes only — actual settlement is in BTC):**
```
payoff_usd = settlement_btc × delivery_price
           = max(delivery_price − strike, 0)   // for call (USD)
           = max(strike − delivery_price, 0)   // for put  (USD)
```

### 3.4 CME Bitcoin options on futures — units and conventions

**Source:** `_text_cache/BTC_pending links/350A.txt` (131 lines: CME Options on Bitcoin Futures).

| Field | Value |
|-------|-------|
| Underlying | 1 CME Bitcoin Futures (5 BTC) |
| Contract multiplier | 5 BTC |
| Settlement currency | USD |
| Minimum tick | 5 index points ($25) |
| Increment for ≤25 pt premiums | 1 index point |
| Exercise style | European, auto-exercise ITM |
| Settlement at expiry | Into 1 Bitcoin Futures at strike |
| Final settlement price | BRR (CME CF Bitcoin Reference Rate), 4 p.m. London |
| Weekly options fix | VWAP 03:30–03:59:59 p.m. London |

### 3.5 Timestamps

All timestamps are UTC-aware and stored as ISO-8601 strings with `Z` suffix or offset (AGENTS.md line 51).

---

## 4. Provenance and source models

### 4.1 Provenance enum

```python
from enum import StrEnum

class Provenance(StrEnum):
    OBSERVED = "observed"              # Direct market observation (e.g. Deribit mark_iv, massive OHLC)
    CALCULATED = "calculated"          # Deterministic computation from observed inputs (e.g. BS price from observed IV)
    MODEL_RECONSTRUCTED = "model_reconstructed"  # Inferred/generated where observed data is missing (AC-5 §5)
    SIMULATED = "simulated"            # Monte Carlo or synthetic generation
    ASSUMED = "assumed"               # Uncalibrated placeholder (e.g. IV give-up 0.5–2.0 vol pts)
    BUSINESS_REQUIREMENT = "business_requirement"  # Configurable mandate parameter
    VENUE_SPECIFICATION = "venue_specification"    # Contract specification from official venue docs
```

### 4.2 Source models (data origin labelling)

| Origin | Use | Label |
|--------|-----|-------|
| Deribit | Live spot index, DVOL, option chain, book summaries, mark IV | `origin=deribit` |
| Massive | Historical BTC spot (primary) | `origin=massive` |
| CryptoDataDownload | Historical DVOL + option OHLCV (fallback) | `origin=cryptodatadownload` |
| CME | BTC futures settlement (BRR), option specs | `origin=cme` |
| Hull/Haug | Textbook golden vectors | `origin=textbook` |
| Parameters | Business config | `origin=business_config` |

### 4.3 Provenance tag on every datum

Every `float` or aggregated result in the engine must carry a provenance tag in its container (e.g., `Pydantic` model fields `provenance: Provenance`, `origin: str | None = None`). Configuration-layer Pydantic models enforce that no value is ingested without provenance assignment.

---

## 5. Venue, product, exercise and settlement models

### 5.1 Settlement decomposition (per AC-1)

```python
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, Field

class SettlementMechanism(StrEnum):
    CASH = "cash"                                    # Cash-settled at expiry (Deribit inverse, Deribit linear)
    FUTURES_DELIVERY_THEN_CASH = "futures_delivery_then_cash"  # Option → futures at strike → cash settle (Deribit linear, CME)
    PHYSICAL_UNDERLYING = "physical_underlying"      # Actual BTC delivery (OTC only, if contract requires)

class SettlementCurrency(StrEnum):
    BTC = "BTC"
    USDC = "USDC"
    USD = "USD"

class ExerciseStyle(StrEnum):
    EUROPEAN = "european"   # Exercise only at expiry
    AMERICAN = "american"   # Exercise at any time before expiry

class Venue(StrEnum):
    DERIBIT = "deribit"
    CME = "cme"
    OTC = "otc"

class DeliveryPriceConvention(StrEnum):
    TWAP_0730_0800_UTC = "twap_0730_0800"     # Deribit (line 187)
    BRR_1600_LONDON = "brr_1600_london"        # CME monthly (Ch. 350A)
    VWAP_0330_035959_LONDON = "vwap_0330_0400_london"  # CME weekly (Ch. 350A)
    NEGOTIATED = "negotiated"                  # OTC bespoke

class SettlementSpec(BaseModel):
    """Separate settlement fields per AC-1. Never use a combined enum."""
    venue: Venue
    product: str  # e.g. "inverse_option", "linear_option", "option_on_futures", "otc_option"
    settlement_mechanism: SettlementMechanism
    settlement_currency: SettlementCurrency
    exercise_style: ExerciseStyle
    contract_multiplier: float  # e.g. 1 (Deribit), 5 (CME)
    delivery_price_convention: DeliveryPriceConvention
```

### 5.2 Venue/product combinations (minimum set)

| Venue | Product | Mechanism | Currency | Exercise | Multiplier | Delivery | Source |
|-------|---------|-----------|----------|----------|-----------|----------|--------|
| Deribit | inverse_option | cash | BTC | European | 1 | TWAP 0730–0800 | `deribitfilesascopiedtxt.txt` lines 1–274 |
| Deribit | linear_option | futures_delivery_then_cash | USDC | European | 1 | TWAP 0730–0800 | `deribitfilesascopiedtxt.txt` lines 3606–3805 |
| CME | option_on_futures | futures_delivery_then_cash | USD | European | 5 | BRR 1600 London | `_text_cache/BTC_pending links/350A.txt` |
| OTC | otc_option | physical_underlying or cash | USD or BTC | Negotiated | Negotiated | Negotiated | ISDA DA Definitions + whitepaper §4–5 |

### 5.3 Separation principle (AC-8)

The engine must separate:
1. **Economic payoff** — what the position would be worth at expiry in an idealised frictionless market.
2. **Venue settlement** — how the contract actually settles under venue rules (cash, futures delivery, physical BTC).
3. **Discretionary inventory action** — any additional BTC purchase or sale after settlement that is a business decision, not a contract obligation.

---

## 6. Market-data and historical-data models

### 6.1 Live market data (Deribit)

```python
from pydantic import BaseModel
from datetime import datetime

class SpotBar(BaseModel):
    timestamp: datetime
    price: float  # USD
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"

class DvolBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float   # annualised, decimal
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"

class BookSummary(BaseModel):
    instrument_name: str
    mark_price: float
    mark_iv: float          # annualised, decimal
    bid_price: float | None
    bid_iv: float | None
    ask_price: float | None
    ask_iv: float | None
    open_interest: float
    underlying_price: float
    interest_rate: float    # decimal
    timestamp: datetime
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"

class OptionInstrument(BaseModel):
    instrument_name: str
    base_currency: str          # "BTC"
    quote_currency: str         # "USD"
    settlement_currency: str    # "BTC" or "USDC"
    instrument_type: str        # "reversed" or "linear"
    option_type: str            # "call" or "put"
    strike: float               # USD
    expiration_timestamp: datetime
    contract_size: float
    min_trade_amount: float
    block_trade_min_trade_amount: float
    tick_size: float
    maker_commission: float
    taker_commission: float
    block_trade_commission: float
    timestamp: datetime
    provenance: Provenance = Provenance.OBSERVED
    origin: str = "deribit"
```

### 6.2 Historical spot data

```python
class HistoricalSpotBar(BaseModel):
    symbol: str            # e.g. "btc_usd"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float          # BTC
    vwap: float | None
    transactions: int | None
    provenance: Provenance
    origin: str            # "massive" or "cryptodatadownload"
```

### 6.3 Historical option data

```python
class HistoricalOptionBar(BaseModel):
    instrument_name: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float
    mark_iv: float | None
    provenance: Provenance  # OBSERVED or MODEL_RECONSTRUCTED
    origin: str             # "cryptodatadownload" or "deribit" or "model_reconstructed"
```

### 6.4 Fixture recording

All live API responses must be cachable and replayable. Fixtures stored under `tests/fixtures/` in Parquet format with a SHA-256 manifest (A2 deliverable, Build Plan §7).

### 6.5 Missing historical options rule (AC-5 §5)

Where observed historical option chains are missing:
- Premium is reconstructed from DVOL + spot using Black-Scholes/Black-76.
- Provenance is `MODEL_RECONSTRUCTED`, origin is `"model_reconstructed"`.
- The engine must never present model-reconstructed values as observed.

---

## 7. Pricing interfaces and compatibility rules

### 7.1 Existing preserved interface

The `OptionQuote` frozen dataclass is preserved (AC-3, AC-6). No Pydantic migration. Extension is permitted only as explicitly approved below.

```python
@dataclass(frozen=True)
class OptionQuote:
    price: float      # USD
    delta: float
    gamma: float
    vega: float       # per 1.00 vol
    theta: float      # per year
    strike: float
```

### 7.2 Required extension — settlement-aware quote

To support venue-aware analysis, a new dataclass wraps `OptionQuote` with settlement metadata (does not replace `OptionQuote`):

```python
@dataclass(frozen=True)
class SettlementOptionQuote:
    quote: OptionQuote
    settlement: SettlementSpec
    price_btc: float          # BTC-denominated price for inverse options
    premium_quoted: float      # In the quoted currency (BTC for inverse, USDC for linear)
```

### 7.3 Pure function signatures (preserved and extended)

Existing signatures preserved exactly (AC-4):

```python
def price(S: float, K: float, r: float, sigma: float, T: float, kind: str = "call") -> float: ...
def greeks(S: float, K: float, r: float, sigma: float, T: float, kind: str = "call") -> OptionQuote: ...
def strike_for_delta(S: float, target_delta: float, r: float, sigma: float, T: float, kind: str = "call") -> float: ...
def implied_vol(target_price: float, S: float, K: float, r: float, T: float, kind: str = "call", lo: float = 1e-4, hi: float = 5.0) -> float: ...
def premium_pct_at_delta(S: float, delta: float, r: float, sigma: float, dte_days: float, kind: str = "call") -> tuple[float, float]: ...
```

New pure functions added:

```python
# Black-76 (A1, Sprint 1) — for futures-underlying options (CME)
def price_black76(F: float, X: float, r: float, sigma: float, T: float, kind: str = "call") -> float: ...
def greeks_black76(F: float, X: float, r: float, sigma: float, T: float, kind: str = "call") -> OptionQuote: ...

# Vectorised grid pricing (A1)
def price_grid(S: float, Ks: np.ndarray, r: float, sigma: float, Ts: np.ndarray, kind: str = "call") -> np.ndarray: ...

# Inverse option pricing (A1, re-derived from Deribit spec — NOT from reconciled audit §10.8)
def price_inverse_btc(S: float, K: float, r: float, sigma: float, T: float, forward: float, kind: str = "call") -> float: ...
def greeks_inverse_btc(S: float, K: float, r: float, sigma: float, T: float, forward: float, kind: str = "call") -> OptionQuote: ...

# Inverse-BTC payoff at expiry (from Deribit spec lines 1–199)
def payoff_inverse_call(delivery_price: float, strike: float) -> float:
    """Returns BTC settlement per contract: max(delivery_price - strike, 0) / delivery_price"""
def payoff_inverse_put(delivery_price: float, strike: float) -> float:
    """Returns BTC settlement per contract: max(strike - delivery_price, 0) / delivery_price"""

# Standard BS payoff (USD)
def payoff_bs_call(S_T: float, K: float) -> float:
    """max(S_T - K, 0)"""
def payoff_bs_put(S_T: float, K: float) -> float:
    """max(K - S_T, 0)"""
```

### 7.4 Compatibility rules

1. All existing test vectors must pass unchanged (golden vectors, parity, roundtrips).
2. New functions must not modify existing function signatures.
3. `price()` and `greeks()` remain the canonical Black-Scholes implementations.
4. The inverse-BTC pricer must be independently unit-checked against examples from Deribit spec (lines 16–56) before merge.
5. Golden vectors are **fixed independent test vectors** — never derived from `params.yaml` (AC-5).

### 7.5 QuantLib parity (A1, A6)

Every pricing function must be independently verified against QuantLib:

```python
# Test interface (no implementation body)
def test_quantlib_parity_price():
    """hypothesis-based: max absolute difference < 1e-6 on 50 random (S,K,r,σ,T) draws."""
```

---

## 8. Volatility-surface, discount-curve and forward-curve interfaces

### 8.1 Volatility surface

```python
@dataclass(frozen=True)
class VolPoint:
    expiry: float            # T in years
    delta: float             # BS delta (not moneyness)
    iv: float                # annualised, decimal
    provenance: Provenance
    origin: str              # "deribit_book_summary" or "model_reconstructed"

@dataclass(frozen=True)
class VolSurface:
    timestamp: datetime
    points: list[VolPoint]

def fit_surface(book_summaries: list[BookSummary]) -> VolSurface: ...
def iv_at(surface: VolSurface, expiry: float, delta: float) -> float: ...
```

### 8.2 Discount curve

```python
@dataclass(frozen=True)
class DiscountCurve:
    """Flat rate initially; extensible to term structure."""
    rate: float              # decimal, continuous
    provenance: Provenance
    origin: str              # "params.yaml" or "deribit_interest_rate"
```

### 8.3 Forward curve

```python
@dataclass(frozen=True)
class ForwardCurve:
    """Forward/futures marks per expiry."""
    points: dict[datetime, float]  # expiry → forward price (USD)
    provenance: Provenance
    origin: str                    # "deribit_futures_mark"
```

---

## 9. Position-leg, strategy, payoff, MTM and breakeven interfaces

### 9.1 Position leg

```python
from pydantic import BaseModel

class Leg(BaseModel):
    """One leg of a strategy."""
    instrument: str             # e.g. "BTC-spot", "BTC-27SEP24-65000-C"
    venue: Venue
    product: str
    side: Literal["LONG", "SHORT"]
    quantity: float             # Positive float; side determines economic effect
    entry_premium: float        # Per-contract premium PAID (positive) or RECEIVED (negative), in quoted currency
    settlement: SettlementSpec
    # For underlying legs:
    entry_spot: float | None = None  # Spot price at leg initiation
```

### 9.2 Strategy

```python
class Strategy(BaseModel):
    strategy_id: str
    business_label: str                 # Source label from mandate/client (may differ from canonical)
    canonical: StrategyKind             # Algorithmically derived from legs (Section 2.2)
    legs: list[Leg]
    classification_warning: str | None  # Non-None if business_label ≠ canonical
    notes: str | None                   # Decision_pending items, assumptions
```

### 9.3 Payoff

```python
@dataclass(frozen=True)
class PayoffPoint:
    S_T: float                 # Underlying spot at evaluation (USD)
    payoff_usd: float          # Total strategy payoff (USD)
    pnl_usd: float             # Payoff net of premiums paid/received
    settlement_btc: float      # BTC settlement under venue rules (or NaN if not BTC-settled)

def strategy_payoff(strategy: Strategy, S_T: float) -> PayoffPoint: ...
def strategy_payoff_curve(strategy: Strategy, S_points: np.ndarray) -> list[PayoffPoint]: ...
```

### 9.4 Mark-to-market

```python
@dataclass(frozen=True)
class MtmPoint:
    timestamp: datetime
    spot: float               # USD
    mtm_usd: float            # Total strategy MTM (USD)
    mtm_btc: float            # BTC-equivalent
    greeks: OptionQuote | None  # Aggregate strategy Greeks (if applicable)

def mtm_at(strategy: Strategy, spot: float, surface: VolSurface, curve: DiscountCurve, t: float) -> MtmPoint: ...
```

### 9.5 Breakeven

```python
def breakeven(strategy: Strategy) -> list[float]:
    """Return all spot prices (USD) where strategy P&L = 0. Returns empty list if none."""
```

### 9.6 Validation invariant — payoff at boundary points

Per AGENTS.md line 64–65, every strategy payoff must be tested at:

| BTC price | Rationale |
|-----------|-----------|
| 0 | Maximum downside |
| S < K (below strike) | Exercise boundary |
| S = K (at strike) | Kink point |
| S = S₀ (initial spot) | No-change scenario |
| S ≫ K (materially above strike) | Maximum upside |

The test harness (`tests/test_payoffs.py`) must verify each strategy at all five points and flag any discrepancy between calculated payoff and any source diagram annotation.

---

## 10. Rolling, closing, exercise and settlement interfaces

### 10.1 Rolling

```python
from pydantic import BaseModel
from datetime import datetime

class RollSpec(BaseModel):
    close_leg: Leg
    open_leg: Leg
    close_price: float         # Premium paid/received to close
    open_premium: float        # Premium received/paid to open
    roll_cost_usd: float       # Net cost of roll (positive = debit)
    timestamp: datetime
    venue_fees_paid: float     # Total venue fees for both legs

def evaluate_roll(close_leg: Leg, open_leg: Leg, spot: float, surface: VolSurface, curve: DiscountCurve) -> RollSpec: ...
```

### 10.2 Early close

```python
class EarlyCloseResult(BaseModel):
    leg: Leg
    close_price: float         # Market price to buy back / sell to close
    close_date: datetime
    days_held: float
    premium_retained: float    # For short positions: initial premium minus close cost
    venue_fees: float
    pnl_usd: float
```

### 10.3 Exercise and settlement

```python
class SettlementResult(BaseModel):
    """What actually happens at expiry under venue rules."""
    leg: Leg
    settlement: SettlementSpec
    delivery_price: float                    # The official settlement/delivery price
    is_itm: bool
    settlement_amount: float                 # In settlement currency (BTC or USD)
    settlement_currency: SettlementCurrency
    venue_delivery_fee: float                # Per Deribit: 0.015% cap 12.5% (line 3755)
    net_to_account: float                    # settlement_amount minus delivery fee
```

---

## 11. Backtest, Monte Carlo, stress and OOS result schemas

### 11.1 Backtest result

```python
class BacktestCycleResult(BaseModel):
    cycle_num: int
    start_date: datetime
    end_date: datetime
    dte: float
    entry_spot: float
    strike: float
    delta_at_entry: float
    entry_iv: float
    premium_received_pct: float      # % of spot
    premium_received_btc: float      # BTC
    premium_provenance: Provenance   # OBSERVED or MODEL_RECONSTRUCTED
    expiry_spot: float
    is_itm: bool
    assignment_btc: float            # BTC debited/credited at settlement
    net_pnl_btc: float               # premium minus assignment
    net_pnl_pct: float               # % of notional
    cumulative_premium_pct: float    # Running sum vs 2.5% target
    venue_fees_btc: float
    impact_iv_giveup: float          # Volatility points given up to execution

class BacktestResult(BaseModel):
    strategy: Strategy
    start_date: datetime
    end_date: datetime
    cycles: list[BacktestCycleResult]
    total_pnl_btc: float
    total_pnl_pct: float
    effective_acquisition_cost_per_btc: float  # USD
    itm_frequency: float                # Fraction of cycles that finished ITM
    touch_frequency: float              # Fraction of cycles where spot touched strike
    max_drawdown_pct: float
    sharpe_ratio: float | None
    oos_window: tuple[datetime, datetime] | None  # If OOS validation performed
```

### 11.2 Monte Carlo result

```python
class MonteCarloResult(BaseModel):
    strategy: Strategy
    n_paths: int
    model: str                     # "GBM", "Merton", "Kou"
    seed: int
    horizon_years: float
    initial_spot: float
    drift: float
    volatility: float
    jump_params: dict | None
    pnl_distribution: list[float]          # Per-path final P&L (USD)
    itm_probability: float                 # Fraction of paths ITM at expiry
    touch_probability: float               # Fraction touching strike during life
    var_95_pct: float                      # Value-at-Risk (95%)
    var_99_pct: float                      # Value-at-Risk (99%)
    es_975_pct: float                      # Expected Shortfall (97.5%)
    es_99_pct: float                       # Expected Shortfall (99%)
    expected_pnl: float
    expected_premium_pct: float
```

### 11.3 Stress test result

```python
class StressScenarioResult(BaseModel):
    scenario_name: str                     # e.g. "2025_breakout_to_126k", "dvol_35_to_65_shock"
    description: str
    start_spot: float
    end_spot: float
    path: list[float]                      # Spot path (or None for instantaneous shock)
    strategy_pnl_usd: float
    strategy_pnl_pct: float
    premium_contribution_pct: float
    itm_on_scenario: bool
    max_adverse_excursion_pct: float       # Worst intra-scenario drawdown
    venue_settlement_applied: bool
```

### 11.4 Out-of-sample validation result

```python
class OOSValidationResult(BaseModel):
    train_period: tuple[datetime, datetime]
    test_period: tuple[datetime, datetime]
    train_sharpe: float | None
    test_sharpe: float | None
    train_itm_freq: float
    test_itm_freq: float
    pbo_estimate: float                    # Probability of Backtest Overfitting (Bailey et al. 2015)
    performance_degradation: float          # Train Sharpe − Test Sharpe (positive = overfit concern)
    cscv_s: int = 16                       # S parameter per Bailey et al. recommendation
    cscv_n: int                            # ≥ 100 per Bailey et al. guideline
```

### 11.5 Regime analysis result

```python
class RegimeAnalysisResult(BaseModel):
    regime_name: str                       # e.g. "bull_2023_2024", "bear_2022", "volatile_2025"
    regime_dates: tuple[datetime, datetime]
    annualised_return: float
    annualised_vol: float
    avg_dvol: float
    strategies: dict[str, BacktestResult]  # Per-strategy backtest within regime
```

---

## 12. Execution-impact, fee and tranche interfaces

### 12.1 Market impact model

```python
class ImpactEstimate(BaseModel):
    order_size_btc: float
    adv_btc: float                     # Average daily volume
    volatility: float                  # decimal, annualised
    i_star_bp: float                   # Instantaneous impact (Kissell eq. 4.6)
    market_impact_bp: float            # Total impact (Kissell eq. 4.7)
    temporary_impact_bp: float
    permanent_impact_bp: float
    square_root_eta: float             # Empirical square-root parameter (Sinclair §6)
    iv_giveup_vol_pts: float           # Per-clip IV give-up (0.5–2.0 default, uncalibrated)
    provenance: Provenance = Provenance.ASSUMED  # Until vendor calibration data available

def estimate_impact(order_size_btc: float, adv_btc: float, volatility: float,
                    a1: float, a2: float, a3: float, b1: float, a4: float) -> ImpactEstimate:
    """I-Star model (Kissell §4, eq. 4.6–4.7). Source: _text_cache/Textbooks/Kissell.txt
       I*_bp = a1 * (Q/ADV)^a2 * σ^a3
       MI_bp = b1 * I* * POV^a4 + (1 - b1) * I*
    """
```

### 12.2 Fee model

```python
class FeeBreakdown(BaseModel):
    asym_fee_usd: float                # Asymmetrica 0.5% on reference notional (configurable)
    asym_fee_btc_equiv: float
    venue_trading_fee_btc: float       # Deribit: MIN(0.0003, 0.125 * premium) * contracts (line 3574)
    venue_delivery_fee_btc: float      # Deribit: 0.015%, cap 12.5% (line 3755)
    block_trade_fee_btc: float         # Deribit: 0.03% (line 3717)
    total_fees_btc: float
    impact_cost_estimate: ImpactEstimate | None
    fee_base: Literal["reference_notional", "executed_volume"]  # TODO(decision_pending: D-1)
```

### 12.3 Tranche scheduler

```python
class Tranche(BaseModel):
    tranche_id: int
    dte: int                          # Days to expiry
    btc_quantity: int
    strike: float                     # USD
    delta_target: float
    target_premium_pct: float
    execution_venue: Venue
    execution_method: str              # "block_rfq", "voice_broker", "otc", "screen"
    estimated_impact: ImpactEstimate
    scheduled_date: datetime

class TrancheSchedule(BaseModel):
    strategy: Strategy
    total_btc: int                    # Must sum exactly to configurable total (30,000)
    tranches: list[Tranche]
    expiry_ladder_dte: list[int]      # e.g. [30, 37, 44]
    clip_size_range: tuple[int, int]  # e.g. (250, 1000)
    duration_weeks: int               # 4–8 weeks

def schedule_tranches(strategy: Strategy, total_btc: int,
                      expiry_ladder: list[int], clip_range: tuple[int, int],
                      duration_weeks: int) -> TrancheSchedule:
    """Must total exactly total_btc. Source: config/params.yaml"""
```

### 12.4 Waterfall — extended sensitivity mode

```python
class WaterfallSensitivity(BaseModel):
    spot_offsets_pct: list[float] = [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
    fee_bases: list[Literal["reference_notional", "executed_volume"]] = ["reference_notional", "executed_volume"]

def waterfall_sensitivity(p: dict, sensitivity: WaterfallSensitivity) -> list[dict]:
    """Produce waterfall for every (spot_offset, fee_base) combination."""
```

---

## 13. Validation invariants and required tests

### 13.1 Golden-vector tests (preserved and extended)

| Test vector | Source | Expected | Tolerance |
|-------------|--------|----------|-----------|
| ATM call, S=K=100, r=0.05, σ=0.20, T=1 | Hull/Haug | 10.4506 | 1e-3 |
| ATM put (same params) | Hull/Haug | 5.5735 | 1e-3 |
| ATM call delta | Haug §2.1 | 0.6368 | 1e-3 |
| Put-call parity | Hull §15.8 | C−P = S−K·e^(-rT) | 1e-9 |
| IV roundtrip | — | σ recovered | 1e-6 |
| Strike-for-delta roundtrip | — | Δ recovered | 1e-6 |
| Black-76, F=X=19, σ=0.28, T=0.75, r=0.10 | Haug §1.1.3, p.6 | 1.7011 | 1e-3 |
| Inverse call: S_T=125k, K=100k, delivery=125k | `deribitfilesascopiedtxt.txt` line 22 | settlement=0.2 BTC | 1e-9 | (independently verified per Pillar 1 §4.6) |

### 13.2 Strategy payoff tests

Every strategy must pass all five boundary points (Section 9.6):

```
test_payoff_zero(S)
test_payoff_below_strike(S < K)
test_payoff_at_strike(S == K)
test_payoff_at_entry_spot(S == S₀)
test_payoff_above_strike(S >> K)
```

### 13.3 Classification integrity tests

```
test_covered_call_legs():        long BTC + short call → COVERED_CALL
test_csp_legs():                 cash + short put → CASH_SECURED_PUT
test_long_btc_short_put_legs():  long BTC + short put → LONG_BTC_PLUS_SHORT_PUT
test_covered_put_legs():         short underlying + short put → COVERED_PUT
test_label_mismatch_flagged():   when business_label ≠ canonical → warning present
```

### 13.4 Provenance integrity tests

```
test_no_observed_label_on_simulated()
test_no_observed_label_on_model_reconstructed()
test_provenance_field_present_on_all_outputs()
```

### 13.5 QuantLib parity

```
test_quantlib_bs_parity:         hypothesis, 50 random draws, max abs diff < 1e-6
test_quantlib_black76_parity:    hypothesis, 50 random draws, max abs diff < 1e-6
```

### 13.6 Waterfall tests (preserved and extended)

```
test_waterfall_mandate_numbers:            (existing — 7 assertions, all passing)
test_waterfall_fee_base_sensitivity:       both reference_notional and executed_volume variants
test_waterfall_spot_sensitivity:           all offsets produce valid arithmetic
```

### 13.7 Configuration tests

```
test_params_schema_validates:    pydantic wrapper rejects malformed params.yaml
test_params_no_hardcode:         no magic numbers in source modules
test_all_values_have_provenance: provenance field set on every ingested value
```

---

## 14. Reporting interfaces

### 14.1 Principle

Reporting is a **downstream consumer** of validated strategy results. The reporting layer must not make strategy recommendations or numerical claims not present in the analysis output.

### 14.2 Chart pack interface

```python
class PayoffChartSpec(BaseModel):
    strategy: Strategy
    spot_range: tuple[float, float]     # (min, max) USD
    n_points: int = 500
    include_premium: bool = True        # Show breakeven adjusted for premium
    highlight_entry_spot: bool = True
    correct_business_label: bool = True  # Flag mislabeled source diagrams

def generate_payoff_chart(spec: PayoffChartSpec) -> bytes:   # PNG bytes
    """A5: matplotlib. Six-chart sequence per Build Plan §5 item 3."""

def generate_cycle_report(backtest: BacktestResult) -> str:  # Markdown
    """Per-cycle premium tracker vs 2.5% cumulative target."""

def generate_waterfall_chart(waterfall: dict) -> bytes:      # PNG bytes
    """Waterfall economics at live spot."""

def generate_stress_reel(results: list[StressScenarioResult]) -> str:  # Markdown
    """Stress scenario replay commentary."""

def generate_demo_pack() -> None:
    """python -m reports.demo → full offline demo < 60s (A5 DoD)."""
```

### 14.3 Report output constraints

- All tables must display provenance column/annotation.
- Where business_label ≠ canonical, emit a warning cell.
- All financial values must include explicit units.
- `TODO(decision_pending: D-N)` markers must render visibly in any table where unresolved decisions affect the number.
- No strategy may be presented as "optimal", "recommended" or "preferred".

---

## 15. Error taxonomy

### 15.1 Error hierarchy

```python
class EngineError(Exception): ...

class ConfigurationError(EngineError): ...          # Malformed params.yaml
class ValidationError(EngineError): ...             # Invariant violation
class PricingError(EngineError): ...                # Root-finding failure, NaN
class DataError(EngineError): ...                   # Missing/corrupt market data
class VenueError(EngineError): ...                  # Unsupported settlement path
class ClassificationError(EngineError): ...         # Cannot derive StrategyKind from legs
class ProvenanceError(EngineError): ...             # Simulated value presented as observed
class SensitivityError(EngineError): ...            # Sensitivity analysis parameter out of range
class ReportingError(EngineError): ...              # Chart generation failure
```

### 15.2 Severity levels

| Level | Meaning | Action |
|-------|---------|--------|
| `FATAL` | Cannot proceed — missing required data or config | Halt pipeline, log, raise |
| `ERROR` | Contract violation (e.g. provenance mislabel, label/classification mismatch) | Log, flag in output, continue with warning |
| `WARNING` | Suspicious result (e.g. PBO > 0.5, negative effective discount) | Log, include in report caveats |
| `INFO` | Normal operational event | Log only |

### 15.3 Warning catalogue

| Code | Condition | Level |
|------|-----------|-------|
| W-CLASSIFY-MISMATCH | business_label ≠ canonical StrategyKind | ERROR |
| W-PROVENANCE-MISLABEL | Model-reconstructed value without provenance tag | ERROR |
| W-NO-OBSERVED-CHAINS | Backtest cycle using DVOL proxy | WARNING |
| W-DECISION-PENDING | Output affected by unresolved human decision | WARNING |
| W-PBO-HIGH | PBO > 0.5 on backtest comparison | WARNING |
| W-NEGATIVE-DISCOUNT | Net effective cost > reference spot | WARNING |
| W-UNCALIBRATED-IMPACT | Impact model using assumed parameters | WARNING |
| W-BREAKEVEN-NOT-FOUND | Breakeven solver returned empty | WARNING |

---

## 16. Configuration schema

### 16.1 Pydantic wrapper for params.yaml

```python
from pydantic import BaseModel, Field, field_validator

class EngineConfig(BaseModel):
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
    risk_free_rate_pct: float = Field(ge=0, le=100)
    tranche_btc: list[int] = Field(min_length=2, max_length=2)
    expiry_ladder_dte: list[int] = Field(min_length=1)

    # DVOL-triggered execution rules (Build Plan §7) — TODO: add after decision D-8
    sell_when_dvol_above: float | None = None       # e.g. 55.0
    stand_down_on_breakout: bool | None = None

    # Unresolved decisions — carried as explicit markers
    fee_base: str = Field(default="reference_notional")  # TODO(decision_pending: D-1)
    reference_spot_source: str = "config"                 # TODO(decision_pending: D-2)
    primary_venue: str = "deribit"                        # TODO(decision_pending: D-3)

    @field_validator("call_delta_target")
    @classmethod
    def deltas_in_0_1_range(cls, v):
        assert 0.0 < v[0] < 1.0, "Deltas must be in (0, 1)"
        assert 0.0 < v[1] < 1.0, "Deltas must be in (0, 1)"
        assert v[0] <= v[1], "First delta must be ≤ second"
        return v

    @field_validator("risk_free_rate_pct")
    @classmethod
    def rate_sane(cls, v):
        assert -1.0 <= v <= 50.0, "Risk-free rate out of plausible range"
        return v

    def to_decimal_dict(self) -> dict:
        """Return dict with percentage values divided by 100 for pricing functions."""
        return {
            k: v / 100 if k.endswith("_pct") and isinstance(v, (int, float)) else v
            for k, v in self.model_dump().items()
        }
```

### 16.2 Validation at config boundary

`EngineConfig` validates `params.yaml` at ingestion. Pure pricing functions never read `params.yaml` directly — the application layer injects decimal values (AC-4).

```python
def load_validated_config(path: pathlib.Path) -> EngineConfig:
    """Returns validated config. Raises ConfigurationError on any violation."""
```

---

## 17. A1–A6 ownership and dependency map

### 17.1 Ownership matrix

| Agent | Module(s) | Primary source | Branch |
|-------|-----------|---------------|--------|
| A1 | `pricing/black_scholes.py` (extend), `pricing/inverse.py`, `pricing/black76.py`, `pricing/grid.py` | `deribitfilesascopiedtxt.txt` §1–274, Hull/Haug text caches | `feat/pricing` |
| A2 | `vol/dvol_feed.py` (harden), `vol/surface.py`, `vol/history.py`, `vol/garch.py`, `data/` | Massive docs, Deribit API, CDD CSVs | `feat/vol` |
| A3 | `scenarios/montecarlo.py`, `scenarios/backtest.py`, `scenarios/stress.py`, `strategies/payoffs.py` | A1 interfaces + A2 fixtures + McNeil/Bailey | `feat/scenarios` |
| A4 | `execution/impact.py`, `execution/tranches.py`, `execution/waterfall.py` (extend) | Kissell/Harris/Sinclair text caches, Deribit Block RFQ docs | `feat/execution` |
| A5 | `reports/charts.py`, `reports/cycle_report.py`, `reports/demo.py` | A1–A4 outputs | `feat/reports` |
| A6 | `contracts.md`, `pyproject.toml`, CI, Pydantic models, merge coordination, cross-validation | All of the above | `main` (merge owner) |

### 17.2 Dependency graph

```
contracts.md (A6 freeze, Day 0)
     │
     ├── A1 (pricing) ───────────┐
     ├── A2 (data/vol) ──────────┤
     └── A4 (execution/impact) ──┤
                                  │
                                  ▼
                            A3 (scenarios) ──→ A5 (reports) ──→ A6 cross-validation
```

### 17.3 Required brief corrections before Phase 1

| Agent | Correction | Source authority |
|-------|-----------|------------------|
| A1 | Replace `price_in_BTC = USD_price / index` with re-derivation from Deribit spec §"Inverse Options" | authoritative_corrections.md §4, Pillar 1 C-1 |
| A2 | Add Massive as primary spot source; CDD as fallback | mandate_sanitized.md §"Data rules", AC-5 §5 |
| A3 | Add VaR, ES, PBO, OOS protocol, transaction costs, GARCH diagnostics | Pillar 2 C-1, C-2, C-3, C-4 |
| A4 | Add I-Star equations, timing risk, benchmark selection, voice-broker RFQ workflow | Pillar 3 §6.2 |

---

## 18. Phase-0 acceptance criteria

Per reconciled audit §6 and Build Plan §3:

| # | Criterion | Owner | Source |
|---|-----------|-------|--------|
| P0-1 | This `contracts.md` is frozen | A6 | Build Plan §3 |
| P0-2 | CI operational (pytest + mypy + ruff) | A6 | P0-2 |
| P0-3 | First Deribit fixtures recorded and replayable | A2 | P0-3 |
| P0-4 | `params.yaml` wrapped with `EngineConfig` pydantic schema | A6 | P0-4 |
| P0-5 | `waterfall.py` typed; file-handle leak fixed | A6/A4 | P0-5 |
| P0-6 | `pricing/` wired to validated config for `risk_free_rate_pct` | A1 | P0-6 |
| P0-7 | Branch strategy documented; AGENTS.md updated ("Three commits on main") | A6 | P0-7, Pillar 5 C-1 |
| P0-8 | Anonymisation CI grep active (no wallet/ID/API-key in repo) | A6 | P0-8 |
| P0-9 | `Provenance` enum frozen (Section 4.1) | A6 | P0-9 |
| P0-10 | Agent briefs A1–A4 corrected per Section 17.3 | A6 | Pillar 5 C-2, C-3 |
| P0-11 | `pyproject.toml` created with mypy/ruff config | A6 | AGENTS.md §"Gotchas" |
| P0-12 | All 9 existing tests pass | All | Sprint 0 baseline |

---

## 19. Unresolved human decisions

These are not source gaps — they require explicit human decisions. They are carried as `TODO(decision_pending)` markers throughout the engine until resolved:

| # | Decision | Impact | Source-of-record | Owner |
|---|----------|--------|-----------------|-------|
| D-1 | Fee base: reference notional vs executed (discounted) notional | $243,750 swing on $9.75M fee | Build Plan §7, reconciled audit §5 | Mandate issuer / Francisco |
| D-2 | Reference spot price source (live Deribit index vs Massive vs blended) | Affects all notional, fee BTC-equivalent, net discount | `params.yaml` reference_spot_usd | Mandate issuer |
| D-3 | Primary venue selection (Deribit, CME, OTC, multi-venue) | Determines settlement mechanics, margin, instrument-type modelling | Build Plan §4 | Mandate issuer |
| D-4 | Put-sleeve consent: is Long BTC + Short Put in scope for live transaction? | Determines A3 backtest paths, A4 tranche scheduler, A5 chart pack | mandate_sanitized.md | Mandate issuer |
| D-5 | Massive vs CryptoDataDownload as primary v1 historical source | A2 ingestion brief self-contradictory | AC-5 §5, mandate_sanitized.md | Mandate issuer (resolved by AC-5 — Massive primary, but brief not corrected) |
| D-6 | Waterfall overlay target label: "target" vs "forecast" | Client-facing report labelling | Build Plan §7 | Mandate issuer |
| D-7 | Put-sleeve scope for first client presentation | Determines A5 deliverables | Build Plan §5 | Mandate issuer / Francisco |
| D-8 | DVOL-triggered execution rules: `sell_when_dvol_above`, `stand_down_on_breakout` values | Vol-opportunistic policy parameters | Build Plan §7 | A6 (to set defaults; final approval from mandate issuer) |
| D-9 | Hedge strategy: delta hedging, static overlay, or no hedging | Backtest hedge-cost line item | mandate_sanitized.md §"Required analysis" | Mandate issuer |

---

## 20. Source traceability matrix

Every interface, model and invariant in this document is traceable to a source file and section.

| Contract Section | Interface/Model | Source document | Section/Line |
|------------------|-----------------|-----------------|--------------|
| 2.2 | `StrategyKind` enum | AGENTS.md | §"Strategy classification" lines 53–67 |
| 2.2 | `COVERED_PUT` requires short underlying + short put | AGENTS.md | line 61 |
| 3.1 | Vega/theta conventions (÷100, ÷365) | AGENTS.md / pricing/black_scholes.py | line 19-20 / docstring |
| 3.1 | Decimal rates/vols, T in years | AGENTS.md | line 24 |
| 3.3 | Deribit inverse settlement `(delivery_price − strike) / delivery_price` | `deribitfilesascopiedtxt.txt` | lines 1–199 |
| 3.3 | Delivery price = TWAP 07:30–08:00 UTC | `deribitfilesascopiedtxt.txt` | line 187 |
| 3.3 | Contract multiplier = 1, exercise = European/cash | `deribitfilesascopiedtxt.txt` | lines 135, 191 |
| 3.3 | Trading fee: MIN(0.0003 BTC, 0.125 × premium) × contracts | `deribitfilesascopiedtxt.txt` | lines 3572–3574 |
| 3.3 | Delivery fee: 0.015%, cap 12.5% | `deribitfilesascopiedtxt.txt` | line 3755 |
| 3.4 | CME 5 BTC multiplier, BRR settlement | `_text_cache/.../350A.txt` | 131 lines |
| 3.4 | CME weekly fix VWAP 0330-0400 London | `_text_cache/.../350A.txt` | — |
| 4.1 | `Provenance.MODEL_RECONSTRUCTED` | authoritative_corrections.md | §5 |
| 5.1 | Separate settlement fields (AC-1) | authoritative_corrections.md | §1 |
| 5.1 | `SettlementMechanism`, `SettlementCurrency` enums | authoritative_corrections.md | §1 |
| 7.1 | `OptionQuote` frozen dataclass preservation (AC-3, AC-6) | authoritative_corrections.md | §3 |
| 7.3 | Pure function signatures (AC-4) | authoritative_corrections.md | §2 |
| 7.3 | Inverse-BTC function derived from venue docs, not reconciled audit (AC-4) | authoritative_corrections.md | §4 |
| 9.2 | `Strategy.canonical` derived from legs only | AGENTS.md | lines 55–57 |
| 9.6 | Payoff test at 5 boundary points | AGENTS.md | lines 64–65 |
| 10.1 | Rolling/closing interfaces | mandate_sanitized.md | §"Required analysis" |
| 11.2 | `MonteCarloResult` VaR, ES fields | McNeil et al. Ch.9–11 | Verified Pillar 2 §4.1 |
| 11.4 | `OOSValidationResult` PBO field | Bailey et al. (2015) | Verified Pillar 2 §4.2 |
| 11.4 | CSCV S=16, N≥100 | Bailey et al. §4 | Verified Pillar 2 §4.2 |
| 12.1 | I-Star impact model eq. 4.6–4.7 | Kissell §4, `_text_cache/Textbooks/Kissell.txt` | Verified Pillar 3 §4.1 |
| 12.3 | Tranche ladder DTE [30, 37, 44] | config/params.yaml | line 15 |
| 13.1 | Black-76 golden vector F=X=19, c=1.7011 | Haug §1.1.3 | Verified Pillar 1 §4.3 |
| 13.1 | Inverse call example 0.2 BTC | `deribitfilesascopiedtxt.txt` | lines 16–24 |
| 15.1 | Error taxonomy | AGENTS.md conventions | §"Gotchas" |
| 16.1 | Pydantic `EngineConfig` | authoritative_corrections.md §3 | — |
| 16.1 | `sell_when_dvol_above`, `stand_down_on_breakout` | Build Plan §7 | — |
| 17.3 | A1 brief correction (inverse-BTC derivation) | authoritative_corrections.md §4, Pillar 1 C-1 | — |
| 17.3 | A2 brief correction (Massive primary) | mandate_sanitized.md §"Data rules", AC-5 | — |
| 17.3 | A3 brief enrichment (VaR/ES/PBO, OOS, GARCH diag) | Pillar 2 C-1 through C-4 | — |
| 17.3 | A4 brief enrichment (I-Star, timing risk, block RFQ) | Pillar 3 §6.2 | — |
| 18 | Phase-0 acceptance criteria P0-1 through P0-12 | Reconciled audit §6, Build Plan §3 | — |
| 19 | Unresolved decisions D-1 through D-9 | Reconciled audit §5, Build Plan §6–7 | — |

---

## Document version

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 0.1 | 2026-07-28 | System (architecture pass) | Initial source-backed draft. All sections. |
