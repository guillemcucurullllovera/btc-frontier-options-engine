Now let me verify a few more details before writing the audit — specifically the `.opencode/` configuration and any existing contracts or schemas.
Now I have a complete picture. Let me compile the audit.

---

# Asymmetrica BTC Engine — Quantitative Audit

**Auditor role:** Read-only repository auditor (`.opencode/agents/audit.md`).  
**Date:** 28 July 2026.  
**Scope:** All committed and staged source, configuration, agent briefs, requirements, and reference artefacts.  
**Status of code under audit:** `main` branch, single commit `7a22caf`; 9 tests pass, waterfall runs clean.

---

## 1. Current Repository Functionality

| Component | File | What exists | Status |
|---|---|---|---|
| Black–Scholes pricer | `pricing/black_scholes.py` | European call and put pricing with Greeks, delta→strike inversion, implied volatility (Brent-Q), premium-at-delta utility | **Sprint 0 — working** |
| Execution waterfall | `execution/waterfall.py` | Reads `config/params.yaml`; computes reference notional, seller discount, Asymmetrica fee, option-overlay target, effective client cost, net discount | **Sprint 0 — working** |
| Deribit public feed | `vol/dvol_feed.py` | REST calls to `/get_index_price`, `/get_volatility_index_data`, `/get_instruments`, `/get_book_summary_by_currency`; no auth, running from Hetzner only | **Sprint 0 — networking verified** |
| Test suite | `tests/test_engine.py` | 9 tests: 3 golden vectors (call, put, delta), 2 roundtrips (IV, delta inversion), 2 mandate-economics guards, 1 target-yield delta-solver, 1 waterfall-arithmetic check | **All green** |
| Agent task briefs | `agents/A1…A6.md` | Paste-ready OpenCode prompts with branch, DoD, parallel-safe flags | **Design artefacts** |
| Build plan | `docs/requirements/BTC_30K_Build_Plan_Parallel_Agents.md` | Sprint 0–4 delivery plan, data table, demo script | **Design artefact** |
| Sanitised mandate | `docs/requirements/mandate_sanitized.md` | Business requirements with source-diagram discrepancy | **Business requirements** |

**What does not exist yet** (empty directories or entirely missing):

- `scenarios/` — empty
- `reports/` — empty (except an empty `docs/reports/deepseek_initial_audit.md`)
- `logs/` — empty
- `data/` — not created
- `docs/references/` — only a README, no implementation notes
- `contracts.md` — not created (A6 gate is unfrozen)
- No pydantic models, no API schema, no CI, no Docker
- No Black-76, no inverse-option adjustment, no vectorised grid pricing
- No volatility surface, no smile fitting, no GARCH
- No historical data ingestion (Massive or CryptoDataDownload)
- No Monte Carlo, backtest, stress-test, tranche scheduler, impact model
- No chart pack, no cycle-report, no demo script
- No fixture-recording infrastructure

---

## 2. Exact Existing Interfaces and Data Models

### 2.1 `pricing/black_scholes.py`

```python
@dataclass(frozen=True)
class OptionQuote:
    price: float     # option premium in same units as S (USD for BTC/USD options)
    delta: float     # ∂price/∂S; call ∈ [0,1], put ∈ [-1,0]
    gamma: float     # ∂²price/∂S²; same for call and put
    vega: float      # ∂price/∂σ per 1.00 absolute change in σ (divide by 100 for per‑vol‑point)
    theta: float     # ∂price/∂T, annualised (divide by 365 for per‑day); negative for long options
    strike: float    # K as passed in
```

Public functions (all decimals for rates and vols; T in years; `kind` is `"call"` or `"put"`):

| Signature | Returns | Notes |
|---|---|---|
| `price(S, K, r, sigma, T, kind)` | `float` | Uses `scipy.stats.norm.cdf` |
| `greeks(S, K, r, sigma, T, kind)` | `OptionQuote` | No dividend yield (q is hard‑coded to zero) |
| `strike_for_delta(S, target_delta, r, sigma, T, kind)` | `float` | Closed‑form from `N(d₁)`; `target_delta` for puts is negative (e.g. `‑0.15`) |
| `implied_vol(target_price, S, K, r, T, kind, lo=1e-4, hi=5.0)` | `float` | Brent-Q root‑finder; bounds 0.01%–500% |
| `premium_pct_at_delta(S, delta, r, sigma, dte_days, kind)` | `tuple[float, float]` | Returns `(premium_as_pct_of_spot, strike)`; converts DTE from days→years internally |

### 2.2 `execution/waterfall.py`

```python
def load_params(path=CFG) -> dict
  # Returns parsed YAML dict from config/params.yaml

def waterfall(p: dict | None = None) -> dict
  # Returns dictionary with keys:
  #   reference_spot_usd, btc_quantity, reference_notional_usd,
  #   seller_discount_usd, price_after_discount_per_btc,
  #   asymmetrica_fee_usd, asymmetrica_fee_btc_equiv,
  #   client_cash_at_close_per_btc, client_cash_at_close_total,
  #   overlay_target_usd, client_effective_cost_per_btc_target_case,
  #   client_effective_cost_total_target_case,
  #   net_discount_vs_reference_pct
```

The waterfall arithmetic is:
- Reference notional = S × q
- Discounted price per BTC = S × (1 − seller_discount_pct/100)
- Asymmetrica fee = reference_notional × execution_fee_pct/100
- Client cash at close per BTC = discounted_price_per_BTC + S × execution_fee_pct/100
- Overlay target per BTC = S × target_option_yield_pct/100
- Effective cost per BTC = client_cash_at_close_per_BTC − overlay_target_per_BTC

**Key modelling decision:** The fee is charged on the *reference* notional (S × q), not the *discounted executed* notional. This is the “fee on full notional vs executed volume” question flagged in the build plan — a $9.75M swing. The engine currently implements only the full-notional path.

### 2.3 `vol/dvol_feed.py`

```python
BASE = "https://www.deribit.com/api/v2/public"

spot_index(currency_pair="btc_usd") -> float             # GET /get_index_price
dvol_latest(currency="BTC") -> float                     # GET /get_volatility_index_data
option_chain(currency="BTC") -> list[dict]               # GET /get_instruments
book_summary(currency="BTC") -> list[dict]               # GET /get_book_summary_by_currency
```

No error classification, no retry/backoff, no caching, no WebSocket, no fixture recorder.

### 2.4 Configuration (`config/params.yaml`)

Fields that control model behaviour (all percentage fields are in percentage points, e.g. `2.5` = 2.5%):

| Key | Value (27.07.2026) | Used by |
|---|---|---|
| `btc_quantity` | 30000 | waterfall |
| `reference_spot_usd` | 65000 | waterfall, tests (working value — replace via live feed) |
| `seller_discount_pct` | 2.5 | waterfall |
| `target_option_yield_pct` | 2.5 | waterfall |
| `combined_target_discount_pct` | 5.0 | *(not yet consumed by any module)* |
| `execution_fee_pct` | 0.5 | waterfall |
| `call_delta_target` | [0.10, 0.15] | *(not yet consumed)* |
| `dte_target_days` | [30, 45] | *(not yet consumed)* |
| `strike_target_pct_above_spot` | [15, 20] | *(not yet consumed)* |
| `target_monthly_premium_pct` | 3.0 | *(not yet consumed; test `test_target_yield_requires_higher_delta_or_iv` uses this implicitly)* |
| `iv_working_band_pct` | [40, 50] | tests (DVOL band 27.07.2026) |
| `risk_free_rate_pct` | 4.0 | *(not yet consumed by code; tests hard‑code r=0.04)* |
| `tranche_btc` | [250, 1000] | *(not yet consumed)* |
| `expiry_ladder_dte` | [30, 37, 44] | *(not yet consumed)* |

**Observation:** Several params.yaml entries exist for mandate structures that no module yet loads. This is consistent with the build‑first philosophy: define configuration upfront and wire it in as code arrives. However, `risk_free_rate_pct` (4.0) is listed but the BS functions and tests hard‑code `r=0.04` independently — a future source of drift if params.yaml changes.

---

## 3. What the Nine Tests Validate and Do Not Validate

### 3.1 Tests that *pass* (all green)

| Test | What it validates | Tolerance | Status |
|---|---|---|---|
| `test_call_golden` | Hull/Haug ATM call (S=K=100, r=5%, σ=20%, T=1) → $10.4506 | 1×10⁻³ | ✅ |
| `test_put_golden` | Hull/Haug ATM put → $5.5735 | 1×10⁻³ | ✅ |
| `test_put_call_parity` | C − P = S − K·e⁻ʳᵀ | 1×10⁻⁹ | ✅ |
| `test_delta_golden` | ATM call delta → 0.6368 | 1×10⁻³ | ✅ |
| `test_implied_vol_roundtrip` | IV(price(σ)) → σ | 1×10⁻⁶ | ✅ |
| `test_strike_for_delta_roundtrip` | greeks(S, strike_for_delta(…)).delta → target_delta | 1×10⁻⁶ | ✅ |
| `test_mandate_125delta_premium_band` | 12.5Δ call, 37 DTE, 45% IV, S=65k yields 0.7–1.0% premium; strike ~76–80k (1.15–1.23× spot) | Bands | ✅ |
| `test_target_yield_requires_higher_delta_or_iv` | To reach 3% premium in 37 DTE at 45% IV requires ≈28–38Δ | Bands | ✅ |
| `test_waterfall_mandate_numbers` | Waterfall arithmetic at reference params: notional $1.95B, fee $9.75M / 150 BTC, client cost $62,075/BTC, net discount 4.5% | 1×10⁻¹…1×10⁻⁹ | ✅ |

### 3.2 What the tests do *not* validate

- **Put Greeks** (`greeks` is called only for calls; put gamma, vega, theta are untested).
- **Extreme parameter regimes:** T→0, σ→0, σ→∞ (brentq bounds at 500%), deep ITM/OTM, S≪K, S≫K.
- **Negative rates** (relevant for some currencies; no effect on crypto now but untested).
- **QuantLib parity** — no cross-implementation check exists (QuantLib is installed but unused).
- **Black-76, inverse BTC adjustment, vectorised grid** — not implemented, therefore not testable.
- **Smile/surface, GARCH, fixture replay** — not implemented.
- **Any strategy payoff** — no covered call, CSP, long-BTC+short-put, collar, or rolling test.
- **Backtest/Monte Carlo/stress** — not implemented.
- **Execution impact, tranche scheduler** — not implemented.
- **Live Deribit round‑trip** — no integration test exists; `dvol_feed.py` is verified only via manual execution from Hetzner.
- **Data provenance** — no test verifies that model‑generated data is never confused with observed data.
- **Security and confidentiality** — no test checks for keys, wallet addresses, or counterparty identifiers in outputs.

### 3.3 Test‑architecture concern

The `sys.path.insert(0, …)` pattern in `tests/test_engine.py` works for direct execution but is fragile. It relies on the exact working directory and the absence of `__init__.py` files. This is unconventional for Python packaging and would fail under `pytest` discovery from a different working directory with standard `PYTHONPATH` rules. This is a known convention of the repo (documented in AGENTS.md), but it creates friction for CI integration.

---

## 4. Pricing, Greeks, Implied Volatility, and Delta‑Inversion Correctness

### 4.1 Black‑Scholes formula

The implementation follows the standard Hull formulation:

- `d₁ = [ln(S/K) + (r + σ²/2)T] / (σ√T)`
- `d₂ = d₁ − σ√T`
- Call = S·N(d₁) − K·e⁻ʳᵀ·N(d₂)
- Put  = K·e⁻ʳᵀ·N(−d₂) − S·N(−d₁)

**Verdict:** Correct. Golden vectors and put–call parity confirm it.

### 4.2 Delta

- Call delta = N(d₁) — correct for Black–Scholes without dividends.
- Put delta = N(d₁) − 1 — correct.

**Verdict:** Correct.

### 4.3 Gamma

`gamma = pdf / (S * sigma * sqT)` where `pdf = φ(d₁)`.

**Verdict:** Correct (shared by calls and puts).

### 4.4 Vega

`vega = S * pdf * sqT`.

**Verdict:** Correct. **However**, the standard market convention quotes vega as sensitivity to a 1‑percentage‑point move in σ (e.g. 0.20 → 0.21). This implementation returns vega per 1.00 absolute change (0.20 → 1.20). The docstring correctly notes this: “divide by 100 for per‑vol‑point”. No test verifies this scaling.

### 4.5 Theta

- Call theta = `−(S·φ(d₁)·σ) / (2√T) − r·K·e⁻ʳᵀ·N(d₂)`
- Put theta  = `−(S·φ(d₁)·σ) / (2√T) + r·K·e⁻ʳᵀ·N(−d₂)`

This is the standard expression for continuous‑time theta (annualised, represents decay per year). The sign convention (negative for long calls, may be positive for deep ITM puts due to the financing term) is correct.

**Verdict:** Correct formulaically. No golden vector for theta exists in the test suite.

### 4.6 Implied volatility

Brent-Q root‑finder over bounded interval [1×10⁻⁴, 5.0].

**Verdict:** Correct for the tested regime (ATM, moderate IV). Potential failure modes not covered by tests:
- Prices below intrinsic value (f(σ) never crosses zero — Brent raises `ValueError`).
- Deep OTM options where the function is nearly flat (convergence issues).
- The upper bound of 500% may be insufficient for extreme crypto vol events. Consider increasing to 10.0 (1000%) or using an unbracketed method with fallback.

### 4.7 Delta inversion

Analytical: `ln(K/S) = (r + σ²/2)T − d₁·σ·√T`, where `d₁ = Φ⁻¹(target_delta)` for calls and `d₁ = Φ⁻¹(1 + target_delta)` for puts.

**Verdict:** Mathematically correct. For puts, `target_delta` must be negative (e.g. −0.15), which maps to `N(d₁) − 1 = −0.15 → N(d₁) = 0.85 → d₁ = Φ⁻¹(0.85)`. The code implements `norm.ppf(1.0 + target_delta)` which for target_delta = −0.15 yields `norm.ppf(0.85)`. Correct. Roundtrip passes at 1×10⁻⁶.

### 4.8 Missing: dividend yield (q)

BTC does not pay dividends, so q=0 is physically correct. However, many textbooks parameterise Black–Scholes with q, and the lack of q support may complicate the planned QuantLib parity test (QuantLib’s `BlackScholesMertonProcess` requires setting a dividend yield, even if zero). Adding a `q=0.0` parameter with a default avoids interface churn later.

**Verdict:** Not a mathematical error, but an interface gap that A1 should address.

---

## 5. Current Deribit Integration and Missing Functionality

### 5.1 What exists

Four stateless REST functions that call Deribit’s public API (`/public/get_index_price`, `/public/get_volatility_index_data`, `/public/get_instruments`, `/public/get_book_summary_by_currency`). The module can print live spot, DVOL, and active instrument count when run from a networked environment.

### 5.2 Critical gaps

| Gap | Agent responsible | Impact |
|---|---|---|
| No HTTP error handling beyond `raise_for_status()` | A2 | Transient network failures crash the entire pipeline; no retry, no backoff |
| No response caching | A2 | Every call re‑fetches; cannot run offline; CI depends on exchange uptime |
| No fixture recorder for offline testing | A2 | Tests that depend on Deribit data cannot run in CI or offline |
| No WebSocket subscription for real‑time updates | A2 (implied) | Live waterfall/cycle‑simulator cannot stream; demo is stale |
| No vol‑surface construction from `book_summary` | A2 | Cannot compute IV(delta, dte) for arbitrary strikes; all IVs are flat or manually input |
| No smile/skew model (spline or SVI) | A2 | Surface module is empty; IV for delta‑targeted strikes is uncalibrated |
| No historical DVOL/option OHLCV ingestion | A2 | Backtest (A3) cannot run without model‑reconstructed IVs, which the mandate explicitly requires be labelled as such |
| No GARCH realised‑vol forecast | A2 | Regime‑aware vol forecasting is absent |
| No venue‑rulebook documentation fetched | A2 (Sprint 1 side task) | Settlement, exercise, and margin rules are not codified; code may contradict Deribit/CME specs |
| No authentication for private endpoints | Not in scope for A2 | Order placement, position management, and RFQ quote capture (Sprint 4) need auth |

### 5.3 dvOL usage concern

The `dvol_latest()` function fetches the last hour’s candle from a 24‑hour window and returns the closing value. This is DVOL, Deribit’s BTC volatility index (30‑day constant‑maturity model‑free implied vol). The build plan correctly treats DVOL as a **proxy** for option‑implied volatility when historical chains are missing. However, DVOL is a *synthetic index*, not a traded instrument price. Using it as σ in Black‑Scholes pricing for historical backtests will produce **model‑generated** option premiums indistinguishable from observed prices unless explicitly labelled. The mandate requires this distinction.

---

## 6. Missing Massive Historical‑Data Integration

The mandate states: “Massive is the primary long‑history BTC spot source.” The `.env.example` contains `MASSIVE_API_KEY=` and `MASSIVE_BASE_URL=https://api.massive.com`.

**Status:** No code, no configuration file, no ingestion module, no data directory for Massive exists. The build plan lists “Spot history” under “Any major venue API / CSV” rather than Massive specifically, creating a **documentation conflict**: the mandate says Massive is primary; the plan treats it as fungible.

A2 is the correct agent to implement Massive ingestion. The task brief mentions “CryptoDataDownload free CSVs” but does not reference Massive. This is a gap: either A2 must be instructed to treat Massive as primary (wired to `MASSIVE_BASE_URL` from `.env.example`) or the mandate must be amended.

---

## 7. Observed versus Model‑Generated Historical Option Data

### 7.1 The mandate’s rule

> Observed market data must remain separate from model‑generated historical option prices. No simulated bid, ask, implied volatility, Greek or liquidity value may be represented as an observed market value.

### 7.2 Current state

No historical option data exists in the repo. All prices, IVs, and Greeks are calculated by `pricing/black_scholes.py` from input parameters. The test suite uses hard‑coded values that are **calculated** (even when they match known Hull/Haug vectors — those are reference computed values, not observed market prices).

### 7.3 Future risk (identified from build plan and A3 brief)

The A3 backtest brief states:

> “Where historical chains are missing, premiums are DVOL‑reconstructed and labeled as such — honest v1.”

This is the correct principle. However, the repo currently lacks:

- A **provenance‑tagging** mechanism (e.g. a data class with `.source: Literal["observed", "model_reconstructed", "assumed"]`).
- A **schema** that enforces this distinction in serialised outputs.
- A **test** that verifies no model‑generated value is serialised without its source tag.

**Recommendation:** Freeze a provenance enum in A6’s `contracts.md` before any historical data ingestion begins. Every time‑series point should carry a mandatory source field.

---

## 8. Missing Volatility‑Surface and Forward‑Curve Components

### 8.1 Volatility surface

The complete vol‑surface stack is missing:

| Component | Agent | Status |
|---|---|---|
| Per‑expiry smile fit (spline or SVI) | A2 | Not implemented |
| Interpolation in delta space | A2 | Not implemented |
| IV(delta, dte) query function | A2 | Not implemented |
| Surface visualisation | A5 | Not implemented |
| Skew‑sensitive strike generation for backtest | A3 | Not implemented; backtest will use flat‑vol (DVOL) |

**Consequence:** Every pricing call currently assumes constant σ across all strikes and expiries. This systematically mis‑prices OTM calls (the mandate structure) because BTC options exhibit a persistent positive skew (OTM calls trade at higher IV than ATM). A flat 45% IV undervalues the 10–15Δ call premium relative to a smile‑aware price. This understates the overlay yield, making the mandate structure appear *less* attractive than it actually is — a conservative error, but an error nonetheless.

### 8.2 Forward curve

No forward‑curve component exists. For BTC, the futures curve is in contango during normal markets (futures > spot). Black‑76 on futures, which A1 is tasked to implement, addresses this for Deribit inverse/BTC‑settled options. Without it:

- BTC‑settled (inverse) options cannot be priced correctly.
- Futures hedging costs cannot be modelled.
- Basis risk between spot‑referenced and futures‑referenced derivatives is unquantified.

---

## 9. Covered‑Call, Cash‑Secured‑Put, and Long‑BTC‑Plus‑Short‑Put Requirements

### 9.1 What exists

The only strategy‑adjacent function is `premium_pct_at_delta()`, which computes the premium (as % of spot) and strike for a call at a given delta. This answers “what does a single short call at this delta yield?” but nothing else.

### 9.2 What is required by the mandate but missing

| Strategy | Required analysis | Current status |
|---|---|---|
| Covered call (long BTC + short call) | Expiry payoff, MTM P&L, premium contribution, effective BTC acquisition cost, ITM probability, rolling, early close, hedge costs | **None implemented** |
| Cash‑secured put | Same as above, plus cash‑collateral yield, assignment mechanics | **None implemented** |
| Long BTC + short put | Same as covered call, but payoff is fundamentally different (see §15) | **None implemented** |
| Partial covered‑call overlay | Fractional overlay (e.g. 50% of position overwritten with calls) | **None implemented** |
| Staggered strikes/expiries | Ladder of strikes across the expiry range | **None implemented** |
| Call spreads | Cap upside, reduce premium outlay | **None implemented** |
| Collars | Long put protection + short call financing | **None implemented** |
| Rolling and closing rules | DVOL‑triggered execution rule, early‑close cost model | **Params exist (`sell_when_dvol_above`, `stand_down_on_breakout`) but no code consumes them** |

### 9.3 Payoff function module

No module exists that defines strategy payoffs piecewise. This is a foundational gap: backtests, charts, and the demo all need the same payoff functions. A dedicated `strategies/payoffs.py` (or similar) should be created, and A5’s charts must import it rather than re‑implementing payoff logic.

---

## 10. Assignment, Exercise, Cash Settlement, Inverse‑BTC Settlement, and Rolling

### 10.1 Status

**None of these are modelled.** The repo contains zero code that handles:

- **Physical assignment:** What happens when a short call expires ITM (BTC is delivered)? What is the effective sale price? What is the remaining BTC position?
- **Cash settlement:** Deribit options are cash‑settled in BTC or USDC. The mapping from payoff formula to actual settlement currency is not modelled.
- **Inverse‑BTC settlement:** Deribit inverse options have a payoff denominated in BTC: `max(0, 1/K − 1/S_T)` instead of `max(0, S_T − K)`. This creates a non‑linearity that standard Black‑Scholes does not capture. A1’s brief mentions “inverse‑option adjustment (BTC‑settled payoff: price in BTC = USD price / index; document convention vs Deribit spec)” but the implementation doesn’t exist yet.
- **Rolling mechanics:** Closing an expiring option and opening a new one incurs bid/ask spread, fees, and potential slippage. None of this is modelled.
- **Early close:** Closing before expiry incurs a different spread environment and potentially worse pricing. No model exists.
- **DVOL‑triggered rules:** The params mention `sell_when_dvol_above: 55, stand_down_on_breakout: true` but no code reads or enforces these.

### 10.2 Venue rulebook gap

The build plan (Sprint 1 side task) tasks A2 with fetching, dating, and versioning venue rulebooks into `docs/`. Until this is done, the settlement logic cannot be verified against actual contract specifications. Deribit’s inverse option conventions are non‑trivial and differ from textbook Black–Scholes.

---

## 11. Backtesting, Monte Carlo, Stress Testing, and Out‑of‑Sample Validation

### 11.1 Current state

**Nothing exists.** The `scenarios/` directory is empty. A3 is responsible for building all of this.

### 11.2 A3 brief analysis

The A3 brief is comprehensive and well‑specified:

- **Monte Carlo:** GBM + Merton jump‑diffusion + Kou double‑exponential; antithetic variates; 100k paths in <5s. **Good:** covers fat‑tailed distributions relevant to BTC.
- **Backtest:** Five paths over Jan‑2023 → Jul‑2026. **Good:** covers the key structures. **Gap:** no mention of transaction costs, bid/ask, or execution delay in the backtest loop.
- **Stress:** Replay of three specific BTC regimes. **Good:** realistic scenarios. **Gap:** no forward‑looking stress scenarios (e.g. regulatory ban, exchange hack, stablecoin de‑peg).
- **Hygiene:** Deterministic seeds; no parameter fitting inside the evaluation window (Lopez de Prado standard). **Good.**

### 11.3 Out‑of‑sample validation

The mandate requires it. The A3 brief does not explicitly define an out‑of‑sample period. The Jan‑2023 → Jul‑2026 window is a single contiguous sample. A proper out‑of‑sample split (e.g. train on 2023–2024, validate on 2025–2026, or walk‑forward cross‑validation) is not mentioned.

### 11.4 Dependencies not yet satisfied

A3 depends on A1 (pricers) and A2 (IV history). Neither is ready. A3 cannot start until both have produced consumable outputs.

---

## 12. Execution, Impact, Tranching, and Fee Modelling for 30,000 BTC

### 12.1 Current state

Only the static waterfall exists. The `execution/` directory contains only `waterfall.py`.

### 12.2 A4 brief analysis

| Component | Specification | Status |
|---|---|---|
| `impact.py` | Parametric per‑clip IV give‑up (0.5–2.0 vol pts), square‑root spot impact (Kissell/Almgren‑Chriss) | **Not implemented** |
| `tranches.py` | Scheduler across [30,37,44] DTE and [250..1000] BTC clips over 4–8 weeks | **Not implemented** |
| Waterfall sensitivity | Spot ±1–10%, fee‑base variants (full notional vs executed volume) | **Not implemented** |

### 12.3 Fee‑base sensitivity

This is the single biggest open modelling decision: whether Asymmetrica’s 0.5% fee applies to the *reference* notional ($1.95B → $9.75M) or the *executed* notional (~$1.90B → $9.51M). The difference is $240k, which is material. The current waterfall implements only the full‑notional path. A4 is tasked to add the variant but has not started.

### 12.4 Square‑root impact concerns for crypto

The Kissell/Almgren‑Chriss square‑root impact model was developed for equities and does not directly translate to OTC BTC options where liquidity is discontinuous and RFQ‑driven. The A4 brief should specify the calibration source (historical Deribit block trades? dealer surveys?) or note the limitation explicitly.

### 12.5 Tranching schedule constraint

The brief states: “Schedule totals exactly 30,000 BTC.” With clips of 250–1000 BTC across three expiries over 4–8 weeks, finding integer combinations that sum exactly to 30,000 is a combinatorial optimisation problem. A4’s approach (brute‑force enumeration, integer linear programming, or heuristic packing) should be specified in the implementation.

---

## 13. Validation, Reporting, Security, and Data‑Governance Gaps

### 13.1 Cross‑validation

The build plan mandates: “every human‑facing number is independently re‑derived in the Fable pass before it leaves the repo.” This is a **manual gate**, not an automated one. There is no tooling to:

- Detect if a number in a chart or report was produced by a single model.
- Flag arithmetic inconsistencies between the pricer, the backtest, and the static waterfall.
- Verify that QuantLib parity checks (A1) passed before charts (A5) consume pricer output.

A6 should implement a **cross‑validation registry** (a JSON or YAML file in `reports/` that records for each output number: which module produced it, which module independently verified it, and the verification tolerance).

### 13.2 Security

- `.env` is gitignored (confirmed). `.env.example` is safe but contains placeholder values — ensure it never gets real keys committed.
- No secrets appear in any committed file.
- `opencode.json` uses `{env:…}` variable substitution correctly — API keys are never stored in the config.
- The Deribit feed uses only public, unauthenticated endpoints — no API-key exposure risk.
- No wallet‑address, counterparty‑identity, or deal‑identifying information found in any committed file, test fixture, or prompt.

### 13.3 Data governance

| Gap | Risk | Recommended action |
|---|---|---|
| No provenance tagging for time‑series data | Model‑generated values exported without source label, mistaken for observed data | Add `DataSource` enum in contracts.md |
| No data versioning | `config/params.yaml` changes break historical comparisons silently | Version params alongside backtest results |
| No data retention or deletion policy for cached Deribit/Massive data | Regulatory risk if data is stored and later subject to GDPR or similar | Define in data/README.md (A2 task) |
| No audit trail of parameter changes | Cannot reproduce past analyses | Add git‑versioned params snapshots in reports |
| `reference_spot_usd` labeled “working value 27.07.2026; replace via live feed” | Ambiguous whether the replacement is the engine’s job or manual | Wire live spot from dvol_feed into waterfall as A2/A4 deliver |

### 13.4 Reporting

A5 is tasked to produce charts, a cycle‑report, and a demo script. None of this exists yet. The empty `reports/` directory implies a complete greenfield build in Sprint 3.

---

## 14. Conflicts and Unclear Dependencies in A1–A6

### 14.1 A1 (Pricing & Greeks)

- **Unclear:** “document convention vs Deribit spec” — Deribit inverse options have a specific BTC‑denominated payoff formula. A1 needs Deribit’s actual contract specification, which A2 is tasked to fetch in Sprint 1 (venue rulebooks). This creates a hidden dependency: A1 may need A2’s fetched spec before finalising inverse‑option code, but the merge order is A1→A2, not A2→A1.
- **QuantLib dependency:** The brief mentions QuantLib parity but doesn’t specify which QuantLib classes to use (EuropeanOption + BlackScholesMertonProcess? or AnalyticEuropeanEngine?). The Haug golden vectors should come from Haug’s book, not from QuantLib itself (to avoid circular validation).
- **Vectorised grid:** “numpy pricing over strike/expiry grids” — this implies a different code path from the scalar functions. Tests must cover both paths with the same golden vectors.

### 14.2 A2 (Data & Vol)

- **Massive gap:** The brief mentions CryptoDataDownload but not Massive, contradicting the mandate’s “Massive is primary” requirement.
- **Fixture recorder:** “Recorded fixtures enable full offline test run” — but the fixture format is not specified (JSON? Parquet? Pickle?). A6 must standardise this in contracts.md.
- **Vol‑surface spec:** “Fit smile per expiry from book_summary mark_iv (spline; SVI stretch goal)” — no outcome specified for what happens when a strike range is sparse. Fallback behaviour (linear? flat? ignore expiry?) is undefined.

### 14.3 A3 (Scenarios)

- **Depends on A1 interfaces, A2 fixtures** — but the merge order is A1→A2→A4→A3→A5. By the time A3 merges, A1 and A2 are expected to be stable. This is fine.
- **CryptoDataDownload vs DVOL:** “IV from A2 history (DVOL proxy where chains missing, labeled ‘model‑reconstructed’)” — A3 needs A2 to provide a unified function `get_iv(strike, dte, date)` with provenance metadata. This interface is not specified in any brief.
- **Monte Carlo scope:** GBM + Merton + Kou is good but missing stochastic volatility (Heston), which is significant for BTC due to vol‑of‑vol effects. Not a Sprint‑1 blocker but worth noting.

### 14.4 A4 (Execution)

- **Depends on contracts.md** — correctly identifies the freeze gate.
- **Waterfall sensitivity:** The brief says “fee‑base variants: full notional vs executed volume” but doesn’t specify whether the variant should also affect `asymmetrica_fee_btc_equiv` and the client‑cost calculation chain, or just the fee line.
- **IV give‑up model:** “0.5–2.0 vol pts” — where do these numbers come from? They appear to be assumptions. The brief should indicate they need calibration against RFQ data once available (Sprint 4).

### 14.5 A5 (Reports)

- **“Regenerate the circulating long‑BTC+short‑put chart CORRECTLY labeled”** — this is explicitly about the source‑diagram discrepancy. See §15.
- **Chart enumeration:** The brief lists “A1 long spot, A2 short OTM call, A3 combined covered call; B1 reserved cash, B2 short OTM put, B3 combined cash‑secured put” — these six charts plus the corrected long‑BTC+short‑put chart. The corrected chart exists *outside* the A1–B3 enumeration (it is not a covered call or CSP). This could cause confusion about how many charts are required (6? 7? 8?).
- **Cycle‑report dependency:** Needs A3’s backtest output. Merge order (A3→A5) handles this.

### 14.6 A6 (QA & Integration)

- **First task: “Freeze contracts.md + pydantic models FIRST (Sprint 0 gate)”** — this has not happened. The repo has no `contracts.md` and no pydantic models. Until A6 completes this gate, A1–A5 are working against undocumented interfaces, and A1/A2/A4 (all marked “Depends on: contracts.md”) cannot safely start.
- **CI (GitHub Actions):** Not set up. No workflow files exist.
- **Cross‑validation protocol:** Described as a manual Fable pass. No automated tooling. This is a process risk: manual verification at the end of a sprint is vulnerable to schedule pressure.

### 14.7 Summary of conflict/dependency matrix

| From | Depends on | Status | Issue |
|---|---|---|---|
| A1 | contracts.md | Not frozen | Cannot guarantee interface stability |
| A1 | Deribit inverse spec (A2) | Not fetched | Can implement placeholder but risks rework |
| A2 | contracts.md | Not frozen | Same as A1 |
| A2 | Massive (mandate) | Not mentioned in brief | Brief omits mandate’s primary data source |
| A3 | A1 pricers, A2 IV history | Neither ready | Correct dependency; waiting for Sprint 1 |
| A4 | contracts.md | Not frozen | Same as A1 |
| A5 | A1–A4 outputs | None ready | Correct dependency |
| A6 | All agents | Gate 1 incomplete | Blocking all parallel work |

**Critical path issue:** A6 must complete Sprint 0 gate (contracts.md + CI) before A1, A2, A4 can safely start. This is a single‑threaded dependency that delays the entire parallel build.

---

## 15. Source‑Diagram Discrepancy — Detailed Analysis

### 15.1 The position legs (as stated in the mandate)

- **Leg 1:** Long BTC (physical holding, cost basis at acquisition price).
- **Leg 2:** Short put (sell a put option, receive premium).

### 15.2 Canonical classification

**This position is NOT a covered put.**

A conventional covered put consists of:
- **Short underlying exposure** (or a short futures/physical position) + **short put**.

Long BTC + short put has **long** underlying exposure, not short. The position name “Covered Put Strategy (Long BTC + Short Put)” is a contradiction: the title says “Covered Put” but the parenthetical description correctly names the legs.

The canonical classification is:

> **Leveraged‑bullish yield enhancement** (also describable as: **long BTC plus short put, or “married put” written from the long side**).

It is sometimes colloquially called a “yield‑enhanced long” or “long synthetic with downside gearing.” The key characteristic is that downside exposure is *doubled* (the put creates an obligation to buy more BTC at the strike, so the effective delta below strike is +2), while upside participation remains +1.

### 15.3 Expiry payoff — piecewise derivation

Let:
- `S₀` = acquisition cost of 1 BTC (cost basis)
- `S_T` = BTC spot at expiry
- `K` = short put strike
- `P` = put premium received per BTC

At expiry, the combined payoff (ignoring financing costs) is:

**Leg 1 — long BTC:**
`Payoff₁ = S_T − S₀`

**Leg 2 — short put:**
- If `S_T ≥ K`: put expires worthless → `Payoff₂ = +P`
- If `S_T < K`: put is exercised, seller buys 1 BTC at K → `Payoff₂ = +P − (K − S_T)`

**Combined P&L (per BTC of initial position):**

---

**Region 1: S_T ≥ K** (spot above strike)

P&L = (S_T − S₀) + P

Slope = +1 (pure long BTC participation).  
No cap on upside.  
Breakeven: S_T = S₀ − P

---

**Region 2: S_T < K** (spot below strike, put is ITM)

P&L = (S_T − S₀) + P − (K − S_T)  
  = 2·S_T − S₀ − K + P

Slope = +2 (BTC doubles down — the short put requires purchasing additional BTC at K, so effective BTC exposure doubles below strike).

Breakeven: S_T = (S₀ + K − P) / 2

(Only relevant if this breakeven falls below K; otherwise all losses occur in region 2 with no breakeven.)

---

### 15.4 How this differs from a covered call

| Property | Covered Call (Long BTC + Short Call) | Long BTC + Short Put |
|---|---|---|
| Directional bias | Neutral to mildly bullish | **Aggressively bullish (leveraged below strike)** |
| Max profit | Capped at K − S₀ + premium | **Uncapped** (slope +1 above K) |
| Max loss | S₀ − premium (BTC→0) | **S₀ + K − premium** (greater than covered call because of put exercise obligation) |
| Slope above strike | 0 (capped) | +1 |
| Slope below strike | +1 | **+2** |
| Premium income | Call premium (typically modest for OTM) | Put premium (skew‑dependent) |
| Physical settlement | BTC called away if S_T > K | Additional BTC purchased if S_T < K (increases position, not reduces it) |

### 15.5 How this differs from a cash‑secured put

| Property | Cash‑Secured Put | Long BTC + Short Put |
|---|---|---|
| Initial position | Cash (no BTC exposure) | Long BTC (full exposure) |
| Payoff profile | Put‑like (limited upside) | **Leveraged‑long** |
| Upside participation | None (only premium kept) | **Full +1 participation** |
| Downside | Assigned BTC at K (cost K − premium) | **Doubled downside to (S₀ + K − premium)** |

### 15.6 Source annotations requiring mathematical verification

The mandate states the supplied diagram includes “breakeven and profit/loss annotations.” Without seeing the diagram, these specific items must be verified:

1. **Breakeven point(s):** The diagram likely shows one breakeven. Verify it matches the piecewise formula above. If it shows a single breakeven at S₀ − P, check whether this breakeven is above or below K (if below K, the actual breakeven depends on the regime and may be at (S₀ + K − P)/2).

2. **Max‑profit annotation:** If the diagram indicates any profit cap, it is **wrong** — this position has no max profit (slope +1 persists above K).

3. **Max‑loss annotation:** Should be S₀ + K − P (if BTC → 0). This is significantly larger than a long‑only loss of S₀ and larger than a covered call’s max loss of S₀ − P.

4. **Delta annotation:** If the diagram labels the position with a single delta, it is incorrect — the effective delta is +2 below K and +1 above K. This is a state‑contingent delta, not a single number.

5. **The title itself:** “Covered Put Strategy” is misleading. If the diagram’s P&L annotations match the piecewise payoff derived above, the title is wrong but the annotations may be correct. If both title and annotations are wrong, there is a deeper error in the source material.

### 15.7 Recommended canonical software representation

In `pricing/black_scholes.py` or a new `strategies/payoffs.py`:

```python
@dataclass(frozen=True)
class PositionLeg:
    quantity: float           # +1 = long, -1 = short
    instrument: str           # "btc_spot", "call", "put"
    strike: float | None      # None for spot leg
    premium_received: float   # 0 for spot leg; positive for short options

def strategy_payoff(legs: list[PositionLeg], S_T: float) -> float:
    """Compute total payoff at expiry for any collection of legs."""
    ...

def classify_strategy(legs: list[PositionLeg]) -> str:
    """Derive canonical classification from legs alone.
    
    Long BTC + short call → 'covered call'
    Cash collateral + short put → 'cash-secured put'
    Long BTC + short put → 'leveraged-bullish (long BTC + short put)'
    Short BTC + short put → 'covered put'
    """
    ...
```

The `classify_strategy` function must:
- Derive the classification from legs, **never** from titles, filenames, or labels.
- Return both `canonical_classification` and `source_label` (the label from the original diagram) when they differ.
- Flag discrepancies as warnings in any report or chart that references the strategy.

A5’s corrected chart must:
- Show the piecewise payoff with labelled regions.
- Display the canonical classification as the primary title.
- Include the source label as a subtitle with a correction note.
- Compute breakeven lines from the payoff function, not from annotations.

---

## 16. Safest Implementation Sequence

Given the dependency analysis in §14, the recommended sequence is:

### Phase 0 — Gate (A6, Day 0–1)

1. **Freeze `contracts.md`**: Define function signatures for all modules (pricing, vol, surfaces, strategies, execution, backtest/MC, reports). Include pydantic models for:
   - `OptionQuote` (already exists as dataclass; upgrade to pydantic)
   - `PositionLeg` (new)
   - `Strategy` (collection of legs + metadata)
   - `DataSource` enum (observed, model_reconstructed, assumed, business_requirement)
   - `WaterfallOutput` (typed version of the dict)
   - `BacktestResult`, `MonteCarloResult`, `StressTestResult`
2. **Stand up CI**: GitHub Actions with `pytest`, `mypy --strict`, `ruff` on every PR.
3. **Record first live Deribit fixtures**: so A2–A5 can work offline.
4. **Create stub files** for modules that don't exist yet, so A1–A5 can import against frozen interfaces.

### Phase 1 — Parallel core (Days 1–4)

| Agent | Deliverable | Dependency on others |
|---|---|---|
| **A1** | Black‑76, inverse‑BTC adjustment, vectorised grid, QuantLib parity tests | contracts.md only |
| **A2** | Hardened Deribit feed with caching + fixture recorder, surface.py (smile fit), CryptoDataDownload ingest, Massive ingest (add to brief), GARCH | contracts.md only |
| **A4** | impact.py (IV give‑up + square‑root spot), tranches.py (30,000 BTC scheduler), waterfall sensitivity mode | contracts.md only |

**Parallelism:** All three agents work against stubs and fixtures. No cross‑dependency at implementation time.

### Phase 2 — Scenarios (A3, Days 4–7)

Consumes A1 pricers and A2 IV history. Merge order: A1 → A2 → A4 → **A3**.

### Phase 3 — Integration & reports (A5 + Fable, Days 7–10)

Consumes everyone's outputs. Corrected chart pack, cycle‑report, demo. Merge order: A3 → **A5**.

### Phase 4 — Hardening (Days 10–14)

- Fable cross‑validation of all human‑facing numbers.
- Live RFQ hook (optional).
- Docker + one‑command deploy (optional).
- Parameter presets for collar, put‑sleeve variants.

### Why this sequence?

- A6’s gate is the single‑threaded bottleneck — it must be done first, no workaround.
- Sprint 1 (A1, A2, A4) is genuinely parallel because contracts.md makes them independent.
- A3 is the only serialised Sprint‑2 work; it can start as soon as A1 delivers pricers and A2 delivers fixtures with an `get_iv(strike, dte, date)` interface.
- A5 is naturally last; the merge order A3→A5 is correct.
- The most critical path item to accelerate: A6’s Sprint‑0 gate. If contracts.md takes >1 day, every other agent is blocked. Consider pre‑drafting the contracts with stub signatures before A6 formalises them, so A1/A2/A4 can soft‑start against draft interfaces.

### Risks if the sequence is not followed

- Starting A1 without frozen contracts → interface churn breaks A3/A5.
- Starting A2 without fixture‑format standardisation → A3 cannot ingest data reliably.
- Delaying Massive integration → backtest uses only CryptoDataDownload or DVOL‑reconstructed data, which the mandate would flag as insufficient.
- Merging A5 before A3 → charts reference backtest results that don't exist.

---

## Appendix A — Observed vs Calculated vs Assumed Classification

| Value | Classification | Source |
|---|---|---|
| Spot price $65,000 | **Assumed** working value (27.07.2026) | `config/params.yaml` — replace via live feed |
| DVOL 40–45% | **Observed** via Deribit public API (27.07.2026) | `vol/dvol_feed.py` — live‑only |
| Risk‑free rate 4.0% | **Assumed** (business parameter) | `config/params.yaml` |
| Option prices in tests | **Calculated** from Black–Scholes with test parameters | `pricing/black_scholes.py` |
| Hull/Haug golden vectors (10.4506, 5.5735, 0.6368) | **Calculated** reference values from textbook — not market‑observed | Haug, *Complete Guide to Option Pricing Formulas* |
| Waterfall arithmetic ($9.75M fee, $62,075/BTC) | **Calculated** from mandate parameters | `execution/waterfall.py` |
| “DVOL‑reconstructed” historical premiums | **Model‑generated** (future) — must be labelled as such | A3 backtest output (not yet built) |
| Seller discount 2.5% | **Business requirement** | Mandate |
| Target option overlay 2.5% | **Business requirement** | Mandate |
| Execution fee 0.5% | **Business requirement** | Mandate |
| 30,000 BTC quantity | **Business requirement** — configurable | Mandate + `config/params.yaml` |
| IV give‑up 0.5–2.0 vol pts | **Assumed** (to be calibrated from RFQ data) | A4 brief |
| The source‑diagram label “Covered Put Strategy” | **Incorrect source label** — the canonical classification is “leveraged‑bullish (long BTC + short put)” | Mandate §Source‑diagram discrepancy |

---

## Appendix B — Audit Checklist Summary

| # | Area | Status | Criticality |
|---|---|---|---|
| 1 | Repository functionality | Sprint‑0 working; A1–A6 unimplemented | — |
| 2 | Exact interfaces | 11 public functions across 3 modules; no pydantic/models | Medium |
| 3 | Test coverage | 9 tests pass; 0 strategy, 0 backtest, 0 integration, 0 edge‑case, 0 provenance tests | High |
| 4 | BS/IV/delta correctness | Mathematically correct for tested regimes; q=0 hard‑coded; no theta golden vector | Low |
| 5 | Deribit integration | Basic REST only; no WS, no caching, no fixtures, no surface | High |
| 6 | Massive integration | Completely missing; brief conflicts with mandate | High |
| 7 | Observed vs model‑generated data | No provenance mechanism exists | High |
| 8 | Vol surface & forward curve | Fully absent; all pricing uses flat vol | High |
| 9 | Strategy requirements | None implemented beyond single‑call premium‑at‑delta | Critical |
| 10 | Settlement mechanics | None implemented | Critical |
| 11 | Backtesting/MC/stress | None implemented; A3 brief is well‑specified | Critical |
| 12 | Execution/impact/tranching | Waterfall only; no impact or tranche modules | Critical |
| 13 | Validation/reporting/governance | No automated cross‑validation; no reporting modules; no data‑governance policy | High |
| 14 | A1–A6 conflicts | A6 gate unfrozen → all agents blocked; Massive omission in A2; A1 inverse‑spec dependency on A2 | Critical |
| 15 | Implementation sequence | A6→(A1∥A2∥A4)→A3→A5 is correct but single‑threaded gate blocks all | Critical |
| 16 | Source‑diagram classification | “Covered Put” label is wrong; payoff is leveraged‑bullish with slope +2 below K, +1 above, no cap | Critical |
