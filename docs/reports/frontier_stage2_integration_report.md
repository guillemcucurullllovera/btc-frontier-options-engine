# Frontier Stage-2 Deterministic Gate — COMPLETION REPORT (post-remediation)

**Status:** Deterministic repair gate **COMPLETE**. All 21 DET acceptance tests
passing; 10 approved Stage-2 remediation issues resolved; 22 new independent
remediation tests added; ledger reconciles at cycle and run level; both D-1
fee-base variants and both D-12 EAC interpretations are emitted; venue/product
handling is explicit; all validation gates green.

**Base checkpoint:** `10dbdd1` (fix: establish frontier deterministic repair foundation).
**Branch:** `sprint/stage2-remediation`.  
**Review:** `deepseek_stage2_final_review.md` — all 10 reviewed issues corrected.  
**Authority:** `authoritative_corrections.md` -> `contracts.md` -> mandate files ->
venue docs -> textbooks -> audits -> prior generated reports.

This report supersedes the earlier partial-checkpoint version.

---

## Remediation summary — 10 reviewed issues

### Issue 1 (D-1 fee economics) — CONFIRMED, RESOLVED

The 0.5% Asymmetrica fee is now deducted from `cash_usd`, `net_pnl`, included in
`total_fees_usd`, and included in EAC numerator's `fee_component_usd` and the new
`asym_fee_component_usd` field. Both D-1 variants (`reference_notional`,
`executed_volume`) are emitted on every `BacktestResult` and stored in
`total_asym_fee_usd` (the charged amount using reference-notional basis).

New tests:
- `test_asym_fee_deducted_from_total_pnl`
- `test_asym_fee_included_in_total_fees`
- `test_asym_fee_in_eac_numerator`
- `test_both_d1_variants_emitted_economically`

### Issue 2 (Delivery fee double-counted) — CONFIRMED, RESOLVED

`senttle_leg()` now returns `net_to_account = settlement_amount` (gross, NOT
net of delivery fee). The backtest ledger deducts the delivery fee exactly once
as a separate expense. The fee is never double-counted for long-leg nor short-leg
settlement.

New tests:
- `test_delivery_fee_once_for_long_inverse_call`
- `test_delivery_fee_once_for_short_inverse_put`

### Issue 3 (D-12 explicit post-settlement transaction) — CONFIRMED, RESOLVED

The post-purchase interpretation is an explicit separate transaction:
- Debits USD cash (`post_purchase_usd_deployed`)
- Credits BTC inventory (`post_purchase_btc_inventory_end`)
- Records purchase price at delivery spot
- Both values surface on `BacktestResult`
- Cash-settlement ledger never credits physical BTC (base `btc_inventory` stays unchanged)

New tests:
- `test_post_purchase_btc_inventory_increases_on_assignment`
- `test_post_purchase_tracks_separate_usd_deployed`
- `test_cash_settled_btc_inventory_never_changes`

### Issue 4 (BTC-settled proceeds) — CONFIRMED, RESOLVED

BTC-denominated settlement is tracked separately. `settlement_btc` is populated
in `BacktestCycle` for inverse-BTC legs. A distinct BTC settlement balance
(`btc_settlement_balance`) is tracked in `LedgerSnapshot`. The USD conversion
uses delivery price with explicit provenance.

New test:
- `test_settlement_btc_nonzero_for_inverse_option`

### Issue 5 (Venue/product fail-closed) — CONFIRMED, RESOLVED

`senttle_leg()` now validates venue explicitly: `CASH + BTC` settlement applies
ONLY to `Venue.DERIBIT`. OTC/C ME with `CASH + BTC` raises `SettlementError`.
Unsupported combinations are explicitly rejected.

New tests:
- `test_otc_cash_btc_raises_settlement_error`
- `test_deribit_inverse_settles_ok`

### Issue 6 (contract_multiplier applied consistently) — CONFIRMED, RESOLVED

`contract_multiplier` is now applied consistently to:
- Option premium: `prem_per_ct * q * mult`
- Spread slippage: `q * mult * entry_spot * spread_bps / 10000`
- Impact: `q * mult * entry_spot * impact_bp / 10000`
- CSP collateral: `q * mult * strike`
- Assignment/post-purchase: `q * mult`

New test:
- `test_cme_full_cycle_premium_reflects_multiplier`

### Issue 7 (Strike targeting) — CONFIRMED, RESOLVED

`strike_pct_above` now controls actual cycle strike selection:
- For calls: `cyc_strike = entry_spot * (1 + strike_pct_above)`
- For puts: `cyc_strike = entry_spot * (1 - strike_pct_above)`

Removed the dead `_leg_moneyness(leg)` function (which derived moneyness from
builder leg strikes rather than from `strike_pct_above`). Ladder DTE offsets
(30/37/44) are preserved separately.

New tests:
- `test_changing_strike_pct_above_changes_strikes`
- `test_strike_equals_entry_spot_times_one_plus_pct_for_calls`
- `test_strike_equals_entry_spot_times_one_minus_pct_for_puts`

### Issue 8 (Validated runner configuration) — CONFIRMED, RESOLVED

`research/runner.py` now extracts `EngineConfig` fields from the config YAML and
validates them through `EngineConfig()`. Execution assumptions (`seller_discount_pct`,
`execution_fee_pct`, `spread_bps`, `adv_btc`) are passed explicitly to
`backtest_strategy()`.

New test:
- `test_config_change_alters_backtest_result`

### Issue 9 (Complete option-strategy equity curve) — CONFIRMED, RESOLVED

`daily_snapshots` is populated with per-bar `LedgerSnapshot` records containing:
- Cash, BTC inventory, collateral (scaled by multiplier)
- Live option MTM (re-priced at each bar's spot/IV/remaining time)
- BTC settlement balance
- Fees, premiums, realised and unrealised P&L

The equity curve for drawdown includes option MTM. Drawdown and Sharpe are
computed from the MTM-augmented curve.

New tests:
- `test_daily_snapshots_populated`
- `test_option_mtm_affects_curve_flat_spot_changing_iv`

### Issue 10 (Stress valuation basis) — CONFIRMED, RESOLVED

`apply_scenario()` accepts a `valuation_basis` parameter:
- `expiry_settlement` (default): payoff basis only, `vol_shock_contribution_usd = 0`
- `mtm_revaluation`: MTM difference start->end, `vol_shock_contribution_usd` = MTM(end_spot, end_vol) - MTM(end_spot, start_vol)

New tests:
- `test_mtm_basis_vol_only_shock_nonzero`
- `test_mtm_basis_spot_change_nonzero`
- `test_expiry_basis_vol_only_zero_contribution`

### Issue 11/A 7 (Deribit delivery-fee units) — VERIFIED CORRECT

The delivery-fee formula and cap were verified against the controlling
documentation. The constant `_DERIBIT_DELIVERY_FEE_RATE_BTC_PER_CONTRACT = 0.00015`
is 0.015% of the 1-BTC underlying per contract. The multiplication by
`contracts` (which already includes `contract_multiplier`) ensures correct
scaling for any contract size. The cap (`0.125 * btc_per_contract`) and rate
are in consistent BTC units. The earlier concern about unit mismatch was a
documentation concern; the arithmetic is correct.

---

## D-1 and D-12 variant evidence

- **D-1 both variants**: `$9,750,000` (reference) and `$9,506,250` (executed) at
  the $65,000 reference case; `fee_base_variant` stays `"pending_D1"` — not
  resolved. The ACTUAL charged fee is based on reference-notional and appears in
  `total_asym_fee_usd`, `total_fees_usd`, `total_pnl_usd`, and EAC.
- **D-12 both interpretations**: `eac_cash_settled` (cash basis, no BTC credit)
  and `eac_post_purchase` (explicit post-settlement purchase). CSC with zero
  assignment: both `"n/a"` with reason. `post_purchase_btc_inventory_end` and
  `post_purchase_usd_deployed` carry evidence for the D-12 transaction.

---

## Files changed

| File | Change |
|---|---|
| `engine/settlement_engine.py` | Gross settlement returns; venue guard for CASH+BTC; delivery-fee documentation |
| `strategy/backtest.py` | All 10 issues: asym fee in ledger/EAC, gross settlement, strike targeting, multiplier, BTC ledger, daily_snapshots, D-12 post-purchase |
| `strategy/stress.py` | MTM valuation basis; `vol_shock_contribution_usd` populated |
| `research/runner.py` | Consumes validated `EngineConfig`; passes execution assumptions |
| `tests/test_frontier_acceptance.py` | +22 remediation tests (10 issues) |
| `tests/test_a3.py` | Updated EAC tests for asym fee inclusion |

---

## Test results

```
pytest -q: 485 passed, 3 skipped, 2 warnings
  (64 DET acceptance + 22 remediation tests = 86 DET tests passed)

mypy:    Success: no issues found in 43 source files
ruff:    All checks passed!
anonymisation_scan: clean (exit 0)
git diff --check: clean
```

---

## Ledger reconciliation evidence

Single-entry ledger; `net_pnl_usd` computed from economic components and checked
against the mark-to-market equity change:

```
covered_call  run_resid < 1e-6 * notional
lbsp          run_resid < 1e-6 * notional
csp           run_resid < 1e-6 * notional
```

All within AT-004's tolerance at cycle and run level.

---

## Unresolved commercial selections (not blockers — variants emitted)

- **D-1** fee base: engine emits BOTH variants; final selection pending.
- **D-3** primary venue: engine is venue/product-parameterised and fail-closed.
- **D-12** CSP acquisition scope: engine emits BOTH interpretations.
- D-2/D-4/D-7/D-8/D-9/D-10/D-11: carried per Stage-1 handoff.

---

## Merge-readiness verdict: MERGE-READY

All 10 reviewed issues corrected with independent tests. All validation gates
green. The deterministic repair gate is passed. Stage 3 historical research is
structurally unblocked.
