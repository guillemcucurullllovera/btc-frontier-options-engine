# Asymmetrica BTC Engine — Repository Audit

**Mode:** read-only · **Audit date:** 28.07.2026 · **Tests:** 9 green · **Commit posture:** single commit on `main`, working tree dirty only against untracked docs/prompts

---

## 0. Executive summary

The scaffold delivers exactly the three artefacts promised at Sprint 0: a Black-Scholes pricer with Greeks/delta-inversion/IV, a parameter-driven waterfall that reproduces the mandate's headline numbers (1.95 bn USD notional, 150 BTC / 9.75 M USD fee, 4.5% net), and a Deribit public-API wrapper. It does **not** deliver any of the structures required by the sanitised mandate: no covered-call, cash-secured-put, long-BTC-plus-short-put, collar, or rolling engine exists in code; no scenarios/, data/, reports/, fixtures/, or contracts.md exist on disk; Massive and the OTC/vol-surface/backtest layers are absent. The agent briefs (A1–A6) and the build plan describe a comprehensive programme, but only Sprint 0 has been executed. The mislabelled "Covered Put = Long BTC + Short Put" diagram called out in the mandate is currently unaddressed: no software exists to flag it.

---

## 1. Current repository functionality

### 1.1 What actually runs today

| Module | File | Capability |
|---|---|---|
| Pricing | `pricing/black_scholes.py` | European call/put Black-Scholes; full Greek set (Δ, Γ, Vega per 1.00 vol, Θ per year); analytical `N(d1)=Δ` strike inversion; Brent-based implied-vol solver; helper `premium_pct_at_delta`. |
| Volatility | `vol/dvol_feed.py` | Deribit public REST: spot index, latest DVOL (1h resolution window), option chain metadata, per-instrument book summary (mark/IV/Δ/bid/ask/OI). |
| Execution | `execution/waterfall.py` | Reads `config/params.yaml`; computes reference notional, seller discount USD, Asymmetrica fee (USD + BTC-equivalent), client cash-per-BTC at close, overlay-target USD, effective cost per BTC and total, net discount %. |
| Tests | `tests/test_engine.py` | 9 tests: BS call/put golden (Hull/Haug), put-call parity, Δ golden, IV round-trip, Δ→strike round-trip, mandate 12.5Δ premium band, target-yield delta inversion, waterfall mandate numbers. |
| CLI | `python3 -m execution.waterfall` | Prints all 12 waterfall keys with thousands separators. |
| CLI | `python3 -m vol.dvol_feed` | Prints BTC index, latest DVOL, live option-instrument count (requires network, Hetzner only). |

### 1.2 What is configured vs hard-coded

`config/params.yaml` is read by `waterfall.py` only. The pricing module receives all numeric inputs as arguments. Nothing in `pricing/` or `vol/` reads `params.yaml` — so spot, strikes, IV, rate, DTE are still passed as literals at every call site (tests and `waterfall` only). This complies with the "single source of truth" rule for fee/discount/quantity, but not for pricing inputs (no default loaded from params).

### 1.3 Confirmed working outputs

`python3 -m execution.waterfall` produces (validated against `tests/test_engine.py::test_waterfall_mandate_numbers`):

```
reference_notional_usd            1,950,000,000.00   (= 65,000 × 30,000)
seller_discount_usd                  48,750,000.00   (= 1.95bn × 2.5%)
price_after_discount_per_btc           63,375.00      (= 65,000 × 0.975)
asymmetrica_fee_usd                    9,750,000.00   (= 1.95bn × 0.5%)
asymmetrica_fee_btc_equiv                  150.00     (= 9.75M / 65,000)
client_cash_at_close_per_btc            63,700.00      (= 63,375 + 65,000 × 0.005)
overlay_target_usd                     48,750,000.00   (= 1.95bn × 2.5%)
client_effective_cost_per_btc           62,075.00      (= 63,700 − 65,000 × 0.025)
net_discount_vs_reference_pct               4.50       (= 100 × (1 − 62,075/65,000))
```

These are *calculated values* from `params.yaml`. They are *not* observed market data.

### 1.4 Repository hygiene observations

- The empty brace-expansion directory `{config,pricing,vol,execution,scenarios,tests,agents,reports}/` exists and is empty; AGENTS.md states it was previously removed. It should be deleted (a separate housekeeping PR) but is harmless.
- `prompts/00_deepseek_repository_audit.md` is the verbatim audit prompt and is untracked.
- `docs/reports/minimax_initial_audit.md` contains stray reasoning fragments from a prior tool run; it is not a real audit deliverable and is untracked.
- `docs/requirements/BTC_30K_Build_Plan_Parallel_Agents.md` (untracked) is the most substantive untracked document; effectively the v1 implementation plan.
- `docs/architecture`, `docs/data`, `docs/model_validation`, `docs/venue_rules` are all empty directories.
- No `__init__.py` anywhere; modules are loaded via `sys.path.insert` + `python3 -m` per AGENTS.md.
- No `pyproject.toml`, no `requirements.txt`, no lockfile. Deps managed ad hoc by `uv` into `.venv/`.

---

## 2. Exact existing interfaces and data models

### 2.1 Pricing — `pricing/black_scholes.py`

**Frozen dataclass**
```python
@dataclass(frozen=True)
class OptionQuote:
    price: float
    delta: float
    gamma: float
    vega: float      # per 1.00 vol (divide by 100 for per-vol-point)
    theta: float     # per year (divide by 365 for per-day)
    strike: float
```

**Functions (signatures verbatim)**

| Function | Signature | Returns |
|---|---|---|
| `price` | `(S, K, r, sigma, T, kind="call") -> float` | Scalar premium |
| `greeks` | `(S, K, r, sigma, T, kind="call") -> OptionQuote` | Frozen dataclass |
| `strike_for_delta` | `(S, target_delta, r, sigma, T, kind="call") -> float` | Analytic strike for Δ |
| `implied_vol` | `(target_price, S, K, r, T, kind="call", lo=1e-4, hi=5.0) -> float` | Brent IV |
| `premium_pct_at_delta` | `(S, delta, r, sigma, dte_days, kind="call") -> (premium %, K)` | Convenience tuple |

**Internal helper:** `_d1_d2(S, K, r, sigma, T) -> (d1, d2)`.

**Conventions (stated in module docstring):**
- Rates and vols are decimals (`0.45` = 45%).
- `T` always in years.
- "Hull/Haug standard" expected test vectors.

### 2.2 Volatility — `vol/dvol_feed.py`

| Function | Signature | Source endpoint |
|---|---|---|
| `_get` | `(method: str, **params) -> dict` | internal |
| `spot_index` | `(currency_pair="btc_usd") -> float` | `public/get_index_price` |
| `dvol_latest` | `(currency="BTC") -> float` | `public/get_volatility_index_data` (last 24h, 1h candles, last close) |
| `option_chain` | `(currency="BTC") -> list[dict]` | `public/get_instruments` (`kind=option, expired=false`) |
| `book_summary` | `(currency="BTC") -> list[dict]` | `public/get_book_summary_by_currency` (`kind=option`) |

Base URL constant: `BASE = "https://www.deribit.com/api/v2/public"`.
Timeout: 15s. No retries. No caching. No rate-limit handling. No websocket.

### 2.3 Execution — `execution/waterfall.py`

| Function | Signature | Notes |
|---|---|---|
| `load_params` | `(path=CFG) -> dict` | Opens `config/params.yaml`. **No context manager** (file handle leak). |
| `waterfall` | `(p: dict \| None = None) -> dict` | 12 keys listed above. Reads `reference_spot_usd`, `btc_quantity`, `seller_discount_pct`, `execution_fee_pct`, `target_option_yield_pct` only. Other params (`call_delta_target`, `dte_target_days`, `strike_target_pct_above_spot`, `target_monthly_premium_pct`, `iv_working_band_pct`, `risk_free_rate_pct`, `tranche_btc`, `expiry_ladder_dte`) are **unused**. |

### 2.4 Config — `config/params.yaml`

```yaml
btc_quantity: 30000
reference_spot_usd: 65000          # working value 27.07.2026
seller_discount_pct: 2.5
target_option_yield_pct: 2.5
combined_target_discount_pct: 5.0
execution_fee_pct: 0.5
call_delta_target: [0.10, 0.15]
dte_target_days: [30, 45]
strike_target_pct_above_spot: [15, 20]
target_monthly_premium_pct: 3.0
iv_working_band_pct: [40, 50]
risk_free_rate_pct: 4.0
tranche_btc: [250, 1000]
expiry_ladder_dte: [30, 37, 44]
```

`combined_target_discount_pct` is declared but never consumed by `waterfall.py`.

### 2.5 Tests — `tests/test_engine.py`

**Modules imported:** `math`, `sys`, `pathlib`, `pricing.black_scholes` (5 names), `execution.waterfall` (2 names), `scipy.optimize.brentq` (used inline in one test).

**Top-level constants:** `S=K=100`, `r=0.05`, `sig=0.20`, `T=1.0` (the standard Hull vector).

**No fixtures, no `tests/fixtures/` directory exists.** AGENTS.md references "offline fixtures for tests live in tests/fixtures/" — that directory is missing.

### 2.6 Missing interfaces

- No pydantic models. `contracts.md` referenced by A1, A3, A4, A6 is **not on disk**. AGENTS.md and A6 both acknowledge this is a planned Sprint 0 freeze gate that has not yet been performed.
- No `Option`/`Leg`/`Strategy` dataclass for composed positions.
- No `Quote`/`BookSnapshot`/`VolSurface`/`ForwardCurve` data classes.
- No domain enums (option kind, exercise style, settlement type).

---

## 3. What the nine tests validate and do not validate

### 3.1 Tests as committed

| # | Test | What it validates |
|---|---|---|
| 1 | `test_call_golden` | BS call price at S=K=100, r=0.05, σ=0.20, T=1 → 10.4506 (Hull). Tolerance 1e-3. |
| 2 | `test_put_golden` | BS put price at same vector → 5.5735. Tolerance 1e-3. |
| 3 | `test_put_call_parity` | C − P = S − K·exp(−rT) to 1e-9. |
| 4 | `test_delta_golden` | Call Δ → 0.6368. Tolerance 1e-3. |
| 5 | `test_implied_vol_roundtrip` | `implied_vol(price(σ=0.20), …) ≈ 0.20` to 1e-6. |
| 6 | `test_strike_for_delta_roundtrip` | Strike-from-Δ(0.125, 37DTE, σ=0.45) feeds back into Δ to 1e-6. |
| 7 | `test_mandate_125delta_premium_band` | At S=65k, Δ=0.125, 37DTE, σ=0.45 → premium in (0.7%, 1.0%) and K in (76k, 80k) and K/S in (1.15, 1.23). |
| 8 | `test_target_yield_requires_higher_delta_or_iv` | Root-finds the Δ that yields 3% premium-per-cycle at the mandate vol/DTE; asserts Δ ∈ (0.28, 0.38). |
| 9 | `test_waterfall_mandate_numbers` | The seven headline waterfall numbers vs `params.yaml`. |

### 3.2 What the suite does **not** validate

- **No put Greeks test.** Only call Δ is golden-tested; Γ, Vega, Θ are unverified.
- **No Black-76 test** (futures-payoff options — required by A1 and by Deribit's inverse contracts).
- **No inverse-BTC adjustment test** (required by A1 and by the mandate's "Cash and inverse-BTC settlement" requirement).
- **No dividend-yield / cost-of-carry test.** Treated as zero (`r` only), which is acceptable for European options on the *spot index* but **inadequate** for inverse contracts and for futures-settled BTC options on Deribit, where the cost-of-carry / funding basis is non-trivial.
- **No finite-difference or numerical-Greek cross-check.** The Greeks are returned as closed-form derivatives with no independent cross-validation.
- **No American-option test** (Deribit instruments are European, so this is acceptable but should be documented).
- **No DVOL feed test.** No recorded fixtures, no offline replay, no assertion on a known value.
- **No scenario / backtest / Monte Carlo / stress test** (these modules do not exist).
- **No coverage of the mislabelled "Covered Put = Long BTC + Short Put" diagram** (the canonical-classification check mandated by AGENTS.md §"Strategy classification and payoff integrity").
- **No tests at the AGENTS.md-mandated payoff breakpoints** (S=0, S<K, S=K, S=S₀, S≫K) for any strategy leg.
- **No QuantLib parity suite** (installed but unused).
- **No hypothesis property tests** (installed but unused).
- **No tranche-reconciliation test** for the [30/37/44] DTE ladder summing to 30,000 BTC.
- **No fee-base sensitivity test** (full notional vs executed-volume variants).

The "9 green at handover" badge is a true statement of the test surface, but it covers only pricing-math sanity plus one fee economic — none of the structures required by the mandate.

---

## 4. Pricing, Greeks, implied-volatility and delta-inversion correctness

### 4.1 Closed-form Black-Scholes

The implementation in `pricing/black_scholes.py` is textbook-correct against Hull:

- d₁ = [ln(S/K) + (r + ½σ²)T] / (σ√T)
- d₂ = d₁ − σ√T
- Call: S·N(d₁) − K·e^(−rT)·N(d₂)
- Put: K·e^(−rT)·N(−d₂) − S·N(−d₁)
- Δ_call = N(d₁), Δ_put = N(d₁) − 1
- Γ = φ(d₁) / (S·σ·√T)
- Vega = S·φ(d₁)·√T
- Θ_call = −S·φ(d₁)·σ/(2√T) − r·K·e^(−rT)·N(d₂)
- Θ_put = −S·φ(d₁)·σ/(2√T) + r·K·e^(−rT)·N(−d₂)

Verified by tests 1–4 and the put-call parity check to ~1e-9.

### 4.2 Vega / Theta units (mismatch risk)

`vega` is returned per 1.00 of vol, `theta` per year. The docstring notes the conversion (`÷100`, `÷365`). This is a *convention*, not an error, but **no test enforces the convention**, and there is no helper to convert. If downstream code mistakenly uses the raw vega as a "per vol point" number, the impact estimate will be 100× too large. A5's "IV give-up model" is the first downstream consumer; this is the first failure mode.

### 4.3 Inverse-BTC options — **not handled**

Deribit BTC options can be linear (USD-settled) or inverse (BTC-settled, payoff `max(S−K, 0) / S` for inverse calls, in BTC). The current pricer has no flag for settlement currency and treats K as a USD-strike on USD-spot. The build plan says inverse adjustment will be added by A1 with a "documented convention vs Deribit spec". Until then, any price produced for an inverse Deribit instrument is wrong by a factor of `S` per BTC.

### 4.4 Implied volatility

Brent on `(price − target)` over `[1e-4, 5.0]` with `xtol=1e-8`. Roundtrip test passes to 1e-6. Two concerns:

- No arbitrage-bound enforcement inside the solver (e.g. check that target price is above intrinsic and below a sensible upper bound). A pathological input (e.g. negative price or price above S) will raise a `ValueError` from `brentq` rather than return a typed `ImpliedVolError`. Robustness is fine for a single-shot CLI but insufficient for a calibration loop over a surface.
- No SVI / SABR / parametric fit. The build plan defers this to A2 (`surface.py`).

### 4.5 Delta inversion

Closed-form `N(d₁)=Δ → d₁ = Φ⁻¹(Δ)`, then `K = S·exp((r + σ²/2)T − d₁·σ√T)`. For puts it inverts `N(d₁)−1 = Δ → d₁ = Φ⁻¹(1+Δ)`. Roundtrip test verifies `Δ(strike_for_delta(...)) ≈ target_delta` to 1e-6. **Caveat:** this is the *undiscounted* forward-moneyness inversion. It is exact under Black-Scholes only if `σ` is the BS vol and `r` is the risk-free rate for the *same* discount curve that priced the option. For a DVOL-implied vol versus a USD risk-free rate versus a USD-quoted option on a Deribit inverse, this needs an explicit term-structure and a forward. Not addressed.

### 4.6 Pricing inputs are not from `params.yaml`

`r=0.04`, `S=65_000`, `σ=0.45` in the mandate-economics tests are *hard-coded literals*. AGENTS.md says "no parameter is hardcoded in source — always read from params". Today `pricing/` does not import `params.yaml` at all; only `waterfall.py` does. This is a soft violation of the project's own rule and should be fixed before any agent brief lands.

### 4.7 Numerical-method concerns

- `scipy.stats.norm` and `scipy.optimize.brentq` are used. Both numerically stable; no custom erf implementation.
- No vectorised numpy pricing for grids — required by A1 ("vectorized numpy pricing over strike/expiry grids") and by A2's surface fit.
- No finite-difference bump-and-revalue for cross-checking Greeks.

### 4.8 Bottom line

Pricing and IV/Δ-inversion are mathematically correct **for a single-leg, European, USD-settled, zero-cost-of-carry BS option at the standard Hull vector**. Every structural extension needed by the mandate (inverse, futures-payoff, surfaces, dividend/funding) is absent and must be built and tested before any number derived from this engine can be trusted on a live Deribit instrument.

---

## 5. Current Deribit integration and missing functionality

### 5.1 Present (Sprint 0)

- Public REST only; **no authentication**.
- Four endpoints: `get_index_price`, `get_volatility_index_data` (1h, last 24h), `get_instruments`, `get_book_summary_by_currency`.
- Hard-coded base URL; env vars in `.env.example` (`DERIBIT_BASE_URL`, `DERIBIT_WS_URL`, `DERIBIT_TEST_BASE_URL`, `DERIBIT_TEST_WS_URL`) are **not consumed** by `dvol_feed.py`.
- No retries, no exponential backoff, no rate-limit handling, no 429 detection.
- No on-disk caching of responses.
- No fixture recorder.
- No websocket client (env vars hint one is intended).

### 5.2 Missing functionality (against mandate)

| Need | Status |
|---|---|
| Historical DVOL back beyond 24h | Not implemented (1h window only). |
| Historical option OHLCV | Not implemented (build plan defers to CryptoDataDownload). |
| Full option chain with strikes/expiries/settlement type/exercise style | Partial — `option_chain` returns metadata; nothing parses it. |
| Trade prints / block RFQ results | Not implemented. |
| Websocket subscription for live order-book | Not implemented (env vars exist). |
| Test-environment endpoint | `.env.example` defines it; `dvol_feed.py` does not honour it. |
| Authenticated endpoints (account positions, fills) | Not implemented. |
| Massive.com historical spot (per sanitised mandate §"Data rules") | **Not implemented at all** — see §6. |
| Per-instrument Greeks (Δ, Γ, Vega, Θ) from Deribit | Endpoint exists (`/public/get_book_summary_by_currency` returns `mark_iv`, `greek` fields indirectly via `delta`); parser is not written. |
| Settlement-currency / contract-type metadata | Returned by `get_instruments` but not surfaced. |
| Timezone-aware UTC timestamps | `time.time()` is used as ms; output is not converted to tz-aware UTC. Violates AGENTS.md. |
| Error model (`ImpliedVolError`, `StaleQuoteError`, `VenueUnreachable`) | None. |

### 5.3 Reliability gaps

- No circuit-breaker / dead-letter handling for venue outages.
- No deterministic replay from cached fixtures; CI depends on network if the feed is ever wired into tests.
- The Hetzner-only assumption is documented in the module docstring but not enforced by code; an accidental run elsewhere will fail noisily.

### 5.4 What is acceptable

Public endpoints, base URL, timeout, and the four core calls are all in place. The module is enough to fetch live spot, DVOL, chain and book from Hetzner. Nothing more is promised at Sprint 0.

---

## 6. Missing Massive historical-data integration

### 6.1 Current state

- `MASSIVE_API_KEY`, `MASSIVE_BASE_URL` are declared in `.env.example` only. Nothing in the repo imports them, calls Massive, or has a Massive client stub.
- No `data/` directory exists at the repo root (only `docs/data/`, empty). AGENTS.md's "data/raw/" and "data/hist/" paths are referenced but unmaterialised.
- No CSV/Parquet files anywhere (verified by glob).
- No spot-history module, no DVOL-history module, no option-OHLCV-history module.

### 6.2 Why this matters against the mandate

The sanitised mandate states:
> "Massive is the primary long-history BTC spot source. … Observed market data must remain separate from model-generated historical option prices. No simulated bid, ask, implied volatility, Greek or liquidity value may be represented as an observed market value."

The build plan relies on **CryptoDataDownload** (free CSV tier) for the v1 backtest. There is a real conflict here:

- The mandate names **Massive** as the primary source.
- The build plan names **CryptoDataDownload** as the v1 source.
- Neither is integrated.

This needs a resolution in `contracts.md` (A6) before any agent touches historical data.

### 6.3 Missing pieces (against mandate §"Data rules")

- A Massive REST client (or CSV bulk loader if Massive offers files).
- A typed `SpotBar` / `DvolBar` / `OptionBar` pydantic/dataclass model.
- A provenance tag on every datum: `source ∈ {massive, deribit, cme, otc, vendor, model}`.
- A label distinguishing `observed` from `model_reconstructed` (DVOL-proxy option chain reconstruction).
- A tz-aware UTC timestamp on every record (AGENTS.md requirement).
- A cache layer (Parquet per symbol/expiry/day) with explicit freshness.
- A fixture-recording mode so tests run offline.

---

## 7. Observed versus model-generated historical option data

### 7.1 What exists today

- **Nothing.** No historical option data is loaded, stored, parsed, or labelled by provenance. There is no observed-vs-modelled distinction enforced anywhere in code.

### 7.2 What must exist (per AGENTS.md and mandate)

- Every price, IV, Greek or liquidity estimate must carry a provenance tag.
- Any option price, IV or Greek that is *not* from a live venue feed must be flagged `model_reconstructed` (or similar).
- The build plan acknowledges this explicitly: "Where historical chains are missing, premiums are DVOL-reconstructed and labelled as such — honest v1, upgradeable to vendor data later."

### 7.3 Required artefacts (not yet built)

- A `Provenance` enum and a column/tag on every dataframe / dataclass.
- A `model_reconstructed_iv_from_dvol(...)` helper that explicitly labels its output.
- A backtest harness that asserts it never mixes observed and reconstructed chains without surfacing the boundary to the reader.
- Reports that print the observed/reconstructed split per cycle, per path.

### 7.4 The audit recommends

- Introduce a single `Provenance` literal per datum (never inferred from nullness).
- Make it a compile/runtime invariant: any value crossing a pricing boundary without provenance raises.
- Tag the reference spot (`reference_spot_usd: 65000`) in `params.yaml` as `provenance: working_2026_07_27, source: synthetic_working_value`. Currently it is silently labelled "working value" in a comment only.

---

## 8. Missing volatility-surface and forward-curve components

### 8.1 Current state

- Single scalar vol used in every test (0.20 Hull, 0.45 mandate).
- No expiry dimension.
- No strike dimension beyond single strikes.
- No `ForwardCurve`, `DiscountCurve`, or `VolSurface` dataclass.

### 8.2 What the mandate requires

- "Implied volatility and volatility surfaces" is on the references list.
- A5's six-chart payoff pack needs strikes around spot; without a surface the charts use a flat vol assumption and misrepresent risk.
- A3's stress scenarios require at minimum a per-expiry scalar vol series; with vol-regime shifts (DVOL 35→65) they require a per-expiry-per-strike surface or a deterministic skew function.

### 8.3 Required artefacts

- `VolSurface` (per expiry: strike grid + IV grid; SVI or spline fit).
- `ForwardCurve` (per expiry: forward from put-call parity or cost-of-carry).
- `DiscountCurve` (USD OIS or flat `r` as proxy).
- `surface.py` from A2 brief.
- `IV(delta, dte)` interpolation API.
- QuantLib cross-check (`vanilla.option.delta`, `impliedVolatility`) per A6 brief.

### 8.4 Risk if absent

The cycle simulator and the six-chart pack will look correct numerically but will be flat-vol approximations. For 10–15Δ OTM calls at 30–45 DTE, the smile lift is non-trivial (DVOL is at-the-money; 10Δ calls can price ~5–10 vol points higher in stress regimes). Reporting these as plain BS prices will systematically understate the cycle yield and the impact cost.

---

## 9. Covered-call, cash-secured-put and long-BTC-plus-short-put requirements

### 9.1 Covered call (long BTC + short call)

- **Required by mandate and by AGENTS.md.**
- **Not implemented.** No `Strategy`/`Leg` model, no payoff function, no breakeven computation, no assignment rule.
- For the mandate economics, this is the structure that produces the 2.5% overlay yield (combined with the 2.5% seller discount = 5.0% gross, less 0.5% fee = 4.5% net, per `waterfall.py`). It is the single most important structure to implement.

### 9.2 Cash-secured put (cash + short put)

- **Required.**
- **Not implemented.** No `CashLeg`, no reserved-cash accounting, no short-put payoff, no expiry-ITM conversion into BTC-acquisition cost.
- The build plan mentions CSP only in the cycle-simulator paths and the corrected chart pack. No code.

### 9.3 Long BTC + short put (the mislabelled "covered put")

- **Required explicitly** by AGENTS.md §"Strategy classification and payoff integrity":
  > "Long BTC plus short put must be represented explicitly as long BTC plus short put."
- **Not implemented.** No payoff, no classification rule.
- This is the diagram flagged in the sanitised mandate §"Source-diagram discrepancy". See §16 for the full mathematical derivation.

### 9.4 Collars, partial overlays, staggered expiries, call spreads, rolling

- **All required, all unimplemented.**
- Staggered expiries is partially parameterised via `expiry_ladder_dte: [30, 37, 44]` in `params.yaml`, but the parameter is unused by `waterfall.py`.
- Rolling is mentioned by A4 and A5 ("rolling and closing rules", "rolling and dynamic hedging" in references) but absent from code.

### 9.5 Required software skeleton (not to be implemented in this audit)

- `Leg` dataclass: `{side, instrument, quantity, strike, premium, expiry, settlement}`.
- `Strategy`: list of legs with named canonical classification (covered call, CSP, long BTC + short put, collar, etc.) **plus** an optional `source_label` so the mislabelled diagram's name survives alongside the canonical name.
- `payoff(strategy, S) -> dict[leg -> float]` evaluable at `S=0, S<K, S=K, S=S₀, S≫K`.
- `breakeven(strategy) -> list[float]`.
- `mtm(strategy, market) -> dict[leg -> float]`.
- `assignment_underlyings(strategy) -> list[float]` (physical vs cash vs inverse-BTC).
- A canonical-classification function whose input is legs, not titles.

---

## 10. Assignment, exercise, cash settlement, inverse-BTC settlement and rolling

### 10.1 Current state

- **Nothing.** No code path distinguishes physical assignment from cash settlement from inverse-BTC settlement. No rolling logic.

### 10.2 Required handling per mandate and AGENTS.md

- **Physical assignment:** for an inverse-BTC short put ITM at expiry, the seller is *assigned* a long BTC position funded in BTC (delivery at strike × quantity). The realised acquisition cost equals `strike − premium`, in BTC.
- **Cash settlement:** for a USD-settled short call ITM at expiry, the seller pays `(S_T − K) × q` in USD and retains the premium.
- **Inverse-BTC settlement:** for an inverse-BTC short call ITM at expiry, the seller pays `(S_T − K)/S_T × q` in BTC. The realised cost in BTC equals `1 − K/S_T − premium/S_T`.
- **Rolling:** replace a position with one at a later expiry (and typically a different strike), booking a debit/credit from the premium differential. Costs include the bid/ask on close and on open.

### 10.3 Audit recommendation

- Implement three settlement flags on `Option`/`Leg`: `settlement ∈ {physical_usd, cash_usd, inverse_btc}`.
- Write three settlement converters, each unit-tested against a manual worked example at S_T = {0, K/2, K, S₀, 2K}.
- Implement rolling as `(close_payoff, open_premium) → net_debit` with explicit bid/ask impact and an "early close" toggle.
- Document each rule with the underlying venue contract spec (Deribit inverse-BTC contract spec is the canonical source; A2 is responsible for ingesting it under `docs/venue_rules/`).

### 10.4 Reverse-BTC / quanto adjustments

Not addressed. For an instrument settled in BTC but struck in USD on a USD-quoted index, the cost-of-carry adjustment between the risk-free curve and the BTC repo/funding curve matters. A1's brief implies Black-76 plus inverse adjustment will handle this; both are absent.

---

## 11. Backtesting, Monte Carlo, stress testing and out-of-sample validation

### 11.1 Current state

- No `scenarios/`, `montecarlo.py`, `backtest.py`, or `stress.py`.
- No deterministic seeds anywhere.
- No historical data file.
- Five-path cycle-simulator described in build plan §Sprint 2 has zero code behind it.

### 11.2 What is required

- **Monte Carlo** with GBM, Merton jump-diffusion, Kou double-exponential, antithetic variates, 100k paths in <5s (A3 spec).
- **Backtest engine** cycling over Jan-2023 → Jul-2026 with the five paths (spot / OTC −2.5% / covered call 10–15Δ / covered call at ~30–35Δ that yields 3%/cycle / CSP entry).
- **Stress scenarios:** 2023–24 surge, 2025 breakout to 126k ATH, 2026 retrace to ~65k, DVOL 35→65 shock.
- **Lopez de Prado hygiene:** no parameter fitting inside the evaluation window. Documented. Deterministic seeds.

### 11.3 Out-of-sample validation

The build plan mentions out-of-sample validation in the mandate §"Required analysis" but not in A3's brief. This needs to be added explicitly:
- Train/validation split on the historical window.
- Held-out last 20% of paths for cross-checking calibrated-vs-naïve parameters.
- Walk-forward (rolling re-calibration) for the vol surface.

### 11.4 Gap summary

Backtesting, MC, stress and OOS are entirely absent. Without them the mandate's "Historical backtesting / Monte Carlo and stress testing / Out-of-sample validation / Regime analysis" requirements are unsatisfied.

---

## 12. Execution, impact, tranching and fee modelling for 30,000 BTC

### 12.1 Current state

- `waterfall.py` models the **level economics** (notional, discount, fee, net discount) — a single-shot calculation.
- No clip-by-clip impact.
- No tranche scheduler.
- No bid/ask spread model.
- No square-root impact (Kissell / Almgren-Chriss).

### 12.2 What is required

- **Per-clip IV give-up:** 0.5–2.0 vol pts default, configurable, fed from the A2 mark-IV surface (A4 spec).
- **Square-root impact for spot leg** per Kissell/Almgren-Chriss.
- **Tranche scheduler** across `[30, 37, 44]` DTE and clips `[250..1000]` BTC over 4–8 weeks, summing **exactly to 30,000 BTC** (A4 spec).
- **Sensitivity mode** in `waterfall.py` for spot ±10% and fee-base variants (full notional vs executed volume). The fee-base sensitivity is the "$9.75M swing" called out in §7 of the build plan.
- **Bid/ask, market impact, slice-by-slice slippage** for institutional scale.

### 12.3 Audit observations on waterfall math

- `asymmetrica_fee_usd = notional × fee = S × q × 0.005`. This treats the fee as a fraction of **reference notional**, not of executed volume. The build plan's open question ("fee base: full notional vs executed volume") is unanswered.
- `client_cash_per_btc = price_after_disc + S × fee`. The `S × fee` term is the per-BTC fee allocation; multiplying by `q` and adding to `q × price_after_disc` should equal `q × price_after_disc + notional × fee`, which equals `1_911_000_000` — matches the printed output. ✓
- `client_effective_cost_per_btc = client_cash_per_btc − S × ovl`. The overlay target `ovl` is `target_option_yield_pct` applied to notional — i.e. an **assumption that the option-leg yield equals 2.5% of notional every cycle**. This is a *business assumption* / target, not a calculated value. It is correctly labelled in `params.yaml` as `target_*`, but the waterfall output column `overlay_target_usd` should be re-read as "target" not "expected", and any downstream report should not present it as a forecast. Currently the waterfall reports it without that qualifier.
- `net_discount_vs_reference_pct = 100 × (1 − 62,075 / 65,000) = 4.5%`. This is the *target* net discount, conditional on the overlay being achieved. Any actual realised overlay will produce a different net.

### 12.4 Math review: is the overlay-side handling correct?

Covered-call contribution in USD terms, assuming premium of σ·S·√(T/π) (rough ATM-proxy), a 12.5Δ 37DTE call at σ=0.45 yields ~0.82% of spot per cycle (test 7 confirms). Annualised at 30–45 DTE (~9 cycles/year), that is ~7–8% per year, or ~0.65% of notional per cycle. The mandate target is 2.5% of notional per cycle. That is roughly **3.8× the realistic yield at the low end of the mandate delta band**, consistent with test 8's finding that the target yield requires ~30–35Δ.

Implication: `waterfall.py` is correctly arithmetic but **its "target_case" output is the desired business outcome, not the cycle-implied outcome**. Without a `cycle-implied overlay` calculation fed from `premium_pct_at_delta`, the displayed 4.5% net discount is an aspiration, not a forecast. This should be flagged in reports (A5) and called out in the demo script.

### 12.5 No 30,000 BTC scheduling yet

`tranche_btc: [250, 1000]` and `expiry_ladder_dte: [30, 37, 44]` are declared but unused. The tranche scheduler (A4) is the only thing that will validate the 30,000 BTC schedule reconciles.

---

## 13. Validation, reporting, security and data-governance gaps

### 13.1 Validation gaps

- **No CI.** AGENTS.md explicitly states "No CI/CD, no Docker, no pre-commit hooks." A6 brief requires GitHub Actions with pytest + mypy + ruff + QuantLib parity. **Absent.**
- **No mypy config.** AGENTS.md says `mypy <file>` per-file. Without a config, `mypy --strict` (required by A1) will be a moving target.
- **No ruff config.** Same caveat.
- **No type annotations on `waterfall.py`.** Function arguments are untyped; return dict has untyped values.
- **No docstrings on `waterfall.load_params`, `waterfall.waterfall`.**
- **`load_params` leaks file handle** (no context manager).
- **No property-based / hypothesis tests.**
- **No recorded fixtures; no offline CI replay.**

### 13.2 Reporting gaps

- No `reports/` directory at repo root.
- No `cycle_report.py` (cycle premium vs 2.5% cumulative target tracker).
- No `demo.py` (single command → full demo pack).
- No chart pack (`charts.py`, six-chart corrected payoff sequence).
- No `tests/fixtures/`.
- The single artefact that exists is `python3 -m execution.waterfall` printing 12 lines — sufficient for the Sprint-0 demo of "the waterfall" but insufficient for the cycle simulator and chart pack.

### 13.3 Security gaps

- **No secret management.** `.env` is gitignored, `.env.example` declares keys. OpenCode's `opencode.json` reads `DEEPSEEK_API_KEY` and `MINIMAX_API_KEY` from env. **But** the audit did not find the `.env` file on disk (it is correctly excluded). This is a risk: anyone running the project must populate `.env` manually before opencode.json's `{env:...}` resolves.
- **No rate limiting / API-budget guards** on Massive or Deribit.
- **No input validation on `params.yaml`.** A malformed YAML will crash with a stack trace. A typed pydantic schema is required (A6).
- **No provenance tagging** for any datum (see §7).
- **No allowlist of writable paths** in the opencode permission set. The auditor agent is correctly scoped to read-only, but the implementation agents (when invoked) will need explicit constraints on `reports/`, `tests/fixtures/`, `docs/venue_rules/` to prevent leaking outside the repo.
- **`.env` is correctly gitignored** (verified).

### 13.4 Data-governance gaps

- The mandate names Massive, Deribit, CME and OTC as origins. **No data origin is actually used today.** CME and OTC are entirely absent.
- The sanitised mandate's confidentiality clause (counterparty names, sovereign-fund identities, introducers, wallet addresses, API keys, deal identifiers) has no enforcement mechanism in code today — it relies on discipline only. `contracts.md` (A6) should encode it as a `ConfidentialityError` raised on any detected PII pattern in prompts/fixtures/logs/commits.
- The `docs/reports/minimax_initial_audit.md` file contains stray model-reasoning fragments from a previous run. It is untracked. It is not a deliverable. It should be deleted or moved out of `docs/`.

### 13.5 Logging / timestamps

- AGENTS.md requires tz-aware UTC timestamps. `vol/dvol_feed.py` uses `int(time.time()*1000)` — naive Unix-ms. `execution.waterfall.py` prints no timestamps. This is a soft violation today; will become a hard violation once cycle-reporting is added.

---

## 14. Conflicts or unclear dependencies in A1–A6

### 14.1 Missing contracts.md freeze

A1, A3, A4 explicitly depend on `contracts.md`. A6 says it freezes `contracts.md` "FIRST (Sprint 0 gate)". **Sprint 0 has been delivered but `contracts.md` was not frozen.** No pydantic models exist. The current "frozen" interfaces are the function signatures in `pricing/black_scholes.py` and `vol/dvol_feed.py` — these are not formally frozen, not versioned, not reviewed. Any agent that lands now risks having its branch rejected by A6's merge.

### 14.2 Merge order conflict

A6 states: "Merge order: A1 → A2 → A4 → A3 → A5." The build plan §Sprint 1 also says A1 ∥ A2 ∥ A4 in parallel. **Contradiction resolved in favour of A6** (merge order). Implication: A3 must not start until A1+A2 are merged. The brief "A3 depends on A1 interfaces, A2 fixtures" is correct but soft — A3 can start prototyping once stubs exist (which is what the parallelisation rationale says).

### 14.3 Source-of-truth conflict on historical data

- Sanitised mandate §"Data rules": Massive is the primary long-history BTC spot source.
- Build plan §"Data plan": CryptoDataDownload free CSVs is the v1 source.

A2 brief says "ingest CryptoDataDownload free CSVs". This contradicts the mandate. **The mandate prevails** (business requirement). Resolution options:
- Massive for spot/DVOL history; CryptoDataDownload only for option OHLCV (Massive's free option coverage may be limited).
- Both, with Massive preferred and CDD as fallback.
- Reject the v1 plan and gate on Massive ingestion.

A6 must resolve this in `contracts.md`.

### 14.4 A5's mislabelled-chart correction depends on strategy code that does not exist

A5 says: "regenerate the circulating long-BTC+short-put chart CORRECTLY labeled (leveraged-bullish; slope +1 above strike, +2 below; no max-profit cap)". The chart pack and the underlying payoff function **do not exist**. A5 cannot complete without A1 + an unbuilt strategy engine. This is acknowledged in the build plan (Sprint 3 "consuming everyone's outputs") but should be made explicit in A5's DoD.

### 14.5 A3's DVOL-reconstructed chains are not part of the strategy-engine interface

A3 will produce reconstructed option chains using DVOL as the vol input and a flat-skew assumption. These reconstructed chains must be tagged `model_reconstructed` everywhere they cross an interface. None of A1, A3, A4, A5 mention provenance as a contract field. This is a gap in `contracts.md`'s intended content.

### 14.6 A4 fee-base sensitivity depends on waterfall.py internals that aren't extensible

A4 brief says `waterfall.py: add sensitivity mode (spot ±1..10%; fee-base variants: full notional vs executed volume)`. Current `waterfall()` takes a single `params` dict and returns a flat dict. Adding sensitivity cleanly requires either:
- A `waterfall_with_sensitivities(p, spot_grid, fee_base_grid) -> pd.DataFrame`-style extension, or
- A class-based refactor.

Neither path is documented. A4 will need to refactor `waterfall.py` as part of DoD.

### 14.7 A6's QuantLib parity job requires A1 to install/import QuantLib

`QuantLib` is "installed in `.venv` but not yet used" per AGENTS.md. A1 must add the parity test. A6 must wire the CI job. Neither is done.

### 14.8 Anonymisation rule has no automated enforcement

A6 §"Anonymization rule (hard)" — no counterparty names, wallets, deal identifiers in prompts/commits/fixtures. There is no pre-commit hook or CI grep to enforce. Reliance on discipline alone is a governance gap.

### 14.9 Branch / workflow ambiguity

AGENTS.md: "Single commit (`7a22caf`), single branch (`main`)." Agent briefs reference `feat/pricing`, `feat/vol`, `feat/scenarios`, `feat/execution`, `feat/reports` branches. There is no branching strategy, no PR template, no CODEOWNERS, no merge gate. A6's "merge owner on main" is a person, not a system.

### 14.10 Untracked `contracts.md` references

The build plan and agent briefs all reference `contracts.md`. It does not exist. **This is the single highest-risk blocker** — every parallel agent depends on it.

---

## 15. The safest implementation sequence

The dependency graph below is ordered so that every step is small, testable, and adds an enforceable invariant. It assumes no `contracts.md` is yet frozen (which is the audit's #1 finding to address first).

### Phase 0 — Contracts and governance (Day 0–1)

1. **Freeze `contracts.md`** with pydantic v2 models for: `Option`, `Leg`, `Strategy`, `Quote`, `BookSummary`, `SpotBar`, `DvolBar`, `OptionBar`, `VolPoint`, `VolSurface`, `ForwardCurve`, `DiscountCurve`, `Provenance`, `SettlementType`, `ExerciseStyle`.
2. **Add CI** (GitHub Actions): pytest + mypy + ruff on every PR. Pin mypy `--strict` and ruff rules in `pyproject.toml`.
3. **Add type annotations to `waterfall.py`** and fix the file-handle leak. Wrap `params.yaml` with a pydantic schema; reject malformed files.
4. **Add pre-commit hook** (or CI step) that greps prompts, fixtures, logs and commits for known PII patterns and refuses on hit (anonymisation enforcement).

### Phase 1 — Pricing completeness (Day 1–3, single agent, sequential)

5. Extend `pricing/black_scholes.py` with **Black-76** (futures-payoff options) and an **inverse-BTC adjustment** (document the convention against Deribit's spec). Add at least 10 Haug golden vectors for each.
6. Add a **full Greeks test for puts** (Γ, Vega, Θ) with golden vectors.
7. Add a **finite-difference cross-check** of all Greeks against closed-form on a 5×5 grid.
8. Add a **QuantLib parity suite** (50 random draws, max abs diff < 1e-6) using `hypothesis` for property generation.
9. Add **vectorised numpy** pricing for grids.

### Phase 2 — Data and vol surface (Day 2–5, parallel after Phase 1)

10. **Massive client** for spot + DVOL history. Decision on CryptoDataDownload vs Massive resolved here.
11. **Harden `vol/dvol_feed.py`**: retries/backoff, parquet caching, fixture recorder, tz-aware UTC timestamps, env-driven base URL.
12. **`surface.py`**: per-expiry IV fit (spline; SVI stretch) from `book_summary` mark_iv; `IV(delta, dte)` interpolator.
13. **`garch.py`**: GARCH(1,1) realised-vol forecast; comparison vs DVOL.

### Phase 3 — Strategy and settlement engine (Day 4–7)

14. Implement `Leg`, `Strategy`, payoff, breakeven, MTM using the `contracts.md` models. Canonical-classification function with explicit legs (no title dependency).
15. Implement three settlement converters (physical_usd, cash_usd, inverse_btc), each unit-tested at S_T = {0, K/2, K, S₀, 2K}.
16. Implement rolling as `(close_payoff, open_premium) → net_debit`.
17. Implement the **source-diagram discrepancy check**: when a chart label and the canonical classification disagree, both are preserved and a `LabelConflict` warning is raised.

### Phase 4 — Scenarios (Day 6–9)

18. `montecarlo.py`: GBM + Merton + Kou with antithetic variates and 100k paths <5s.
19. `backtest.py`: five-path cycle engine over Jan-2023 → Jul-2026 with `model_reconstructed` provenance labels.
20. `stress.py`: 2023-24 surge / 2025 breakout to 126k / 2026 retrace / DVOL 35→65 shock.
21. OOS validation: walk-forward re-calibration on a 20% hold-out.
22. Determinism + Lopez de Prado hygiene asserted by tests.

### Phase 5 — Execution (Day 7–10)

23. `impact.py`: per-clip IV give-up (configurable) + square-root impact.
24. `tranches.py`: scheduler across `[30, 37, 44]` DTE and `[250..1000]` clips summing to exactly 30,000 BTC.
25. Extend `waterfall.py` with a sensitivity mode (spot ±10%, fee-base variants) producing a typed result.
26. Tests asserting tranche reconciliation and fee-base monotonicity.

### Phase 6 — Reports and demo (Day 9–12)

27. `charts.py`: six-chart corrected payoff sequence at live spot, premium-inclusive breakevens.
28. Regenerate the long-BTC+short-put chart with the canonical label and piecewise payoff shape (slope +1 above strike, +2 below, no max-profit cap).
29. `cycle_report.py`: per-cycle premium vs 2.5% cumulative target.
30. `demo.py`: one-command full demo pack from cached fixtures, offline, <60s.

### Phase 7 — QA close (Day 12–14)

31. Fable cross-validates every human-facing number independently.
32. Internal dry-run of the demo script.
33. Hardening (Docker, one-command Hetzner deploy, optional vendor-data slot).

**Critical sequencing constraints:**
- Phase 0 must complete before any other phase.
- Phase 1 must complete before Phase 3 (strategy payoff uses the pricers).
- Phase 2 must complete enough that A2 fixtures exist before Phase 4 (backtest needs history).
- Phase 5 can start in parallel with Phase 4 after Phase 3's impact helpers exist.
- Phase 6 is downstream of everything; never start it before Phase 5 completes.

The **single most important** action is item 1 (freeze `contracts.md` + pydantic models). Every other phase is blocked on it or significantly de-risked by it.

---

## 16. The source-diagram discrepancy: canonical derivation

The sanitised mandate §"Source-diagram discrepancy" specifies:

> **Source label:** "Covered Put Strategy (Long BTC + Short Put)"
> **Actual legs:** Long BTC, Short put

The title must not be treated as authoritative. The audit derives the canonical classification, payoff and software representation strictly from the legs.

### 16.1 Position legs and unit conventions

Let:

- `q > 0` be the BTC quantity (per `params.yaml: btc_quantity: 30000`, fully configurable).
- `K_put` be the short-put strike in USD.
- `P₀` be the premium received per BTC for the short put, in USD.
- `S₀` be the spot at trade entry (per `params.yaml: reference_spot_usd: 65000`, working value).
- `S_T` be the spot at expiry.
- `r` be the USD risk-free rate (per `params.yaml: risk_free_rate_pct: 4.0`).
- `σ` be the vol used to price the put (per `params.yaml: iv_working_band_pct: [40, 50]`).
- `T` be the time to expiry in years (from `expiry_ladder_dte`).

The "short put" leg is **USD-settled** (we assume cash-settled for the structural derivation; the inverse-BTC variant is in §16.6). The "long BTC" leg is the physical BTC held (or equivalent long exposure).

### 16.2 Canonical classification

A conventional *covered put* (per AGENTS.md) consists of **short underlying exposure** plus a **short put** — i.e. it is the put-side analogue of a covered call. The position in the diagram has **long**, not short, underlying.

The correct canonical name for **Long BTC + Short Put** is the standard market term for the position: a **synthetic long** (long futures-style exposure) or, more specifically, a **long-BTC-plus-short-put** structure — explicitly per AGENTS.md §"Strategy classification and payoff integrity":

> "Long BTC plus short put must be represented explicitly as long BTC plus short put."

It is **not** a covered put. It is **not** a covered call. It is **not** a cash-secured put. The mandate explicitly says these terms must not be conflated.

### 16.3 Expiry payoff — piecewise

Let `Π(S_T)` be the per-BTC payoff at expiry, before marking the initial spot cost. Per BTC of short put, one short put sold at strike `K_put` pays:

```
short_put_payoff(S_T) = +P₀           if S_T ≥ K_put     (put expires worthless, premium kept)
                       = +P₀ − (K_put − S_T)   if S_T < K_put   (put assigned, seller buys at K)
```

Per BTC of long BTC, the mark-to-market P&L relative to `S₀` is:

```
long_btc_pnl(S_T) = S_T − S₀
```

Total per-BTC P&L (relative to entry):

```
Π(S_T) = (S_T − S₀)  +  P₀                          if S_T ≥ K_put
Π(S_T) = (S_T − S₀)  +  P₀ − (K_put − S_T)          if S_T < K_put
```

Equivalently:

```
Π(S_T) = (S_T − S₀)  +  P₀ − max(K_put − S_T, 0)
```

At expiry the *realised acquisition cost per BTC* (the economic figure relevant to the mandate's "effective BTC acquisition cost") is the entry spot minus the per-BTC premium kept plus the put assignment buy-in:

```
effective_cost_per_btc(S_T) = S₀ − P₀                 if S_T ≥ K_put
effective_cost_per_btc(S_T) = K_put − (S_T − S₀) + S₀ − P₀
                             = K_put − P₀             if S_T < K_put
```

The structure therefore yields a per-BTC effective cost of:

- `S₀ − P₀` if the put expires OTM (the upside scenario — same as writing a covered call: keep premium, no further obligation).
- `K_put − P₀` if the put finishes ITM (the downside scenario — the put converts into a buy at the strike, so the cost basis is the strike minus the premium kept).

### 16.4 Comparison with the other named structures

| Property | Covered call (long BTC + short call) | Cash-secured put (cash + short put) | **Long BTC + short put** (the diagram) |
|---|---|---|---|
| Underlying leg | Long BTC | Cash reserved at strike (no BTC held) | **Long BTC** |
| Option leg | Short call OTM | Short put OTM | **Short put OTM** |
| Expiry OTM payoff | `S_T − S₀ + P₀` (capped at `K_call − S₀ + P₀`) | `−K_put + P₀` (cash earns interest, premium kept) | **`S_T − S₀ + P₀`** (uncapped on the upside; spot leg keeps appreciating) |
| Expiry ITM payoff | `K_call − S₀ + P₀` (flat) | `(S_T − K_put) − K_put + P₀` (BTC acquired at K, premium kept, in BTC terms) | **`S_T − S₀ + P₀ − (K_put − S_T)`** (= `2·S_T − S₀ − K_put + P₀`) |
| Breakeven | `S₀ − P₀` | `K_put − P₀` (in BTC-acquisition-cost space) | **`S₀ − P₀`** (same as covered call on the upside; identical breakeven above strike) |
| Slope above K | `+1` (cap at K) | `0` (no BTC exposure; cash flat) | **`+1` (no cap)** |
| Slope below K | `0` | `+1` (assigned, acquire BTC at K) | **`+2`** (BTC appreciates, put assigns cheaper) |
| Max profit | Capped at `K_call − S₀ + P₀` | Capped at `P₀` (premium only) | **Uncapped** (the long spot leg has no ceiling) |
| Max loss | `S₀ − P₀` (spot to zero, premium kept) | `K_put − P₀` (acquire at K, premium kept) | **`K_put − P₀ − S₀`** (spot to zero, premium kept, put assigned, but spot leg also worth zero; net cost = K − premium, but loss vs entry = S₀ − K + premium) |
| Capital at risk | Full BTC notional + margin on short call | Cash `K_put × q` reserved + margin | Full BTC notional + margin on short put |
| Net effect | Income overlay with capped upside | BTC acquisition at lower-than-spot cost | Leveraged bullish: amplifies BTC gains AND effectively buys the dip |

### 16.5 Key annotations in the source diagram that require mathematical verification

If the source diagram presents the position with any of the following annotations, **they are mathematically wrong** and must be flagged:

1. **A horizontal payoff plateau above the strike** — the long-BTC leg has no cap. The diagram is incorrect if it shows flattening above `K_put`.
2. **A flat zero slope above the strike** — slope is `+1`, not `0`.
3. **A single linear segment below the strike** — slope is `+2` (combined long BTC + long put assigned at K), not `+1`.
4. **A "max profit" annotation above the strike** — there is no maximum profit from the long BTC leg alone.
5. **The label "Covered Put"** — a covered put has **short** underlying, not **long**. The label is misclassified.
6. **A breakeven annotated at `S_T = K_put`** — breakeven is at `S₀ − P₀` (where entry cost is recovered by the premium). `S_T = K_put` is the assignment boundary, not the breakeven.
7. **A "margin" or "collateral" annotation referencing only the put premium** — the position requires full BTC notional, not just the put collateral.

Any of (1)–(7) is a red flag that the diagram was produced from the title rather than from the legs. A5's brief says exactly this — the chart must be regenerated correctly with slope `+1` above strike and slope `+2` below strike, with no profit cap, labelled "Long BTC + Short Put (leveraged-bullish)".

### 16.6 Inverse-BTC settlement variant

If the short put is **inverse-BTC settled** (Deribit does issue inverse puts), the per-BTC payoff in BTC at expiry becomes:

```
Π_btc(S_T) = (S_T − S₀)/S₀ + P₀/S₀                     if S_T ≥ K_put
           = (S_T − S₀)/S₀ + P₀/S₀ − (K_put − S_T)/S_T  if S_T < K_put
```

The realised acquisition cost in BTC:

```
effective_cost_btc(S_T) = 1 − P₀/S₀                if S_T ≥ K_put
                        = K_put/S_T − P₀/S₀         if S_T < K_put
```

Note `K_put/S_T > K_put/S₀` when `S_T < S₀` — i.e. inverse-BTC settlement gives a *worse* acquisition cost for the same strike in a sell-off than cash settlement would. This is the standard inverse-contract convexity.

### 16.7 Recommended canonical software representation

The audit recommends the following minimal data model (compatible with the still-to-be-frozen `contracts.md`):

```
@dataclass(frozen=True)
class Leg:
    side: Literal["long", "short"]
    instrument: Literal["spot", "call", "put"]
    quantity_btc: float
    strike: Optional[float]            # USD, required for options
    premium: float                     # USD per unit, positive = paid, negative = received
    expiry: datetime                   # tz-aware UTC
    settlement: SettlementType          # physical_usd | cash_usd | inverse_btc
    exercise: ExerciseStyle            # european (default) | american

@dataclass(frozen=True)
class Strategy:
    name: str                          # human label
    source_label: Optional[str]        # preserves the original business label if it disagrees
    legs: tuple[Leg, ...]

def canonical_classification(s: Strategy) -> StrategyKind:
    """Derive canonical name strictly from legs. Returns one of:
       covered_call, cash_secured_put, long_btc_plus_short_put,
       collar, put_spread, call_spread, ... plus a structural check
       that the source_label (if any) matches, otherwise raises
       LabelConflict carrying both names."""
```

Required invariants:

- `canonical_classification` **must not** consult `source_label`.
- If `source_label` is provided and disagrees with `canonical_classification`, return both in the response (a `LabelConflict` object) rather than choosing one.
- `payoff(strategy, S_T)` must use the same payoff functions as the backtester and the chart pack.
- The `source_label "Covered Put Strategy (Long BTC + Short Put)"` should round-trip through `canonical_classification` as `long_btc_plus_short_put` with `LabelConflict(source_label="Covered Put Strategy (Long BTC + Short Put)", canonical="long_btc_plus_short_put")`.
- Tests must assert the payoff at `S_T = {0, K/2, K, S₀, 2K}` per AGENTS.md.

### 16.8 What "long BTC plus short put" is for in this mandate

In the Asymmetrica BTC acquisition context, the structure serves a *leveraged-bullish accumulation* purpose:

- If BTC rises above `K_put` at expiry: keep the premium; the long BTC leg captures the upside. This is the pure "hold-and-collect" use case.
- If BTC falls below `K_put` at expiry: the put assignment means you effectively buy more BTC at the strike, **lower than spot** — a desirable acquisition price. Per-BTC realised cost: `K_put − P₀`.

This is structurally different from a covered call (which is the natural "hold-and-collect" income strategy) and different from a cash-secured put (which is the natural "acquire-at-lower" entry strategy). Long BTC + short put does **both**, with leveraged upside on the long leg.

---

## 17. Cross-cutting observations

### 17.1 Test coverage is shallow but correct for its surface

The nine tests are correctly scoped to validate the BS math + one fee economic. They do not over-claim. The "9 green" badge is honest. The risk is downstream consumers trusting the engine beyond its scope.

### 17.2 The mandate's confidentiality clause is honoured only by discipline

No automated check exists. Recommend a CI grep step that fails on regex matches for typical PII patterns (BTC addresses, common wallet format strings, ISO-country codes for known sovereign funds, etc.) in any committed file under `prompts/`, `agents/`, `tests/fixtures/`, `docs/reports/`, `reports/`.

### 17.3 The data-origin labelling must precede the data itself

Before any historical option bar is ingested, the loader must attach `Provenance` (Deribit / Massive / CME / OTC / vendor / model_reconstructed). Otherwise the post-hoc labelling will be unreliable.

### 17.4 The waterfall's "target_case" output is an aspiration

`net_discount_vs_reference_pct: 4.5%` is the *target* net discount, not the *expected* net discount, because `target_option_yield_pct: 2.5%` is a target not a forecast. Reports and the demo script must distinguish these or risk misrepresenting expected economics to the client.

### 17.5 The single commit posture is incompatible with the parallel-agent plan

A6 prescribes six agents on six branches merging into `main`. AGENTS.md says "single commit, single branch". These are not simultaneously satisfiable. The audit recommends moving to a branch-based workflow with A6 as merge owner, with a documented CI gate, before any agent starts.

### 17.6 The `quantlib` and `hypothesis` packages are dead weight today

Installed but unused. If they remain unused after Phase 1, they should be removed from `.venv` (no lockfile makes this harmless).

### 17.7 The empty `{config,pricing,vol,execution,scenarios,tests,agents,reports}/` directory should be deleted

It is a leftover from the brace-expansion artefact noted in AGENTS.md. It is harmless but is a stale visible signal.

---

## 18. Direct answers to the user's enumerated questions

1. **Current functionality:** BS pricer with Greeks/IV/Δ-inversion, Deribit REST feed, parameter-driven waterfall; nine tests green. No strategies, no scenarios, no backtest, no Monte Carlo, no charts, no fixtures, no Massive integration.

2. **Existing interfaces:** `OptionQuote` frozen dataclass; `price`, `greeks`, `strike_for_delta`, `implied_vol`, `premium_pct_at_delta` in `pricing/black_scholes.py`; `_get`, `spot_index`, `dvol_latest`, `option_chain`, `book_summary` in `vol/dvol_feed.py`; `load_params`, `waterfall` in `execution/waterfall.py`. No pydantic models. No `contracts.md`.

3. **Nine tests validate:** BS call/put golden vectors, put-call parity, call delta golden, IV round-trip, Δ→strike round-trip, mandate 12.5Δ premium band at 37DTE / 45% vol, 3%-yield-implied delta band, waterfall mandate numbers.
   **Do not validate:** put Greeks, Black-76, inverse-BTC adjustment, settlement rules, strategies, scenarios, Massive ingestion, fixtures, DVOL feed, label-conflict detection, QuantLib parity, property tests, tranche reconciliation, fee-base sensitivity.

4. **Pricing/Greeks/IV/Δ correctness:** Mathematically correct for the standard Hull vector (verified to ~1e-9). Convention mismatch risk on Vega/Theta units (no test enforces). Inverse-BTC, Black-76, dividend/funding, surface calibration absent. Strike inversion assumes flat vol and flat rate; no term-structure.

5. **Deribit integration:** Public REST only; spot/DVOL/chain/book-summary; 15s timeout, no retry, no cache, no fixture recorder, no websocket, env vars declared but unused, no auth. Missing: history beyond 24h, option OHLCV, Massive side, websocket, testnet, settlement-type parsing, per-instrument Greeks parsing, error model.

6. **Missing Massive integration:** None exists. `MASSIVE_API_KEY` declared in `.env.example` only; no client, no data files, no schemas, no provenance tracking.

7. **Observed vs model-generated option data:** Not separated today. No provenance model exists. The mandate's data rule is unenforced.

8. **Missing vol-surface and forward-curve:** All absent. Single scalar vol used throughout. No expiry axis, no strike axis. QuantLib not yet used despite being installed.

9. **Covered-call / cash-secured-put / long-BTC+short-put:** None implemented. The mandate and AGENTS.md explicitly require all three. See §16 for the full derivation of the source-diagram discrepancy.

10. **Assignment / exercise / settlement / rolling:** All absent. Three settlement modes not implemented; rolling is not implemented.

11. **Backtest / Monte Carlo / stress / OOS:** All absent. No scenarios module, no deterministic seeds, no historical data.

12. **Execution / impact / tranching / fee modelling:** Per-clip impact absent. Tranche scheduler absent. Fee-base sensitivity absent. Current waterfall computes level economics only.

13. **Validation / reporting / security / data-governance gaps:** No CI, no mypy/ruff config, no fixtures, no pre-commit hooks, no PII enforcement, no provenance tracking, no tz-aware timestamps in `dvol_feed.py`, file-handle leak in `load_params`, `combined_target_discount_pct` unused, target vs expected semantics mixed in waterfall output, single-commit posture incompatible with branch-based plan.

14. **A1–A6 conflicts:** `contracts.md` referenced everywhere but not frozen (highest-risk blocker). Merge order A1→A2→A4→A3→A5 (A6) vs parallel A1∥A2∥A4 (build plan). Massive vs CryptoDataDownload as primary source. A5's chart correction depends on strategy code that does not exist. A4's fee sensitivity requires refactor of `waterfall.py`. Provenance field not in any agent's contract. No branching strategy. No anonymisation enforcement.

15. **Safest implementation sequence:** §15 above. Phase 0 (contracts + governance) is the single highest-priority action.

---

## 19. Source-diagram discrepancy — concise canonical answer

- **Position from legs:** Long BTC + Short put, USD-settled (or inverse-BTC variant).
- **Canonical classification:** `long_btc_plus_short_put`. **Not** covered put, covered call, or cash-secured put.
- **Piecewise payoff (USD-settled, per BTC, relative to entry):**
  - `S_T ≥ K_put`: `Π(S_T) = (S_T − S₀) + P₀` (slope `+1`, uncapped).
  - `S_T <  K_put`: `Π(S_T) = (S_T − S₀) + P₀ − (K_put − S_T)` (slope `+2`).
  - Breakeven at `S_T = S₀ − P₀`.
  - Max profit: uncapped.
  - Max loss at `S_T = 0`: `−S₀ + P₀ − K_put`.
- **Differs from covered call:** covered call caps upside at `K_call − S₀ + P₀` and has slope `+1` above `K_call` and `0` below; long-BTC+short-put has slope `+1` above `K_put` (uncapped) and slope `+2` below.
- **Differs from cash-secured put:** CSP has zero underlying exposure (no BTC leg), payoff slope `0` above `K_put` and `+1` below; long-BTC+short-put has slope `+1` above and `+2` below because of the BTC leg.
- **Source annotations that require mathematical verification:** any plateau or max-profit annotation above the strike (wrong — should be linear slope `+1` with no cap), any single-segment below-strike line (wrong — should be slope `+2`), the label "Covered Put" (wrong classification), any breakeven marked at `K_put` (wrong — breakeven is `S₀ − P₀`), any collateral annotation that omits the full BTC notional.
- **Recommended software representation:** `Strategy` with `legs = (Leg(side="long", instrument="spot", quantity_btc=q, …), Leg(side="short", instrument="put", quantity_btc=q, strike=K_put, premium=P₀, expiry=…, settlement=cash_usd or inverse_btc, exercise="european"))`, `source_label="Covered Put Strategy (Long BTC + Short Put)"`, `canonical_classification → long_btc_plus_short_put`, `LabelConflict` raised because `source_label` ≠ canonical. Tests assert payoff at `S_T ∈ {0, K_put/2, K_put, S₀, 2·K_put}`. Same payoff function used in backtest and chart pack per AGENTS.md.

---

*End of audit. All files read were unmodified. No code was implemented. No transaction identities were reproduced or inferred.*
