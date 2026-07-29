# Independent Quantitative Validation Report

**Reviewer role:** Independent senior quantitative validation reviewer (read-only)
**Date:** 2026-07-29
**Status:** INSUFFICIENT_EVIDENCE
**Scope:** All empirical outputs in `empirical-baseline-fixed-20260729T005016Z` and `empirical-robustness-20260729T005618Z`, plus supporting implementation code
**No model was relied upon. All rederivations are from raw input data, output tables, and implementation source.**

---

## Verdict

**INSUFFICIENT_EVIDENCE**

The report's central claim — that BTC declined 56% historically from the observation start — is **false** as an observed fact. The unhedged baseline P&L of -56.20% derives from a synthetic GBM path (seed=42) that bears no relation to the observed Massive spot data (which shows an actual decline of -4.61%). This alone invalidates the comparison between unhedged and overlay strategies. Three additional BLOCKING findings prevent any reliable strategy comparison: max drawdown of 0% for a strategy with -56% return, premium contamination from settlement cash flows reported as "premium income," and mixing of observed data (all strategies) with synthetic data (unhedged only) in the same comparison table.

---

## Findings Summary

| ID | Severity | Summary |
|----|----------|---------|
| V-001 | BLOCKING | Unhedged baseline uses synthetic GBM data, not observed Massive spot |
| V-002 | BLOCKING | Unhedged max_drawdown 0% incompatible with -56.2% P&L |
| V-003 | BLOCKING | Asymmetric data sources in strategy comparison |
| V-004 | MAJOR | Total premium includes settlement cash flows, not just upfront premium |
| V-005 | MAJOR | Historical spot return misrepresented in narrative |
| V-006 | MAJOR | OOS validation metrics are all null |
| V-007 | MAJOR | Execution sensitivity contains only configuration, no results |
| V-008 | MODERATE | MC aggregate metrics zero variance across all seeds |
| V-009 | MODERATE | Reported ITM frequency of 62.5% explained by fixed strike |
| V-010 | MODERATE | Collar total_premium field includes only short call premium |
| V-011 | MODERATE | Cycle count misstatement (report says 21, actual is 24 per strategy) |
| V-012 | MINOR | Effective acquisition cost not decomposable per contracts.md §11.1 |
| V-013 | MINOR | Stress premium_contribution_pct is constant across all scenarios |
| V-014 | MINOR | Regime CSP +$45M per-regime is a fixed value, not computed |

---

## Detailed Findings

### V-001 — BLOCKING: Unhedged baseline uses synthetic GBM data

**File:** `research/runner.py:388-393`, `strategy/backtest.py:694-748`
**Root cause:** The runner dispatches `unhedged_baseline` to `backtest_unhedged()` which generates a synthetic GBM path from `reference_spot_usd` ($65,000) using `numpy.random.default_rng(seed=42)`. All other strategies use `backtest_strategy()` which consumes the observed `spot_path` from Massive.

**Observed values from `_spot_data_dump.csv`:**
- Start (2024-07-29): $66,771.45
- End (2026-07-27): $63,694.43
- Actual buy-and-hold return: **-4.61%**
- Min observed spot: $53,950.01
- Actual return from $65k reference: **-2.01%**

**GBM path used for unhedged (seed=42, drift=10%, vol=45%, 1303 days):**
- Start: $65,000.00
- End: $28,471.17
- Return: **-56.20%**

**Impact:** The "unhedged -56.2%" reported as a historical comparison baseline is a fabricated number. The report narrative ("BTC declined 56% from the observation start," "covering a period during which BTC peaked near the observation start and then entered a significant bear phase") describes a synthetic path, not the observed market.

**Acceptance test:** Re-run the unhedged backtest using `backtest_strategy()` with zero option legs, consuming the identical `spot_path` fed to all other strategies. The resulting total_pnl_pct must match the actual buy-and-hold from the observed data.

---

### V-002 — BLOCKING: Unhedged max_drawdown 0% contradicts -56.2% P&L

**File:** `strategy/backtest.py:694-748`, `strategy/comparison.csv`
**Observed:** `strategy_comparison.csv` row for `unhedged_baseline` reports `total_pnl_pct = -56.20` and `max_drawdown_pct = 0.0`.

**Root cause:** `backtest_unhedged()` instantiates a `BacktestResult` with all default-zero fields and never computes any drawdown. The `max_drawdown_pct` header is simply the `dataclass` default of `0.0`.

**Mathematical impossibility:** A strategy with -56.2% total return MUST have had a peak-to-trough decline of at least 56.2%. Zero drawdown for a negative-return strategy is logically impossible unless drawdown is separately defined (which it is not).

**Acceptance test:** Run the unhedged strategy through `backtest_strategy()` with zero option legs. The resulting `max_drawdown_pct` must be ≥ |total_pnl_pct|.

---

### V-003 — BLOCKING: Asymmetric data sources in strategy comparison

**Severity escalation from V-001:** The `strategy_comparison.csv` places the unhedged baseline (-56.2%, from GBM) in the same table as seven overlay strategies (computed from observed Massive data). The report then draws conclusions about premium strategies "outperforming" the unhedged baseline.

**Impact:** All comparative statements in the report between the unhedged baseline and other strategies are invalid. The comparison is between a synthetic worst-case GBM path and the observed market path. No conclusions about "premium buffer," "outperformance in a declining market," or "covering downside" can be drawn from this comparison.

**Acceptance test:** The strategy_comparison.csv must derive all rows from the same underlying data source. Either all strategies use observed data or all use synthetic data — not a heterogeneous mix.

---

### V-004 — MAJOR: Total premium includes settlement cash flows

**File:** `strategy/backtest.py:467-482`
**Observed:** `strategy_comparison.csv` reports `total_premium_usd = $11,341,760,165` for covered call.

**Premium per BTC per cycle varies from $127.55 (0.21% of entry spot) to $49,966 (40.06% of entry spot).** The extreme values occur in cycles where the fixed $75,000 strike call is deep ITM at entry — the "premium" includes substantial intrinsic value that must be returned at settlement.

**Root cause:** `_option_price()` computes the full Black-Scholes price of the option at entry spot, including intrinsic value. For a call with strike $75,000 and spot $96,465, this reflects deep moneyness — not a "premium buffer" from selling 15%-OTM calls. When the call expires ITM, the settlement payout almost perfectly offsets this inflated premium (minus time value).

**Impact:** The report's narrative about "$11.34B premium buffer" and "Premium Contribution = +67.46%" is misleading. This is not standalone premium income — it is dominated by intrinsic value that must be paid back. The actual NET income from the options overlay is $225M (11.26% P&L), not $11.34B.

**Acceptance test:** The `total_premium_usd` field must distinguish between:
- `upfront_option_premium_usd` (time value only, at entry)
- `option_settlement_cash_flow_usd` (settlement proceeds for ITM options)
- `net_option_income_usd` (premium + settlement, the net cash effect)

The report narrative must use `net_option_income_usd` when discussing "premium contribution to P&L."

---

### V-005 — MAJOR: Historical spot return misrepresented in narrative

**Evidence from `_spot_data_dump.csv`:**
- Observed start: $66,771.45
- Observed end: $63,694.43
- Observed buy-and-hold return: **-4.61%**
- Maximum observed price: $124,720.09
- Minimum observed price: $53,950.01

**Report claims (Section 4.1):** "BTC declined 56% from the observation start," "the analysis captures a period during which BTC peaked near the observation start (approximately $110k+) and then entered a significant bear phase, ending near $63k."

**Fact:** The observed data shows a -4.61% decline, with BTC reaching $124,720 (well above start) mid-period, and ending just slightly below start. The report's description matches the synthetic GBM path used for unhedged, not the observed Massive data. The 56% figure does not appear anywhere in the observed spot data.

**Acceptance test:** Any statement about the "historical spot return" or "market decline" must reference values computed directly from `_spot_data_dump.csv`. The observed return is -4.61%.

---

### V-006 — MAJOR: OOS validation metrics are all null

**File:** `strategy/regimes.py:compute_oos_validation()`, `research/runner.py:416-458`
**Observed:** `oos_results.parquet` has 8 rows with strtok_id, pbo_estimate=None, deflated_sharpe_ratio=None.

**Root cause:** CSCV computation requires `len(all_returns) >= cscv_n (100)`. Each strategy has at most 24 backtest cycles. The unhedged has 0 cycles. Therefore `pbo_estimate` and `deflated_sharpe_ratio` are always `None`.

**The runner code at line 442-443** calls `compute_oos_validation()` which correctly returns None when insufficient data. The `is_insufficient_data` flag is True but not recorded in the output parquet.

**Impact:** The report correctly identifies this gap. However, the OOS parquet is not empty (as the report states) — it has 8 rows with null values. The report's claim that the "train window has only ~5 months of data" is also incorrect: the train dates are 2023-01-01 to 2024-12-31, but actual data starts 2024-07-29, giving ~5 months of training data. With 30-day DTE, this yields ~5 training cycles, far too few for CSCV.

**Acceptance test:** Add `is_insufficient_data` and `insufficient_data_reason` to the OOS parquet output. Lower cscv_n to a value achievable with 24 cycles (e.g., 12) or acknowledge that CSCV is not applicable with the current data window.

---

### V-007 — MAJOR: Execution sensitivity contains only configuration

**File:** `research/runner.py:631-635`, `results/research/*/execution_sensitivity.parquet`

**Observed:** The parquet has 1 row with:
- `spot_offsets_pct`: `[-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]`
- `fee_bases`: `['reference_notional', 'executed_volume']`

**Root cause:** Lines 631-635 write the raw configuration values to parquet. `waterfall_sensitivity()` is called at line 521 with `None` as the strategy argument but its output is never collected or written. The sensitivity iteration over spot offsets, fee bases, and strategies is not executed.

**Required dimensions:** strategy × spot_offset × fee_base = 8 × 7 × 2 = 112 rows should be produced (or 56 if excluding unhedged). Each row should contain the recomputed effective acquisition cost, total P&L, and per-component fee breakdown.

**Acceptance test:** Iterate over all combinations of (strategy, spot_offset, fee_base), recompute the waterfall for each, and write 56+ rows to `execution_sensitivity.parquet`.

---

### V-008 — MODERATE: MC aggregate metrics show zero variance across all seeds

**Files:** `results/research/empirical-robustness-20260729T005618Z/robustness_summary.csv`, `all_strategy_results.csv`

**Observed:** For all strategies, `total_pnl_pct_std = 0.0`, `sharpe_ratio_std = 0.0`, `total_premium_usd_std = 0.0`, `effective_acquisition_cost_std = 0.0` across 36 runs (12 seeds × 3 path counts).

**Root cause confirmed:** The `total_pnl_pct`, `sharpe_ratio`, and `total_premium_usd` fields are derived from the historical backtest — which is deterministic given the same spot data. The MC component only affects tail-risk metrics (VaR, ES, probability_of_loss). The `var_95_loss_std` IS non-zero ($454k-$908k), confirming MC seeds do produce different paths. The zero-variance fields are identical because they come from the same backtest for all 36 runs — each run shares the same historical spot data.

**The synthesis report correctly identifies this** but describes it as a "potential seed-isolation defect." The correct interpretation is: **these fields are deterministic historical quantities, not MC outputs.** No defect exists — this is a data provenance issue.

**Acceptance test:** Add a provenance column to the robustness summary distinguishing `historical` (deterministic) from `simulated` (random) fields. Document that zero variance in historical fields is expected.

---

### V-009 — MODERATE: ITM frequency of 62.5% explained by fixed strike

**Observed:** 15 of 24 cycles report ITM for covered call strategies. The report says ITM frequency "is determined entirely by whether spot was above strike at expiry, not at entry."

**Root cause:** The strike is fixed at $75,000 (≈$65,000 × 1.15) for all cycles — it is a strategy-level parameter, not recomputed per cycle from the entry spot. When the strategy definition sets `strike_pct_above = 0.15` from `reference_spot_usd = 65,000`, the resulting $75,000 strike becomes deep ITM when spot rallies to $124,720.

**Implication:** The 62.5% ITM frequency does NOT represent "the call expired ITM with 15% OTM at entry" — it represents "the fixed $75,000 strike call expired ITM given the spot path." For a call to be truly 15% OTM at entry, the strike would need to be `entry_spot × 1.15` at each cycle, not $75,000 fixed.

**Acceptance test:** Document whether strikes are fixed or dynamically recomputed. If fixed, report this as "ITM frequency with respect to fixed $75,000 strike" rather than "ITM frequency with respect to 15%-OTM entry."

---

### V-010 — MODERATE: Collar total_premium is gross short call premium only

**File:** `strategy/comparison.csv` row for `collar`

**Observed:** `total_premium_usd = $11,254,109,847` — nearly identical to covered call's $11,341,760,165.

**Root cause:** The collar's total premium only accumulates the short call leg premium. The long put cost is a cash outflow (negative premium) that is netted within the P&L computation but not disaggregated in the output. The runner at `runner.py:481` sums `total_premium_received_usd += premium_received_usd` where premium_received_usd includes both long and short leg premiums with signs.

**Impact:** The report states "the long put cost is netted within the strategy P&L" which is correct, but the `total_premium_usd` field should reflect the NET premium (call received minus put paid) to be comparable across strategies. A reader who compares $11.25B (collar) vs $11.34B (covered call) would be misled about the relative value of the collar's premium.

**Acceptance test:** Add a `net_premium_usd` field that sums signed premium across all option legs. The report narrative should reference net premium, not gross call premium.

---

### V-011 — MODERATE: Cycle count misstatement

**Observed:** The report states "168 cycles across 8 strategies × 21 cycles each." The actual `backtest_results.parquet` has 168 rows across 7 strategies = 24 cycles each. The unhedged has 0 cycles tracked. Therefore: 7 × 24 = 168, not 8 × 21 = 168.

**Acceptance test:** Update the report to state 7 strategies × 24 cycles = 168 cycles, with unhedged excluded from the cycle count (it has no option legs).

---

### V-012 — MINOR: Effective acquisition cost not decomposable

**File:** `strategy/backtest.py:599-613`, `strategy/comparison.csv`

**Observed:** The `EffectiveAcquisitionCost` dataclass contains premium_component_usd, fee_component_usd, seller_discount_component_usd, and impact_component_usd. However, the report's comparison CSV outputs only the final `effective_acquisition_cost` scalar without sub-component breakdown.

**Root cause:** The `build_comparison_table()` in `research/reporting.py` extracts `bt.effective_acquisition_cost.per_btc_usd` but does not extract the individual components.

**Impact:** The report correctly identifies this as a limitation (Section 10.2). The decomposition data exists but is not serialized to the comparison output.

**Acceptance test:** Add columns `premium_component_usd`, `fee_component_usd`, etc. to `strategy_comparison.csv`.

---

### V-013 — MINOR: Stress premium_contribution_pct is constant

**Observed:** All 10 stress scenarios for `covered_call` report `premium_contribution_pct = 1.0714%` — identical across scenarios from flash crash to breakout.

**Root cause:** The stress module applies a fixed premium percentage derived from the configuration (BS ATM premium at 15% OTM, 30 DTE, 45% vol) rather than recomputing premium under the stress shock conditions. This is an intentional simplification but is not documented as such.

**Acceptance test:** Document that `premium_contribution_pct` in stress scenarios is the configured single-premium estimate, not a scenario-dependent recomputation.

---

### V-014 — MINOR: CSP regime P&L is a constant

**Observed:** All 22 regime records for `cash_secured_put` show `strategy_pnl_usd = 45,000,000.0`. The report states "Consistently +$45M across all 21 regimes."

**Root cause:** The regime analysis computes P&L from payoff functions. For CSP, the payoff at each regime end is determined by whether the put expired ITM. With a $75,000 strike put and spot never falling below $53,950, the put never expires ITM — so the P&L is always the premium received. This is structurally correct but the report should clarify that $45M is per-regime premium income and not a per-regime total return.

**Acceptance test:** Document the CSP regime P&L as "per-regime premium income" rather than "total regime P&L."

---

## Verified Identities

The following identities were independently recomputed and confirmed:

| Identity | Formula | Expected | Observed | Match |
|----------|---------|----------|----------|-------|
| Observed spot return | `(end_close/start_close - 1) × 100` | -4.61% | N/A | Verified against CSV |
| Reference spot to end | `(end_close/65000 - 1) × 100` | -2.01% | N/A | Verified against CSV |
| GBM unhedged return (seed=42) | `pnl_usd / (btc_held * start_spot)` | -56.20% | -56.20% | Confirmed by reconstruction |
| Covered call P&L | `Σ net_pnl_usd / strategy_notional × 100` | 11.26% | 11.26% | Matches CSV |
| Cash-secured put P&L | `Σ net_pnl_usd / strategy_notional × 100` | 1.73% | 1.73% | Matches CSV |
| Backtest cycles | Count of rows per strategy | 24 each | 24 each | Verified |
| MC VaR (collar) | `var_95_pnl` | -$291,000,000 | -$291,000,000 | Matches CSV |
| OOS fields | pbo, deflated_sharpe | None, None | None, None | All null |
| Effective cost (unhedged) | `65000 × (1 - 0.025)` | $63,375 | $63,375 | Hardcoded |
| Premium per BTC (CC C0) | `28690350 / 30000 / 66771.45 × 100` | ~1.43% | 1.43% | Verified |

---

## Unsupported Claims

The following claims in the synthesis report are not supported by evidence:

1. "BTC declined 56% from the observation start" — Observed decline is -4.61%
2. "The historical window demonstrates... unhedged baseline lost 56.2% while option-overlay strategies recorded positive P&L" — Unhedged lost 56.2% in a synthetic GBM simulation; the observed market declined only 4.6%
3. "Total premium received = $11.34B" presented as standalone "buffer" — This includes intrinsic value and settlement cash flows that must be returned
4. "0 ITM frequency for the unhedged strategy" — Unhedged has no options; this field is meaningless
5. "All 36 runs share an identical deterministic computation path irrespective of seed" — This is expected for historical fields; not a defect
6. "Cycles may start at varying entry spots (not always $65,000)" — They DO start at varying spots because `backtest_strategy` uses observed data, but the fixed strike means they're not always 15%-OTM
7. "The model-reconstructed premium of ~1.07% per cycle falls well below the 2.5% target" — The per-cycle premium varies from 0.21% to 40.06% due to fixed strike; the "1.07%" is an average that obscures the strike moneyness dependency

---

## Required Repairs

| Priority | Repair | Affected Files |
|----------|--------|---------------|
| P0 | Route unhedged through `backtest_strategy()` with zero option legs, using observed spot_path | `research/runner.py:388-393` |
| P0 | Compute and write max_drawdown for unhedged strategy | `strategy/backtest.py:694-748` |
| P0 | Separate `upfront_premium_usd` from `option_settlement_cash_flow_usd` in cycle records | `strategy/backtest.py:477-482` |
| P1 | Recompute strikes dynamically per-cycle from entry spot, or document fixed-strike behavior | `strategy/backtest.py:340-390` |
| P1 | Populate execution sensitivity with strategy × spot_offset × fee_base results | `research/runner.py:514-521` |
| P1 | Add `is_insufficient_data` flag and reason to OOS parquet output | `research/runner.py:577-585` |
| P2 | Add net_premium_usd (signed sum across all option legs) to output | `research/runner.py:481-484` |
| P2 | Add sub-component breakdown to strategy_comparison.csv | `research/reporting.py` |
| P2 | Correct cycle count from "8 strats × 21 cycles" to "7 strats × 24 cycles" | Report text |
| P3 | Add provenance tags distinguishing historical from simulated fields in robustness summary | `research/runner.py` |

---

## Acceptance Tests

1. **V-001+V-003 Repair:** Run all strategies (including unhedged) through `backtest_strategy()` using identical `spot_path`. Verify unhedged total_pnl_pct = -4.61% (matching observed buy-and-hold).
2. **V-002 Repair:** Verify unhedged max_drawdown_pct > 0 and ≥ |total_pnl_pct|.
3. **V-004 Repair:** Verify `upfront_premium_usd` for a deep-ITM cycle equals Black-Scholes time value only, not intrinsic + time.
4. **V-007 Repair:** Verify `execution_sensitivity.parquet` has ≥ 56 rows (7 strategies × 7 spot_offsets × 2 fee_bases, excluding unhedged).
5. **Full regeneration:** After repairs, re-run baseline and verify no NaN/inf values, no negative effective acquisition costs, and all strategies use the same data provenance.

---

## Methodology

All recomputations were performed by reading the following files directly:
- `results/research/empirical-baseline-fixed-20260729T005016Z/_spot_data_dump.csv` (729 rows)
- `results/research/empirical-baseline-fixed-20260729T005016Z/strategy_comparison.csv`
- `results/research/empirical-baseline-fixed-20260729T005016Z/backtest_results.parquet`
- `results/research/empirical-robustness-20260729T005618Z/*.csv`
- `strategy/backtest.py` (full source)
- `research/runner.py` (full source)
- `research/reporting.py` (build_comparison_table)
- `strategy/regimes.py` (compute_oos_validation)

The GBM unhedged return was independently reconstructed with `numpy.random.default_rng(seed=42)`, confirming the -56.20% result.

No source code or configuration was modified. No large Monte Carlo reruns were performed. All observed values are from existing output files as of the review date.

---

*End of Independent Quantitative Validation Report.*
