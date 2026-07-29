# Frontier Repair Specification (Stage 1)

Checkpoint: `92acecf`. Companion to `frontier_consensus_findings.json` and
`frontier_acceptance_tests.md`. This document orders the accepted findings by
**dependency**, not convenience, and states an implementation-ready repair for
each. It does not modify production code (Stage 1 rule). No work package here
may begin until its listed dependencies are complete and its gating acceptance
tests (AT-xxx, defined in `frontier_acceptance_tests.md`) are written and pass.

Authority for every repair is the hierarchy in
`frontier_consensus_findings.json.authority_hierarchy`. Where a repair needs a
primary source or a business decision, that is stated as a precondition, not
silently resolved.

## 0. Gate rules restated (binding)

- **No historical research** (Stage 3) until every WP whose findings carry
  `blocking.historical_research=true` passes its acceptance tests.
- **No large Monte Carlo** until every WP whose findings carry
  `blocking.large_mc=true` passes, AND an approved simulation-methodology
  specification exists (MS-26), AND the deterministic ledger reconciles.
- **No strategy called best/optimal/preferred** until an objective function is
  approved (MS-25) and empirical evidence supports it.

## Dependency levels (topological)

- **Level 0** — foundational; no intra-finding dependency.
- **Level 1** — depends on the re-striking + settlement foundation.
- **Level 2** — depends on the reconciled ledger and repriced instruments.
- **Level 3** — depends on repaired stress + observed data.

The work packages below are grouped so that each package is internally
coherent and its dependencies precede it.

---

## PHASE A — Process & contract preconditions (must precede any code change)

### WP-A1 · Restore the verification discipline — FRF-036 (critical)
**Depends on:** none. **Blocks:** all Stage-2 code work.
**Repair:**
- Restore the full assertions in `strategy/backtest.py:backtest_no_lookahead`
  (`is_itm`, `strike`, `net_pnl` per cycle) that were deleted after they
  detected genuine look-ahead.
- Adopt red-green discipline: the gating acceptance test (AT-xxx) is written
  and shown failing before each repair, and shown passing after.
- Every Stage-2 repair receives independent re-review before merge; no
  self-certified fix report is accepted as evidence of correctness.
**Gate:** AT-031.

### WP-A2 · Versioned contract amendments — FRF-018, FRF-031, FRF-037 (high)
**Depends on:** none. **Blocks:** WP-B4 (pricing), WP-C1 (classification), any inverse-venue work.
**Repair (A6-owned `contracts.md` amendment record, versioned):**
- **Premium sign convention (FRF-018):** choose ONE convention. Recommended:
  keep contracts §9.1 (signed premium, received = negative) and correct
  `strategy/payoffs.py:97-118` + all builders + `engine/strategy.py:55-61` to
  match; OR amend §9.1 to unsigned-with-side. Record the choice; add a property
  test that both documented entry paths yield identical P&L.
- **Inverse pricing text (FRF-037 / conflict C-2.2):** rewrite the garbled §7.3
  sketch and the "TBD" §13.1 golden-vector rows to document the BTC numeraire
  and the `exp(−qT)` factor (price_BTC × S = Black-76 USD at q=0). This is the
  precondition the MiniMax pre-merge review requires before `f75e148` merges.
- **Citation corrections (FRF-037):** fix the Hull/Haug golden-vector
  attributions, put-call parity §11.4, the Bailey "N≥100" attribution (relabel
  as business_requirement), the §3.4 BRR/BRRNY/BVX and §5.2 linear-mechanism
  citations. No numeric change — values verified correct.
- **Do NOT reintroduce** reconciled §10.8 formulas or a combined settlement enum
  (FRF-031 superseded; FRF-032 rejected). Annotate the traceability matrix.
**Gate:** AT-032; must land before AT-015 test-strengthening merges.

### WP-A3 · Confidentiality & governance disclosure — FRF-038 (high)
**Depends on:** none. **Blocks:** nothing technical; immediate owner action.
**Repair:**
- Disclose the flagged prompt artefact to the owner for confidential review
  (do not reproduce content in any report). Decision to redact/quarantine/accept
  is the owner's.
- Harden `scripts/anonymisation_scan.py`: remove the comment-line and
  keyword ("exclude"/"confidentiality") exemptions; scan `prompts/` and binary
  content; record the exception.
**Gate:** AT-033. **Note:** single-source finding; treat as reported until owner
confirms.

---

## PHASE B — Deterministic economics foundation (Level 0 → 1 → 2, Stage 2)

Historical research and large MC remain blocked throughout Phase B.

### WP-B1 · Per-cycle strike & expiry reselection — FRF-001 (critical)
**Depends on:** WP-A1. **Blocks:** FRF-004, FRF-005, FRF-010, FRF-011, and every downstream metric.
**Repair:** at each cycle open, re-derive strike from prevailing spot and the
configured targeting rule (`strike_pct_above` or a delta target via
`pricing.black_scholes.strike_for_delta`), rebuild the option legs, and reprice
premium at prevailing spot/vol. Record per-cycle strike, delta, premium and
targeting rule in `BacktestCycle`. Remove or wire the dead `strike_pct_above`
/`overlay_ratio`/`seed` parameters (`strategy/backtest.py:274-275`).
**Files:** `strategy/backtest.py:backtest_strategy`, `strategy/definitions.py`,
`research/runner.py`. **Gate:** AT-001.

### WP-B2 · Observed-data baseline comparability — FRF-002 (critical)
**Depends on:** WP-A1. **Blocks:** all comparison outputs.
**Repair:** the unhedged baseline consumes the identical observed date/spot
series, calendar and applicable cost model as every strategy (buy at first
observed bar, hold; consistent seller discount and fees). Quarantine the
synthetic wrappers (`backtest_unhedged`, `backtest_covered_call_overlay`) so no
production path can call them. **Files:** `research/runner.py:388-401`,
`strategy/backtest.py`. **Gate:** AT-002. **Branch note:** `8743811` partially
does this but with a 50-pt tolerance test — insufficient (see handoff).

### WP-B3 · Lifecycle calendar correctness — FRF-003 (critical)
**Depends on:** WP-A1. **Blocks:** FRF-007, FRF-004 accuracy.
**Repair:** drive the cycle calendar from actual dates (no gap between
consecutive cycles: next entry = expiry bar); expiry = calendar date (entry +
DTE) mapped to the nearest available bar; price the final cycle with its true
remaining T (or exclude it); settle each leg at its own `expiry_timestamp`
(fixes the ladder). **Files:** `strategy/backtest.py` cycle loop,
`strategy/definitions.py:build_strike_ladder`. **Gate:** AT-003.

### WP-B4 · Pricing corrections — FRF-015, FRF-016 (high/medium)
**Depends on:** WP-A2 (contract amendment). **Blocks:** any Deribit/CME venue analysis; FRF-005 repricing accuracy.
**Repair:** inverse pricer uses `exp(−qT)` not `exp(−rT)` (identity
price_BTC × S = Black-76 USD at q=0); guard `delivery_price > 0` and reject
non-positive S/K/σ/T and invalid kind with the project error taxonomy; fix
`greeks_black76` put theta to `−term1 + r·P`. Derive golden vectors from the
official worked example + the no-arbitrage identity for calls AND puts over a
parameter grid. **Files:** `pricing/inverse.py`, `pricing/black76.py`.
**Gate:** AT-015, AT-016. **Branch note:** `f75e148` implements the core fix and
is conditionally merge-ready once WP-A2 lands and independent tests are added.

### WP-B5 · Settlement & inventory engine; ledger reconciliation — FRF-004, FRF-025 (critical/medium)
**Depends on:** WP-B1, WP-B3. **Blocks:** FRF-007, FRF-014, FRF-006, FRF-026.
**Repair:** a settlement engine keyed on `SettlementSpec` with exactly one
settlement pathway per leg (cash in settlement currency; futures-delivery-then-
cash; physical only where required); single-entry ledger effects; discretionary
post-settlement BTC purchases modelled as explicit separate actions; CSP
collateral re-reserved each cycle; consume `contract_multiplier`; implement
`SettlementResult` (contracts §10.3) with provenance; delivery price per
convention (documented TWAP proxy = MODEL_RECONSTRUCTED where intraday absent).
Enforce the reconciliation identity Δcash + Δbtc·S + Δcollateral = net P&L at
cycle and run level. **Files:** `strategy/backtest.py:418-499`, new
`engine/settlement` settlement-result path, `strategy/definitions.py`.
**Gate:** AT-004, AT-025. **Decision:** D-12 (CSP acquisition scope / post-
settlement repurchase) — carry both interpretations until resolved.

### WP-B6 · Instrument repricing for MC/stress/regime — FRF-005 (critical)
**Depends on:** WP-B1, WP-B4. **Blocks:** FRF-006, FRF-021, FRF-011.
**Repair:** legs used by MC/stress/regime carry premiums repriced from the
evaluation context (spot/vol/T at evaluation) via the pricing layer, or the
evaluators reprice; builder placeholder premiums are labelled ASSUMED and
rejected by evaluators. **Files:** `strategy/definitions.py`,
`strategy/monte_carlo.py`, `strategy/stress.py`, `strategy/regimes.py`,
`strategy/comparison.py`. **Gate:** AT-005.

### WP-B7 · Fee engine — FRF-013 (high)
**Depends on:** WP-B5. **Blocks:** FRF-014.
**Repair:** fee engine keyed on venue/product from `SettlementSpec`: Deribit
formulas only for Deribit BTC legs with documented caps/bases (trading fee
`MIN(0.0003 BTC, 0.125×premium)×contracts`; delivery fee 0.015% capped 12.5% of
option value); OTC legs use negotiated/zero venue fees per D-1/D-3; Asymmetrica
0.5% modelled separately on the D-1 base (BOTH variants until resolved);
roll-frequency-aware impact (only incremental re-execution charged); ADV from
config with ASSUMED provenance. **Files:** `strategy/backtest.py:392-437`,
`execution/impact.py`, `execution/waterfall.py`. **Gate:** AT-013.
**Decision:** D-1 (fee base). **Branch note:** A2 (`8743811`) and A4
(`fda2a1b`) both touch fees and must be unified into ONE fee ledger, fee counted
exactly once per strategy, no silent D-1 default (fda2a1b currently defaults it).

### WP-B8 · Return, drawdown, Sharpe, touch — FRF-007 (critical)
**Depends on:** WP-B5. **Blocks:** comparison validity.
**Repair:** build the equity curve solely from the reconciled ledger (populate
`daily_snapshots` with daily MTM); drawdown on that curve in consistent units;
annualise Sharpe with explicit risk-free and cycle frequency; per-leg touch with
correct direction per option type using the intra-cycle path. **Files:**
`strategy/backtest.py:488-570`, `strategy/comparison.py`. **Gate:** AT-007.

### WP-B9 · Effective acquisition cost — FRF-014 (high)
**Depends on:** WP-B5, WP-B7. **Blocks:** comparison EAC column.
**Repair:** one EAC definition per contracts §11.1 computed from the reconciled
ledger (numerator = net cash deployed incl. all provenance-labelled cost
components; denominator = actual BTC held at end); strategies acquiring zero BTC
report EAC = n/a with reason; comparison layer consumes only this value.
**Files:** `strategy/backtest.py:579-613`, `strategy/comparison.py:85-99`.
**Gate:** AT-014. **Decision:** D-12.

### WP-B10 · Premium-percentage metric — FRF-030 (medium)
**Depends on:** WP-B1. **Repair:** `premium_pct = net premium USD (per-leg quote
currency at entry spot) / (entry spot × reference quantity)`, no leg-count
division; per-leg and net reported separately. **File:**
`strategy/backtest.py:345-404`. **Gate:** AT-030.

### WP-B11 · Loss quantities — FRF-026 (medium)
**Depends on:** WP-B5. **Repair:** analytic structural max loss per strategy
kind from leg identities (no ±50% curve truncation); consistent sign; loss block
in every report (USD, per-BTC, %notional, %capital, ledger-reconciled historical
worst). `structural_max_loss` verified against actual payoff extremum, not just a
stored builder field. **Files:** `strategy/payoffs.py:compute_strategy_payoff`,
`engine/strategy.py:Strategy`. **Gate:** AT-026. **Decision:** D-10 (loss budget).

### WP-B12 · Stress single-basis valuation — FRF-006 (critical)
**Depends on:** WP-B5, WP-B6. **Repair:** one valuation basis per scenario
(expiry settlement OR MTM revaluation incl. spot and vol — never the sum); path
scenarios track MTM changes; adverse excursion = worst signed loss;
`venue_settlement_applied` reflects what was applied; swallow no pricing
exceptions to 0.0. **Files:** `strategy/stress.py:apply_scenario`. **Gate:** AT-006.

### WP-B13 · Classification, config, schema hygiene — FRF-019, FRF-020 (medium/high)
**Depends on:** WP-A2 (for any schema decision). **Repair:**
- `classify()`: reachable PARTIAL_OVERLAY (overlay ratio < 1), CALL_SPREAD
  requires opposite sides + distinct strikes, return BESPOKE for unknown combos,
  handle short-spot legs; full §13.3 matrix incl. negatives (FRF-019).
- Config: one validated schema for research runs (documented decimal
  convention); runner consumes it; unknown keys rejected; waterfall reads through
  the validated layer; D-gates emit dual-variant outputs rather than blocking
  research (FRF-020).
**Files:** `engine/strategy.py:classify`, `config/*`, `research/runner.py`,
`execution/waterfall.py`. **Gate:** AT-019, AT-020.

### WP-B14 · Acceptance-test suite as the gate — FRF-023 (high)
**Depends on:** the AT it encodes. **Repair:** implement AT-001…AT-033 as real
numeric invariants; convert every skipped required stub into a real test or an
explicit contract amendment; hypothesis-based QuantLib parity (50 draws);
fixture sha256 verification at load. **Files:** `tests/*`,
`engine/fixture_loader.py`. **Gate:** the suite itself. This WP runs *alongside*
every other WP (red-green).

### WP-B15 · Hygiene (dependency-free, opportunistic) — FRF-029 (medium)
Raise on unparseable timestamps; PricingError on non-finite grid prices;
ValueError-raising validators (not `assert`); checksum excludes the mutating log
or is written last; MC distribution persistence policy; guarded S_T=0 boundary
for inverse legs. **Gate:** AT-029.

---

## PHASE C — Research subsystem (Level 1 → 3, Stage 3)

Blocked until Phase B deterministic acceptance tests pass.

### WP-C1 · Historical DVOL ingestion — FRF-008 (critical)
**Depends on:** Phase B. **Repair:** historical DVOL provider (official Deribit
DVOL history; CDD daily DVOL as explicitly-labelled fallback); wire `iv_history`
from observed DVOL; premium provenance = MODEL_RECONSTRUCTED only when produced
by the §6.5 reconstruction from observed DVOL, ASSUMED when from flat config vol
(such runs labelled diagnostic). **Files:** new DVOL provider in `vol/`,
`research/runner.py:339`. **Gate:** AT-008. **Missing source:** MS-1.

### WP-C2 · Historical coverage gate & window — FRF-009 (critical)
**Depends on:** Phase B. **Repair:** coverage gate fails (or relabels) when
actual coverage differs from requested beyond tolerance; implement Massive
pagination; do not silently accept truncation. **Files:**
`vol/history.py:fetch_bars`, `research/runner.py:286-382`. **Gate:** AT-009.
**Decision:** D-11 (procure pre-2024-07 history or re-scope). **Branch note:**
`8743811` adds a gate but it passes silently on missing metadata and uses a
hard-coded 30-day threshold — must be corrected.

### WP-C3 · Provenance & reporting controls — FRF-017, FRF-033 (high)
**Depends on:** Phase B. **Repair:** reports derive attribution from the run's
`data_manifest`; provenance column on every reported number; implement the
§15.3 warning catalogue with tests (W-PROVENANCE-MISLABEL, W-NO-OBSERVED-CHAINS,
W-DECISION-PENDING, W-COVERED-CALL-OPTIMALITY-CLAIM); correct the category
mapping (CDD = observed/fallback; synthetic = SIMULATED; flat-vol premiums =
ASSUMED); MR-11 range-consistency reporting (implied delta/IV for target yield).
**Files:** `research/reporting.py`, `research/runner.py:376-380`,
`strategy/scenarios.py:27`, `strategy/backtest.py:310`, `vol/`. **Gate:** AT-017.

### WP-C4 · OOS / CSCV / PBO / DSR — FRF-010, FRF-028 (high/medium)
**Depends on:** WP-B1 (variant grid needs re-striking). **Repair:** true CSCV
over a variant grid (delta × DTE × overlay × roll rule) producing an
N-strategy per-period matrix; C(S,S/2) combinations; rank-logit PBO; Bailey DSR;
chronological walk-forward; typed insufficient-data verdict. Assign cycles by
settlement date strictly inside window; embargo ≥ DTE between train and test.
**Files:** `strategy/regimes.py:194-389`, `research/runner.py:404-458`.
**Gate:** AT-010, AT-028. **Note:** do not claim F-08 repaired until the real
method exists (branches do not).

### WP-C5 · Regime analysis — FRF-011 (high)
**Depends on:** WP-B1, WP-C1. **Repair:** run the repaired cycle backtest within
each regime window with re-struck legs and window-local data; `avg_dvol` only
from observed DVOL (else rename `realized_vol`); non-overlapping/weighted
windows. **Gate:** AT-011.

### WP-C6 · Execution sensitivity persistence — FRF-012 (high)
**Depends on:** WP-B7. **Repair:** persist the actual `waterfall_sensitivity`
rows (all spot-offset × fee-base combinations); extend to strategy-level
sensitivity (ADV, spread, IV give-up). **Files:** `research/runner.py:514-521,
631-635`. **Gate:** AT-012. **Branch note:** A2+A4 overlap — neither persists it
today; the fix must live in one place.

### WP-C7 · Monte Carlo methodology — FRF-021 (high)
**Depends on:** WP-B5, WP-B6, approved sim spec MS-26. **Repair:** multi-cycle
MC consistent with the repaired lifecycle (re-strike, per-cycle repricing along
each path); model-keyed result storage (no overwrite); CSP capital = strike
notional; ASSUMED provenance on drift/jump with sensitivity reporting.
**Files:** `strategy/monte_carlo.py`, `research/runner.py:469-505`.
**Gate:** AT-021. **Gate precondition:** MS-26 approved simulation methodology.

### WP-C8 · Vol analytics — FRF-024 (medium)
**Depends on:** WP-C1. **Repair:** parse strikes from instrument names;
out-of-sample GARCH with working diagnostics; 365-day annualisation; single DVOL
client (decimal); surface fit quality on held-out quotes. **Gate:** AT-024.

### WP-C9 · Stress scenario realism — FRF-027 (medium)
**Depends on:** WP-B12, WP-C2. **Repair:** replay scenarios consume observed
historical windows; synthetic bridges relabelled `shock_type=synthetic`/
SIMULATED; settlement shock models delivery-price basis. **Gate:** AT-027.
**Missing source:** pre-2024 replay windows depend on D-11.

### WP-C10 · Results governance & registry — FRF-022 (critical)
**Depends on:** Phase B + WP-C3. **Repair:** run registry marking all existing
runs superseded/diagnostic (no deletion); retract the DeepSeek-synthesis claims
list before any client-facing use; pointers reference only gate-passing runs;
value-plausibility gates (premium %-of-notional bounds, ledger reconciliation)
replace existence-only gates; CLI exits non-zero on missing outputs; git SHA +
environment + per-file checksums in manifests. **Files:**
`research/runner.py:_validate_results`, `.latest_research_*`, run registry.
**Gate:** AT-022.

---

## Preserve (do not regress) — FRF-034

Golden BS suites, LBSP +1/+2 identities, settlement enums, Massive provider,
waterfall arithmetic, EngineConfig validator structure, and the correct
classification of the mislabelled "Covered Put" diagram are verified correct and
must remain green through every WP. (Verifier note: `SettlementSpec.contract_
multiplier` carries a `Field(gt=0)` tightening not in the frozen §5.1 text; fold
into WP-A2 if a contract-exact match is desired.)

## Decisions & missing sources that gate work (summary)

| Ref | Type | Gates |
|---|---|---|
| D-1 fee base | business | WP-B7, WP-C6 (dual-variant until resolved) |
| D-3 primary venue | business | WP-B4/B5 venue-true pricing/settlement |
| D-10 loss budget | business (new) | WP-B11 strategy selection |
| D-11 historical data | business (new) | WP-C2, WP-C9, all pre-2024 claims |
| D-12 CSP acquisition scope | business (new) | WP-B5, WP-B9 |
| MS-1 official DVOL history | primary source | WP-C1 |
| MS-9/MS-10 inverse pricing anchor | primary source | WP-B4 golden vectors |
| MS-25 objective function | approval | any ranking/"optimal" claim |
| MS-26 simulation methodology | approval | WP-C7 / large MC |
