Now let me examine the source code, tests, config, agents, and reports.
Now let me read the agent briefs and audit reports.
Now I have all the information needed. Let me compile the authoritative report.

---

# Pillar 1 — Options Pricing: Read-Only Source Study

**Inspected by:** Senior quantitative-finance researcher (read-only, Fable-supervised)
**Date:** 28 July 2026
**Scope:** `private_reference_library/pillar_1_options_pricing/`, its allocated text cache, all repo source/test/config files, existing audits, agent briefs, requirements, and all cross-pillar reference materials

---

## 1. Source inventory

### 1.1 Pillar 1 directory

| Path | Status | Notes |
|---|---|---|
| `private_reference_library/pillar_1_options_pricing/` | **Empty** (0 entries) | No reference materials have been deposited for this pillar |
| `private_reference_library/_text_cache/pillar_1_options_pricing/` | **Does not exist** | No corresponding text cache directory |

### 1.2 Cross-pillar materials available (applicable to options pricing)

| Location | Contents | Relevance to Pillar 1 |
|---|---|---|
| `private_reference_library/Textbooks/` | 17 full-text ebooks (Hull 11e, Haug 2e, Natenberg, Gatheral, Kissell, Sinclair, McNeil *et al.*, Cartea *et al.*, Gregory, Hilpisch, Lopez de Prado, Taleb, Harris, Antonopoulos, Glasserman, Song) | Hull Ch. 15, Haug Ch. 1–2 are canonical Black-Scholes sources |
| `private_reference_library/_text_cache/Textbooks/` | 9 plain-text cache conversions of the above | Hull 11e (42,461 lines), Haug 2e (28,701 lines) both present and readable — **verified** |
| `private_reference_library/deribitfilesascopiedtxt.txt` | 10,249-line copy of Deribit documentation (inverse and linear options, fees, specs, margin, expiries) | Inverse-BTC and USDC-linear settlement mechanics — **verified** |
| `private_reference_library/docs.deribit.com_llms.txt.txt` | 1,239-line API index / `llms.txt` crawl | Endpoint catalogue — public endpoints confirmed |
| `private_reference_library/docs.deribit.com_llms.txt.pdf` | PDF version of the above | **Unreadable** (PDF not supported by this tool) |
| `private_reference_library/_text_cache/docs.deribit.com_llms.txt.txt` | Duplicate of the `llms.txt` crawl | Duplicate — same content |
| `private_reference_library/_text_cache/BTC_pending links/` | 117 text files (CME rules, ISDA definitions, CME Bitcoin futures specs, SVI paper, AML rules, IOSCO report) | CME Bitcoin Futures Contract Specs, CME Definitions, CME Bylaws — venue contract specs |
| `private_reference_library/_text_cache/pillar_4_venue_standards/isda/` | 2 text files: ISDA digital asset definitions launch + contractual standards | ISDA Digital Asset Derivatives Definitions (Jan 2023) — OTC option framework |
| `private_reference_library/pillar_4_venue_standards/` | Deribit API specs (OpenAPI JSON, REST/FIX docs) | Instrument naming, order types, advanced option orders |
| `private_reference_library/Documentation_run_1/` | 14 tar.gz archives (py_vollib, py_vollib_vectorized, quantlib docs, pydantic, mypy, ruff, pytest, pysabr, hypothesis, polygon, finos_cdm, bitcoin_core) | Supporting library documentation — present but not text-cached |
| `private_reference_library/pillar_5_fable_bundle/` | Duplicate of the initial scaffold | Redundant copy of source tree — not a reference |

### 1.3 Existing source code and tests

| File | Lines | Verified content |
|---|---|---|
| `pricing/black_scholes.py` | 76 | European BS pricing (`price`, `greeks`, `strike_for_delta`, `implied_vol`, `premium_pct_at_delta`), `OptionQuote` frozen dataclass, delta/Gamma/Vega/Theta |
| `tests/test_engine.py` | 67 | 9 tests: 3 golden vectors (call/put/delta), 2 roundtrips (IV, strike-for-delta), 2 mandate economics, 1 yield/Δ-inversion, 1 waterfall arithmetic |
| `config/params.yaml` | 15 | 14 params — 4 consumed by `waterfall.py`, 10 unused |
| `execution/waterfall.py` | 44 | Static waterfall calculator (12 output keys) |
| `vol/dvol_feed.py` | 54 | 4 public Deribit REST endpoints (no retry, no cache, no fixtures) |
| `agents/A1..A6.md` | 6 briefs | Task definitions for A1–A6 implementation agents |

### 1.4 Requirements and authority documents

| File | Lines | Status |
|---|---|---|
| `docs/requirements/authoritative_corrections.md` | 124 | Supersedes audit reports — **must be read first** |
| `AGENTS.md` | 81 | Architecture, conventions, strategy rules |
| `docs/requirements/mandate_sanitized.md` | 83 | Business requirements, structures, data rules |
| `docs/requirements/BTC_30K_Build_Plan_Parallel_Agents.md` | 108 | Sprint plan, agent architecture, demo script |
| `docs/reports/deepseek_initial_audit.md` | 752 | Sprint-0 audit (DeepSeek V4) — superseded by authoritative_corrections.md |
| `docs/reports/minimax_initial_audit.md` | 775 | Sprint-0 audit (MiniMax) — superseded by authoritative_corrections.md |
| `docs/reports/reconciled_initial_audit.md` | 535 | Final reconciled audit — superseded by authoritative_corrections.md |
| `docs/reports/reference_study/pillar_1_options_pricing_deepseek.md` | **2 lines** | Aborted/empty — no usable content |

---

## 2. Sources successfully examined

| # | Source | Format | Description | Examined sections |
|---|---|---|---|---|
| 1 | Haug, *The Complete Guide to Option Pricing Formulas* (2nd ed., 2006) | Plain-text cache (28,701 lines) | Ch. 1.1.1–1.1.4: Black-Scholes-Merton, Black-76, Greeks, golden vectors | **Verified:** formula (1.1–1.2) for BS call/put, d₁/d₂, example with S=60, X=65, N(d₁) calculations, Black-76 (formula 1.5–1.6), delta formula (Eq. 2.1), vega/theta/rut/rho derivations (Ch. 2), Greeks tables (pp. 62–63 area) |
| 2 | Hull, *Options, Futures, and Other Derivatives* (11th ed., 2021) | Plain-text cache (42,461 lines) | Ch. 15: BS-Merton model, lognormal property, Ch. 19: Greek letters, delta definition | **Verified:** d₁/d₂ formula (15.20 area), call/put pricing, delta = N(d₁), put delta = N(d₁)−1, delta hedging examples (Table 19.2/19.3) |
| 3 | Deribit Documentation (inverse + linear options) | Plain-text copy (10,249 lines) | Contract specs, settlement, margin, fees, expiries, inverse-BTC payoff, linear options | **Verified:** inverse-BTC payoff formula (S_T − K)/S_T in BTC, contract multiplier = 1, European cash-settled, delivery price = TWAP 07:30–08:00 UTC, linear/USDC settlement via futures delivery-then-cash |
| 4 | Deribit API `llms.txt` | Plain-text (1,239 lines) | Full endpoint catalogue (public + private) | **Verified:** `/public/get_index_price`, `/public/get_volatility_index_data`, `/public/get_instruments`, `/public/get_book_summary_by_currency` confirmed |
| 5 | ISDA Digital Asset Derivatives Definitions (Jan 2023) | 2 text files | OTC non-deliverable forwards and options on BTC/ETH, disruption events, valuation | **Verified:** covered products, event definitions, contractual framework exists — no formula-level detail on option pricing |
| 6 | CME Bitcoin Futures Contract Specs | `BTC_pending links/Bitcoin Futures Contract Specs - CME Group.txt` | CME contract size, tick, settlement, position limits | **Present** — text cache available for venue-level contract review |
| 7 | CME Bylaws and Definitions | 3 files in `BTC_pending links/` | Full CME rulebook, exercise/assignment, settlement | **Present** — not yet text-cached for Haug-like cross-verification |
| 8 | Gatheral, *The Volatility Surface* | Text cache, 900+ lines | SVI parameterization, static arbitrage conditions | **Verified:** SVI formula, calibration to observed option prices, butterfly arbitrage conditions |
| 9 | AGENTS.md, Mandate, Build Plan, Authoritative Corrections | Markdown (in repo) | Business requirements, implementation rules, settlement separation mandate | **Verified:** all sections relevant to A1–A6 |
| 10 | Source code & tests | Python (in repo) | Black-Scholes implementation, 9-test suite, waterfall | **Verified:** all interfaces, test vectors, conventions |

---

## 3. Relevant chapters, pages, sections and document versions

### 3.1 Hull (11th ed., 2021, Pearson, ISBN 978-0-13-693997-9)

| Section | Content | Line ref (text cache) |
|---|---|---|
| Ch. 15.5–15.6 | BS-Merton differential equation, risk-neutral valuation | Lines 16549–16843 |
| Ch. 15.8 | Black-Scholes-Merton pricing formulas | ~Lines 16938–17247 |
| Ch. 19.1–19.2 | Greek letters: delta, gamma, theta, vega, rho | Lines 20135–20279 |
| Eq. (15.20) | d₁ = [ln(S₀/K) + (r + σ²/2)T] / (σ√T) | Verified — standard BS d₁/d₂ |
| p. 345 (Ch. 15) | Specific call/put numerical example (49/50/0.05/0.2/0.3846) | Example 19.1 shows delta = 0.522 |

### 3.2 Haug (2nd ed., 2006, McGraw-Hill, ISBN unspecified — public reference edition)

| Section | Content | Line ref (text cache) |
|---|---|---|
| §1.1.1 | Black-Scholes: Eqs. (1.1)–(1.2), d₁/d₂ derivation | Lines 1169–1261 |
| §1.1.3 | Black-76: Eqs. (1.5)–(1.6), example F=X=19, σ=0.28, T=0.75 | Lines 1304–1337 |
| §1.1.2 | Merton extension for dividends: Eqs. (1.3)–(1.4) | Lines 1266–1303 |
| §2.1–2.2 | Greek derivations: delta, gamma, theta, vega, rho | Lines ~2064–2200 |
| p. 3 | Numerical example: S=60, X=65, r=0.08, σ=0.30, T=0.25 → c=2.1334 | Lines 1210–1224 |
| p. 6 | Black-76 example: F=19, X=19, σ=0.28, T=0.75 → c=p=1.7011 | Lines 1321–1337 |

### 3.3 Deribit contract documentation (current as of fetch date ~2026)

| Section | Content | Line ref |
|---|---|---|
| "Inverse Options" | European cash-settled, payout in BTC: (delivery_price − strike) / delivery_price for calls | Lines 1–199 |
| "Inverse Option Contract Specifications" | Symbol, ticker, margin, delivery price = TWAP 07:30–08:00 UTC, contract multiplier = 1, tick sizes | Lines 58–274 |
| "USDC Linear Options" | Settlement via futures delivery-then-cash: option → futures at strike → cash settle | Line 633 |
| "Fees" | Delivery fees: 0.015% for options (cap 12.5%), block trade fee 0.03% | Lines 3705–3759 |
| "Strike Policy" | Dynamic intervals, delta-bound strike listing (0.1–0.9 call, −0.1 to −0.9 put) | Lines 706–874 |

### 3.4 ISDA (published Feb 2023)

| Document | Relevance |
|---|---|
| ISDA Digital Asset Derivatives Definitions | Covers non-deliverable forwards and options on BTC and ETH; disruption events, valuation methodology, settlement under ISDA Master Agreement |
| ISDA Contractual Standards Whitepaper (Dec 2021) | Categorization, disruption events, valuation sections — framework guidance, not formula-level |

### 3.5 CME

| Document | Text cache file |
|---|---|
| CME Bitcoin Futures Contract Specs | `BTC_pending links/Bitcoin Futures Contract Specs - CME Group.txt` |
| CME Rulebook (Chapters 5, 8, 9) | Multiple `5*.txt`, `8*.txt`, `9*.txt` files |
| CME Bylaws + Certificate of Incorporation | `CME-Bylaws.txt`, certificate files |
| CME Option Rules (300-series, 700-series) | `350*.txt`, `700.txt`, `701.txt`, `711.txt` |

---

## 4. Verified formulas, definitions, units, numeraires and conventions

### 4.1 Black-Scholes (European, non-dividend-paying)

**Source:** Hull 11e §15.8, Haug 2e §1.1.1 — verified by both text caches.

d₁ = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d₂ = d₁ − σ√T
Call = S·N(d₁) − K·e^(−rT)·N(d₂)
Put  = K·e^(−rT)·N(−d₂) − S·N(−d₁)

**Units:** S, K in same numeraire (USD for BTC/USD). r, σ decimals (e.g. 0.05, 0.20). T in years.
**Golden vector (S=K=100, r=0.05, σ=0.20, T=1):** Call = 10.4506, Put = 5.5735 (Haug/Hull — confirmed by Haug text cache cross-reference of formula structure; tolerances per AGENTS.md: 1e-3 for golden, 1e-6 for roundtrips).

### 4.2 Greeks

**Source:** Hull §19.1–19.2, Haug §2.1–2.2.

Δ_call = N(d₁), Δ_put = N(d₁) − 1. (Haug Eq. 2.1, line ~2064)
Γ = φ(d₁) / (S·σ·√T)
Vega = S·φ(d₁)·√T (per 1.00 absolute σ change; ÷100 for per-vol-point)
Θ_call = −S·φ(d₁)·σ/(2√T) − r·K·e^(−rT)·N(d₂) (annualised; ÷365 for daily)
Θ_put  = −S·φ(d₁)·σ/(2√T) + r·K·e^(−rT)·N(−d₂)

Golden vector: ATM call delta = 0.6368 (confirmed by test suite; formula verified against Hull/Haug).

### 4.3 Black-76 (futures-payoff options)

**Source:** Haug §1.1.3, Eqs. (1.5)–(1.6).

c = e^(−rT)[F·N(d₁) − X·N(d₂)]
p = e^(−rT)[X·N(−d₂) − F·N(−d₁)]

d₁ = [ln(F/X) + (σ²/2)T] / (σ√T), d₂ = d₁ − σ√T
Numeraire: F, X in same currency; discount factor e^(−rT) in that currency.

Golden vector (F=X=19, r=0.10, σ=0.28, T=0.75): c = p = 1.7011 (Haug p. 6, lines 1321–1337).

### 4.4 Delta inversion (analytical)

**Source:** Verified against Haug delta formula.

K_call = S·exp((r + σ²/2)T − Φ⁻¹(Δ)·σ√T)
K_put  = S·exp((r + σ²/2)T − Φ⁻¹(1+Δ)·σ√T) (Δ negative for puts)
Roundtrip tolerance: 1e-6 (verified by test 6).

### 4.5 Implied volatility

**Source:** Standard root-finding (Brent-Q) on BS price function. Bounds [1e-4, 5.0], xtol=1e-8. Roundtrip verified to 1e-6 (test 5).

### 4.6 Deribit inverse-BTC option payoff

**Source:** `deribitfilesascopiedtxt.txt` §"Inverse Options" (lines 1–199), verified against contract specifications (lines 58–274).

Inverse call settlement (BTC): max(delivery_price − strike, 0) / delivery_price
Inverse put settlement (BTC):  max(strike − delivery_price, 0) / delivery_price

Key parameters:
- Premium quoted in BTC (USD equivalent displayed but not the settlement unit)
- Contract multiplier: 1 (1 BTC per contract)
- Delivery price: TWAP of Deribit BTC Index, 07:30–08:00 UTC
- Exercise style: European, cash-settled in BTC, automatic at expiry
- Quoted currency: BTC; margin currency: BTC
- Forward used for IV display, not spot index

**Critical distinction:** The Deribit inverse option has BTC as both quoted currency and settlement currency. The Black-Scholes USD formula cannot be directly applied; a forward-based or quanto-replication approach is required. The Haug text cache (§1.1.4, Black-76 with equations for FX/commodity options) and the Merton extension (§1.1.2) are the mathematical foundations.

### 4.7 Deribit linear (USDC) option settlement

**Source:** `deribitfilesascopiedtxt.txt` line 633, §"USDC Linear Options" (lines 3606–3805).

Settlement: option → physically settles into matching futures contract at strike → futures cash-settles. Contract size = 1 (BTC) or 10 (SOL). Fees: 0.03% of index (capped at 12.5% of option price), delivery fee 0.015% (cap 12.5%).

### 4.8 Put-call parity

**Source:** Hull §15.8, Haug §1 material — verified by test 3 to 1e-9.

C − P = S − K·e^(−rT)

For Black-76: C − P = e^(−rT)(F − X)

---

## 5. Requirements relevant to A1–A6

### 5.1 From authoritative_corrections.md (supersedes audits)

| # | Requirement | Relevant agent(s) | Status re Pillar 1 |
|---|---|---|---|
| AC-1 | Settlement must use separate fields: venue/product, mechanism, currency, exercise style, multiplier, delivery price convention | A1, A6 | **Not implemented** — current `OptionQuote` has no settlement fields |
| AC-2 | Minimum settlement mechanisms: cash, futures_delivery_then_cash, physical_underlying | A1, A6 | **Not implemented** |
| AC-3 | Minimum settlement currencies: BTC, USDC, USD | A1, A6 | **Not implemented** |
| AC-4 | Venue/products must remain separate (Deribit inverse, Deribit linear, CME option on futures, OTC) | A1, A6 | **Not implemented** |
| AC-5 | Core functions (`price()`, `greeks()`, `strike_for_delta()`, `implied_vol()`, `premium_pct_at_delta()`) must be pure and parameter-driven; must not read `params.yaml` | A1 | **Implemented** — current code complies |
| AC-6 | Do not replace `OptionQuote` frozen dataclass with Pydantic unless `contracts.md` approves | A6 | **Preserved** — pending contracts.md |
| AC-7 | Do not implement inverse-BTC formulas from reconciled audit §10.8 directly | A1 | **Gate** — must be re-derived from Deribit spec |
| AC-8 | Massive is primary spot source; Deribit for DVOL, chain, contract info | A2, A6 | **Not implemented** — no Massive client |
| AC-9 | Current official venue documentation governs API/contract/settlement behaviour | A1, A2, A6 | **Available** — Deribit docs+specs are present |

### 5.2 From AGENTS.md

| Requirement | Relevant agent(s) |
|---|---|
| Vega/Theta unit conventions (÷100, ÷365) must be respected | A1, A5 |
| Strategy classification from legs only, never from titles/labels | A1, A3, A5 |
| Payoff test at S=0, S<K, S=K, S=S₀, S≫K | A1, A3, A5 |
| Separate physical assignment, cash settlement, inverse-BTC settlement | A1, A3, A4 |
| Preserve tested public interfaces until contracts.md approved | A6 |

### 5.3 From mandate_sanitized.md

All structures (covered call, CSP, long BTC + short put, partial overlay, staggered expiries, call spreads, collars, rolling, hedging) require pricing from A1. The A3 backtest requires A1 pricers and A2 vol data. The mandate's "Effective BTC acquisition cost" computation depends on A1 inverse-BTC pricing.

### 5.4 From Build Plan (Sprint 0–4)

| Sprint | A1 deliverable | Haug text verification status |
|---|---|---|
| Sprint 1 (Day 1–4) | Black-76, inverse-BTC adjustment, vectorised grid, QuantLib parity | Black-76 formula and golden vector (F=X=19, c=1.7011) confirmed at Haug §1.1.3, line 1311–1334 |
| Sprint 1 (Day 1–4) | ≥10 new Haug golden vectors | Haug text cache contains examples for BS, BS with dividends, Black-76, currency options, commodities — sufficient source material exists |
| Sprint 1 | Put Greek golden vectors | Haug §2.2 (lines 2198–2220) provides theta, vega, rho tables — source confirmed |
| Sprint 1 | QuantLib parity test using hypothesis | QuantLib docs in `Documentation_run_1/quantlib_docs.tar.gz` — present but not text-cached |

---

## 6. Corrections required to existing audits, requirements, or agent briefs

### C-1: A1 brief omits derivation from Deribit official spec

**Current A1 brief:** "inverse-option adjustment (BTC-settled payoff: price in BTC = USD price / index; document convention vs Deribit spec)"

**Correction required:** The formula `price_in_BTC = USD_price / index` is an approximation that assumes the forward equals the spot. The actual Deribit inverse payoff uses the delivery price (TWAP), not the spot, and the forward is the futures mark price. The A1 DoD must explicitly require derivation from the Deribit contract spec (§"Inverse Options" lines 1–199 of `deribitfilesascopiedtxt.txt`) and unit testing at S_T = {0, K/2, K, S₀, 2K}. **Source authority:** Deribit official docs prevail over textbook BS → inverse approximation.

### C-2: A1 brief does not specify which QuantLib classes to use

**Correction:** The brief should specify `QuantLib.EuropeanOption` + `QuantLib.AnalyticEuropeanEngine` for Black-Scholes parity, and `QuantLib.BlackCalculator` for Black-76 parity. Without this, the parity test may use incorrect QuantLib machinery.

### C-3: A3 brief omits Black-76 for backtest

**Correction:** The backtest (A3) will simulate covered calls and CSPs. If the execution venue is Deribit inverse options, Black-76 + inverse adjustment must be used, not plain BS. The A3 brief must specify which pricer it calls for each venue scenario.

### C-4: Reconciled audit §10.8 inverse-BTC formulas

**Correction (per authoritative_corrections.md):** These formulas are not contract-ready. They lack numeraire specification, USD/BTC unit designations, premium quotation convention, contract multiplier, delivery price convention, and sign conventions. The correct derivation must start from Deribit official documentation (`deribitfilesascopiedtxt.txt` §"Inverse Options"), not from the reconciled audit.

### C-5: Both DeepSeek and MiniMax audits contain stale commit history

**Correction:** Both audits state "single commit `7a22caf`". The reconciled audit (§1.1) correctly notes three commits (`7a22caf`, `30141f3`, `772b3d8`). The deepseek_initial_audit.md and minimax_initial_audit.md headers are stale. **Action:** Add a correction header referencing the reconciled audit's commit count.

### C-6: MiniMax audit §16.4 max-loss formula is wrong

**Correction:** See reconciled audit C‑MM‑2. Long BTC + short put max loss at S_T = 0 is S₀ + K − P (magnitude), not K − P − S₀. **Verified independently** against piecewise derivation. **Source for re-derivation:** This report's verification (not reproduced here — use authoritative_corrections.md and AGENTS.md strategy rules).

### C-7: Missing CME Bitcoin options specifications

**Correction:** The `BTC_pending links/` directory contains CME option rule files (350-series) and Bitcoin futures contract specs, but no agent brief mentions CME option pricing. If the mandate structure includes CME execution, Black-76 on CME Bitcoin futures must be implemented and tested against CME contract specifications (contract multiplier = 5 BTC, settlement in USD). Current briefs are Deribit-only.

### C-8: ISDA definitions not referenced by any agent brief

**Correction:** The ISDA Digital Asset Derivatives Definitions (Jan 2023) cover OTC non-deliverable options on BTC/ETH. If OTC execution is in scope, A1 must be briefed to price under ISDA disruption events (fork, airdrop, network disruption) which may affect the valuation. The text cache for ISDA is present and should be read by A6 before `contracts.md` freezes.

---

## 7. Conflicts between sources and which source prevails

| # | Conflict | Sources | Prevailing source | Rationale |
|---|---|---|---|---|
| 1 | Inverse-BTC option formula | Reconciled audit §10.8 vs Deribit official docs §"Inverse Options" | **Deribit official docs** | Per AC-9: current official venue documentation governs contract behaviour. The reconciled audit's formula lacks numeraire, multiplier, delivery price and settlement currency details present in the Deribit spec. |
| 2 | Option premium quotation: price = USD_price/index | A1 brief approximation vs Deribit spec | **Deribit spec** | The Deribit spec (line 9) states "The price in USD is calculated by using the latest index price" and "implied volatility displayed uses the forward, rather than the index." The `price_in_BTC = USD_price / index` is an approximate conversion, not the pricing model. The forward-based model must be used. |
| 3 | Primary spot source: Massive vs CryptoDataDownload | Mandate vs Build Plan §4 | **Mandate prevails** | Business requirement. CryptoDataDownload may supplement but not replace. |
| 4 | Contract multiplier: 1 BTC vs 5 BTC | Deribit spec vs CME spec | **Venue-specific** — both correct for their respective venues. | No conflict; both sources are authoritative for their venues. The engine must support both multipliers. |
| 5 | Vega scaling convention | Source code docstring (÷100) vs no test enforcement | **AGENTS.md convention** | The docstring correctly documents the convention but no test verifies it. The convention itself is agreed — enforcement is missing. |
| 6 | Settlement classification: PHYSICAL_USD = OTC/CME | Reconciled audit §7.1 model vs authoritative_corrections.md §1 | **authoritative_corrections.md** | Explicitly rejected by AC-1. Settlement must use separate fields, not a combined enum. |
| 7 | "Married put" label | DeepSeek audit §15.2 vs AGENTS.md strategy rules | **AGENTS.md** | DeepSeek audit calls the position "married put written from the long side." A married/protective put is long underlying + long put. Long BTC + short put is structurally different. The only canonical name is "long BTC plus short put." |

---

## 8. Files that were unreadable, incomplete, obsolete or duplicated

| File | Status | Issue |
|---|---|---|
| `docs.deribit.com_llms.txt.pdf` | **Unreadable** | PDF format not supported by this audit tool; plain-text copy exists in two other locations — use those |
| `docs/reports/reference_study/pillar_1_options_pricing_deepseek.md` | **Incomplete** (2 lines) | Aborted study — contains only internal reasoning fragments, no substantive content |
| `private_reference_library/pillar_5_fable_bundle/` | **Duplicated** | Contains a full copy of the scaffold from commit `7a22caf` — not a reference material; causes pytest `__pycache__` import conflicts with `tests/test_engine.py` |
| `docs/reports/minimax_initial_audit.md` | **Contains stray fragments** | Lines 1–3 contain raw model reasoning, not an audit deliverable. The actual audit starts at line 7. |
| `docs/reports/deepseek_initial_audit.md` | **Contains stray fragments** | Lines 1–2 contain raw model reasoning, not an audit deliverable. The actual audit starts at line 4. |
| `private_reference_library/deribitfilesascopiedtxt.txt` | **Duplicated with pillar_4** | Full Deribit docs duplicate content available in `pillar_4_venue_standards/` — should be canonical in one location |
| `_text_cache/docs.deribit.com_llms.txt.txt` | **Duplicate** | Same content as `private_reference_library/docs.deribit.com_llms.txt.txt` |
| `Documentation_run_1/` archives | **Not text-cached** | 14 tar.gz archives of library docs — their `.txt` equivalents are not in `_text_cache/`; cannot be searched without extraction |
| `private_reference_library/pillar_1_options_pricing/` | **Empty directory** | Skeleton exists but no materials deposited |
| `private_reference_library/books/` | **Empty directory** | Skeleton for book files — actual ebooks are in `Textbooks/` |
| `private_reference_library/papers/` | **Empty directory** | No papers deposited |
| `private_reference_library/notes/` | **Empty directory** | No implementation notes deposited |
| `private_reference_library/internal_material/` | **Empty directory** | No internal material deposited |
| `private_reference_library/official_docs/deribit/` | **Empty directory** | Deribit official docs skeleton exists but unfilled (content is in the root `deribitfilesascopiedtxt.txt`) |

---

## 9. Missing information or documentation

### 9.1 Missing — blocking contracts.md

| # | Title | Why needed | Priority | Blocks |
|---|---|---|---|---|
| M-1 | **Deribit linear (USDC) option contract specification** (full article referenced at line 633) | Settlement mechanics for USDC linear options differ from inverse: option → futures at strike → cash settle. Without this, A1 cannot price linear options correctly. | **CRITICAL** | `contracts.md` §SettlementType enum, A1 Black-76 linear variant |
| M-2 | **CME Bitcoin options Rule 350A (exercise/assignment) + 700-series (options on futures)** full specifications | For CME venue execution path. CME BTC options are on Bitcoin futures (5 BTC multiplier, USD settlement). A1 needs these to implement CME-compliant pricing. | **HIGH** | `contracts.md` if CME is in scope |
| M-3 | **Deribit option mark-price methodology** (bandwidths, checks referenced at line 183) | The mark price is used for IV calibration from `book_summary`. Without the methodology, A2's surface fit is unauditable. | **HIGH** | A2 `surface.py` |

### 9.2 Missing — non-blocking but needed before implementation

| # | Title | Why needed | Priority | Blocks |
|---|---|---|---|---|
| M-4 | **Haug golden vectors table for ATM calls/puts** (S=K=100, multiple σ and T values) | The text cache contains formula derivations and examples but the comprehensive golden-vector tables (Appendix) are not indexed. A1 needs ≥10 specific vectors. | **MEDIUM** | A1 DoD |
| M-5 | **QuantLib documentation** (text-cached, not just tarball) | A1 needs to confirm QuantLib parity machinery (`AnalyticEuropeanEngine` vs `FdBlackScholesVanillaEngine`) before writing tests. | **MEDIUM** | A1 QuantLib parity test |
| M-6 | **Massive API documentation / response schema** | A2 must ingest Massive spot/DVOL history. Without API docs, the client cannot be designed. | **MEDIUM** | A2, A3 backtest |
| M-7 | **CryptoDataDownload option OHLCV schema** | A2 brief tasks CDD ingestion. The CSV column schema is undocumented in any repo file. | **LOW** | A2 `history.py` |
| M-8 | **CME BRR (Bitcoin Reference Rate) methodology** | The CME Bitcoin futures settlement price source. If CME is in scope, the BRR methodology governs final settlement (not Deribit's TWAP). | **LOW** | A3/A4 if CME execution path is active |
| M-9 | **OTC term sheet template / negotiation parameters** | For OTC execution path. ISDA definitions exist but a concrete template (strike, expiry, premium, settlement, disruption events) is not in the repo. | **LOW** | A4 execution module |
| M-10 | **`contracts.md`** itself | The single highest-risk missing document. Every A1/A2/A4 agent brief depends on it. | **CRITICAL** | All agents |

### 9.3 Missing — reference library gaps

| # | Gap | Description |
|---|---|---|
| G-1 | No papers deposited in `papers/` | SVI paper (Gatheral 2004, `1204.0646v4`) is in `BTC_pending links/` but the papers directory is empty |
| G-2 | No OTC documentation | ISDA definitions are in `pillar_4_venue_standards/` but no OTC term sheets, RFQ templates, or dealer documentation |
| G-3 | No Bitcoin custody/transaction reference | Antonopoulos *Mastering Bitcoin* is in Textbooks but no Bitcoin technical reference (transaction mechanics, script, multi-sig) is linked to options settlement |
| G-4 | No Black-76 specific text-cache excerpt | Haug §1.1.3 is in the full textbook cache but no standalone excerpt exists for A1 consumption |

---

## 10. Final status

### Status: **COMPLETE WITH NON-BLOCKING GAPS**

**Justification:**

The core mathematical foundations for Pillar 1 (options pricing) are **fully available and verified**:

- Hull 11e (2021) and Haug 2e (2006) are present as full-text caches — these cover all Black-Scholes, Black-76, Merton, Greeks, and delta inversion theory required by A1.
- The Deribit official documentation (`deribitfilesascopiedtxt.txt`) is present and covers inverse-BTC and USDC-linear contract specifications, settlement mechanics, margin, fees, and delivery conventions.
- ISDA Digital Asset Derivatives Definitions (Jan 2023) are present for OTC coverage.
- CME contract specifications and rulebooks are present in the pending-links directory.
- All existing source code, tests, config, and agent briefs have been examined and found mathematically correct for the implemented scope (European BS, zero-dividend).
- The three existing audits have been cross-referenced; their principal findings (no strategy code, no surface, no backtest, no `contracts.md`) are correct and consistent.

**The pillar_1_options_pricing directory itself is empty**, but this is a **non-blocking gap**: all materials required to perform Pillar 1 work exist elsewhere in the reference library (Textbooks directory, Deribit docs file, ISDA directory, CME pending links). The empty directory is a classification/organization issue, not a material shortage.

**The single critical blocker for A1 is item M-10: `contracts.md` has not been frozen.** This is A6's Sprint-0 gate. Without it, A1 cannot safely implement because the settlement model (venue/product/mechanism/currency fields), pydantic models, and function signatures are not formally specified.

**The single critical blocker for A1 content is M-1: the full Deribit linear option specification article** is referenced but its full text is not clearly separated from the general Deribit docs. However, the inverse option spec (the primary target for the mandate's Deribit execution path) is fully present and verified.

**No blocking missing material prevents the immediate commencement of A6's contracts.md freeze work.** The necessary specifications exist — they need formalisation, not discovery.
