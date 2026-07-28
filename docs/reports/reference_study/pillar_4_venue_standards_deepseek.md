Now let me read the key Deribit articles and instrument documentation, plus the Massive and ISDA materials.
Now I have all the information needed to compile the comprehensive report.

---

# Pillar 4: Venue Standards — Source Study Report

**Date:** 2026-07-28  
**Assessor:** Senior Quantitative-Finance Researcher (read-only audit)  
**Scope:** `private_reference_library/pillar_4_venue_standards` and text cache `private_reference_library/_text_cache/pillar_4_venue_standards`

---

## 1. Source Inventory

### 1.1 Deribit — Primary BTC Options Venue

| Category | Files/Artifacts | Date Retrieved |
|---|---|---|
| Core metadata | `00_core/API_ROOTS.md`, `00_core/llms.txt` (340-line documentation index) | 2026-07-28 |
| API reference pages (market-data) | 31 endpoint specifications including `public/get_instruments`, `public/get_instrument`, `public/get_contract_size`, `public/get_delivery_prices`, `public/get_book_summary_by_currency`, `public/get_volatility_index_data`, `public/get_last_settlements_by_*` | 2026-07-28 |
| API reference pages (trading) | 38 endpoint specifications including `private/buy`, `private/sell`, `private/get_settlement_history_*` | 2026-07-28 |
| API reference pages (block-rfq) | 13 endpoint specifications for institutional RFQ workflow | 2026-07-28 |
| Articles | 26 articles: Block Trading API, Options Data Collection Best Practices, Quickstart, Block RFQ Walkthrough, Mass Quotes, Market Maker Protection, Rate Limits, API Usage Policy, Authentication, etc. | 2026-07-28 |
| Changelogs | FIX, JSON-RPC, Starbase changelogs | 2026-07-28 |
| FIX API | 28 production FIX message specification pages | 2026-07-28 |
| Starbase API | 31 pages: market model, account model, order entry, mass quotes, binary API reference, multicast guide, speed bumps | 2026-07-28 |
| Subscription channels | 8 channel categories: announcements, block-rfq, block-trade, market-data, orderbook, platform, trades, user | 2026-07-28 |
| OpenAPI specs | `deribit_openapi.json` (v2.1.1), `deribit_upcoming_openapi.json`, `starbase_rest_openapi.json`, `openapi.json` (api-reference) | 2026-07-28 |
| AsyncAPI specs | `deribit_asyncapi.json`, `deribit_upcoming_asyncapi.json`, `deribit_asyncapi_upcoming.json` | 2026-07-28 |
| Download tooling | `download_deribit_docs.py`, `download_manifest.csv` (with SHA-256 checksums) | 2026-07-28 |

### 1.2 CME — Futures & Options on Bitcoin Futures

| Category | Files/Artifacts |
|---|---|
| Download script | `download_cme_crypto.py` — targets CME rulebook PDFs and product specification pages |
| Crypto filter terms | bitcoin, ether, crypto, sol futures, solana, xrp, avax, avalanche, sui futures, link futures, lumens futures, ada futures |
| Product pages targeted | CME cryptocurrency page, Bitcoin/Micro Bitcoin futures & options specs, Bitcoin Friday Futures options, FAQ |
| **Actual CME documents** | **None downloaded — directory contains only the download script** |

### 1.3 ISDA — Digital Asset Derivatives Definitions

| Category | Files/Artifacts |
|---|---|
| README | `00_README.md` — states full Definitions require ISDA account/licence; do not substitute press release or whitepaper for actual Definitions |
| Press release (PDF) | `01_isda_launches_digital_asset_definitions.pdf` — 26 Jan 2023, ISDA Digital Asset Derivatives Definitions published |
| Whitepaper (PDF) | `02_contractual_standards_for_digital_asset_derivatives.pdf` — Dec 2021, 26-page whitepaper |
| Text cache (press release) | `01_isda_launches_digital_asset_definitions.txt` (101 lines) |
| Text cache (whitepaper) | `02_contractual_standards_for_digital_asset_derivatives.txt` (1365 lines) |
| **Actual ISDA Definitions** | **Missing — requires ISDA account at https://www.isda.org/book/isda-digital-asset-derivatives-definitions/** |

### 1.4 Massive — Primary BTC Spot Data Source

| Category | Files/Artifacts |
|---|---|
| Core metadata | `00_core/llms.txt` (220-line documentation index), `00_core/source_url.txt` |
| Flat files docs (crypto) | Day/min aggregates, trades |
| REST API docs (crypto) | Aggregates (custom bars, daily market/ticker summary, previous day bar), market operations (condition codes, exchanges, holidays, status), snapshots (full market, single ticker, top movers, unified), technical indicators, tickers, trades |
| REST API docs (options) | Aggregates, contracts, condition codes, exchanges, snapshots (chain, contract, unified), trades, quotes |
| REST API docs (futures, indices, stocks, forex, economy, alternative data) | Full documentation sets |
| Websocket docs | Websocket documentation |
| Download tooling | `download_massive_docs.py`, `download_manifest.csv` (with SHA-256 checksums, 28 Jul 2026) |

### 1.5 Existing Source Code (Sprint 0 Baseline)

| Module | File | Key Entities |
|---|---|---|
| `pricing/` | `black_scholes.py` (76 lines) | `OptionQuote` frozen dataclass, `price()`, `greeks()`, `strike_for_delta()`, `implied_vol()`, `premium_pct_at_delta()` |
| `execution/` | `waterfall.py` (44 lines) | `load_params()`, `waterfall()` — mandate economics calculator |
| `vol/` | `dvol_feed.py` (54 lines) | `spot_index()`, `dvol_latest()`, `option_chain()`, `book_summary()` — Deribit public feed |
| `config/` | `params.yaml` (15 lines) | Single source of truth: BTC quantity 30,000, spot $65,000, seller discount 2.5%, fee 0.5%, target yield 2.5%, delta [0.10,0.15], DTE [30,45], IV [40,50], rate 4.0% |
| `tests/` | `test_engine.py` (67 lines) | 9 tests: Haug golden call/put, put-call parity, delta golden, IV roundtrip, strike-for-delta roundtrip, mandate premium band, target yield, waterfall economics |
| `agents/` | `A1_pricing.md` through `A6_qa_integration.md` | Parallel agent task briefs |

---

## 2. Sources Successfully Examined

All accessible files in the pillar directory and text cache were examined:

- **Deribit:** API roots page, full `llms.txt` index (340 lines), all endpoint specification pages (market data, trading, block-rfq, subs, etc.), all article pages (Block Trading, Options Data Collection Best Practices, Block RFQ Walkthrough, Deribit Quickstart), Starbase market-model page, all 6 OpenAPI/AsyncAPI spec JSON files, download manifest.
- **CME:** Download script (no actual CME documents present).
- **ISDA:** README, press release text, full whitepaper text (1365 lines covering executive summary through section 5 on valuation).
- **Massive:** Core `llms.txt` index, crypto REST/flat-files/websocket documentation pages, download manifest.
- **Source code:** All modules in `pricing/`, `execution/`, `vol/`, `config/`, `tests/`, `agents/`.

---

## 3. Relevant Chapters, Pages, Sections, and Document Versions

### 3.1 Deribit API Documentation
- **Version:** API v2.1.1 (OpenAPI 3.0.0 spec)
- **Key instrument model fields** (from `public/get_instruments`, `get_instrument`):
  - `base_currency` (BTC/ETH), `quote_currency` (USD), `settlement_currency` (BTC/ETH), `counter_currency` (USD/USDC)
  - `contract_size` (integer; for futures: USD, for options: base currency coin)
  - `instrument_type`: `linear` or `reversed`
  - `option_type`: `call` or `put`, `strike` (number)
  - `expiration_timestamp`, `tick_size`, `min_trade_amount`
  - `settlement_period`: `month`, `week`, or `perpetual`
  - `block_trade_min_trade_amount`, `block_trade_commission`
  - Book states: open → settlement → delivered/inactive/locked/halted → archivized
- **Key settlement endpoints:**
  - `public/get_delivery_prices`: Historical settlement prices per index (`btc_usd`, etc.), paginated via offset/count (max 1000)
  - `public/get_last_settlements_by_instrument`: Settlement/delivery/bankruptcy events per instrument with `settlement_type` enum
- **Contract size:** `public/get_contract_size` — for options: base currency of instrument (BTC, ETH); for futures: USD
- **Volatility:** `public/get_volatility_index_data` — DVOL candles, resolutions 1/60/3600/43200/1D seconds; `deribit_volatility_index.{index_name}` WebSocket channel
- **Order book amounts for options:** denominated in underlying cryptocurrency (BTC/ETH contracts), not USD
- **Ticker channels:** `mark_iv`, `bid_iv`, `ask_iv`, full `greeks` object (delta, gamma, theta, vega, rho)
- **Block trading:** Two-party workflow (verify → execute), RFQ protocol with maker/taker roles; 5-minute approval timer; `block_trade_commission` per instrument
- **Rate limits (options):** `public/get_instruments` has sustained rate of 1 req/s; other market-data endpoints have higher limits

### 3.2 ISDA Whitepaper (Dec 2021)
- **Section 1:** Executive Summary — digital asset derivatives need contractual standards for safe, efficient markets
- **Section 2:** Introduction — OTC derivatives on Bitcoin/Ether; CME futures; need for standardised provisions
- **Section 3:** Categorizing Digital Assets — native vs asset-referenced; blockchain/DLT technology; market infrastructure; property status
- **Section 4:** Disruption Events — forks (soft/hard/controversial), airdrops, cyberattacks, change in law, market infrastructure risks, private key loss; consequences: economic adjustment vs termination, cash settlement fallback
- **Section 5:** Valuation — valuation sources (screen rates, trading venue data, published indices, internal modelling); valuation for payment/delivery, close-out, collateral; need for deterministic computational logic

### 3.3 ISDA Press Release (26 Jan 2023)
- Initial coverage: non-deliverable forwards and options on Bitcoin and Ether
- Controlled language structure for Common Domain Model integration and smart contract automation
- Definitions available through ISDA MyLibrary — require ISDA account

### 3.4 Massive Documentation
- **Crypto REST API:** OHLC aggregates, daily summaries, trades, tickers, snapshots, technical indicators
- **Crypto Flat Files:** Day/minute aggregates, trade-level data with nanosecond timestamps, S3 delivery
- **Crypto Websocket:** Real-time feeds for crypto tickers
- **Response fields for OHLC:** `o`, `h`, `l`, `c`, `v` (volume), `vw` (VWAP), `t` (Unix ms timestamp), `n` (number of transactions)

### 3.5 Existing Source Code
- **pricing/black_scholes.py:** Standard Hull Black-Scholes; OptionQuote dataclass with delta, gamma, vega (per 1.00 vol), theta (per year), strike; all rates/vols as decimals, T in years
- **execution/waterfall.py:** Reads `config/params.yaml`; calculates notional, fees, effective cost, net discount
- **config/params.yaml:** btc_quantity=30000, spot=65000, seller_discount=2.5%, fee=0.5%, target_option_yield=2.5%, call_delta_target=[0.10,0.15], dte_target_days=[30,45], iv_working_band_pct=[40,50], risk_free_rate=4.0%, tranche_btc=[250,1000], expiry_ladder_dte=[30,37,44]

---

## 4. Verified Formulas, Definitions, Units, Numeraires, and Conventions

### 4.1 Deribit Contract Conventions (from official API docs)

| Item | Convention | Source |
|---|---|---|
| Options contract size | 1 BTC (integer, in base currency) | `public/get_contract_size` schema: "for options in base currency of the instrument (BTC, ETH, ...)" |
| Futures contract size | 10 USD (integer, in USD) | `public/get_contract_size` schema description |
| Option contract min trade amount | 0.1 BTC (in base currency coin) | `public/get_instruments` schema: `min_trade_amount` |
| Block trade min for options | 25 contracts | `public/get_instrument` example: `block_trade_min_trade_amount: 25` |
| Settlement currency | BTC (for BTC options), ETH (for ETH options) | `settlement_currency` enum: `["BTC", "ETH"]` |
| Quote currency | USD | `quote_currency` enum: `["USD"]` |
| Counter currency | USD or USDC | `counter_currency` enum: `["USD", "USDC"]` |
| Instrument type | `linear` or `reversed` (reversed = inverse) | `instrument_type` schema |
| Price index for BTC options | `btc_usd` or `btc_usdc` | `price_index` field; correlated index IDs |
| Tick sizes | Variable per instrument; block trades have own tick size | `block_trade_tick_size` field |
| Commission model | Maker/taker/block-trade tiers per instrument | `maker_commission`, `taker_commission`, `block_trade_commission` |
| Settlement types | `settlement`, `delivery`, `bankruptcy` | `settlement_type` enum |
| Delivery prices | USD-denominated, retrieved per index for historical settlement | `public/get_delivery_prices` |
| Order book amounts for options | Denominated in BTC (underlying), not USD | Options Data Collection article |
| DVOL index | Annualised volatility in decimal; candles with open/high/low/close | `public/get_volatility_index_data` response |
| Mark IV | Annualised implied volatility in decimal for mark price | `mark_iv` field in book_summary |
| Greeks from ticker channels | Delta, gamma, theta, vega, rho per option | ticker channel specification |

### 4.2 Black-Scholes Engine Conventions (from existing code)

| Item | Convention |
|---|---|
| Spot (S) | USD price of 1 BTC |
| Strike (K) | USD strike price |
| Rate (r) | Continuous risk-free rate, decimal (0.04 = 4%) |
| Vol (σ) | Annualised, decimal (0.45 = 45%) |
| T | Time to expiry in years |
| Price output | USD per unit (100 shares assumption in standard BS) |
| Delta | Unitless, 0–1 for calls, -1–0 for puts |
| Gamma | Per 1 USD move in spot |
| Vega | Per 1.00 (100%) change in vol; divide by 100 for per-vol-point |
| Theta | Per year; divide by 365 for per-day |
| premium_pct_at_delta | Percentage of spot (100 × option_price / S) |

### 4.3 Waterfall Conventions

| Item | Convention |
|---|---|
| Notional | spot × quantity (USD) |
| Seller discount | percentage × notional (USD) |
| Fee | percentage × notional (USD) |
| Fee BTC equivalent | fee_usd / spot |
| Effective cost | per-BTC cost net of discount, fee, and option overlay |

---

## 5. Requirements Relevant to A1–A6

### 5.1 A1 (Pricing & Greeks)
- **Deribit instrument_type** convention: `reversed` (= inverse) means BTC-settled payoff. The formula must be derived from Deribit's official settlement mechanics — not from the reconciled audit's section 10.8.
- **Numeraire:** Deribit specifies `settlement_currency = BTC` for BTC options, `quote_currency = USD`. The economic payoff must be computed in the correct numeraire, then separately mapped to settlement mechanics.
- **Contract size:** Deribit BTC options have contract_size=1 (BTC). The standard BS formula returns a price per share (assumes 100-share lot). The engine must handle contract scaling explicitly.
- **Required venues:** Deribit inverse (BTC-settled), Deribit linear (USDC-settled), CME options on BTC futures (cash-settled in USD), OTC (bespoke settlement). Each requires separate settlement modelling.
- **Black-76:** Required for CME options on Bitcoin futures — must use futures price as underlying, with appropriate discounting.

### 5.2 A2 (Data & Vol Layer)
- **Deribit endpoints already mapped:** `public/get_instruments`, `public/get_book_summary_by_currency`, `public/get_index_price`, `public/get_volatility_index_data` are pre-integrated in `vol/dvol_feed.py`.
- **Rate limits documented:** `get_instruments` has 1 req/s sustained limit — must use `instrument.state`/`instrument.creation` WS channels for chain tracking per Options Data Collection article.
- **Historical data source:** CryptoDataDownload is the approved fallback; Massive is the primary spot source.
- **Mark IV:** Available from `book_summary` field `mark_iv` and ticker channel `mark_iv`.
- **Interest rate:** Available from `book_summary` field `interest_rate` for IV calculations.

### 5.3 A3 (Scenarios/Backtest/MC)
- **Delivery prices:** `public/get_delivery_prices` provides historical settlement prices for backtesting option expiries.
- **Missing historical option chains must carry `model_reconstructed` provenance** per authoritative_corrections.md §5.

### 5.4 A4 (Execution/Impact)
- **Block trading thresholds:** `block_trade_min_trade_amount` (e.g., 25 contracts for BTC options), `block_trade_commission`, `block_trade_tick_size`.
- **RFQ workflow:** Taker creates RFQ, makers quote, taker accepts — documentation covers the institutional execution path.
- **Fee model:** Deribit maker/taker fees per instrument; separate Asymmetrica 0.5% fee modelled independently.
- **Tranche scheduling:** Must respect `min_trade_amount`, `qty_tick_size`, and block trade thresholds.

### 5.5 A5 (Reports/Charts/Demo)
- **Corrected chart pack:** The mislabeled "Covered Put Strategy" (actually Long BTC + Short Put) requires canonical strategy classification derived from position legs, not from chart title, per both mandate_sanitized.md and authoritative_corrections.md.
- **Payoff functions must match backtest engine.**

### 5.6 A6 (QA/Integration)
- **contracts.md must be frozen before A1–A5 implementation.**
- **A6 must freeze:**
  - Separate settlement fields (venue, product, settlement_mechanism, settlement_currency, exercise_style, contract_multiplier, delivery_price_convention)
  - Pure function signatures (price, greeks, strike_for_delta, implied_vol, premium_pct_at_delta)
  - Pydantic models at configuration/API boundaries only
  - Dataclass for numerical internals (OptionQuote preserved)
- **Cross-validation:** QuantLib parity on all pricing functions; every human-facing number independently re-derived.

---

## 6. Corrections Required to Existing Audits, Requirements, or Agent Briefs

### 6.1 Agent Brief A1 (pricing.md)
**Error:** References "inverse-option adjustment (BTC-settled payoff: price in BTC = USD price / index)."
**Correction:** The formula "price in BTC = USD price / index" is a simplistic USD→BTC conversion that does not capture Deribit's actual inverse option settlement. The reconciled audit's section 10.8 also presents formulas that authoritative_corrections.md §4 explicitly prohibits implementing. The correct formula must be re-derived from Deribit's official `settlement_currency`, `instrument_type: reversed`, `contract_size`, and delivery price conventions — and independently unit-checked. The A1 brief must reference the deriving procedure, not a pre-canned formula.

### 6.2 Agent Brief A2 (data_vol.md)
**Gap:** References "Deribit specs/Block RFQ, CME specs/Rule 526-538/BRR/BVX" under the data plan table. The CME rulebook files are not downloaded — only the download script exists. A2 cannot read CME contract specifications from the reference library.
**Correction:** Either download CME documents before A2 starts, or narrow A2's scope to Deribit-only until CME materials are available.

### 6.3 Authoritative Corrections §5 (Source Ownership)
**Observation:** CryptoDataDownload is listed as "an explicitly labelled fallback." The existing code already correctly labels Massive as primary and can label CDD as fallback. No correction needed, but A2 must implement the provenance labelling.

### 6.4 ISDA Definitions
**Error in ISDA/00_README.md:** States "Do not substitute the press release or the contractual-standards whitepaper for the actual Definitions." This is correct, but the actual Definitions are not in the repository. The press release provides only scope (NDFs and options on BTC/ETH initially), not executable contract language.
**Impact:** Until the actual ISDA Digital Asset Derivatives Definitions are obtained, OTC settlement terms cannot be fully specified. This blocks contracts.md if OTC is a required venue.

---

## 7. Conflicts Between Sources and Which Source Prevails

### 7.1 Authoritative Corrections vs Reconciled Audit (inverse-BTC formulas)
**Conflict:** The reconciled audit's section 10.8 proposes inverse-BTC option formulas. authoritative_corrections.md §4 prohibits their implementation.
**Resolution:** authoritative_corrections.md prevails. Deribit's official API spec (`settlement_currency`, `instrument_type: reversed`, `contract_size`, `delivery_price` convention) must be the basis for any inverse-option modelling.

### 7.2 Mandate vs Agent Brief A1 (formula detail)
**Conflict:** A1 brief says "price in BTC = USD price / index" as an inverse adjustment convention. authoritative_corrections.md §4 requires full derivation from current official venue documentation.
**Resolution:** authoritative_corrections.md prevails. The simple division formula is incomplete and must be replaced with a documented derivation from Deribit's actual settlement mechanics.

### 7.3 Build Plan Data Table vs Reference Library Contents
**Conflict:** Build Plan §4 table lists "Venue rulebooks (Deribit specs/Block RFQ, CME specs/Rule 526-538/BRR/BVX, Binance VIP-OTC, ISDA DA definitions summaries, FINMA guidance)" as fetched into `docs/` during Sprint 1. CME rulebooks are not present in the reference library; Binance and FINMA are not represented at all.
**Resolution:** The build plan's data table represents aspirational/planned content, not current state. This is non-blocking for implementation but must be tracked. Deribit documentation is comprehensive and sufficient for Deribit-venue implementation. CME, Binance, and FINMA materials are absent.

### 7.4 OptionQuote dataclass preservation
**Conflict:** Some audit recommendations may have suggested Pydantic migration for OptionQuote.
**Resolution:** authoritative_corrections.md §3 prevails — preserve existing tested OptionQuote dataclass unless contracts.md explicitly approves a migration.

---

## 8. Files That Are Unreadable, Incomplete, Obsolete, or Duplicated

### 8.1 CME Directory — Empty Except for Download Script

| File | Status |
|---|---|
| `cme/download_cme_crypto.py` | Download script only — no actual CME documents retrieved |
| `cme/rulebook/` | Does not exist |
| `cme/product_pages/` | Does not exist |
| `cme/download_manifest.csv` | Does not exist |

**Reason:** Script requires network access to `cmegroup.com` and was not executed or failed during the download phase.

### 8.2 ISDA — Actual Definitions Missing

| File | Status |
|---|---|
| ISDA Digital Asset Derivatives Definitions (full document) | Not present. `00_README.md` confirms it requires ISDA account and licence |
| Press release PDF | Present but truncated in text cache (101 lines — contains only the text before the standard ISDA boilerplate) |
| Whitepaper PDF | Present; full text cached (1365 lines) |

### 8.3 Deribit — Empty Subdirectories

| Directory | Contents |
|---|---|
| `api/01_market_data/` | Empty |
| `api/02_account_risk/` | Empty |
| `api/03_trading/` | Empty |
| `api/04_websocket/` | Empty |

**Explanation:** These were planned directory structures in the download tool but all downloaded content was placed in `pages/` mapped to URL paths. The empty directories are scaffolding artifacts, not missing content. The actual market data, account, trading, and WebSocket documentation is present under `pages/api-reference/` and `pages/subscriptions/`.

### 8.4 Massive — Non-Crypto Documentation

A large portion of the Massive documentation covers non-crypto assets (forex, futures, indices, stocks, options on equities, economy, alternative data). This is expected — the download script fetched the full `llms.txt` index. The relevant crypto-specific pages are correctly populated.

---

## 9. Missing Information or Documentation

### 9.1 CRITICAL — ISDA Digital Asset Derivatives Definitions

| Item | Detail |
|---|---|
| **Title:** | ISDA Digital Asset Derivatives Definitions (full document) |
| **Source:** | `https://www.isda.org/book/isda-digital-asset-derivatives-definitions/` |
| **Why needed:** | Defines OTC settlement terms for digital asset derivatives (NDFs and options), disruption events, fallback provisions, and interaction with ISDA Master Agreement. Without it, OTC venue classification and settlement specification in contracts.md cannot be authoritative. |
| **Priority:** | HIGH |
| **Blocks contracts.md?** | Only if OTC venue is in scope for contracts.md. If contracts.md covers only Deribit and CME, it does not block. But the Build Plan §4 data table explicitly lists "ISDA DA definitions summaries." |
| **Blocks implementation?** | Does not block Deribit-based A1-A5 implementation. Blocks OTC-specific settlement modelling. |

### 9.2 HIGH — CME Rulebook and Product Specifications

| Item | Detail |
|---|---|
| **Title:** | CME Rulebook (crypto-relevant chapters: Bitcoin futures, options on Bitcoin futures, Micro Bitcoin futures/options, Bitcoin Friday Futures options), plus BRR/BVX methodology |
| **Source:** | `https://www.cmegroup.com/rulebook/CME/` (targeted via `download_cme_crypto.py`) |
| **Why needed:** | CME options on Bitcoin futures have different contract specifications, exercise style (American), settlement mechanics (cash-settled to BRR), and multipliers than Deribit options. The A1 brief requires Black-76 on futures (relevant to CME), and A6 must specify separate settlement fields per venue. |
| **Priority:** | HIGH |
| **Blocks contracts.md?** | Only if CME venue is required in contracts.md. The Build Plan includes CME as a venue. |
| **Blocks implementation?** | Yes, for A1 Black-76 implementation and CME pricing paths. Does not block Deribit-only implementation. |
| **Recommended action:** | Run `download_cme_crypto.py` from the Hetzner box with network access to retrieve the rulebook PDFs. |

### 9.3 MEDIUM — Deribit Official Contract Specifications (beyond API)

| Item | Detail |
|---|---|
| **Title:** | Deribit options contract specifications (exercise style, settlement timing, delivery price calculation methodology) |
| **Source:** | Deribit website — contract specs page (not fully captured in API docs) |
| **Why needed:** | The API docs describe instrument metadata endpoints but do not exhaustively document: (a) the precise delivery price calculation at expiry; (b) exercise style (European vs American) for BTC options; (c) the exact timestamp at expiry; (d) the relation between settlement at `delivered` state and the delivery price retrieval via `get_delivery_prices`. |
| **Priority:** | MEDIUM |
| **Blocks contracts.md?** | Potentially — exercise style and settlement timing are required fields per authoritative_corrections.md §1. |
| **Blocks implementation?** | Not immediately — can be initially modelled as European (standard for Deribit BTC options based on industry practice), but final confirmation from official documentation is needed for contracts.md. |

### 9.4 MEDIUM — Binance VIP-OTC Documentation

| Item | Detail |
|---|---|
| **Title:** | Binance VIP-OTC trading rules and specifications |
| **Why needed:** | Listed in Build Plan §4 data table |
| **Priority:** | MEDIUM |
| **Blocks implementation?** | No — Binance OTC is not referenced in any agent brief or mandate requirement. It is listed as a data source but no implementation task depends on it. |

### 9.5 MEDIUM — FINMA Guidance

| Item | Detail |
|---|---|
| **Title:** | FINMA guidance on digital asset derivatives |
| **Why needed:** | Listed in Build Plan §4 data table; may be relevant for Swiss regulatory compliance |
| **Priority:** | MEDIUM |
| **Blocks implementation?** | No — no agent brief references Swiss regulatory compliance. This is a production-gate item only. |

### 9.6 LOW — Deribit Historical Mark Price History (partial coverage)

| Item | Detail |
|---|---|
| **Observation:** | `public/get_mark_price_history` is available only for "a subset of options that participate in volatility index calculations" per the API docs. All other instruments (including futures, perpetuals) return empty lists. |
| **Priority:** | LOW |
| **Impact:** | A2's historical backfill must use trade prints and book summaries, not mark price history, for most instruments. This is a known API limitation, not a documentation gap. |

### 9.7 LOW — Historical Option Data (Live Data Only for Deribit)

| Item | Detail |
|---|---|
| **Observation:** | Deribit API provides live instrument data and recent settlement history but no long-history option chain snapshots or historical IV surfaces. The data plan lists CryptoDataDownload as the free-tier source for this. |
| **Priority:** | LOW (already planned) |
| **Impact:** | Addressed by the Build Plan's data strategy. No new documentation needed. |

---

## 10. Final Status

### COMPLETE WITH NON-BLOCKING GAPS

**Rationale:**

**Complete for current phase (Sprint 0 → contracts.md drafting):**
- Deribit API documentation is comprehensive and current (2026-07-28). The instrument model, settlement types, contract specifications, block trading workflow, RFQ protocol, market data channels, rate limits, and commission structures are all documented and verified.
- Massive spot data documentation is complete and current (2026-07-28).
- The existing codebase (Sprint 0) is running, tested (9/9 green), and documented.
- Agent briefs A1-A6 exist and are reviewed for correctness.

**Non-blocking gaps:**
1. **ISDA Definitions:** Missing but obtainable. Blocks OTC settlement specification in contracts.md only if OTC is required. Deribit and CME implementation can proceed without it.
2. **CME rulebooks:** Missing but downloadable via the provided script. Blocks CME-specific implementation in A1 (Black-76) and A6 (venue-specific contract specs). Deribit-only implementation can proceed.
3. **Deribit contract spec nuances:** Exercise style and settlement timing details require confirmation from Deribit's product pages (not fully captured in API docs). Industry convention (European for BTC options) provides a working assumption, but contracts.md should note this as requiring confirmation.
4. **Binance and FINMA materials:** Absent but not on any agent's critical path.

**Recommended next actions before contracts.md freeze:**
1. Execute `download_cme_crypto.py` to retrieve CME rulebook PDFs.
2. Obtain ISDA Digital Asset Derivatives Definitions through ISDA account.
3. Confirm Deribit BTC option exercise style and settlement timing from Deribit's product specification pages or support channel.
4. Archive these documents with SHA-256 checksums and retrieval timestamps as done for Deribit and Massive.

**All corrections identified in §6 of this report must be applied to agent briefs before implementation begins.**
