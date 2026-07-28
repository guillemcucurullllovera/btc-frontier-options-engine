Now I have reviewed every document. Let me verify the tests and waterfall output to confirm the repository is in working order before producing the final report.

All evidence is gathered. Below is the authoritative pre-implementation report.

---

# Asymmetrica BTC Engine — Senior Quant‑Engineering Reviewer Report

**Auditor role:** Read‑only repository auditor (`.opencode/agents/audit.md`).  
**Date:** 28 July 2026 20:19 UTC.  
**Scope:** All committed source (`HEAD: 772b3d8`), configuration, agent briefs, requirements documents, and two non‑authoritative AI audits (`deepseek_initial_audit.md`, `minimax_initial_audit.md`).  
**Test posture:** 9/9 green. Waterfall produces verified mandate numbers.  

---

## 1. Verified current repository state

### 1.1 Commit history — three commits, not one

| Commit | Date | Description |
|---|---|---|
| `7a22caf` | 2026‑07‑27 | Sprint 0: verified Fable BTC engine scaffold |
| `30141f3` | 2026‑07‑27 | Configure OpenCode context, strategy rules and data providers |
| `772b3d8` | 2026‑07‑27 | Add sanitised mandate and reference library structure |

**Current HEAD:** `772b3d84470def9ffdf002ca80c623c53e7a5e0a`.  
**Branch:** `main` (three linear commits).  
**Working tree:** clean on tracked files. Untracked: `.opencode/`, `docs/reports/`, `docs/requirements/BTC_30K_Build_Plan_Parallel_Agents.md`, `prompts/`.

Both audits state *“single commit `7a22caf`, single branch `main`”*. This claim is **stale**. The `contracts.md` single‑commit posture incompatibility flagged by MiniMax (§17.5) is already resolved: the repo has three commits and can accommodate feature branches.

### 1.2 Modules and what they do

| Module | File | Capability | Tests |
|---|---|---|---|
| Pricing | `pricing/black_scholes.py` | European BS call/put, full‑Greek `OptionQuote` frozen dataclass, analytic Δ→strike inversion, Brent IV solver, `premium_pct_at_delta` utility | 6 |
| Volatility | `vol/dvol_feed.py` | Deribit public REST: spot index, DVOL (1h candles, last 24h), option‑chain metadata, per‑instrument book summary | 0 |
| Execution | `execution/waterfall.py` | Reads `config/params.yaml`; computes 12 waterfall keys reproducing mandate economics | 1 |
| Configuration | `config/params.yaml` | 14 params; consumed by `waterfall.py` only | 2 mandate‑economics tests use hard‑coded values, not `params.yaml` |
| Tests | `tests/test_engine.py` | 9 tests: 3 Hull/Haug golden vectors, 2 roundtrips, 2 mandate‑economics guards, 1 delta root‑find, 1 waterfall arithmetic | — |

### 1.3 What does **not** exist

- `contracts.md` — the Sprint‑0 freeze gate required by A6
- Any pydantic models
- Any strategy/payoff engine (no `Leg`, `Strategy`, covered‑call, CSP, long‑BTC+short‑put, collar, rolling)
- Any `scenarios/`, `data/`, `reports/`, `fixtures/` module
- `surface.py`, `impact.py`, `tranches.py`, `montecarlo.py`, `backtest.py`, `stress.py`, `charts.py`, `cycle_report.py`, `demo.py`
- `garch.py`, `history.py`, Massive client, CryptoDataDownload ingestion
- Black‑76, inverse‑BTC adjustment, vectorised grid pricing
- Vol‑surface, forward‑curve, discount‑curve models
- CI (GitHub Actions), mypy/ruff config, Docker
- Any Recorded Deribit fixtures for offline testing
- Any provenance‑tagging mechanism for data provenance

### 1.4 Key params.yaml entries

| Key | Value | Consumed? | Notes |
|---|---|---|---|
| `btc_quantity` | 30000 | ✅ waterfall | Configurable |
| `reference_spot_usd` | 65000 | ✅ waterfall | Working value; replaceable via live feed |
| `seller_discount_pct` | 2.5 | ✅ waterfall | Business requirement |
| `target_option_yield_pct` | 2.5 | ✅ waterfall | Target, not a forecast |
| `execution_fee_pct` | 0.5 | ✅ waterfall | On reference notional (full‑notional path only) |
| `combined_target_discount_pct` | 5.0 | ❌ | Unused; declared but no consumer |
| `call_delta_target` | [10, 15] | ❌ | For A3/A4 |
| `dte_target_days` | [30, 45] | ❌ | For A3/A4 |
| `strike_target_pct_above_spot` | [15, 20] | ❌ | For A3/A4 |
| `target_monthly_premium_pct` | 3.0 | ❌ | Implicitly used in test 8 |
| `iv_working_band_pct` | [40, 50] | ❌ | Tests hard‑code σ=0.45 |
| `risk_free_rate_pct` | 4.0 | ❌ | Tests hard‑code r=0.04 independently |
| `tranche_btc` | [250, 1000] | ❌ | For A4 |
| `expiry_ladder_dte` | [30, 37, 44] | ❌ | For A4 |

**Drift risk:** `risk_free_rate_pct` in `params.yaml` will diverge from hard‑coded test literals unless wired. A1 must fix this.

---

## 2. Findings agreed by both audits

Both the DeepSeek audit and the MiniMax audit agree on the following, and the present audit **confirms** each item:

1. **Black‑Scholes math is correct.** The Hull‑formula implementation passes golden‑vector tests (call, put, delta) to 1×10⁻³ and put‑call parity to 1×10⁻⁹. Δ‑inversion and IV round‑trip are correct to 1×10⁻⁶.

2. **No strategy code exists.** Covered calls, cash‑secured puts, long‑BTC+short‑put, collars, rolling — none are implemented.

3. **No backtest / Monte Carlo / stress code exists.** The `scenarios/` directory is empty.

4. **No volatility surface exists.** All pricing uses a single flat scalar σ per call.

5. **No Massive integration exists.** `MASSIVE_API_KEY` and `MASSIVE_BASE_URL` are declared in `.env.example` only; no client, no data files, no schemas.

6. **No `contracts.md` exists.** This is the single highest‑risk blocker: A1, A2, and A4 explicitly depend on it, and A6’s Sprint‑0 gate has not been executed.

7. **Deribit integration is basic.** Public REST only (4 endpoints); no retry/backoff, no caching, no fixture recorder, no WebSocket, no error model, no tz‑aware UTC timestamps. The time‑data call violates the AGENTS.md timestamp requirement.

8. **Data provenance is unenforced.** No `Provenance` enum, no source‑tagging, no separation between observed and model‑generated data.

9. **Ten params.yaml entries are unused.** Only 4 of 14 entries are consumed by `waterfall.py`; the pricing module reads none of them.

10. **The waterfall’s “target_case” output is an aspiration.** `net_discount_vs_reference_pct: 4.5%` is the *target* net discount conditional on the 2.5% overlay being achieved, not a *forecast* of realised economics.

11. **Vega/Theta unit conventions are undocumented in code.** Vega is per 1.00 absolute σ change; Theta is per year. No test enforces the convention conversions (÷100, ÷365). Downstream code (A5’s IV give‑up model) could misinterpret raw values.

12. **No CI, no mypy/ruff config, no pre‑commit hooks, no Docker.**

13. **The source‑diagram label “Covered Put Strategy (Long BTC + Short Put)” is wrong.** The canonical classification from legs is **long BTC plus short put**, with a leveraged‑bullish payoff. Both audits derive the correct payoff but contain errors detailed below.

---

## 3. Corrections required to the DeepSeek audit

### C‑DS‑1: Stale commit history

**Audit states:** “`main` branch, single commit `7a22caf`” (header + §16 checklist).  
**Corrected:** Three commits exist (`7a22caf`, `30141f3`, `772b3d8` HEAD). The “single‑commit posture” incompatibility with the parallel‑agent plan is moot.

### C‑DS‑2: Mislabeling as “married put”

**Audit §15.2 states:** “Leveraged‑bullish yield enhancement (also describable as: long BTC plus short put, or ‘married put’ written from the long side).”  
**Corrected:** A married or protective put is **long underlying plus long put**. Long BTC plus short put is structurally different (short, not long, option leg). The phrase “married put” must never be used to describe long BTC plus short put. The only canonical name is **long BTC plus short put** (leveraged‑bullish, downside‑geared payoff).

### C‑DS‑3: Physical settlement language not separated from Deribit cash settlement

**Audit §15.4 comparison table:** “Physical settlement: BTC called away if S_T > K” and “Additional BTC purchased if S_T < K.”  
**Corrected:** Deribit options are European and cash‑settled in USD (linear) or BTC (inverse). Automatic physical delivery does not occur on Deribit. The economic strategy payoff and the venue settlement mechanism must be described separately. When physical‑delivery language is used (e.g., for hypothetical OTC or CME contracts), it must be explicitly flagged as *not Deribit settlement* and must reference a documented venue rulebook.

### C‑DS‑4: Volatility‑skew direction presented as permanent fact

**Audit §8.1:** “BTC options exhibit a persistent positive skew (OTM calls trade at higher IV than ATM).”  
**Corrected:** Skew direction is observed market data (current snapshot) or an explicit modelling assumption, never a permanent fact. Skew can invert (e.g., during crash regimes). Future modules must fetch skew from live `book_summary` mark‑IV surfaces rather than hard‑coding an assumption.

### C‑DS‑5: Breakeven analysis omits below‑strike breakeven

**Audit §15.3:** Lists “Breakeven: S_T = S₀ − P” in the above‑K region but does not surface the below‑strike breakeven formula in the summary. The detailed piecewise derivation is correct, but the report’s summary of key structural properties should explicitly list the below‑strike breakeven: **S_T = (S₀ + K − P) / 2**.

### C‑DS‑6: “BTc called away” / “Additional BTC purchased” conflates settlement with economics

**Audit §15.4 table, “Physical settlement” row.** See C‑DS‑3. Additionally, the row heading “Physical settlement” is misleading for a column comparing three structures. The row should be labelled “Hypothetical physical assignment (venue‑dependent)” with a footnote that Deribit is cash‑settled.

---

## 4. Corrections required to the MiniMax audit

### C‑MM‑1: Stale commit history

**Audit states:** “Commit posture: single commit on `main`” (§0, §17.5).  
**Corrected:** Three commits exist. See §1.1.

### C‑MM‑2: Incorrect max‑loss formula in §16.4 comparison table

**Audit §16.4 table, “Max loss” column for Long BTC + short put:** `K_put − P₀ − S₀`.  
**Corrected:** The signed PnL at S_T = 0 is `P₀ − S₀ − K_put` = `−(S₀ + K_put − P₀)`. The **loss magnitude** is `S₀ + K_put − P₀`.  
MiniMax’s expression `K_put − P₀ − S₀` evaluates to `−(S₀ + P₀ − K_put)`, which swaps the sign of K and P relative to the correct formula. For S₀=65k, K=55k, P=2k: MiniMax gives |55k − 2k − 65k| = 12k; correct is 65k + 55k − 2k = 118k. A factor‑of‑10 error.

### C‑MM‑3: “Net cost = K − premium” misrepresented as full‑position cost basis

**Audit §16.3:** “effective_cost_per_btc(S_T) = K_put − P₀ if S_T < K_put.”  
**Audit §16.4 parenthetical:** “net cost = K − premium.”  
**Corrected:** K − P is the cost basis of the **assigned BTC only**, not the full combined position. Under a hypothetical physical acquisition of a second BTC, the position holds **two BTC**. Total basis = S₀ + K − P. Average basis = (S₀ + K − P) / 2. Reports must distinguish per‑leg cost from full‑position cost.

### C‑MM‑4: “Loss vs entry = S₀ − K + premium” is wrong

**Audit §16.4 parenthetical:** “loss vs entry = S₀ − K + premium.”  
**Corrected:** At S_T = 0, signed PnL = −S₀ + P − K = −(S₀ + K − P). The loss magnitude is S₀ + K − P. MiniMax’s expression S₀ − K + P differs by having K and P swapped in sign. With S₀=65k, K=55k, P=2k: MiniMax gives 65k − 55k + 2k = 12k; correct is 65k + 55k − 2k = 118k.

### C‑MM‑5: Self‑contradiction in max‑loss between §16.4 and §19

**Audit §16.4:** max loss = `K_put − P₀ − S₀` (wrong, see C‑MM‑2).  
**Audit §19:** “Max loss at S_T = 0: −S₀ + P₀ − K_put” (correct signed PnL).  
These are algebraically different expressions. §19 is correct; §16.4 contradicts it and must be corrected.

### C‑MM‑6: Breakeven omission of below‑strike formula

**Audit §19:** “Breakeven at S_T = S₀ − P₀” — lists only the above‑strike breakeven.  
**Corrected:** The structure has potentially two breakevens. For typical mandate parameters where S₀ − P > K, the only valid breakeven is S₀ − P. When S₀ − P < K (large premium or tight strike), the relevant breakeven is the below‑strike formula **(S₀ + K − P) / 2**. The audit must present both and explain the conditional selection.

### C‑MM‑7: Deribit settlement confusion in §16.5

**Audit §16.5 item 7:** “A ‘margin’ or ‘collateral’ annotation referencing only the put premium — the position requires full BTC notional, not just the put collateral.”  
**Observation:** This is correct for economics but silent on the fact that Deribit cash‑settled options never involve physical BTC delivery. The audit should explicitly note that Deribit inverse‑BTC settlement (§16.6 is correct on this) is a separate concept from physical acquisition cost basis used in the P&L derivation.

---

## 5. Unresolved business or quantitative decisions requiring human approval

| # | Decision | Impact | Owner |
|---|---|---|---|
| D‑1 | **Fee base: reference notional vs executed notional** | $240k swing on a $9.75M fee; also affects per‑BTC client cost and net discount | Mandate issuer / Francisco |
| D‑2 | **Reference spot price source** for the waterfall (live Deribit index vs Massive vs blended) | Affects all notional calculations, fee BTC‑equivalent, and net‑discount display | Mandate issuer |
| D‑3 | **Primary venue selection** for option execution (Deribit, CME, OTC) | Determines settlement mechanics, margin, counterparty risk, and the inverse‑vs‑linear option convention | Mandate issuer |
| D‑4 | **Put‑sleeve consent:** whether the long‑BTC+short‑put structure is in or out of scope for the live transaction (the diagram exists but the mandate does not specify whether it is for live execution or analysis only) | Determines whether A3 backtest paths, A4 tranche scheduler, and A5 chart pack must include this structure in production‑ready form | Mandate issuer |
| D‑5 | **Massive vs CryptoDataDownload as primary v1 historical source** | The mandate says Massive; the build plan says CDD. Until resolved, A2’s ingestion brief is self‑contradictory and A3’s backtest has no authoritative data origin | Mandate issuer / A6 |
| D‑6 | **Waterfall overlay target: display as “target” or “forecast”** | $48.75M overlay_target_usd is a business aspiration, not a cycle‑implied expected value. Reports must label it as `target` not `expected` to avoid misrepresenting economics to clients | Mandate issuer |
| D‑7 | **Exact scope of the put‑sleeve for the first client presentation:** does the demo include it (leveraged‑bullish payoff) or is it analysis‑only? | Determines A5 chart‑pack scope and A3 backtest path count | Mandate issuer / Francisco |

---

## 6. Exact Phase 0 acceptance criteria

Before **any** agent (A1, A2, A4) begins implementation, the following must be true:

### P0‑1: `contracts.md` frozen with pydantic models

Minimum pydantic v2 models (see §7). Function signatures for all Phase‑1 deliverables must be declared as abstract interfaces. A1, A2, and A4 must import against these contracts, not against each other’s implementations.

### P0‑2: CI operational

GitHub Actions workflow on every PR enforcing:
- `python3 -m pytest -q` (all 9 current tests + any new ones)
- `mypy --strict` on all `.py` files (requires a `pyproject.toml` with mypy config)
- `ruff check` on all `.py` files (requires a `pyproject.toml` with ruff config)

### P0‑3: First Deribit fixtures recorded

At least one snapshot each of `get_index_price`, `get_volatility_index_data`, `get_instruments`, and `get_book_summary_by_currency` saved to `tests/fixtures/` in a replayable format (JSON or Parquet). Tests that consume Deribit data must replay from fixtures, not live network.

### P0‑4: `params.yaml` wrapped with pydantic schema

Malformed YAML must raise a typed validation error. The `reference_spot_usd` field must carry a provenance tag (`source: working_value_2026_07_27`).

### P0‑5: `waterfall.py` typed and leak‑fixed

- `load_params` must use a context manager (current file‑handle leak is a bug).
- All function return types must be annotated.
- `overlay_target_usd` and downstream keys must include a `_target` suffix and the docstring must state they represent business targets, not forecasts.

### P0‑6: `pricing/` wired to `params.yaml`

The `risk_free_rate_pct` from `params.yaml` must be the single source for r in all pricing calls. Tests must read r from params, not hard‑code `0.04`.

### P0‑7: Branch strategy documented

A6 must document the merge order and feature‑branch naming convention (`feat/pricing`, `feat/vol`, `feat/execution`, `feat/scenarios`, `feat/reports`). The “single branch” language in AGENTS.md must be updated.

### P0‑8: Anonymisation CI grep

A CI step that greps all committed files (including prompts, fixtures, agent‑brief stubs) for known PII patterns (BTC address regex, sovereign‑fund identifiers, wallet‑address patterns) and fails on hit.

### P0‑9: `Provenance` enum frozen in contracts.md

Before any historical data is ingested, the provenance taxonomy must exist. See §7.

---

## 7. Required contracts, enums and data models

All must be defined in `contracts.md` as pydantic v2 models before Phase‑1 implementation begins.

### 7.1 Core domain enums

```python
from enum import Enum

class OptionKind(str, Enum):
    CALL = "call"
    PUT = "put"

class OptionSide(str, Enum):
    LONG = "long"
    SHORT = "short"

class Instrument(str, Enum):
    BTC_SPOT = "btc_spot"
    CALL = "call"
    PUT = "put"

class SettlementType(str, Enum):
    CASH_USD = "cash_usd"        # Deribit linear: payoff in USD
    INVERSE_BTC = "inverse_btc"  # Deribit inverse: payoff in BTC
    PHYSICAL_USD = "physical_usd"  # OTC/CME: BTC delivery at USD strike

class ExerciseStyle(str, Enum):
    EUROPEAN = "european"
    AMERICAN = "american"

class Provenance(str, Enum):
    OBSERVED = "observed"                 # live venue feed
    MODEL_RECONSTRUCTED = "model_reconstructed"  # DVOL‑proxy, flat‑vol, etc.
    CALCULATED = "calculated"             # derived from observed inputs via a model
    ASSUMED = "assumed"                   # not observed, not calculated from observed
    BUSINESS_REQUIREMENT = "business_requirement"  # mandate parameter
```

### 7.2 Data models

| Model | Key fields | Purpose |
|---|---|---|
| `OptionQuote` (upgrade existing dataclass) | `price, delta, gamma, vega, theta, strike, provenance, calculation_timestamp` | Pricer output; add provenance and tz‑aware UTC timestamp |
| `PositionLeg` | `side: OptionSide, instrument: Instrument, quantity_btc: float, strike: float\|None, premium_per_unit: float, expiry: datetime, settlement: SettlementType, exercise: ExerciseStyle` | Atomic leg of any strategy |
| `Strategy` | `name: str, source_label: str\|None, legs: tuple[PositionLeg, ...], classification: str, label_conflict: bool` | Collection of legs with canonical classification; preserves source label when it disagrees |
| `StrategyKind` (enum) | `COVERED_CALL, CASH_SECURED_PUT, LONG_BTC_PLUS_SHORT_PUT, COVERED_PUT, COLLAR, CALL_SPREAD, PUT_SPREAD, NAKED_PUT, NAKED_CALL, CUSTOM` | Canonical classifications derived from legs only |
| `WaterfallOutput` | Typed version of current `waterfall()` dict, with `provenance` and `calculation_timestamp` fields | Replaces untyped dict |
| `VolPoint` | `strike, expiry, iv, delta, provenance, timestamp` | Single point on the vol surface |
| `VolSurface` | `method: str, points: list[VolPoint], metadata: dict` | Full surface (spline or SVI) |
| `SpotBar` / `DvolBar` / `OptionBar` | Time‑series bars with `provenance`, `timestamp`, `source` fields | Historical data containers |
| `BacktestResult` / `MonteCarloResult` | Generic result containers with `parameters`, `paths`, `summary_stats` | A3 output schemas |
| `Tranche` | `clip_btc: int, dte: int, expiry: datetime, target_delta: float` | A4 scheduler output |

### 7.3 Required module stubs

The following files must exist in the repo (with type stubs only) before A1/A2/A4 start, so they can import against frozen interfaces:

- `strategies/__init__.py` → NOT created (no `__init__.py` convention); instead `strategies/payoffs.py` with stub signatures
- `strategies/payoffs.py` — `strategy_payoff(strategy, S_T) -> float`, `classify_strategy(legs) -> StrategyKind`, `breakeven(strategy) -> list[float]`
- `vol/surface.py` — `fit_surface(points) -> VolSurface`, `iv_at(delta, dte, surface) -> float`
- `execution/impact.py` — `iv_giveup(clip_btc, base_iv, params) -> float`, `spot_impact(clip_btc, params) -> float`
- `scenarios/montecarlo.py` — `run_mc(params, n_paths, seed) -> MonteCarloResult`

---

## 8. Safe implementation dependency and merge sequence

### Phase 0 — Gate (single‑threaded, must complete first)

```
A6: Freeze contracts.md + pydantic models + CI + fixtures + typed waterfall
```

**Outputs:** `contracts.md`, `pyproject.toml` (mypy + ruff config), `.github/workflows/ci.yml`, `tests/fixtures/*.json`, typed `waterfall.py`.

### Phase 1 — Parallel core (independent after Phase 0)

```
A1 (DeepSeek)  ─┐
A2 (MiniMax)   ─┤  all work against contracts.md stubs + recorded fixtures
A4 (MiniMax)   ─┘
```

| Agent | Deliverable | True dependencies |
|---|---|---|
| A1 | Black‑76, inverse‑BTC adjustment, vectorised grid, QuantLib parity, Haug golden vectors (≥10 new), put‑Greek golden vectors, finite‑difference cross‑check, wire r from params.yaml | `contracts.md` only |
| A2 | Hardened Deribit feed (retries/backoff, parquet cache, fixture recorder, tz‑aware UTC), `surface.py` (smile‑per‑expiry), Massive client (if D‑5 resolved), CryptoDataDownload ingest, GARCH, venue rulebook docs | `contracts.md` + live Deribit network |
| A4 | `impact.py` (IV give‑up + square‑root spot), `tranches.py` (30k BTC schedule), waterfall sensitivity mode (spot ±10%, fee‑base variants) | `contracts.md` only |

### Phase 2 — Scenarios (serial, depends on A1 + A2)

```
A1 merged → A2 merged → A3 (DeepSeek)
```

A3 consumes `pricing/` (Black‑76, inverse‑BTC) and `vol/` (surface, fixtures).

### Phase 3 — Integration & reports (serial, depends on A3 + A4)

```
A4 merged → A3 merged → A5 (DeepSeek)
```

A5 consumes everyone’s outputs for chart pack + demo.

### Phase 4 — QA close (serial)

```
A5 merged → A6 cross‑validation → Fable sign‑off
```

### Merge order (by A6 as merge owner)

```
A1 → A2 → A4 → A3 → A5
```

This order resolves soft dependencies: A3 needs A1 pricers and A2 fixtures; A5 needs A3 results and A4 schedules.

**What can truly run in parallel:** A1, A2, A4 are independent once contracts.md is frozen. A3 can soft‑start against A1 stubs + A2 fixtures as soon as those are feature‑complete enough to produce `iv_at(delta, dte, date)` with provenance.

---

## 9. Go/no‑go checklist for starting A1, A2 and A4

| # | Criterion | Status |
|---|---|---|
| G‑1 | `contracts.md` frozen with all models in §7 | ☐ Must pass |
| G‑2 | CI running (pytest + mypy + ruff) on `main` | ☐ Must pass |
| G‑3 | First Deribit fixtures recorded and replayable offline | ☐ Must pass |
| G‑4 | `params.yaml` pydantic‑validated; `reference_spot_usd` has provenance tag | ☐ Must pass |
| G‑5 | `waterfall.py` typed, leak‑fixed, `_target` suffix applied | ☐ Must pass |
| G‑6 | `pricing/` wired to `params.yaml` for `risk_free_rate_pct` | ☐ Must pass |
| G‑7 | Module stubs (`strategies/payoffs.py`, `vol/surface.py`, `execution/impact.py`, `scenarios/montecarlo.py`) exist with type signatures | ☐ Must pass |
| G‑8 | Provenance enum frozen; CI provenance grep active | ☐ Must pass |
| G‑9 | Anonymisation CI grep active | ☐ Must pass |
| G‑10 | Decisions D‑1 (fee base), D‑2 (spot source), D‑5 (Massive vs CDD) resolved | ☐ Should pass |
| G‑11 | Decision D‑4 (put‑sleeve scope) resolved | ☐ Should pass for A3/A5 scope clarity |
| G‑12 | Branch naming convention and PR template documented | ☐ Should pass |

**Go condition:** G‑1 through G‑9 must all pass before any agent writes code. G‑10 through G‑12 are strongly recommended but A1/A2/A4 can start with documented `TODO(decision_pending)` markers if they are unresolved.

---

## 10. Final authoritative description of the long‑BTC‑plus‑short‑put structure

### 10.1 Position legs

| Leg | Side | Instrument | Quantity |
|---|---|---|---|
| 1 | Long | BTC spot | 1 BTC (configurable × q) |
| 2 | Short | Put option | 1 BTC notional (configurable × q) |

### 10.2 Canonical classification

**Long BTC plus short put.** Not a covered put. Not a married put. Not a synthetic long. It is a leveraged‑bullish, downside‑geared yield‑enhancement structure.

### 10.3 Generic expiry P&L (per BTC of initial position, USD‑settled)

```
P&L(S_T) = S_T − S₀ + P − max(K − S_T, 0)
```

where:
- S₀ = BTC acquisition cost (cost basis of the initial long BTC)
- S_T = BTC spot at expiry
- K = short‑put strike (USD)
- P = put premium received (USD per BTC notional)

### 10.4 Piecewise decomposition

**Region: S_T ≥ K (put expires OTM)**

```
P&L = S_T − S₀ + P
```

- Slope = **+1** (pure long‑BTC participation).
- Profit is **uncapped**.
- Breakeven: S_T = S₀ − P (valid when S₀ − P ≥ K).

**Region: S_T < K (put expires ITM, assigned)**

```
P&L = 2·S_T − S₀ − K + P
```

- Slope = **+2** (the put assignment creates an obligation to acquire a second BTC at K, doubling effective delta below strike).
- Breakeven: **S_T = (S₀ + K − P) / 2** (valid when S₀ − P < K).

At S_T = K, the function is continuous: P&L(K) = K − S₀ + P from both pieces.

### 10.5 Key structural properties

| Property | Value |
|---|---|
| **Slope above K** | +1 (uncapped) |
| **Slope below K** | +2 (leveraged) |
| **Max profit** | Uncapped |
| **Max loss (S_T = 0)** | S₀ + K − P (magnitude) |
| **Signed P&L at S_T = 0** | −(S₀ + K − P) |
| **Above‑K breakeven** | S₀ − P (if ≥ K) |
| **Below‑K breakeven** | (S₀ + K − P) / 2 (if < K) |

### 10.6 Hypothetical physical acquisition cost basis (venue‑dependent)

If the put is physically settled (OTC or CME) and the holder is assigned **one additional BTC** at S_T < K:

| Quantity | Cost basis |
|---|---|
| Original 1 BTC | S₀ |
| Assigned 1 BTC | K − P (effective, after premium) |
| **Total 2 BTC** | **S₀ + K − P** |
| **Average per BTC** | **(S₀ + K − P) / 2** |

K − P is the cost basis of the assigned BTC **only**, not the full position.

On Deribit, inverse‑BTC settlement applies (see §10.8); physical delivery does not occur.

### 10.7 Comparison with related structures

| Property | Covered call | Cash‑secured put | **Long BTC + short put** |
|---|---|---|---|
| Underlying | Long BTC | Cash | **Long BTC** |
| Option leg | Short call OTM | Short put OTM | **Short put OTM** |
| Slope above K | 0 (capped at K) | 0 (no BTC exposure) | **+1 (uncapped)** |
| Slope below K | +1 | +1 (BTC acquired at K) | **+2** |
| Max profit | K − S₀ + P (capped) | P only | **Uncapped** |
| Max loss (S_T→0) | S₀ − P | K − P | **S₀ + K − P** |

### 10.8 Inverse‑BTC settlement variant (Deribit inverse puts)

For an inverse‑BTC‑settled short put, the per‑BTC payoff in BTC at expiry is:

```
Π_btc(S_T) = (S_T − S₀)/S₀ + P/S₀                          if S_T ≥ K
           = (S_T − S₀)/S₀ + P/S₀ − (K − S_T)/S_T           if S_T < K
```

The realised acquisition cost in BTC:

```
Effective_cost_btc(S_T) = 1 − P/S₀          if S_T ≥ K
                        = K/S_T − P/S₀      if S_T < K
```

Inverse settlement creates convexity: when S_T < S₀, the cost in BTC terms is worse than the USD‑denominated equivalent because K/S_T > K/S₀. This is a standard inverse‑contract feature and must be documented against the Deribit contract specification (to be fetched by A2).

### 10.9 Source‑diagram discrepancy rule

The supplied diagram is labelled **“Covered Put Strategy (Long BTC + Short Put)”**.

| Field | Value |
|---|---|
| **Source label** | “Covered Put Strategy (Long BTC + Short Put)” |
| **Canonical classification (from legs)** | `long_btc_plus_short_put` |
| **Label conflict** | Yes — “Covered Put” implies short underlying + short put |
| **Required action** | Preserve both labels; display canonical classification as primary; flag discrepancy as a `LabelConflict` warning in all downstream reports and charts |
| **Chart correction** | Slopes must be +1 above K, +2 below K; no profit cap; breakeven from payoff function, not from annotations |

Any annotation on the source diagram depicting a profit cap or a single‑slope payoff is **mathematically wrong** and must be corrected in the regenerated A5 chart.

### 10.10 Required tests

Per AGENTS.md §“Strategy classification and payoff integrity,” the following must pass before the long‑BTC‑plus‑short‑put structure is considered validated:

| S_T | Assertion |
|---|---|
| S_T = 0 | P&L = −(S₀ + K − P) |
| S_T = (S₀ + K − P)/2 (below‑K breakeven, if valid) | P&L ≈ 0 |
| S_T < K (generic) | Slope = +2 (numerical derivative) |
| S_T = K | P&L = K − S₀ + P; function is continuous |
| S_T = S₀ (at initial spot) | P&L = P (above K) or P − (K − S₀) (below K); verify sign |
| S_T ≫ K (materially above strike) | Slope = +1; P&L ≈ S_T − S₀ + P |

These tests must be added to `tests/test_engine.py` before A3 or A5 consume the strategy payoff function.

---

### Summary of audit disposition

Both the DeepSeek and MiniMax audits correctly identify the overwhelming majority of gaps (no strategy code, no surface, no backtest, no `contracts.md`, no Massive, no CI). Their technical analysis of the repo structure, test coverage, and implementation sequence is substantially correct. However, each contains:

- A **stale commit‑history claim** (one commit vs three).
- At least one **strategy‑classification error** (DS calls it “married put”; MM has algebraic errors in max‑loss and cost‑basis formulas).
- Insufficient separation of **economic payoff** from **Deribit cash settlement**.
- An omission of the **below‑strike breakeven formula** in their summaries.

The corrections in §3 and §4 must be applied before either audit is treated as authoritative. The Phase‑0 gate in §6 is the single‑threaded bottleneck: no parallel agent work can safely begin until `contracts.md` is frozen and CI is operational.
