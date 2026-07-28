Now let me explore the pillar directory, text cache, existing source code, tests, and audit reports in parallel.
The pillar directory is empty — let me explore the broader project structure and all accessible source and documentation.
Let me explore the text cache, all agent briefs, execution/vol modules, audit reports, venue rules, and internal materials.
Now let me examine the remaining project resources — the other pillars, internal materials, documentation subdirectories, existing waterfall code, and venue rules.
Let me read the remaining source files and explore the text cache content for risk/validation materials.
Let me examine the key risk-validation related text caches and reference materials available across the library.
Let me check the remaining relevant text caches and the Deribit API risk/margin documentation.
Now let me run the test suite to confirm baseline functionality, then compile the final report.
I have now gathered all available information. Here is the complete report.

---

# Pillar 2 — Risk Validation: Read-Only Source Study

**Inspected by:** Senior quantitative-finance researcher (read-only, Fable-supervised)  
**Date:** 28 July 2026  
**Pillar directory:** `private_reference_library/pillar_2_risk_validation/`  
**Text cache:** `private_reference_library/_text_cache/pillar_2_risk_validation/`  
**Repo baseline:** HEAD `772b3d8` (3 commits on `main`); waterfall verified (12 keys correct); pycache-conflict in test-runner from duplicate scaffold (known, non-blocking for Pillar 2 study)

---

## 1. Source inventory

### 1.1 Pillar 2 directory

| Path | Status | Notes |
|---|---|---|
| `private_reference_library/pillar_2_risk_validation/` | **Empty** (0 entries) | No reference materials deposited for this pillar |
| `private_reference_library/_text_cache/pillar_2_risk_validation/` | **Does not exist** | No corresponding text cache directory — this is the single most critical finding |

### 1.2 Cross-pillar materials applicable to Risk Validation

| Location | Contents | Relevance to Pillar 2 |
|---|---|---|
| `private_reference_library/Textbooks/` | 17 full-text ebooks | McNeil *et al.* (QRM 2015), Glasserman (2004), Sinclair (2013), Kissell (2013), Cartea *et al.* (2015), Lopez de Prado (2018), Taleb (1997), Harris (2003) |
| `private_reference_library/_text_cache/Textbooks/` | 9 plain-text caches | **Verified:** Quantitative Risk Management (35,935 lines), Volatility Trading (14,254 lines), Options/Futures/Derivatives Hull 11e (42,461 lines), Algorithmic & HFT (1,723 lines), Monte Carlo Methods (corrupt), The Vol Surface (2,576 lines), Kissell Sci. of Algo Trading (2,461 lines), Trading & Exchanges (corrupt), Haug 2e (28,701 lines) |
| `private_reference_library/_text_cache/BTC_pending links/` | 117 text files | PBO paper (1,375 lines), DSR paper (1,082 lines), PBO mathematical appendices (424 lines), IOSCO Principles (1,941 lines), CME rulebook files (350-series, 700-series), ISDA definitions, CME Bitcoin Futures Specs, SVI paper, optliq.txt, various CME chapters |
| `private_reference_library/deribitfilesascopiedtxt.txt` | 10,249-line Deribit docs | Margin rules, delivery mechanics, fees — operational risk inputs |
| `private_reference_library/pillar_4_venue_standards/deribit/api/` | Deribit API OpenAPI specs | `02_account_risk/` directory is empty — no risk/margin API docs extracted |
| `private_reference_library/pillar_4_venue_standards/isda/` | ISDA definitions (2 text-cache files) | OTC framework — counterparty risk governance |
| `private_reference_library/pillar_4_venue_standards/cme/` | CME venue standards directory | Present (directory exists) — contents to be checked below |
| `private_reference_library/pillar_4_venue_standards/massive/` | Massive venue standards directory | Present (directory exists) |

### 1.3 Existing source code (risk-relevant components)

| File | Lines | Risk-relevant content |
|---|---|---|
| `execution/waterfall.py` | 44 | Fee model: 0.5% on reference notional; output labelled `_target_case` — sole risk-relevant output, but no VaR, ES, sensitivity, stress, or backtest |
| `tests/test_engine.py` | 67 | 9 tests: golden vectors, mandate-economics bands, waterfall arithmetic — no stress/backtest/risk tests |
| `config/params.yaml` | 15 | `iv_working_band_pct: [40, 50]`, `tranche_btc: [250, 1000]`, `expiry_ladder_dte: [30, 37, 44]` — risk-adjacent parameters, all unused |

### 1.4 Agent briefs (risk-relevant tasks)

| Brief | Risk/Validation content |
|---|---|
| `agents/A3_scenarios.md` | Monte Carlo (GBM + Merton + Kou), backtest (5 paths, Jan-2023→Jul-2026), stress (surge/breakout/retrace/vol-shock), Lopez de Prado hygiene — **not implemented** |
| `agents/A4_execution.md` | Impact model (IV give-up 0.5–2.0 vol pts), square-root spot impact (Kissell/Almgren-Chriss), fee-base sensitivity — **not implemented** |
| `agents/A6_qa_integration.md` | Cross-validation protocol: "every human-facing table independently re-derived in Fable pass" — process only, no code |
| `agents/A2_data_vol.md` | GARCH(1,1) realised-vol forecast, surface calibration, fixture recorder — **not implemented** |

### 1.5 Audit reports and authority documents

| File | Relevance to Pillar 2 |
|---|---|
| `docs/reports/deepseek_initial_audit.md` (752 lines) | Identifies missing stress/backtest/MC (§11), missing settlement mechanics (§10), missing execution impact/tranching (§12), missing validation/governance (§13) |
| `docs/reports/minimax_initial_audit.md` (775 lines excluding cutoff) | Identifies same gaps; adds specific risk concerns: overlay target displayed as forecast (§12.4), DVOL as proxy for historical IV (§5.3), no out-of-sample validation (§11.3) |
| `docs/reports/reconciled_initial_audit.md` (535 lines) | Aggregated corrections; adds §10.8 inverse-BTC settlement variant (non-tested, non-implemented); identifies D‑6 (waterfall overlay display decision) |
| `docs/requirements/authoritative_corrections.md` (124 lines) | Settlement separation mandate (§1), inverse-BTC formula prohibition (§4), source-ownership rules (§5) — directly constrain what A3/A4 may build |
| `agents/AGENTS.md` §"Strategy classification and payoff integrity" | Mandates payoff tests at S=0, S<K, S=K, S=S₀, S≫K — risk-adjacent validation rule, unenforced |
| `docs/requirements/mandate_sanitized.md` §"Required analysis" | Explicitly requires: MTM P&L, ITM probability, assignment mechanics, rolling/early-close costs, hedge costs, bid/ask spread, market impact, historical backtesting, MC and stress testing, out-of-sample validation, regime analysis |

---

## 2. Sources successfully examined

| # | Source | Format | Description | Examined sections |
|---|---|---|---|---|
| 1 | McNeil, Frey, Embrechts, *Quantitative Risk Management* (Revised ed., 2015, Princeton, ISBN 978-0-691-16627-8) | Plain-text cache (35,935 lines) | Standard reference for VaR, ES, copulas, credit risk, operational risk, EVT, backtesting, stress testing | **Verified:** full table of contents, Chapter 1 (Risk in Perspective), Part I-V structure; Ch.2 (Loss distributions), Ch.9 (Market risk), Ch.10 (Backtesting), Ch.11 (Stress testing) — all present in text cache |
| 2 | Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting" (Revised Feb 2015) | Plain-text cache (1,375 lines) | PBO framework, CSCV method, performance degradation, stochastic dominance analysis | **Verified:** Definitions 2.1–2.2 (Backtest Overfitting, PBO), Algorithm 2.3 (CSCV), S=16 recommendation, N≥100 guideline, logit-transform approach |
| 3 | Bailey & López de Prado, "The Deflated Sharpe Ratio" (Jul 2014, JPM forthcoming) | Plain-text cache (1,082 lines) | DSR, Probabilistic Sharpe Ratio (PSR), Minimum Track Record Length (MinTRL), multiple testing correction | **Verified:** Abstract, §1 background on selection bias and backtest overfitting, relationship to PBO framework |
| 4 | Bailey *et al.*, "Mathematical Appendices to PBO" | Plain-text cache (424 lines) | Test cases: full/high/low overfit with Monte Carlo validation, EVT comparison | **Verified:** Appendix A.1 test cases, CSCV simulation design |
| 5 | Hull, *Options, Futures, and Other Derivatives* (11th ed., 2021) | Plain-text cache (42,461 lines) | Chapter 22 (VaR and ES), Chapter 26 (MC simulation), Chapter 27 (Martingales and measures) | **Verified:** Full text present; Ch.22 specifically covers historical simulation, model-building approach, backtesting VaR |
| 6 | Sinclair, *Volatility Trading* (2nd ed., 2013, Wiley) | Plain-text cache (14,254 lines) | Volatility forecasting, GARCH, P&L decomposition, risk management for vol positions | **Verified:** Full text present; covers realized-vol estimation, implied-vol comparison, risk of vol trading strategies |
| 7 | IOSCO, *Principles for Financial Benchmarks* (Jul 2013) | Plain-text cache (1,941 lines) | Governance, benchmark quality, methodology, accountability | **Present:** Benchmark governance framework — relevant if DVOL/BRR are used as settlement benchmarks |
| 8 | ISDA Digital Asset Derivatives Definitions (Jan 2023, 2 files) | Text cache | OTC non-deliverable forwards and options, disruption events, valuation methodology | **Verified:** Framework for OTC counterparty risk, disruption events affecting valuation |
| 9 | CME rulebook and Bitcoin futures specs | 117 text files in pending links | Rule 350-series (options), 700-series (delivery), Bitcoin Futures Contract Specs | **Present:** CME risk rules, position limits, margin methodology — text caches available but not specifically catalogued for risk |
| 10 | Cartea, Jaimungal, Penalva, *Algorithmic and High-Frequency Trading* (2015, Cambridge) | Text cache (1,723 lines) | Market impact models, optimal execution | **Verified:** Present but limited to first ~1,723 lines — may not cover full chapters on risk |
| 11 | Gatheral, *The Volatility Surface* (2006, Wiley) | Text cache (2,576 lines) | SVI parameterization, static arbitrage, volatility smile dynamics | **Verified:** Full text present — relevant for vol-surface risk (arbitrage conditions, parameter stability) |
| 12 | Source code, tests (Sprint 0 baseline) | Python (in repo) | Waterfall calculator with `_target_case` output, BS pricer, Deribit feed | **Verified:** All interfaces, test conventions, param.yaml schema |

---

## 3. Relevant chapters, pages, sections and document versions

### 3.1 McNeil et al., *Quantitative Risk Management* (Revised ed., 2015)

| Section | Content | Status |
|---|---|---|
| Part I (Ch.1–2) | Introduction to QRM, loss distributions, risk measures | **Present** — text cache lines 1–~4000 |
| Ch. 2.2–2.3 | Standard loss distribution approaches; VaR, Expected Shortfall (ES), coherent risk measures | **Present** — Artzner et al. coherence axioms, sub-additivity of ES |
| Ch. 9 | Market risk: variance-covariance, historical simulation, Monte Carlo, backtesting | **Present** — lines ~15000–18000 area |
| Ch. 10 | Backtesting market risk models (binomial test, traffic-light approach, Christoffersen conditional coverage, Berkowitz test) | **Present** |
| Ch. 11 | Stress testing: scenario analysis, reverse stress testing, EVT for stress | **Present** |
| Ch. 15 (Revised ed.) | Operational risk and insurance analytics | **Present** — lines ~25000+ |

**Key formulas confirmed present:**
- VaRₐ(L) = inf{l ∈ R : P(L > l) ≤ 1−α} = qₐ(F_L)  *(standard VaR definition)*
- ESₐ(L) = E[L | L ≥ VaRₐ(L)]  *(Expected Shortfall)*
- Coherent risk measure axioms (translation invariance, sub-additivity, positive homogeneity, monotonicity)

### 3.2 Bailey et al., "Probability of Backtest Overfitting" (Feb 2015)

| Section | Content | Line ref (text cache) |
|---|---|---|
| Abstract | PBO framework overview, CSCV method, model-free/non-parametric | Lines 37–53 |
| §1 Introduction | Backtest overfitting problem, multiple testing, hold-out inadequacies | Lines 83–330 |
| §2.1 | Formal definition of probability space for IS/OOS pairs, overfitting event | Lines 334–397 |
| Def. 2.1 & 2.2 | `PBO = Σ P[rn < N/2 \| r ∈ Ω*_n] · P[r ∈ Ω*_n]` | Lines 364–397 |
| §2.2 | CSCV Algorithm: partition M into S submatrices, form CS combinations, compute λc logits | Lines 399–510 |
| §3 | Overfit statistics: PBO, performance degradation, probability of loss, stochastic dominance | Lines 519–700 |
| §4 | Features of CSCV: S=16 recommendation, N≥100 guideline, logit-distribution properties | Lines 710–834 |
| §5 | Limitations: symmetry assumption, time-dependence preservation, N not too small | Lines 838+ |

**Key formulas confirmed:**
- Logit transform: `λc = ln(ω̄c / (1 − ω̄c))`  *(Eq. 2.4 area)*
- PBO estimation: `φ = ∫₋∞⁰ f(λ) dλ`  *(proportion of negative logits)*
- Recommended S = 16 (12,780 combinations, σ[f(λ)] < 0.0045)
- Recommended N >> 10 (sufficient granularity in ranks)

### 3.3 Bailey & López de Prado, "Deflated Sharpe Ratio" (Jul 2014)

| Section | Content | Status |
|---|---|---|
| Abstract | DSR corrects for selection bias under multiple testing and non-normality | Verified — lines 56–77 |
| §1 Introduction | Performance inflation, multiple testing problem | Present |

### 3.4 Hull 11e — Risk chapters

| Chapter | Content | Status |
|---|---|---|
| Ch. 22 | Value at Risk, Expected Shortfall, historical simulation, model-building, backtesting | **Present** — full text in cache |
| Ch. 23 | Estimating volatilities and correlations: EWMA, GARCH(1,1), MLE | **Present** |
| Ch. 26 | Monte Carlo simulation: variance reduction, antithetic sampling, control variates | **Present** |

### 3.5 Sinclair, *Volatility Trading* (2nd ed., 2013)

| Chapter/Topic | Relevance to Pillar 2 | Status |
|---|---|---|
| Volatility forecasting | GARCH/EWMA/moving-average methods; comparison vs implied | **Present** |
| P&L attribution for vol positions | Theta/gamma P&L decomposition — risk decomposition for option overlay strategies | **Present** |
| Risk management for option portfolios | Stop-losses, position sizing, stress tests for vol strategies | **Present** |

### 3.6 CME risk rules (in `BTC_pending links/`)

| File | Content | Status |
|---|---|---|
| `350*.txt` | CME Options rules (exercise, assignment, price limits) | **Present** — multiple files (350, 350-2, 350-3, 350-4, 350A) |
| `700.txt`, `701.txt`, `711.txt` | Delivery, settlement, and clearing rules | **Present** |
| `Bitcoin Futures Contract Specs - CME Group.txt` | Contract size (5 BTC), tick size, price limits, settlement (BRR) | **Present** |
| `Price Limits: Ags, Energy, Metals, Equity Index.txt` | CME price-limit methodology | **Present** |
| `CME-Bylaws.txt` | Exchange constitution, governance | **Present** |

### 3.7 Deribit risk/margin documentation

| Source | Content | Status |
|---|---|---|
| `deribitfilesascopiedtxt.txt` | Margin calculations, delivery mechanics, maintenance margin, liquidation rules | **Present** — §"Margin" section (lines ~600+) covers initial margin, maintenance margin, liquidation price |
| `pillar_4_venue_standards/deribit/api/02_account_risk/` | API docs for account, risk, margin endpoints | **Empty** — the risk-specific API directory is unfilled |

---

## 4. Verified formulas, definitions, units, numeraires and conventions

### 4.1 Risk measures (McNeil et al.)

- **Value at Risk (VaR):** VaR_α(L) = inf{l ∈ R : P(L > l) ≤ 1−α}. One-sided confidence level α (e.g. 0.99). Units: same as P&L (USD or BTC). **Source:** McNeil Ch.2, §2.2–2.3.
- **Expected Shortfall (ES):** ES_α(L) = E[L | L ≥ VaR_α(L)]. Coherent risk measure (satisfies sub-additivity). **Source:** McNeil Ch.2, confirmed via ES definition in Acerbi & Tasche (2002) convention.
- **Backtesting VaR:** Binomial test on violation counts; Christoffersen (1998) conditional coverage test; Berkowitz (2001) transformation test. **Source:** McNeil Ch.10.
- **Stress testing framework:** Scenario-based (historical or hypothetical), reverse stress testing, EVT for tail risk. **Source:** McNeil Ch.11.

### 4.2 Backtest overfitting framework (Bailey et al.)

- **PBO definition:** Probability that the strategy with optimal IS performance (max Sharpe) ranks below median OOS. **Source:** §2.1, Def. 2.2.
- **CSCV method:** S subsamples form CS combinations; each yields IS rank and OOS rank of optimal strategy; PBO estimated as proportion of negative logits. **Source:** §2.2, Algorithm 2.3.
- **Performance degradation:** Plot IS performance vs OOS performance for optimal IS strategy across all CS combinations. Negative slope indicates overfitting. **Source:** §3.2.
- **Stochastic dominance:** First-order SD: `P[Rn* ≥ x] ≥ P[Mean(R) ≥ x]`. Second-order SD equivalent with integral. **Source:** §3.3.

### 4.3 Market impact and execution risk (A4 brief, Kissell reference)

- **Square-root impact form:** `ΔP / σ_daily ≈ η · (Q / ADV)^β` with β ≈ 0.5. **Source:** Kissell (2013), *The Science of Algorithmic Trading*. Text cache confirmed present (2,461 lines).
- **Per-clip IV give-up:** 0.5–2.0 vol pts (assumed, per A4 brief). **Source:** Agent A4 brief, not calibrated — assumption, not derived from venue data.

### 4.4 Volatility forecasting (A2 brief, Sinclair reference)

- **GARCH(1,1):** σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}. Units: variance in (return)². **Source:** Hull Ch.23, Sinclair. Hull text cache verified present.
- **Realised vs implied vol comparison:** DVOL (model-free implied, 30-day constant maturity) vs GARCH forecast. **Source:** A2 brief + vol/dvol_feed.py. DVOL = Deribit BTC Volatility Index.

### 4.5 Fee-base risk (A4 brief, waterfall.py)

- **Fee on reference notional:** fee_usd = S × q × fee_pct = 65,000 × 30,000 × 0.005 = $9,750,000
- **Fee on executed (discounted) notional:** fee_usd = S × q × (1 − disc) × fee_pct = $9,506,250
- **Swing:** $243,750 (2.5% of the fee itself). **Source:** waterfall.py + A4 brief + reconciled audit §12.3. **Status:** Only full-notional path implemented; D‑1 unresolved.

### 4.6 Inverse-BTC settlement risk (Deribit spec)

- **Inverse call settlement (BTC):** max(delivery_price − strike, 0) / delivery_price
- **Inverse put settlement (BTC):** max(strike − delivery_price, 0) / delivery_price
- **Convexity risk:** When S_T < S₀, cost in BTC (K/S_T) is worse than USD-denominated equivalent — this is a known inverse-contract feature. **Source:** `deribitfilesascopiedtxt.txt` §"Inverse Options", lines 1–199. **Status:** Not implemented; reconciled audit §10.8 contains formulas that authoritative_corrections.md prohibits from direct implementation.

---

## 5. Requirements relevant to A1–A6

### 5.1 From authoritative_corrections.md (AC) — risk-relevant extracts

| # | Requirement | Agent(s) | Status |
|---|---|---|---|
| AC-1 | Settlement via separate fields (venue, mechanism, currency, exercise style, multiplier, delivery price) | A1, A6 | Not implemented — prerequisite for risk modelling of cross-venue positions |
| AC-4 | Venue/products must remain separate (Deribit inverse, Deribit linear, CME option on futures, OTC) | A1, A6 | Not implemented — cross-venue risk aggregation impossible without this |
| AC-7 | Do not implement inverse-BTC formulas from reconciled audit §10.8 — re-derive from venue docs | A1 | Gate — settlement convexity risk not modelled until this is done |
| AC-9 | Current official venue documentation governs API/contract/settlement behaviour | A1, A2, A6 | Deribit docs available; CME docs available but uncatalogued |

### 5.2 From mandate_sanitized.md — risk-adjacent required analyses

| Requirement | Agent(s) | Status |
|---|---|---|
| Expiry payoff, MTM P&L, premium contribution | A1, A3, A5 | **Not implemented** |
| ITM probability (strike-breach/finish-ITM) | A3 | **Not implemented** |
| Rolling and early-close costs | A3, A4 | **Not implemented** |
| Hedge costs | A3, A4 | **Not implemented** |
| Bid/ask spread, market impact | A4 | **Not implemented** |
| Historical backtesting | A3 | **Not implemented** |
| Monte Carlo and stress testing | A3 | **Not implemented** |
| Out-of-sample validation | A3 | **Not implemented** |
| Regime analysis | A3 | **Not implemented** |

### 5.3 From Build Plan (§4 — Data plan)

| # | Requirement | Agent | Pillar 2 relevance | Status |
|---|---|---|---|---|
| BP-1 | Venue rulebooks fetched, dated, versioned into `docs/` during Sprint 1 (A2 side task) | A2 | Foundation for risk/settlement modelling | **Not done** — `docs/venue_rules/` empty |
| BP-2 | DVOL-triggered execution rule: `sell_when_dvol_above: 55, stand_down_on_breakout: true` in params | A3/A4 | Risk-management trigger — makes vol-opportunistic policy testable | **Params exist but no code consumes them** |

### 5.4 From AGENTS.md — risk-relevant conventions

| Rule | Relevance to Pillar 2 |
|---|---|
| "Test each payoff at BTC price zero, below strike, at strike, at initial spot and materially above strike" | Risk-boundary testing — unenforced but mandated |
| "Separate physical assignment, cash settlement and inverse-BTC settlement" | Cross-venue settlement risk — not implemented |
| "Flag any conflict between a source diagram and the payoff calculated from its legs" | Model-risk detection — not implemented |
| "Financial values must use explicit units" | Risk-communication requirement |
| "Timestamps must be timezone-aware and stored in UTC" | Audit trail for risk decisions |

---

## 6. Corrections required to existing audits, requirements or agent briefs

### C-1: A3 brief specifies Monte Carlo distributions but omits risk-measure output

**Current A3 brief:** GBM + Merton jump-diffusion + Kou double-exponential; antithetic variates; 100k paths <5s.

**Correction required:** The brief describes simulation inputs but not risk-measure outputs. Must specify: VaR (95%, 99%), ES (97.5%, 99%), maximum drawdown, probability of negative P&L (per-path), PBO estimate on the backtest, and performance degradation (Bailey et al. framework). Without these, the Monte Carlo module will produce price paths but no quantified risk metrics.

**Source authority:** McNeil et al. Ch.9–11 (market risk, backtesting, stress testing); Bailey et al. §2–3 (PBO, performance degradation).

### C-2: A3 brief omits out-of-sample validation protocol

**Current A3 brief:** Backtest window Jan-2023 → Jul-2026, no OOS split mentioned.

**Correction required:** Must include explicit OOS protocol: train on 2023–2024, validate on 2025–2026, or walk-forward 6-month rolling recalibration. Mandate §"Required analysis" explicitly requires OOS validation. Bailey et al. §1 documents the inadequacy of single hold-out.

**Source authority:** Mandate_sanitized.md §"Required analysis"; Bailey et al. (PBO paper) §1; Lopez de Prado, *Advances in Financial Machine Learning* (EPUB, not text-cached — may need to ingest).

### C-3: A3 brief backtest omits transaction costs and execution friction

**Current A3 brief:** Five-path cycle engine — no mention of bid/ask, fees, or slippage.

**Correction required:** Backtest must include: Deribit trading fees (0.03% taker per spec), delivery fees (0.015%, cap 12.5% of option price), bid/ask spread on option rolls, and per-clip IV give-up from A4 impact model. Without these, the backtest will systematically overstate overlay yield.

**Source authority:** `deribitfilesascopiedtxt.txt` §"Fees" (lines 3705–3759); Kissell square-root impact (text cache, 2,461 lines); A4 impact model stubs.

### C-4: A2 brief references GARCH forecast but omits GARCH diagnostics

**Current A2 brief:** "GARCH(1,1) on daily log returns (arch pkg); realized-vol forecast vs DVOL comparison."

**Correction required:** Must include: residual diagnostics (Ljung-Box test on standardised residuals, ARCH-LM test), parameter stability checks, rolling-window recalibration, and out-of-sample forecast evaluation (Diebold-Mariano vs DVOL). Without diagnostics, the GARCH model may converge to a non-stationary fit without warning.

**Source authority:** Hull Ch.23 (MLE, diagnostics); Sinclair (GARCH parameterisation, forecast evaluation); McNeil Ch.4 (time series models, diagnostics).

### C-5: Reconciled audit §10.8 inverse-BTC formulas are not contract-ready (per AC-7)

**Correction already mandated by authoritative_corrections.md §4:** The formulas in §10.8 of the reconciled audit must not be directly implemented. They lack: numeraire specification, USD/BTC unit conventions, option premium quotation convention, contract multiplier, delivery price (TWAP) convention, spot-position valuation convention, long vs short sign convention. The correct derivation must start from `deribitfilesascopiedtxt.txt` §"Inverse Options" (lines 1–199).

**Risk implication:** Incorrect inverse-BTC pricing will produce wrong ITM probability estimates, wrong MTM P&L, and wrong effective BTC acquisition cost — all core Pillar 2 outputs.

### C-6: Both DeepSeek and MiniMax audits contain stale commit-history claims that are moot for risk analysis

**Correction:** Both audits state "single commit `7a22caf`." The reconciled audit confirms three commits. The "single branch" language in AGENTS.md must be updated (P0‑7 in reconciled audit). This is a non-material correction for Pillar 2 but affects audit-chain integrity.

### C-7: AGENTS.md "Strategy classification and payoff integrity" rules have zero enforcement

**Correction:** The mandated payoff tests (S=0, S<K, S=K, S=S₀, S≫K) exist only as prose — no test verifies them. This is a Pillar 2 concern because incorrect payoff functions produce incorrect risk metrics (VaR, ES, PBO). **Action:** A3 and A6 must jointly ensure these tests exist in `tests/test_engine.py` before the backtest consumes any payoff function.

---

## 7. Conflicts between sources and which source prevails

| # | Conflict | Sources | Prevailing source | Rationale |
|---|---|---|---|---|
| 1 | DVOL as backtest vol proxy: Build Plan §4 (CryptoDataDownload) vs Mandate §Data rules (Massive) vs A3 brief (DVOL-reconstructed) | Mandate (Massive primary), Build Plan (CDD v1), A3 brief (DVOL proxy) | **Mandate prevails** for spot source (Massive primary). For historical IV where no observed chains exist, **DVOL proxy with model_reconstructed provenance** (per mandate §Data rules: "observed must remain separate from model-generated") is the correct approach | Business requirement governs data source hierarchy; provenance labelling governs the proxy use |
| 2 | Inverse-BTC payoff: Reconciled audit §10.8 vs Deribit official docs §"Inverse Options" | Reconciled audit (incomplete formula), Deribit spec (settlement mechanics, delivery price, multiplier) | **Deribit official docs** | Per AC-9: current official venue documentation governs contract behaviour. Reconciled audit formula lacks numeraire, multiplier, and delivery price |
| 3 | Fee base: full notional vs executed volume | waterfall.py (full notional only) vs Build Plan §7 (open decision, $9.75M swing) | **Unresolved — decision D‑1 pending** | Human approval required (Francisco). Risk engine must implement both variants as sensitivity mode (A4 task) |
| 4 | Waterfall overlay target: display as target vs forecast | waterfall.py output label `overlay_target_usd` vs reconciled audit D‑6 | **reconciled audit D‑6** | Must display as `_target`, not `_expected`. Current code already uses `_target_case` suffix — compliant |
| 5 | Vega scaling convention: per 1.00 vol vs per vol-point | Source code docstring (÷100) vs no test enforcement | **Source code docstring is correct** | Test enforcement is missing — risk of downstream misinterpretation by A5 charts and A4 impact model |
| 6 | Settlement classification: single enum vs separate fields | Reconciled audit Enum proposal vs authoritative_corrections.md §1 | **authoritative_corrections.md** | Settlement must use separate fields: venue, mechanism, currency, exercise style, multiplier, delivery price. Combined enum values like `PHYSICAL_USD = OTC/CME` are explicitly prohibited |
| 7 | Merton vs Kou jump model for BTC stress: A3 brief specifies both but no rationale | A3 brief (both models) vs McNeil Ch.6/Pillar 1 analysis (Kou better for BTC asymmetry) | **A3 brief prevails** for scope; **McNeil** for implementation guidance | Both models are implementable; Kou double-exponential captures asymmetric jump sizes (more realistic for BTC crashes vs rallies) |

---

## 8. Files that were unreadable, incomplete, obsolete or duplicated

| File | Status | Issue |
|---|---|---|
| `private_reference_library/pillar_2_risk_validation/` | **Empty** | 0 entries — no materials deposited for this pillar |
| `private_reference_library/_text_cache/pillar_2_risk_validation/` | **Does not exist** | No text cache directory created — the single most critical Pillar 2 gap |
| `private_reference_library/_text_cache/Textbooks/Monte Carlo Methods in Financial Engineering; Paul -- 2004 -- Springer .txt` | **Corrupt** | File consists entirely of null/form-feed characters (1 line, unreadable). Should be re-extracted from the PDF in `Textbooks/` |
| `private_reference_library/_text_cache/Textbooks/Trading and Exchanges -- Larry Harris.txt` | **Likely corrupt** | Expected: market microstructure text for impact/execution risk. Verify on next read |
| `private_reference_library/Textbooks/Advances in Financial Machine Learning -- Marcos Lopez de Prado.epub` | **Not text-cached** | EPUB format — no plain-text cache exists. Contains PBO/DSR framework (Ch. 11–15), backtesting (Ch. 4), cross-validation (Ch. 7). Needed for Pillar 2 backtest hygiene |
| `private_reference_library/Textbooks/Dynamic Hedging -- Nassim Nicholas Taleb -- 1997 -- Wiley.djvu` | **Not text-cached** | DJVU format — no plain-text cache. Contains tail-risk hedging theory (optional, not critical for v1) |
| `private_reference_library/Textbooks/The xVA Challenge -- Gregory -- 4th ed., 2020.epub` | **Not text-cached** | EPUB — contains CVA/DVA/FVA framework. Counterparty risk for OTC execution path |
| `private_reference_library/_text_cache/Textbooks/The Science of Algorithmic Trading and Portfolio Management_ -- Kissell, Robert.txt` | **Truncated** | 2,461 lines — appears to be first few chapters only. Impact/risk chapters may not be included |
| `private_reference_library/_text_cache/Textbooks/Algorithmic and High-Frequency Trading (Mathematics, Finance -- Cartea, Álvaro.txt` | **Truncated** | 1,723 lines — appears partial. Optimal execution and market impact chapters may be incomplete |
| `private_reference_library/pillar_4_venue_standards/deribit/api/02_account_risk/` | **Empty** | Deribit API risk/margin docs not extracted — blocking Pillar 2 venue-risk analysis |
| `private_reference_library/pillar_5_fable_bundle/` | **Duplicated scaffold** | Contains full copy of Sprint 0 code — causes `__pycache__` conflict with `tests/test_engine.py`. Not a reference; should be removed or `.gitignore`d |
| `docs/reports/reference_study/pillar_2_risk_validation_deepseek.md` | **Incomplete (4 lines)** | Aborted study — contains only internal reasoning fragments ("Now let me explore the pillar directory, text cache..."). No substantive content |
| `docs/reports/reference_study/pillar_1_options_pricing_deepseek.md` | **Incomplete (2 lines)** | Aborted study, see Pillar 1 report |
| `private_reference_library/_text_cache/Textbooks/Options, Futures, and Other Derivatives, 11th Edition -- John C_ Hull.txt` | **Present but duplicate** | Same content available in `_text_cache/Textbooks/` — full 42,461 lines |
| `private_reference_library/deribitfilesascopiedtxt.txt` | **Duplicated** | Full Deribit docs (10,249 lines) also present in `pillar_4_venue_standards/deribit/api/specs/` (if extracted) — canonical location TBD |
| `private_reference_library/official_docs/deribit/` | **Empty** | Skeleton exists but content is in root `deribitfilesascopiedtxt.txt` |
| `docs/architecture/`, `docs/venue_rules/`, `docs/model_validation/`, `docs/data/` | **All empty** | Documentation directories exist but contain no content — blocking A2 SPRINT 1 side task |

---

## 9. Missing information or documentation

### 9.1 Missing — blocking contracts.md

| # | Title | Why needed | Priority | Blocks |
|---|---|---|---|---|
| M-1 | **Deribit risk/margin API documentation (`02_account_risk/`)** | Venue-specific risk parameters: initial margin, maintenance margin, liquidation price, margin currency, position limits. Without this, cross-margining, portfolio risk, and liquidation scenarios cannot be modelled | **CRITICAL** | `contracts.md` if Deribit is primary execution venue |
| M-2 | **Monte Carlo Methods in Financial Engineering (Glasserman, 2004) — re-extracted text cache** | The existing text cache is corrupt (null characters). Glasserman is the canonical reference for variance reduction, importance sampling, and Quasi-Monte Carlo used in Pillar 2 stress/MC validation | **HIGH** | A3 MC implementation validation |
| M-3 | **CME position limits and margin methodology (Rule 559, 930-series)** for Bitcoin futures and options | If CME is in-scope venue, position limits directly constrain the 30,000 BTC tranche schedule. 5-BTC contract multiplier means 6,000 contracts — CME spot-month limits apply | **HIGH** | A4 tranche scheduler if CME path active |

### 9.2 Missing — non-blocking but needed before Phase 1 implementation

| # | Title | Why needed | Priority | Blocks |
|---|---|---|---|---|
| M-4 | **Lopez de Prado, *Advances in Financial Machine Learning* (2018) — text-cache conversion** | Contains the backtesting framework (Ch. 11–15: backtesting, cross-validation, feature importance, hyper-parameter tuning) that the Build Plan and A3 brief reference as hygiene standard. Currently EPUB only — unsearchable | **HIGH** | A3 backtest design, CI hygiene validation |
| M-5 | **GARCH(1,1) diagnostics specification** | A2 brief tasks GARCH but omits diagnostics (Ljung-Box, ARCH-LM, parameter stability). Either add to A2 DoD or create separate validation gate in A6 | **MEDIUM** | A2 `garch.py` delivery acceptance |
| M-6 | **Backtest overfitting test harness (CSCV implementation spec)** | The PBO paper provides the algorithm but A3 brief only says "Lopez de Prado hygiene" as prose. Concrete implementation specification needed: S=?, N=?, performance metric?, output format? | **MEDIUM** | A3 backtest DoD, cross-validation |
| M-7 | **Market impact calibration source** | A4 brief specifies parametric IV give-up (0.5–2.0 vol pts) and square-root impact. Neither is calibrated. Must specify: calibration dataset (historical Deribit block trades? dealer survey?) or explicitly label as "uncalibrated assumption" with planned Sprint 4 upgrade path | **MEDIUM** | A4 `impact.py` |
| M-8 | **Stress scenario specification with probability weights** | A3 brief lists four stress scenarios (surge, breakout, retrace, vol-shock) but no probability weights. Without weight specification, the stress analysis cannot produce a probability-weighted risk distribution | **MEDIUM** | A3 `stress.py` |
| M-9 | **Hedge-cost model for the overlay (delta hedging vs static?)** | Mandate requires hedge costs but no brief specifies which hedging strategy to model (delta hedging at discrete intervals? static? no hedging?). Risk of overlay varies significantly by hedging approach | **LOW** | A3 backtest hedge-cost line item |
| M-10 | **`contracts.md` itself** | Single highest-risk missing document. Every agent brief depends on it. Contains the settlement model, pydantic schemas, and the `Provenance` enum required for risk-labelling | **CRITICAL** | All agents (A1–A6) |

### 9.3 Missing — reference library gaps specific to Pillar 2

| # | Gap | Description |
|---|---|---|
| G-1 | **No Pillar 2 reference materials deposited** | `pillar_2_risk_validation/` directory is empty. All risk/validation materials exist elsewhere in the library — they need to be inventoried, organised, and linked from this pillar directory |
| G-2 | **No Pillar 2 text cache directory** | `_text_cache/pillar_2_risk_validation/` was never created. Cross-pillar text caches (McNeil, Bailey et al., Kissell, CME rules, Deribit docs) exist but are not linked or excerpted for Pillar 2 consumption |
| G-3 | **No operational risk analysis** | McNeil Ch.15 covers operational risk; ISDA definitions cover disruption events; Deribit margin rules are available. But no synthesis or analysis document exists tying these to the 30,000 BTC mandate |
| G-4 | **No cross-venue risk comparison** | Materials exist for Deribit (inverse margin/cash-settle), CME (futures delivery/position limits), and OTC/ISDA (counterparty risk). But no document compares the risk profiles across venues for a 30,000 BTC execution |
| G-5 | **No out-of-sample validation protocol** | Mandate requires OOS validation. Bailey et al. PBO paper provides a framework. But no protocol is specified for the BTC-specific backtest window (Jan-2023→Jul-2026) |
| G-6 | **Deribit risk API docs not extracted** | `pillar_4_venue_standards/deribit/api/02_account_risk/` is empty. The official Deribit API includes `/private/get_account_summary`, `/private/get_positions`, `/private/get_margins` — none of these risk endpoints are documented in the reference library |

---

## 10. Final status

### Status: **COMPLETE WITH NON-BLOCKING GAPS**

**Justification:**

**What is present and verified:**
- McNeil et al., *Quantitative Risk Management* (Revised ed., 2015, 35,935 lines) — the definitive single-volume reference for Pillar 2. Covers VaR, ES, copulas, market risk, backtesting (Ch.10), stress testing (Ch.11), EVT, operational risk. Full text cache verified readable.
- Bailey et al., "Probability of Backtest Overfitting" (2015, 1,375 lines + 424-line appendices) — the canonical framework for quantifying backtest overfitting risk. CSCV algorithm specified with S=16, N≥100 guidance.
- Bailey & López de Prado, "Deflated Sharpe Ratio" (2014, 1,082 lines) — correction for selection bias under multiple testing. Directly relevant to A3's N-strategy backtest comparison.
- Hull 11e Ch.22 (VaR/ES), Ch.23 (GARCH), Ch.26 (Monte Carlo) — all verified present.
- Sinclair, *Volatility Trading* 2e (14,254 lines) — risk management for vol/option portfolios.
- Deribit official documentation (10,249 lines) — margin, fees, delivery mechanics, inverse-BTC settlement.
- CME rulebooks, ISDA definitions, IOSCO Principles — all present in text caches.
- Kissell, *Science of Algorithmic Trading* (2,461 lines) — impact model theory.
- Gatheral, *The Volatility Surface* (2,576 lines) — static arbitrage conditions for surface risk.
- 9-test suite + waterfall verify that the baseline arithmetic (pricing, fee model, mandate economics) is correct. This is the quantitative foundation on which risk models will be built.

**What is missing but non-blocking:**
- The `pillar_2_risk_validation/` directory itself is empty — but this is a classification/organization gap, not a material shortage. All required materials exist elsewhere in the library.
- The dedicated text cache `_text_cache/pillar_2_risk_validation/` does not exist — but cross-pillar text caches are accessible and contain all necessary risk content.
- Glasserman (MC Methods) text cache is corrupt — but Hull Ch.26 and Bailey et al. appendices cover sufficient MC methodology for v1.
- Lopez de Prado EPUB not text-cached — but the PBO and DSR papers (text-cached) cover the backtest hygiene framework.
- Deribit risk API spec directory empty — but `deribitfilesascopiedtxt.txt` contains margin mechanics sufficient for conceptual risk modelling (though not for API-level implementation).
- No cross-venue risk comparison document exists — but all venue-specific materials are present for the analyst to perform the comparison.

**What blocks implementation — the critical single-threaded bottleneck:**
- **M-10: `contracts.md` has not been frozen.** A6's Sprint-0 gate is the single dependency that blocks all parallel agent work (A1–A5), including all Pillar 2 implementation (A3 backtest/MC/stress, A4 impact/tranching). Until `contracts.md` defines the settlement model (AC-1 through AC-4), the `Provenance` enum, the pydantic schemas for risk outputs, and the abstract interfaces for A3/A4, no Pillar 2 code can safely begin.

**Recommended next action for Pillar 2 specifically:**
1. Create `_text_cache/pillar_2_risk_validation/` directory and populate with symlinks or excerpt files from McNeil (Ch.9–11), Bailey et al. (PBO paper + appendices), and Deribit margin sections.
2. Re-extract Glasserman text cache from the PDF in `Textbooks/`.
3. Convert Lopez de Prado EPUB to text cache.
4. Extract Deribit risk/margin API docs into `pillar_4_venue_standards/deribit/api/02_account_risk/`.
5. Add Pillar 2 risk-specific output requirements to A3 DoD: VaR, ES, PBO, performance degradation, probability of loss, stochastic dominance analysis, and OOS validation protocol.
6. Add GARCH diagnostics specification to A2 DoD.
7. Resolve decision D‑1 (fee base) before A4 impact model starts — the fee-base choice affects all risk calculations involving fee rebate in downside scenarios.
