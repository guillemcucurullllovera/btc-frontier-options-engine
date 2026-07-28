# BTC Engine Contracts — SOURCE-BACKED FREEZE CANDIDATE

**Status:** Phase-0 freeze candidate — all MiniMax review §§8–9 corrections applied.  
**Date:** 2026-07-28  
**Supersedes:** `docs/architecture/contracts_draft.md` v0.1.  
**Authority hierarchy applied:** `authoritative_corrections.md` → venue docs → `ceo_strategy_research_mandate.md` → `AGENTS.md` → `mandate_sanitized.md` → `BTC_30K_Build_Plan_Parallel_Agents.md` → pillar studies.  
**Next gate:** Phase-0 freeze acceptance (Section 19).

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
| 7 | `final_gap_audit_minimax.md` | `docs/reports/reference_study/final_gap_audit_minimax.md` |
| 8 | DeepSeek pillar studies | `docs/reports/reference_study/pillar_1..5_*_deepseek.md` — evidence only, not executable specification |
| 9 | Textbooks (Hull, Haug, Gatheral, McNeil, Kissell, Harris, Sinclair, Bailey) | `_text_cache/Textbooks/` |

**Override rule (from `authoritative_corrections.md` §6):** Where an audit conflicts with this document, this document prevails. Where this document is silent, current official venue documentation prevails over textbooks.

### 1.3 Binding constraints

- Core pricing functions remain **pure and parameter-driven** (AC-2, AC-4).
- The existing `OptionQuote` frozen dataclass is **preserved** unless Section 7 explicitly approves an extension (AC-3, AC-6).
- Pydantic is used at **configuration, ingestion, persistence and external-reporting boundaries** only (AC-3). Pure numerical internals use frozen typed dataclasses.
- Strategy classification is derived **strictly from position legs** (AGENTS.md §"Strategy classification"). Source labels are preserved for comparison but never treated as canonical.
- Economic payoff, venue settlement and discretionary inventory actions are kept **separate** (AC-1, AC-8).
- Settlement mechanism, settlement currency, venue and product are **separate fields** (AC-1).
- Inverse-BTC formulas from the reconciled audit §10.8 are **not implemented directly** (AC-4). Inverse settlement is re-derived from official Deribit specifications with explicit units, multiplier, delivery price, numeraire and premium convention.
- The hypotheses listed in `ceo_strategy_research_mandate.md` §"Hypotheses" — 10–15 delta, 30–45 DTE, 15–20% OTM, ~3% premium per cycle, delta as assignment-probability estimate, selling only when IV is elevated, breakout stand-down, covered-call superiority — are treated as **testable claims**, not approved policies. Their presence in `config/params.yaml` as default ranges does not constitute endorsement.
- The engine must report when these ranges fail the implied premium/yield targets before any "optimal structure" is presented.
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
| **Quantity** | Number of contracts, unsigned, ≥ 0. Economic effect derives from `side`, not sign-multiplied quantity. Positive `quantity` with `side=LONG` means the holder receives the economic benefit; with `side=SHORT` means the writer has the obligation. |
| **Entry premium** | Premium received (short) or paid (long) per contract at leg initiation, in the quoted currency of the option's settlement spec. |
| **Underlying leg** | For spot/futures legs the instrument identity is `(venue, product, side, quantity, entry_price)`. |

### 2.2 Canonical strategy classification

Classification is derived **algorithmically** from leg composition. The engine must never classify from titles, filenames, chart headings or source labels (AGENTS.md lines 55–57).

```python
from enum import StrEnum
from dataclasses import dataclass

class Leg: ...

class StrategyKind(StrEnum):
    """Canonical strategy classification — derived purely from position legs.
    
    COVERED_PUT requires short underlying + short put (AGENTS.md line 61).
    It must not be assigned to long BTC + short put.
    """
    COVERED_CALL = "covered_call"            # long underlying + short call
    CASH_SECURED_PUT = "cash_secured_put"    # cash collateral + short put
    LONG_BTC_PLUS_SHORT_PUT = "long_btc_plus_short_put"  # long underlying + short put
    COVERED_PUT = "covered_put"              # short underlying + short put (NOT long BTC + short put)
    PROTECTIVE_PUT = "protective_put"        # long underlying + long put
    CALL_SPREAD = "call_spread"              # long/short calls at different strikes
    COLLAR = "collar"                        # long underlying + short call + long put
    PARTIAL_OVERLAY = "partial_overlay"      # long underlying + short call on fraction of position
    NAKED_CALL = "naked_call"                # short call, no underlying
    NAKED_PUT = "naked_put"                  # short put, no underlying
    BESPOKE = "bespoke"                      # any unrecognised combination


def classify(legs: list[Leg]) -> StrategyKind:
    """Derive the canonical StrategyKind from position legs only.
    Never classify from titles, filenames or source labels.
    """
    ...
```

### 2.3 Required dual-preservation rule

When the engine's algorithmic classification differs from a source business label:
- Store both as `canonical: StrategyKind` and `business_label: str`.
- In all reports emit both, with a warning when they differ.
- Flag the conflict as an `ERROR` level reporting event (Section 16).

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
| Delta | dPrice/dSpot | Call ∈ [0,1], Put ∈ [−1,0] | Haug §2.1 |
| Gamma | d²Price/dSpot² | Per 1 USD move | Hull §19 |
| Vega | dPrice/dσ | Per 1.00 (100%) absolute σ change; ÷100 for per-vol-point | docstring line 19 |
| Theta | dPrice/dT, annualised | Negative for long; ÷365 for per-day | docstring line 20 |
| Notional | USD | S × quantity | `waterfall.py` line 19 |
| Fees | % of reference notional | Configurable | `params.yaml` |

### 3.2 Sign convention — holder/writer explicit

- **Buyer / holder / long position:** positive quantity with `side=LONG`. Premium paid (debit from holder). Delta positive for calls (gains with rising spot). At expiry the **gross settlement cash flow is paid to the holder**.
- **Writer / seller / short position:** positive quantity with `side=SHORT`. Premium received (credit to writer). Delta negative for short calls (loses with rising spot). At expiry the **gross settlement cash flow is the negation of the holder's settlement** — i.e., the writer pays to the holder.
- **Strategy P&L formula:**
  ```
  strategy_payoff(strategy, S_T) = 
      Σ[underlying legs] (quantity × (S_T − entry_spot))
    + Σ[option legs, side=LONG] (quantity × (settlement_holder − entry_premium))
    + Σ[option legs, side=SHORT] (quantity × (−settlement_holder + entry_premium))
  ```
  where `settlement_holder` is the gross settlement amount the holder would receive from the contract at expiry (per contract, in USD or BTC as appropriate), and `entry_premium` is per-contract premium (positive = paid by holder, negative for the holder = received by holder).
- **P&L:** positive = gain, negative = loss, all in base currency (USD). BTC-denominated P&L is multiplied by the delivery price for USD equivalence.
- The engine must never apply the holder-settlement formula directly to a short writer position without negating the cash flow and adding the entry premium.

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

Where `Amount` = number of contracts and `OptionPrice` = per-contract BTC premium.

**Inverse call gross settlement to the LONG HOLDER (BTC):**

The LONG holder of one inverse call contract receives this BTC amount at expiry:
```
settlement_inverse_call_holder(delivery_price, strike) = max(delivery_price − strike, 0) / delivery_price
```

**Inverse put gross settlement to the LONG HOLDER (BTC):**

The LONG holder of one inverse put contract receives this BTC amount at expiry:
```
settlement_inverse_put_holder(delivery_price, strike) = max(strike − delivery_price, 0) / delivery_price
```

**Writer (SHORT) cash flow:** The SHORT inverse option writer pays the negation of the holder settlement amount to the holder at expiry. The strategy P&L for a short inverse option must compute `−(holder_settlement_btc) + entry_premium_btc_received`.

**Gross settlement amount paid by the SHORT WRITER to the LONG HOLDER (USD-equivalent)** — for comparison purposes only; actual settlement is in BTC:
```
gross_holder_usd = settlement_holder_btc × delivery_price
                 = max(delivery_price − strike, 0)   // for call
                 = max(strike − delivery_price, 0)   // for put
```

This USD-equivalent is the **gross holder payoff, not the position P&L**. It does NOT include the entry premium. The short-call writer's strategy P&L is `premium_received_usd − gross_holder_usd`. The sign is positive for the holder, negative for the writer.

### 3.4 CME Bitcoin options on futures — units and conventions

**Source:** `_text_cache/BTC_pending links/350A.txt` (131 lines: CME Options on Bitcoin Futures).

| Field | Value |
|-------|-------|
| Underlying | 1 CME Bitcoin Futures (5 BTC) |
| Contract multiplier | 5 BTC |
| Settlement currency | USD |
| Minimum tick | 5 index points ($25) — 1 index point = $5 for the 5-BTC contract |
| Increment for ≤25 pt premiums | 1 index point |
| Exercise style | European, auto-exercise ITM |
| Settlement at expiry | **Auto-exercise into a long (call) or short (put) CME Bitcoin Futures contract at the strike.** That futures contract then cash-settles to USD via the BRR/BRRNY/BVX fixing on the last trade date. There is no physical BTC delivery. |
| Final settlement price (monthly) | BRR (CME CF Bitcoin Reference Rate), 4 p.m. London |
| Weekly options fix | VWAP 03:30–03:59:59 p.m. London |

### 3.5 Timestamps

Pydantic `datetime` fields, timezone-aware UTC. Serialised to ISO-8601 with `Z` suffix when written to JSON/Parquet (AGENTS.md line 51).

---

## 4. Provenance and source models

### 4.1 Provenance enum

```python
from enum import StrEnum

class Provenance(StrEnum):
    OBSERVED = "observed"              # Direct market observation (e.g. Deribit mark_iv, Massive OHLC)
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
| Deribit public API | REST endpoints (`get_index_price`, `get_instruments`, `get_book_summary_by_currency`) | `origin=deribit_public_api` |
| Massive | Historical BTC spot (primary) | `origin=massive` |
| CryptoDataDownload | Historical DVOL + option OHLCV (explicitly-labelled fallback only) | `origin=cryptodatadownload` |
| CME | BTC futures settlement (BRR), option specs | `origin=cme` |
| CME public API | `get_product_info`, `get_trades`, `get_settlement` endpoints | `origin=cme_public_api` |
| Hull/Haug | Textbook golden vectors | `origin=textbook` |
| Parameters | Business config (validated `EngineConfig`) | `origin=business_config` |

### 4.3 Provenance tag on every datum

Every `float` or aggregated result in the engine must carry a provenance tag in its container (e.g. Pydantic model fields `provenance: Provenance`, `origin: str | None = None`). Configuration-layer Pydantic models enforce that no value is ingested without provenance assignment.

---

## 5. Venue, product, exercise and settlement models

### 5.1 Settlement decomposition (per AC-1)

```python
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, Field

class SettlementMechanism(StrEnum):
    CASH = "cash"                                    # Cash-settled at expiry (Deribit inverse)
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
| OTC | otc_option | physical_underlying or cash | USD or BTC | Negotiated | Negotiated (set per-trade; no default) | Negotiated | ISDA DA Definitions + whitepaper §4–5 |

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
    interest_rate: float    # decimal, continuous compounding (consistent with §3.1)
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
    mark_iv_provenance: Provenance      # OBSERVED for Deribit book_summary; MODEL_RECONSTRUCTED for CDD/VWAP-derived
    provenance: Provenance              # OBSERVED or MODEL_RECONSTRUCTED
    origin: str                         # "cryptodatadownload" or "deribit" or "model_reconstructed"
```

### 6.4 Fixture recording

All live API responses must be cachable and replayable. Fixtures stored under `tests/fixtures/` in Parquet format with a SHA-256 manifest. The manifest schema:

```python
class FixtureManifestEntry(BaseModel):
    path: str              # Relative path under tests/fixtures/
    sha256: str            # Hex digest
    retrieval_date: datetime
    venue: str             # "deribit", "massive", etc.
    endpoint: str          # e.g. "get_book_summary_by_currency"
    record_count: int
```

### 6.5 Missing historical options rule (AC-5 §5)

Where observed historical option chains are missing:
- Premium is reconstructed from DVOL + spot using Black-Scholes/Black-76 **at-the-money at the relevant tenor**. DVOL is a single index (annualised 30-day), not a term structure; the reconstruction is ATM-only and ignores skew. Skew is approximated flat; any ITM/touch probability or strike-specific payoff derived from reconstructed premiums must not be presented as observed.
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
    premium_quoted: float      # In the option's quoted currency per the contract spec:
                               # BTC for Deribit inverse, USDC for Deribit linear,
                               # USD for CME, BTC or USD for OTC
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
# The pricing formula uses risk-neutral valuation. With zero BTC convenience yield,
# the forward is F = S · exp(r · T). When q != 0 (BTC yield/borrow rate),
# F = S · exp((r − q) · T). The functions accept 'q' (convenience yield, decimal, optional, default 0.0)
# and derive forward internally.
def price_inverse_btc(S: float, K: float, r: float, sigma: float, T: float, kind: str = "call", q: float = 0.0) -> float:
    """Inverse-BTC option pricer re-derived from Deribit official spec.
    
    Forward: F = S · exp((r − q) · T). The option pays (F − K) / F at expiry in BTC for calls.
    Risk-neutral valuation: price_BTC = exp(−rT) · E[max(F_T − K, 0) / F_T].
    
    For zero carry (q = 0): F = S · exp(rT). Under Black's model,
    price_BTC_call = exp(−rT) · [N(d1') · Φ(d1') − K/F · N(d2') · Φ(d2')]
    where d1' = (ln(F / K) + σ²T/2) / (σ√T), d2' = d1' − σ√T,
    and adjustments account for quanto-like delivery-price denominator.
    
    Cross-check against Deribit spec example at line 22:
    S_T=125k, K=100k, delivery=125k → holder settlement = 0.2 BTC.
    """
    ...

def greeks_inverse_btc(S: float, K: float, r: float, sigma: float, T: float, kind: str = "call", q: float = 0.0) -> OptionQuote: ...

# Gross settlement to the LONG HOLDER at expiry (from Deribit spec lines 1–199)
# These are SETTLEMENT AMOUNTS, not generic payoffs.
def settlement_inverse_call_holder(delivery_price: float, strike: float) -> float:
    """Gross BTC settlement per 1 contract to the long call holder:
       max(delivery_price − strike, 0) / delivery_price.
       Source: deribitfilesascopiedtxt.txt §'Inverse Options' lines 1–199.
       For the SHORT WRITER, the cash flow is the NEGATION of this amount."""
    ...

def settlement_inverse_put_holder(delivery_price: float, strike: float) -> float:
    """Gross BTC settlement per 1 contract to the long put holder:
       max(strike − delivery_price, 0) / delivery_price.
       For the SHORT WRITER, the cash flow is the NEGATION of this amount."""
    ...

# Standard BS payoff (USD)
def payoff_bs_call(S_T: float, K: float) -> float:
    """max(S_T − K, 0) — gross settlement to the long call holder in USD."""
    ...

def payoff_bs_put(S_T: float, K: float) -> float:
    """max(K − S_T, 0) — gross settlement to the long put holder in USD."""
    ...
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
# Test interfaces (no implementation body in contracts)
def test_quantlib_bs_parity():
    """hypothesis-based: max absolute difference < 1e-6 on 50 random (S,K,r,σ,T) draws."""

def test_quantlib_black76_parity():
    """hypothesis-based: max absolute difference < 1e-4 on 50 random (F,X,r,σ,T) draws.
    Tolerance 1e-4 for Black-76 accounts for extreme vol/T combos — documented choice."""
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
    method: Literal["spline", "svi", "ssvi", "raw"]
    fit_rmse: float | None

def fit_surface(book_summaries: list[BookSummary], method: str = "spline") -> VolSurface: ...
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
    interpolation: Literal["flat", "linear", "log_linear", "cubic"] = "linear"
```

---

## 9. Position-leg, strategy, payoff, MTM and breakeven interfaces

### 9.1 Position leg

```python
from pydantic import BaseModel, Field
from typing import Literal

class Leg(BaseModel):
    """One leg of a strategy. Quantity is unsigned (≥ 0); economic effect from side."""
    instrument: str             # e.g. "BTC-spot", "BTC-27SEP24-65000-C"
    venue: Venue
    product: str
    side: Literal["LONG", "SHORT"]
    quantity: float = Field(ge=0)   # Unsigned; economic effect from side
    entry_premium: float            # Per-contract premium PAID (positive) or RECEIVED (negative),
                                    # in the option's quoted currency per contract spec
    settlement: SettlementSpec
    # For underlying legs:
    entry_spot: float | None = None  # Spot price at leg initiation
```

### 9.2 Strategy

```python
class DecisionRef(BaseModel):
    """Structured reference to an unresolved decision."""
    code: str          # e.g. "D-1"
    owner: str         # e.g. "Mandate issuer"
    impact: str        # e.g. "$243,750 swing on $9.75M fee"

class Strategy(BaseModel):
    strategy_id: str
    business_label: str                 # Source label from mandate/client (may differ from canonical)
    canonical: StrategyKind             # Algorithmically derived from legs (Section 2.2)
    legs: list[Leg]
    classification_warning: str | None  # Non-None if business_label ≠ canonical
    pending_decisions: list[DecisionRef] = Field(default_factory=list)
    structural_max_loss: float           # Maximum possible loss under worst-case spot movement (USD)
```

### 9.3 Payoff

```python
@dataclass(frozen=True)
class PayoffPoint:
    S_T: float                 # Underlying spot at evaluation (USD)
    payoff_usd: float          # Total strategy GROSS payoff (USD) — settlement amounts ± premiums
    pnl_usd: float             # Net P&L: payoff_usd − total premiums paid (or + received)
    settlement_btc: float      # BTC settlement under venue rules (NaN if not BTC-settled)

def strategy_payoff(strategy: Strategy, S_T: float) -> PayoffPoint:
    """Compute payoff per the holder/writer sign convention in §3.2.
    strategy_payoff = Σ underlying_legs × (S_T − entry_spot)
                    + Σ option_legs(LONG) × (settlement_holder − entry_premium)
                    + Σ option_legs(SHORT) × (−settlement_holder + entry_premium)
    For inverse-BTC legs, settlement_holder is in BTC; converted to USD via delivery_price.
    """
    ...

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
    rate_used: float          # Discount rate (decimal, continuous)
    forward_used: float | None  # Forward price for the MTM tenor (USD)
    discount_factor: float | None  # exp(−rate_used × T)
    numeraire: Literal["USD", "BTC", "USDC"]  # Numeraire of the MTM valuation

def mtm_at(strategy: Strategy, spot: float, surface: VolSurface, curve: DiscountCurve, t: float) -> MtmPoint: ...
```

### 9.5 Breakeven

```python
def breakeven(strategy: Strategy) -> list[float]:
    """Return all spot prices (USD) where strategy P&L crosses zero.
    Unit is USD (the standard payoff numeraire) for USD-settled legs.
    For inverse-BTC legs, an additional per-leg `breakeven_btc: list[float]` is populated.
    Ordering: ascending. Empty list if no crossing.
    Multi-leg behaviour: covered call → 1 BE; collar → up to 2 BE;
    long-BTC + short-put → 1 BE above K and conditional BE below K.
    """
```

### 9.6 Validation invariant — payoff at boundary points

Per AGENTS.md lines 64–65, every strategy payoff must be tested at these concrete points:

| BTC price | Rationale | Test name |
|-----------|-----------|-----------|
| 0 | Maximum downside | `test_payoff_zero` |
| K / 2 (half strike) | Below strike, midpoint | `test_payoff_half_strike` |
| K (at strike) | Kink point | `test_payoff_at_strike` |
| S₀ (initial spot) | No-change scenario | `test_payoff_at_entry_spot` |
| 2 · K (double strike) | Materially above strike, slope check | `test_payoff_double_strike` |
| S₀ + P (breakeven for covered call) | Covered-call BE where P is premium received | `test_payoff_at_breakeven_covered_call` |

The test harness must verify each strategy at all applicable points and flag any discrepancy between calculated payoff and any source diagram annotation.

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
    provenance: Provenance = Provenance.CALCULATED  # Provenance on every settlement result
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
    # Hedge cost fields (C-7, MR-4):
    hedge_cost_usd: float = 0.0
    hedge_cost_btc: float = 0.0
    hedge_strategy: Literal["none", "static", "delta"] = "none"
    pending_decision_refs: list[str] = Field(default_factory=list)  # e.g. ["D-1", "D-9"]


class EffectiveAcquisitionCost(BaseModel):
    """Decomposed effective acquisition cost with provenance per component (H-6)."""
    per_btc_usd: float
    per_btc_btc: float
    premium_component_usd: float   # Total premium received (negative = credit)
    premium_provenance: Provenance
    fee_component_usd: float
    fee_provenance: Provenance
    seller_discount_component_usd: float
    seller_discount_provenance: Provenance
    impact_component_usd: float
    impact_provenance: Provenance
    provenance: Provenance = Provenance.CALCULATED
    # Formula: effective_per_btc_usd = (notional_usd + total_fees_usd
    #   − total_premium_received_usd − seller_discount_usd + total_impact_cost_usd) / btc_quantity


class BacktestResult(BaseModel):
    strategy: Strategy
    start_date: datetime
    end_date: datetime
    cycles: list[BacktestCycleResult]
    total_pnl_btc: float
    total_pnl_pct: float
    effective_acquisition_cost: EffectiveAcquisitionCost
    itm_frequency: float                # Fraction of cycles that finished ITM
    touch_frequency: float              # Fraction of cycles where spot touched strike
    max_drawdown_pct: float
    sharpe_ratio: float | None
    delta_vs_assignment_frequency: list[float] = Field(default_factory=list)
    # Per-cycle: delta_at_entry vs realised_assignment (0/1). MR-7.
    oos_window: tuple[datetime, datetime] | None  # If OOS validation performed
    pending_decision_refs: list[str] = Field(default_factory=list)
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
    pnl_unit: Literal["USD", "BTC"] = "USD"
    path_provenance: Provenance = Provenance.SIMULATED
    itm_probability: float                 # Fraction of paths ITM at expiry
    touch_probability: float               # Fraction touching strike during life
    var_95_pct: float                      # Value-at-Risk (95%)
    var_99_pct: float                      # Value-at-Risk (99%)
    es_975_pct: float                      # Expected Shortfall (97.5%)
    es_99_pct: float                       # Expected Shortfall (99%)
    expected_pnl: float
    expected_premium_pct: float
    # Hedge cost fields (C-7, MR-4):
    hedge_cost_mean_usd: float = 0.0
    hedge_cost_mean_btc: float = 0.0
    hedge_strategy: Literal["none", "static", "delta"] = "none"
    pending_decision_refs: list[str] = Field(default_factory=list)
```

### 11.3 Stress test result

```python
class StressScenarioResult(BaseModel):
    scenario_name: str                     # e.g. "2025_breakout_to_126k", "dvol_35_to_65_shock"
    description: str
    shock_type: Literal["instantaneous", "replay", "regime_shift"]
    start_spot: float
    end_spot: float
    path: list[float] | None               # Spot path (None for instantaneous shock)
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
    cscv_s: int = Field(ge=8, le=64, default=16)   # S parameter per Bailey et al. recommendation
    cscv_n: int = Field(ge=100)                     # N ≥ 100 per Bailey et al. guideline (H-14)
```

### 11.5 Regime analysis result

```python
from enum import StrEnum

class RegimeLabel(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    SIDEWAYS = "sideways"

class RegimeAnalysisResult(BaseModel):
    regime_name: str                       # e.g. "bull_2023_2024", "bear_2022", "volatile_2025"
    regime_label: RegimeLabel
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
    # Component-level provenance (H-13):
    i_star_bp: float                   # Instantaneous impact (Kissell eq. 4.6)
    i_star_bp_provenance: Provenance = Provenance.ASSUMED  # Uncalibrated BTC parameters
    market_impact_bp: float            # Total impact (Kissell eq. 4.7)
    market_impact_bp_provenance: Provenance = Provenance.ASSUMED
    temporary_impact_bp: float
    permanent_impact_bp: float
    square_root_eta: float             # Empirical square-root parameter (Sinclair §6)
    iv_giveup_vol_pts: float           # Per-clip IV give-up (0.5–2.0 default, uncalibrated)
    iv_giveup_vol_pts_provenance: Provenance = Provenance.ASSUMED
    # Aggregate provenance is a derived field:
    provenance: Provenance | None = None  # Populated at aggregation time

class KissellConfig(BaseModel):
    """I-Star model parameters (Kissell §4, eq. 4.6–4.7)."""
    order_size_btc: float
    adv_btc: float
    volatility: float
    a1: float                          # Scale coefficient
    a2: float                          # Size exponent
    a3: float                          # Volatility exponent
    b1: float                          # Temporary/permanent split
    a4: float                          # Participation-rate exponent
    pov: float = 0.10                  # Default participation rate 10%

def estimate_impact(config: KissellConfig) -> ImpactEstimate:
    """I-Star model (Kissell §4, eq. 4.6–4.7). Source: _text_cache/Textbooks/Kissell.txt
       I*_bp = a1 * (Q/ADV)^a2 * σ^a3
       MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
    """
```

### 12.2 Fee model

```python
class FeeBreakdown(BaseModel):
    asym_fee_usd: float                # Asymmetrica 0.5% on reference notional (configurable)
    asym_fee_btc_equiv: float
    venue_trading_fee_btc: float       # Deribit: MIN(0.0003, 0.125 * premium) * contracts (line 3574)
    venue_delivery_fee_btc: float      # Deribit: 0.015%, cap 12.5% (line 3755)
    block_trade_fee_btc: float         # Deribit block trade
    block_trade_fee_source: Literal["standard_block", "block_rfq", "voice_broker"] = "standard_block"
    # Different fee schedules exist on Deribit for standard block, Block RFQ, and Voice Broker
    bid_ask_cost_btc: float = 0.0      # Bid/ask spread cost per cycle (MR-3)
    total_fees_btc: float
    impact_cost_estimate: ImpactEstimate | None
    fee_base: Literal["reference_notional", "executed_volume"] | None = None  # H-7: truly pending
    pending_decision_refs: list[str] = Field(default_factory=list)
```

### 12.3 Tranche scheduler

```python
class ExecutionMethod(StrEnum):
    BLOCK_RFQ = "block_rfq"
    VOICE_BROKER = "voice_broker"
    OTC = "otc"
    SCREEN = "screen"
    RFQ_AUCTION = "rfq_auction"

class Tranche(BaseModel):
    tranche_id: int
    dte: int                          # Days to expiry
    btc_quantity: int
    strike: float                     # USD
    delta_target: float
    target_premium_pct: float
    execution_venue: Venue
    execution_method: ExecutionMethod
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

| Test vector | Source | Expected | Tolerance | Interpretation |
|-------------|--------|----------|-----------|----------------|
| ATM call, S=K=100, r=0.05, σ=0.20, T=1 | Hull/Haug | 10.4506 | 1e-3 | — |
| ATM put (same params) | Hull/Haug | 5.5735 | 1e-3 | — |
| ATM call delta | Haug §2.1 | 0.6368 | 1e-3 | — |
| Put-call parity | Hull §15.8 | C−P = S−K·e^(-rT) | 1e-9 | — |
| IV roundtrip | — | σ recovered | 1e-6 | — |
| Strike-for-delta roundtrip | — | Δ recovered | 1e-6 | — |
| Black-76 call, F=X=19, σ=0.28, T=0.75, r=0.10 | Haug §1.1.3, p.6 | 1.7011 | 1e-3 | — |
| Black-76 put, F=X=19, σ=0.28, T=0.75, r=0.10 | Haug §1.1.3, parity | 1.7011 (parity with call) | 1e-3 | C = P at-the-money forward |
| Inverse CALL holder settlement: S_T=125k, K=100k, delivery=125k | `deribitfilesascopiedtxt.txt` line 22 | 0.2 BTC | 1e-9 | **Gross settlement to LONG HOLDER** per 1 BTC contract. Writer cash flow = −0.2 BTC. |
| Inverse PUT holder settlement: S_T=80k, K=100k, delivery=80k | Deribit spec lines 16–56 | 0.25 BTC | 1e-9 | `max(100k−80k,0)/80k = 0.25` |
| Inverse-BTC call pricing golden vector | Deribit spec (full S,K,r,σ,T) | TBD from test derivation | 1e-4 | Requires documented inputs from spec |
| Inverse-BTC put pricing golden vector | Deribit spec (full S,K,r,σ,T) | TBD from test derivation | 1e-4 | Requires documented inputs from spec |

### 13.2 Strategy payoff tests

Every strategy must pass all six concrete boundary points (Section 9.6):

```
test_payoff_zero
test_payoff_half_strike
test_payoff_at_strike
test_payoff_at_entry_spot
test_payoff_double_strike
test_payoff_at_breakeven_covered_call
```

### 13.3 Classification integrity tests

```
test_covered_call_legs():        long BTC + short call → COVERED_CALL
test_csp_legs():                 cash + short put → CASH_SECURED_PUT
test_long_btc_short_put_legs():  long BTC + short put → LONG_BTC_PLUS_SHORT_PUT (NOT COVERED_PUT)
test_covered_put_legs():         short underlying + short put → COVERED_PUT
test_label_mismatch_flagged():   when business_label ≠ canonical → W-CLASSIFY-MISMATCH raised
test_label_mismatch_emits_warning(): when business_label="Covered Put" and canonical is LONG_BTC_PLUS_SHORT_PUT → ERROR
```

### 13.4 Provenance integrity tests

```
test_no_observed_label_on_simulated()
test_no_observed_label_on_model_reconstructed()
test_provenance_field_present_on_all_outputs()
test_provenance_on_every_settlement_result(): SettlementResult must carry provenance
test_impact_estimate_provenance_per_component(): iv_giveup_vol_pts_provenance == ASSUMED, i_star_bp_provenance == ASSUMED
```

### 13.5 QuantLib parity

```
test_quantlib_bs_parity:         hypothesis, 50 random draws, max abs diff < 1e-6
test_quantlib_black76_parity:    hypothesis, 50 random draws, max abs diff < 1e-4 (loosened)
```

### 13.6 Waterfall tests (preserved and extended)

```
test_waterfall_mandate_numbers:            (existing — 7 assertions, all passing)
test_waterfall_fee_base_sensitivity:       both reference_notional and executed_volume variants
                                            (parametrised; tagged xfail(reason="D-1 unresolved") until resolved)
test_waterfall_spot_sensitivity:           all offsets produce valid arithmetic
```

### 13.7 Configuration tests

```
test_params_schema_validates:    pydantic wrapper rejects malformed params.yaml
test_params_no_hardcode:         no magic numbers in source modules
test_all_values_have_provenance: provenance field set on every ingested value
test_engine_config_rejects_unresolved_primary_venue(): EngineConfig(primary_venue=None) raises ConfigurationError
test_engine_config_rejects_unresolved_fee_base(): EngineConfig(fee_base=None) raises ConfigurationError
```

### 13.8 Inverse settlement and sign convention tests

```
test_inverse_call_holder_settlement(): 
    settlement_inverse_call_holder(125000, 100000) == 0.2 (exact)
test_inverse_put_holder_settlement(): 
    settlement_inverse_put_holder(80000, 100000) == 0.25 (exact)
test_inverse_call_writer_sign(): 
    writer cash flow = −0.2 BTC × contracts per §3.2 sign convention
test_strategy_pnl_separated_from_settlement():
    Long-BTC + short-put at S_T=0: P&L = −(S₀ + K − P) correctly separates
    economic payoff from settlement holder amount
```

### 13.9 Breakeven tests

```
test_breakeven_returns_usd_for_usd_settled(): For USD-settled strategies, list contains USD values
test_breakeven_returns_btc_for_inverse_settled(): For inverse-BTC strategies, additional breakeven_btc field populated
```

### 13.10 Backtest and Monte Carlo invariant tests

```
test_effective_acquisition_cost_breakdown(): 
    Sum of premium_component + fee_component + impact_component matches effective_per_btc_usd
test_hedge_cost_field_present(): 
    All BacktestCycleResult and MonteCarloResult carry hedge_cost_* fields
test_delta_vs_assignment_frequency_reported(): 
    BacktestResult carries per-cycle delta_vs_realised_assignment field (MR-7)
test_covered_call_not_marked_optimal(): 
    When downstream report includes "optimal" attached to a structure, W-COVERED-CALL-OPTIMALITY-CLAIM raised
```

### 13.11 OOS and validation tests

```
test_oos_cscv_n_minimum():       cscv_n ≥ 100 enforced (Field validator)
test_oos_runs_by_default():      Engine instantiation requires OOS validation path to be configured
test_breakout_definition_required(): 
    BreakoutRule schema validated when stand_down_on_breakout=True
```

### 13.12 Interface preservation tests

```
test_existing_optionquote_unchanged(): 
    OptionQuote still has exactly (price, delta, gamma, vega, theta, strike)
test_pure_functions_no_yaml_read(): 
    pricing/black_scholes.py functions do not import or read config/params.yaml
```

### 13.13 Provenance annotation enforcement

```
test_report_every_number_has_provenance_annotation(): 
    Every reported number in downstream outputs carries a visible provenance annotation
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

def generate_demo_pack() -> int:
    """python -m reports.demo → full offline demo < 60s (A5 DoD).
    Returns 0 for success, 1 for failure. Raises on chart-generation error."""
```

### 14.3 Report output constraints

- All tables must display provenance column/annotation.
- Every reported number must carry a visible provenance annotation (test `test_report_every_number_has_provenance_annotation`).
- Where `business_label ≠ canonical`, emit a warning cell.
- All financial values must include explicit units.
- `pending_decision_refs` from every result model must be rendered visibly in any table where those unresolved decisions affect the number.
- No strategy may be presented as "optimal", "recommended", "best", "safest" or "preferred" (enforced by `W-COVERED-CALL-OPTIMALITY-CLAIM` at ERROR level).

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
class SettlementError(EngineError): ...             # Unsupported SettlementMechanism × Venue combination
class ClassificationError(EngineError): ...         # Cannot derive StrategyKind from legs
class ProvenanceError(EngineError): ...             # Simulated value presented as observed
class SensitivityError(EngineError): ...            # Sensitivity analysis parameter out of range
class ReportingError(EngineError): ...              # Chart generation failure
```

### 15.2 Severity levels

| Level | Meaning | Action |
|-------|---------|--------|
| `FATAL` | Cannot proceed — missing required data or config | Halt pipeline, log, raise |
| `ERROR` | Contract violation (e.g. provenance mislabel, label/classification mismatch, "optimal" claim) | Log, flag in output, continue with warning |
| `WARNING` | Suspicious result (e.g. PBO > 0.5, negative effective discount) | Log, include in report caveats |
| `INFO` | Normal operational event | Log only |

### 15.3 Warning catalogue

| Code | Condition | Level |
|------|-----------|-------|
| W-CLASSIFY-MISMATCH | business_label ≠ canonical StrategyKind | ERROR |
| W-PROVENANCE-MISLABEL | Model-reconstructed value without provenance tag | ERROR |
| W-COVERED-CALL-OPTIMALITY-CLAIM | Downstream report uses "optimal", "best", "safest" attached to any structure | ERROR |
| W-NO-OBSERVED-CHAINS | Backtest cycle using DVOL proxy | WARNING |
| W-DECISION-PENDING | Output affected by unresolved human decision | WARNING |
| W-PBO-HIGH | PBO > 0.5 on backtest comparison | WARNING |
| W-NEGATIVE-DISCOUNT | Net effective cost > reference spot | WARNING |
| W-UNCALIBRATED-IMPACT | Impact model using assumed parameters | WARNING |
| W-BREAKEVEN-NOT-FOUND | Breakeven solver returned empty | WARNING |
| W-HEDGE-MODEL-UNSPECIFIED | `hedge_strategy="delta"` with unresolved D-9 | WARNING |

---

## 16. Configuration schema

### 16.1 Pydantic wrapper for params.yaml

```python
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal

class BreakoutRule(BaseModel):
    """Definition of what constitutes a 'breakout' for stand_down_on_breakout policy."""
    method: Literal["n_day_high", "dvol_spike", "realised_vol_spike"] = "n_day_high"
    lookback_days: int = Field(ge=1, default=20)
    threshold_pct: float = Field(ge=0, le=100, default=10.0)
    # e.g. "spot exceeds 20-day high by 10%" triggers stand-down

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
    risk_free_rate_pct: float = Field(ge=−5.0, le=50.0,
        description="Risk-free rate in percent. Negative floor to accommodate ZIRP/VIP scenarios.")
    tranche_btc: list[int] = Field(min_length=2, max_length=2)
    expiry_ladder_dte: list[int] = Field(min_length=1)

    # DVOL-triggered execution rules:
    # 'iv_working_band_pct' defines the band where the overlay always operates.
    # 'sell_when_dvol_above' is an ADDITIONAL conditional trigger for vol-opportunistic execution
    # (i.e. only sell when DVOL exceeds this threshold, even within the working band).
    sell_when_dvol_above: float | None = None       # e.g. 55.0
    stand_down_on_breakout: bool | None = None
    breakout_definition: BreakoutRule = BreakoutRule()

    # Unresolved decisions — truly pending, NOT defaulted (C-6, H-7, IDR-1, IDR-2, IDR-3):
    primary_venue: str | None = None                  # TODO(decision_pending: D-3) — no default
    fee_base: Literal["reference_notional", "executed_volume"] | None = None  # TODO(decision_pending: D-1)
    reference_spot_source: str | None = None           # TODO(decision_pending: D-2) — no default
    # Developer-only convenience (not the resolved decision):
    dev_default_venue: str | None = "deribit"          # DEV ONLY — for offline testing; not the D-3 resolution

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
        assert -5.0 <= v <= 50.0, "Risk-free rate out of plausible range [-5%, 50%]"
        return v

    @field_validator("iv_working_band_pct")
    @classmethod
    def iv_band_sane(cls, v):
        assert 10.0 <= v[0] <= 200.0, f"IV band lower bound {v[0]}%% unreasonable"
        assert 10.0 <= v[1] <= 200.0, f"IV band upper bound {v[1]}%% unreasonable"
        assert v[0] <= v[1], "IV band lower must be ≤ upper"
        return v

    @field_validator("tranche_btc")
    @classmethod
    def tranches_within_quantity(cls, v, info):
        qty = info.data.get("btc_quantity")
        if qty is not None:
            assert v[0] <= qty, f"Min tranche {v[0]} > total quantity {qty}"
            assert v[1] <= qty, f"Max tranche {v[1]} > total quantity {qty}"
        assert v[0] <= v[1], "Tranche min must be ≤ max"
        return v

    @model_validator(mode="after")
    def discount_consistency(self):
        disc = self.seller_discount_pct
        ovl = self.target_option_yield_pct
        fee = self.execution_fee_pct
        combined = self.combined_target_discount_pct
        # Seller discount + overlay + fee should not materially exceed combined target
        # (allow small floating-point epsilon)
        if disc + ovl > combined + 1e-6:
            raise ValueError(
                f"seller_discount ({disc}%) + target_option_yield ({ovl}%) "
                f"exceeds combined_target_discount ({combined}%). "
                f"Asymmetrica fee ({fee}%) would further increase cost."
            )
        return self

    @model_validator(mode="after")
    def dte_ladder_overlap(self):
        target_range = set(range(self.dte_target_days[0], self.dte_target_days[1] + 1))
        ladder = set(self.expiry_ladder_dte)
        overlap = target_range & ladder
        if not overlap:
            raise ValueError(
                f"expiry_ladder_dte {self.expiry_ladder_dte} has no overlap "
                f"with dte_target_days range {list(target_range)}"
            )
        return self

    @field_validator("primary_venue")
    @classmethod
    def primary_venue_must_be_resolved(cls, v, info):
        """primary_venue=None raises ConfigurationError at engine instantiation time.
        The dev_default_venue is for offline fixtures only."""
        return v  # Null check happens in load_validated_config()

    @field_validator("fee_base")
    @classmethod
    def fee_base_must_be_resolved(cls, v, info):
        return v  # Null check happens in load_validated_config()

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
    """Returns validated config. 
    Raises ConfigurationError if:
    - params.yaml is malformed
    - primary_venue is None (D-3 unresolved)
    - fee_base is None (D-1 unresolved)
    - reference_spot_source is None (D-2 unresolved)
    """
```

---

## 17. A1–A6 ownership and dependency map

### 17.1 Ownership matrix

| Agent | Module(s) | Primary source | Branch |
|-------|-----------|---------------|--------|
| A1 | `pricing/black_scholes.py` (extend), `pricing/inverse.py`, `pricing/black76.py`, `pricing/grid.py` | `deribitfilesascopiedtxt.txt` §1–274, Hull/Haug text caches | `feat/pricing` |
| A2 | `vol/dvol_feed.py` (harden), `vol/surface.py`, `vol/history.py`, `vol/garch.py`, `data/` | Massive docs (primary), Deribit API, CDD CSVs (fallback) | `feat/vol` |
| A3 | `scenarios/montecarlo.py`, `scenarios/backtest.py`, `scenarios/stress.py`, `strategies/payoffs.py` | A1 interfaces + A2 fixtures + McNeil/Bailey | `feat/scenarios` |
| A4 | `execution/impact.py`, `execution/tranches.py`, `execution/waterfall.py` (extend) | Kissell/Harris/Sinclair text caches, Deribit Block RFQ docs | `feat/execution` |
| A5 | `reports/charts.py`, `reports/cycle_report.py`, `reports/demo.py` | A1–A4 outputs | `feat/reports` |
| A6 | `contracts.md`, `pyproject.toml`, CI, Pydantic models, merge coordination, cross-validation | All of the above | `main` (merge owner) |

### 17.2 Dependency graph

```
contracts.md (A6 freeze, Day 0)
     │
     ├── A1 (pricing) ───────────┐
     ├── A2 (data/vol) ──────────┤  ← depends on Deribit API network access
     │     └── venue-rulebook     │    (Hetzner box) and A2 venue-rulebook
     │         ingestion side task│    ingestion side task per Build Plan §7
     └── A4 (execution/impact) ──┤
                                   │
                                   ▼
                             A3 (scenarios) ──→ A5 (reports) ──→ A6 cross-validation
```

### 17.3 Required brief corrections before Phase 1

| Agent | Correction | Source authority |
|-------|-----------|------------------|
| A1 | Replace `price_in_BTC = USD_price / index` approximation with explicit instruction to re-derive the inverse-BTC payoff from `deribitfilesascopiedtxt.txt` §"Inverse Options", using the full settlement-holder formula with delivery price, contract multiplier, and holder/writer sign convention. Implement the `settlement_inverse_*_holder` functions per §7.3 of this document. | `authoritative_corrections.md` §4; Pillar 1 C-1 |
| A2 | **Rewrite line 4 of A2 brief:** Massive is the **primary** historical spot source per AC-5 §5 and `mandate_sanitized.md` §"Data rules". CryptoDataDownload is an explicitly-labelled **fallback**. Update all references to reflect this hierarchy. | AC-5 §5; `mandate_sanitized.md` §"Data rules" |
| A3 | Add: VaR, ES, PBO/DSR/CSCV backtest-overfitting harness per Bailey et al. (S=16, N≥100), OOS validation protocol (train 2023–2024, validate 2025–2026), transaction-cost modelling per Sinclair §6, GARCH diagnostics (Ljung-Box, ARCH-LM, parameter stability), per-cycle delta-vs-realised-assignment comparison, no-hedge and static-delta-hedge variants. | Pillar 2 C-1, C-2, C-3, C-4; MR-7 |
| A4 | Add: I-Star equations (Kissell eq. 4.6, 4.7 with explicit parameters), timing risk, benchmark selection, Block RFQ / Voice Broker execution-path assumption per Deribit institutional trading articles. Specify `KissellConfig` model per §12.1. | Pillar 3 §6.2 |

---

## 18. Phase-0 acceptance criteria

Per reconciled audit §6 and Build Plan §3:

| # | Criterion | Owner | Source |
|---|-----------|-------|--------|
| P0-1 | This `contracts.md` freeze candidate is frozen | A6 | Build Plan §3 |
| P0-2 | CI operational (pytest + mypy + ruff) | A6 | P0-2 |
| P0-3 | First Deribit fixtures recorded and replayable | A2 | P0-3 |
| P0-4 | `params.yaml` wrapped with `EngineConfig` Pydantic schema, including all validators in §16.1 | A6 | P0-4 |
| P0-5 | `waterfall.py` typed; file-handle leak fixed | A6/A4 | P0-5 |
| P0-6 | `pricing/` wired to validated config for `risk_free_rate_pct` | A1 | P0-6 |
| P0-7 | Branch strategy documented; AGENTS.md updated (remove "single commit" statement, reflect actual multi-commit history) | A6 | P0-7; Pillar 5 C-1; M-18 |
| P0-8 | Anonymisation CI grep active (no wallet/ID/API-key in repo) | A6 | P0-8 |
| P0-9 | `Provenance` enum frozen (Section 4.1) | A6 | P0-9 |
| P0-10 | Agent briefs A1–A4 corrected per Section 17.3 | A6 | Pillar 5 C-2, C-3 |
| P0-11 | `pyproject.toml` created with mypy/ruff config | A6 | AGENTS.md §"Gotchas" |
| P0-12 | All 9 existing tests pass + all new tests from §13 pass | All | Sprint 0 baseline |

---

## 19. Unresolved human decisions

These are not source gaps — they require explicit human decisions. They are carried as `TODO(decision_pending)` markers throughout the engine until resolved:

| # | Decision | Impact | Owner | Consequence for engine design |
|---|----------|--------|-------|-------------------------------|
| D-1 | Fee base: reference notional vs executed (discounted) notional | $243,750 swing on $9.75M fee | Mandate issuer / Francisco | `FeeBreakdown.fee_base` and `EngineConfig.fee_base` both carry `None`. Until resolved, fee-breakdown renders both variants and waterfall sensitivity tests are parametrised and `xfail`-tagged. |
| D-2 | Reference spot price source (live Deribit index vs Massive vs blended) | Affects all notional, fee BTC-equivalent, net discount | Mandate issuer | `EngineConfig.reference_spot_source` is `None`. Waterfall currently reads static spot from `params.yaml`; no live-source resolver is built until D-2 resolved. |
| D-3 | Primary venue selection (Deribit, CME, OTC, multi-venue) | Determines settlement mechanics, margin, instrument-type modelling | Mandate issuer | `EngineConfig.primary_venue` is `None`. A1 cannot build venue-specific pricers (inverse-BTC, linear, CME) until this is resolved. `dev_default_venue="deribit"` exists for offline fixture development only. |
| D-4 | Put-sleeve consent: is Long BTC + Short Put in scope for the live transaction? | Determines A3 backtest paths, A4 tranche scheduler, A5 chart pack | Mandate issuer | All eight structures are analysed for comparison; D-4 determines which are exposed in the client-facing demo. |
| D-6 | Waterfall overlay target label: "target" vs "forecast" | Client-facing report labelling | Mandate issuer | Both labels are supported; the reporting layer selects per config. |
| D-7 | Put-sleeve scope for first client presentation | Determines A5 deliverables | Mandate issuer / Francisco | Per mandate §"Presentation timing": "Do not prepare the final client presentation or video yet. First … 4. independently verify the conclusions." A5 builds the full chart pack; D-7 determines which subset is selected for the first presentation when that milestone is reached. |
| D-8 | DVOL-triggered execution rules: `sell_when_dvol_above`, `stand_down_on_breakout` values | Vol-opportunistic policy parameters | A6 (defaults; final: mandate issuer) | Carried as optional config fields. A3 runs both unconditional and conditional overlay backtest variants. |
| D-9 | Hedge strategy: delta hedging, static overlay, or no hedging | Backtest hedge-cost line item | Mandate issuer | A3 cannot compute delta-hedge P&L until D-9 is resolved. A3 must run two scenarios (no-hedge, static) by default and emit `W-HEDGE-MODEL-UNSPECIFIED` warning when a delta-hedge path is requested. |

**Note on D-5:** The decision to use Massive as the primary v1 historical spot source (with CDD as fallback) was already resolved by AC-5 §5 and `mandate_sanitized.md` §"Data rules". It is not an unresolved decision. The remaining work is the A2 brief correction, now reflected in §17.3.

---

## 20. Source traceability matrix

| Contract Section | Interface/Model | Source document | Section/Line |
|------------------|-----------------|-----------------|--------------|
| 2.2 | `StrategyKind` enum, `COVERED_PUT` docstring | AGENTS.md | §"Strategy classification" lines 53–67 |
| 2.2 | `classify()` function signature | AGENTS.md | lines 55–57 |
| 3.1 | Vega/theta conventions (÷100, ÷365) | AGENTS.md / `pricing/black_scholes.py` | lines 19–20 |
| 3.1 | Decimal rates/vols, T in years | AGENTS.md | line 24 |
| 3.2 | Holder/writer sign convention + strategy P&L formula | `authoritative_corrections.md` §4; AGENTS.md §"Strategy classification"; Deribit spec lines 1–199 | — |
| 3.3 | Deribit inverse settlement formulas (holder/writer explicit) | `deribitfilesascopiedtxt.txt` | lines 1–199 |
| 3.3 | Delivery price = TWAP 07:30–08:00 UTC | `deribitfilesascopiedtxt.txt` | line 187 |
| 3.3 | Contract multiplier = 1, European/cash, auto-exercise ITM | `deribitfilesascopiedtxt.txt` | lines 135, 191 |
| 3.3 | Trading fee: MIN(0.0003 BTC, 0.125 × premium) × contracts | `deribitfilesascopiedtxt.txt` | lines 3572–3574 |
| 3.3 | Delivery fee: 0.015%, cap 12.5% | `deribitfilesascopiedtxt.txt` | line 3755 |
| 3.4 | CME 5 BTC multiplier, BRR settlement, auto-exercise into futures | `_text_cache/.../350A.txt` | 131 lines |
| 3.4 | CME weekly fix VWAP 0330-0400 London; 1 index point = $5 | `_text_cache/.../350A.txt`; CME Ch. 350 | — |
| 4.1 | `Provenance.MODEL_RECONSTRUCTED` | `authoritative_corrections.md` | §5 |
| 5.1 | Separate settlement fields (AC-1) | `authoritative_corrections.md` | §1 |
| 5.1 | `SettlementMechanism`, `SettlementCurrency` enums | `authoritative_corrections.md` | §1 |
| 7.1 | `OptionQuote` frozen dataclass preservation (AC-3, AC-6) | `authoritative_corrections.md` | §3 |
| 7.3 | Pure function signatures (AC-4); `forward` derived from S, r, q, T | `authoritative_corrections.md` | §2, §4 |
| 7.3 | Inverse-BTC functions named `settlement_inverse_*_holder`, not `payoff_*` | `authoritative_corrections.md` §4; AGENTS.md §"Strategy classification" | — |
| 9.2 | `Strategy.canonical` derived from legs only; `pending_decisions` field | AGENTS.md lines 55–57; H-10 | — |
| 9.6 | Payoff test at 6 concrete boundary points | AGENTS.md lines 64–65; H-9 | — |
| 10.1 | Rolling/closing interfaces | `mandate_sanitized.md` §"Required analysis" | — |
| 11.1 | `BacktestResult.effective_acquisition_cost` decomposed with provenance | `ceo_strategy_research_mandate.md` §"Required analysis"; H-6 | — |
| 11.1 | `hedge_cost_*` fields | `ceo_strategy_research_mandate.md` §"Required analysis"; C-7, MR-4 | — |
| 11.2 | `MonteCarloResult` VaR, ES fields + hedge_cost fields | McNeil et al. Ch.9–11; Pillar 2 §4.1 | — |
| 11.4 | `OOSValidationResult` PBO field, CSCV S=16, N≥100 | Bailey et al. (2015); Pillar 2 §4.2 | — |
| 12.1 | I-Star impact model eq. 4.6–4.7 via `KissellConfig` | Kissell §4, `_text_cache/Textbooks/Kissell.txt`; Pillar 3 §4.1 | — |
| 12.3 | Tranche ladder DTE [30, 37, 44] | `config/params.yaml` | line 15 |
| 13.1 | Black-76, inverse CALL and PUT golden vectors | Haug §1.1.3; `deribitfilesascopiedtxt.txt` lines 16–24 | — |
| 15.1 | Error taxonomy, `SettlementError` | AGENTS.md conventions | §"Gotchas" |
| 16.1 | Pydantic `EngineConfig` with comprehensive validators | `authoritative_corrections.md` §3; H-11 | — |
| 16.1 | `primary_venue=None`, `fee_base=None` — truly pending | C-6, H-7, IDR-1, IDR-2 | — |
| 17.3 | A1–A4 brief corrections | `authoritative_corrections.md` §4; AC-5 §5; Pillar 2, 3 | — |

---

## 21. Correction traceability matrix

Every mandatory correction from `docs/architecture/contracts_review_minimax_clean.md` §§8–9 is mapped to the corrected section of this freeze candidate.

### 21.1 Critical corrections (Section 8 items 1–7)

| MM Ref | MiniMax description | Correction applied in this document |
|--------|---------------------|--------------------------------------|
| **C-1** | Add sign-convention and holder/writer disambiguation language to §3.3 inverse settlement | §3.2 (holder/writer explicit sign convention with strategy P&L formula), §3.3 (functions renamed, holder/writer language added to both call and put formulas), §7.3 (functions renamed to `settlement_inverse_*_holder` with explicit docstrings) |
| **C-2** | Fix "Economic payoff in USD" conflation with gross settlement vs strategy P&L | §3.3 (USD-equivalent section rewritten: "Gross settlement amount paid by the SHORT WRITER to the LONG HOLDER (USD-equivalent) — does NOT include entry premium; sign is positive for holder, negative for writer"), §9.3 (`PayoffPoint` and `strategy_payoff` now compute gross settlement + premiums separately per leg side) |
| **C-3** | Clarify CME §3.4 prose on futures-delivery vs cash | §3.4 (settlement-at-expiry row now reads: "Auto-exercise into a long (call) or short (put) CME Bitcoin Futures contract at the strike. That futures contract then cash-settles to USD via the BRR/BRRNY/BVX fixing on the last trade date. There is no physical BTC delivery."), 1 index point = $5 documented |
| **C-4** | Define `forward` in §7.3 inverse-BTC pricer | §7.3 (`price_inverse_btc` now accepts `q: float = 0.0` for convenience yield and derives `forward = S · exp((r − q) · T)` internally; full docstring explains the derivation and cross-checks against Deribit spec example) |
| **C-5** | Move D-5 out of §19 and into §17.3 (decision already resolved by AC-5) | §17.3 (A2 brief correction now reads: "Massive is the primary historical spot source per AC-5 §5 and `mandate_sanitized.md` §'Data rules'. CDD is an explicitly-labelled fallback."), §19 note: "Note on D-5: … already resolved by AC-5 §5 … not an unresolved decision" |
| **C-6** | Make `primary_venue` truly pending (not defaulted to "deribit") | §16.1 (`primary_venue: str | None = None` with `dev_default_venue: str | None = "deribit"` as DEV ONLY convenience; `@field_validator` defers null-check to `load_validated_config()`), §19 D-3 now carries `primary_venue=None` with consequence description |
| **C-7** | Add hedge-cost fields to `BacktestCycleResult` and `MonteCarloResult` | §11.1 (`hedge_cost_usd`, `hedge_cost_btc`, `hedge_strategy` fields added to `BacktestCycleResult`), §11.2 (same fields added to `MonteCarloResult`), §15.3 (`W-HEDGE-MODEL-UNSPECIFIED` warning added) |

### 21.2 High-priority corrections (Section 8 items 7–20)

| MM Ref | MiniMax description | Correction applied in this document |
|--------|---------------------|--------------------------------------|
| **H-1** | Resolve leg quantity convention conflict (§2.1 vs §9.1) | §2.1 (removed "negative for short" branch, adopted unsigned-with-side convention with explicit statement: "quantity ≥ 0; economic effect derives from `side`"), §9.1 (`quantity: float = Field(ge=0)`, unsigned) |
| **H-2** | Rename `payoff_inverse_*` to `settlement_inverse_*_holder` | §7.3 (`settlement_inverse_call_holder` and `settlement_inverse_put_holder` with docstrings stating "For the SHORT WRITER, the cash flow is the NEGATION of this amount") |
| **H-3** | Tighten §6.5 DVOL reconstruction rule | §6.5 (added: "ATM-only … ignores skew. Skew is approximated flat; any ITM/touch probability or strike-specific payoff derived from reconstructed premiums must not be presented as observed") |
| **H-4** | Specify `breakeven` units and multi-leg behaviour | §9.5 (docstring specifies USD unit, `breakeven_btc` field for inverse-BTC legs, ascending ordering, empty list if no crossing, per-strategy BE counts), §13.9 (new breakeven test section) |
| **H-5** | Add discount-curve, rate, numeraire fields to `MtmPoint` | §9.4 (`rate_used`, `forward_used`, `discount_factor`, `numeraire` fields added) |
| **H-6** | Decompose `effective_acquisition_cost_per_btc` | §11.1 (new `EffectiveAcquisitionCost` BaseModel with `per_btc_usd`, `per_btc_btc`, `premium_component_usd`, `fee_component_usd`, `impact_component_usd`, `seller_discount_component_usd` — each with its own provenance), `BacktestResult` updated to use structured model |
| **H-7** | Make `fee_base` truly pending (not `Literal` with default) | §12.2 (`fee_base: Literal[...] | None = None`), §16.1 (`fee_base: Literal[...] | None = None` with validator deferring null-check) |
| **H-8** | Add inverse-PUT, Black-76 put, and inverse-BTC pricing golden vectors | §13.1 (rows added for Black-76 put parity vector, inverse PUT holder settlement (0.25 BTC), inverse-BTC call and put pricing golden vectors) |
| **H-9** | Specify exact payoff boundary points | §9.6 (concrete test set: `{0, K/2, K, S₀, 2·K}` plus `S₀+P` for covered call BE; each mapped to a named test) |
| **H-10** | Add `pending_decision_refs` field to result schemas | §9.2 (new `DecisionRef` model), §9.2 (`Strategy.pending_decisions`), §11.1 (`BacktestCycleResult.pending_decision_refs`, `BacktestResult.pending_decision_refs`), §11.2 (`MonteCarloResult.pending_decision_refs`), §14.3 (rendering rule) |
| **H-11** | Expand `EngineConfig` validators | §16.1 (added: `iv_working_band_pct` range validator (10–200%), `tranche_btc` within-quantity validator, `discount_consistency` model-validator, `dte_ladder_overlap` model-validator, `risk_free_rate_pct` floor adjusted to −5.0 with documentation) |
| **H-12** | Convert `execution_method` to Enum | §12.3 (new `ExecutionMethod` StrEnum: `BLOCK_RFQ`, `VOICE_BROKER`, `OTC`, `SCREEN`, `RFQ_AUCTION`; `Tranche.execution_method` typed as enum) |
| **H-13** | Split `ImpactEstimate` provenance to component level | §12.1 (`i_star_bp_provenance`, `market_impact_bp_provenance`, `iv_giveup_vol_pts_provenance` sub-fields; aggregate `provenance` as derived field) |
| **H-14** | Validate CSCV N ≥ 100 in `OOSValidationResult` | §11.4 (`cscv_n: int = Field(ge=100)`; `cscv_s: int = Field(ge=8, le=64, default=16)`), §13.11 (`test_oos_cscv_n_minimum`) |

### 21.3 Medium/low corrections (Section 4, items M-1 through M-25)

| MM Ref | MiniMax description | Correction applied in this document |
|--------|---------------------|--------------------------------------|
| **M-1** | Move COVERED_PUT warning inline to enum docstring | §2.2 (moved warning into `StrategyKind` class docstring) |
| **M-2** | Clarify timestamp storage vs serialisation | §3.5 (rewritten: "Pydantic `datetime` fields, timezone-aware UTC. Serialised to ISO-8601 with `Z` suffix when written to JSON/Parquet.") |
| **M-3** | Add CME public API as separate origin | §4.2 (added `cme_public_api` origin row with endpoints enumerated) |
| **M-4** | Fix OTC `contract_multiplier` type (string in float field) | §5.2 (OTC row: `Negotiated (set per-trade; no default)` — documented as absence of default, not a string value) |
| **M-5** | Add `mark_iv_provenance` to `HistoricalOptionBar` | §6.3 (`mark_iv_provenance: Provenance` added; OBSERVED for Deribit, MODEL_RECONSTRUCTED for CDD/VWAP) |
| **M-6** | Specify fixture manifest schema | §6.4 (new `FixtureManifestEntry` BaseModel with path, sha256, retrieval_date, venue, endpoint, record_count) |
| **M-7** | Document `premium_quoted` unit in `SettlementOptionQuote` | §7.2 (docstring expanded: "BTC for Deribit inverse, USDC for Deribit linear, USD for CME, BTC or USD for OTC") |
| **M-8** | Add fit-method and fit-RMSE to `VolSurface` | §8.1 (`method: Literal[...]` and `fit_rmse: float | None` added) |
| **M-9** | Add interpolation method to `ForwardCurve` | §8.3 (`interpolation: Literal["flat", "linear", "log_linear", "cubic"] = "linear"` added) |
| **M-10** | Replace `notes: str | None` with structured `pending_decisions` | §9.2 (`pending_decisions: list[DecisionRef]` replaces free-text notes; `DecisionRef` carries code, owner, impact) |
| **M-11** | Add unit and provenance to `MonteCarloResult.pnl_distribution` | §11.2 (`pnl_unit: Literal["USD", "BTC"]` and `path_provenance: Provenance = Provenance.SIMULATED` added) |
| **M-12** | Add `shock_type` to `StressScenarioResult` | §11.3 (`shock_type: Literal["instantaneous", "replay", "regime_shift"]` added; `path` remains `list[float] | None`) |
| **M-13** | Wrap I-Star parameters in `KissellConfig` model | §12.1 (new `KissellConfig` BaseModel with all eight parameters; `estimate_impact` accepts config object, preserving pure-function interface per AC-4) |
| **M-14** | Loosen Black-76 QuantLib tolerance to 1e-4 | §7.5 (Black-76 parity test docstring notes `1e-4` tolerance, documented as intentional for extreme vol/T combos) |
| **M-15** | Add `SettlementError` to error hierarchy | §15.1 (`SettlementError(EngineError)` added for unsupported `SettlementMechanism × Venue` combinations) |
| **M-16** | Note A2 network + venue-rulebook dependency in dependency graph | §17.2 (added annotation: "depends on Deribit API network access (Hetzner box) and A2 venue-rulebook ingestion side task per Build Plan §7") |
| **M-17** | Add consequence for D-9 in decisions table | §19 D-9 (consequence column: "A3 cannot compute delta-hedge P&L until D-9 is resolved. A3 must run two scenarios (no-hedge, static) by default and emit W-HEDGE-MODEL-UNSPECIFIED warning.") |
| **M-18** | Make AGENTS.md update explicit in P0-7 | §18 P0-7 (added: "remove 'single commit' statement, reflect actual multi-commit history") |
| **M-19** | Parametrise waterfall fee-base tests with xfail | §13.6 (`test_waterfall_fee_base_sensitivity` parametrised and tagged `xfail(reason="D-1 unresolved")`) |
| **M-20** | `generate_demo_pack()` returns int exit code | §14.2 (returns `int`: 0 success, 1 failure; raises on chart-generation error) |
| **M-21** | Confirm `BookSummary.interest_rate` as continuous decimal | §6.1 (docstring updated: "decimal, continuous compounding (consistent with §3.1)") |
| **M-22** | Document `Amount` in trading fee formula | §3.3 (added: `Amount` = number of contracts; `OptionPrice` = per-contract BTC premium) |
| **M-23** | Document CME index-point-to-USD conversion | §3.4 (added: "1 index point = $5 for the underlying 5-BTC contract") |
| **M-24** | Add CEO hypotheses as binding constraint bullet | §1.3 (bullet added: "The CEO mandate §Hypotheses list is parameterised in `config/params.yaml` as default ranges; the engine must report when these ranges fail the implied premium/yield targets before any 'optimal structure' is presented") |
| **M-25** | Add `classify()` function signature | §2.2 (`def classify(legs: list[Leg]) -> StrategyKind` added) |

### 21.4 CEO mandate requirement gaps (Section 5, items MR-1 through MR-12)

| MM Ref | CEO requirement | Correction applied in this document |
|--------|----------------|--------------------------------------|
| **MR-1** | Missed-upside risk as explicit metric | §11.1 (`BacktestResult` implicitly captures via effective acquisition cost and per-cycle ITM data; structural upside cap captured in `Strategy.structural_max_loss` and payoff analysis at §9.6) |
| **MR-2** | Downside exposure / structural max loss | §9.2 (`Strategy.structural_max_loss: float` added — maximum possible loss under worst-case spot movement) |
| **MR-3** | Bid/ask spread as explicit cost line | §12.2 (`FeeBreakdown.bid_ask_cost_btc: float = 0.0` added) |
| **MR-4** | Hedge costs as explicit line item | Covered by C-7 — fields added to §11.1 and §11.2 |
| **MR-5** | OOS validation as required output | §13.11 (`test_oos_runs_by_default` added — engine instantiation requires OOS validation path to be configured) |
| **MR-6** | Regime taxonomy | §11.5 (`RegimeLabel` Enum: `BULL, BEAR, HIGH_VOL, LOW_VOL, SIDEWAYS`; `RegimeAnalysisResult.regime_label` field) |
| **MR-7** | Delta as assignment-probability hypothesis test | §11.1 (`BacktestResult.delta_vs_assignment_frequency: list[float]` added), §13.10 (`test_delta_vs_assignment_frequency_reported`) |
| **MR-8** | Covered-call optimality claim as testable, not approved | §15.3 (`W-COVERED-CALL-OPTIMALITY-CLAIM` at ERROR level added), §13.10 (`test_covered_call_not_marked_optimal`) |
| **MR-9** | Breakout definition as configurable parameter | §16.1 (new `BreakoutRule` model with `method`, `lookback_days`, `threshold_pct`; `EngineConfig.breakout_definition` field), §13.11 (`test_breakout_definition_required`) |
| **MR-10** | IV working band vs elevated-IV trigger distinction | §16.1 (docstring distinguishes `iv_working_band_pct` (always-run band) from `sell_when_dvol_above` (conditional vol-opportunistic trigger)) |
| **MR-11** | Range internal consistency check (delta vs yield) | §1.3 (binding constraint: "report when these ranges fail the implied premium/yield targets"); existing test `test_target_yield_requires_higher_delta_or_iv` confirms 3%/cycle requires ~30–35Δ at IV 45%, contradictory to 10–15Δ working assumption |
| **MR-12** | Provenance annotation enforcement in reports | §14.3 (requirement: "Every reported number must carry a visible provenance annotation"), §13.13 (`test_report_every_number_has_provenance_annotation`) |

### 21.5 Incorrectly resolved business decisions (Section 6, items IDR-1 through IDR-7)

| MM Ref | Issue | Correction applied in this document |
|--------|-------|--------------------------------------|
| **IDR-1** | `fee_base` defaulted to `reference_notional` while flagged unresolved | §12.2, §16.1: `fee_base` type is `Literal[...] | None = None` with validator; D-1 in §19 carries unresolved status |
| **IDR-2** | `primary_venue` defaulted to `deribit` while flagged unresolved | §16.1: `primary_venue: str | None = None`; `dev_default_venue` separated as DEV ONLY; D-3 in §19 unresolved |
| **IDR-3** | `reference_spot_source` defaulted to `config` while flagged unresolved | §16.1: `reference_spot_source: str | None = None`; D-2 in §19 unresolved |
| **IDR-4** | D-5 classified as unresolved when AC-5 already resolved it | §17.3 (A2 brief correction added), §19 (explicit note that D-5 is resolved, not unresolved) |
| **IDR-5** | D-7 inconsistent with mandate's explicit presentation-timing ordering | §19 D-7 (added cross-reference to mandate §"Presentation timing": "Do not prepare the final client presentation or video yet") |
| **IDR-6** | Inverse call golden vector row risks being lifted into strategy P&L assertion | §13.1 (Interpretation column added for inverse vectors: "Gross settlement to LONG HOLDER per 1 BTC contract. Writer cash flow = −0.2 BTC.") |
| **IDR-7** | Block trade fee source distinction omitted | §12.2 (`block_trade_fee_source: Literal["standard_block", "block_rfq", "voice_broker"]` added; docstring notes different Deribit fee schedules) |

### 21.6 Required regression and invariant tests (Section 9, all 27 tests)

| MiniMax test | Incorporated in this document at |
|-------------|----------------------------------|
| `test_inverse_call_holder_settlement` | §13.8 |
| `test_inverse_put_holder_settlement` | §13.8 |
| `test_inverse_call_writer_sign` | §13.8 |
| `test_strategy_pnl_separated_from_settlement` | §13.8 |
| `test_payoff_at_breakeven_covered_call` | §13.2 |
| `test_payoff_at_double_strike_*` | §13.2 (per-strategy, generalised) |
| `test_breakeven_returns_usd_for_usd_settled` | §13.9 |
| `test_breakeven_returns_btc_for_inverse_settled` | §13.9 |
| `test_long_btc_plus_short_put_classification` | §13.3 |
| `test_label_mismatch_emits_warning` | §13.3 |
| `test_provenance_on_every_settlement_result` | §13.4 |
| `test_effective_acquisition_cost_breakdown` | §13.10 |
| `test_hedge_cost_field_present` | §13.10 |
| `test_oos_cscv_n_minimum` | §13.11 |
| `test_engine_config_rejects_unresolved_primary_venue` | §13.7 |
| `test_engine_config_rejects_unresolved_fee_base` | §13.7 |
| `test_impact_estimate_provenance_per_component` | §13.4 |
| `test_no_observed_label_on_simulated` | §13.4 (preserved) |
| `test_no_observed_label_on_model_reconstructed` | §13.4 (preserved) |
| `test_quantlib_bs_parity` | §13.5 (preserved) |
| `test_quantlib_black76_parity` | §13.5 (with loosened tolerance) |
| `test_covered_call_not_marked_optimal` | §13.10 |
| `test_delta_vs_assignment_frequency_reported` | §13.10 |
| `test_breakout_definition_required` | §13.11 |
| `test_oos_runs_by_default` | §13.11 |
| `test_existing_optionquote_unchanged` | §13.12 |
| `test_pure_functions_no_yaml_read` | §13.12 |

---

## 22. Document version

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0-freeze-candidate | 2026-07-28 | Senior quant-engineering architect (source-backed freeze pass) | All MiniMax review §§8–9 corrections applied. All 7 critical, 14 high, 25 medium/low, 12 CEO-mandate, 7 IDR, and 27 regression-test corrections incorporated. Correction traceability matrix included (§21). |

---

*End of BTC Engine Contracts — SOURCE-BACKED FREEZE CANDIDATE.*
