# Senior Quant-Engineering Reviewer Report — `contracts_draft.md`

**Auditor role:** Read-only senior reviewer.  
**Subject:** `docs/architecture/contracts_draft.md` (v0.1, 2026-07-28, 1,197 lines).  
**Authority order applied:** `authoritative_corrections.md` → `ceo_strategy_research_mandate.md` → `AGENTS.md` → `mandate_sanitized.md` → `BTC_30K_Build_Plan_Parallel_Agents.md` → `final_gap_audit_minimax.md` → five DeepSeek pillar studies → current source / tests / config / A1–A6 briefs → draft.  
**Scope of inspection:** Lines 1–1197 of the draft cross-referenced against the authority documents above, the live code (`pricing/black_scholes.py`, `vol/dvol_feed.py`, `execution/waterfall.py`), the live tests (`tests/test_engine.py`, 9/9 green), the live config (`config/params.yaml`, 14 keys) and the six agent briefs in `agents/`.

---

## 1. Executive verdict

The draft is a genuine, source-backed attempt and correctly inherits most binding constraints from `authoritative_corrections.md` (AC-1, AC-3, AC-4, AC-5, AC-6, AC-8). It is far from a stub: it freezes pydantic schemas, separates settlement fields, preserves the existing `OptionQuote` frozen dataclass by extension (not migration), and carries the unresolved human decisions as explicit markers.

However, the draft has **at least five mathematically/contractually incorrect statements**, **at least seven HIGH-severity gaps** against the CEO research mandate, and **incorrectly resolves at least two decisions that AC and the build plan mandate remain pending**. It also encodes the CEO hypotheses (10–15Δ, 30–45 DTE, ~3% premium) as the **default values in `config/params.yaml`** and does not enforce their treatment as testable claims anywhere in the schema layer. The hedge-cost line item required by the mandate is missing from every result schema.

The draft cannot freeze as written. **Verdict: READY AFTER REQUIRED CORRECTIONS** (the corrections below are bounded; none requires a redesign).

---

## 2. Critical-error table

| # | Draft section | Incorrect / ambiguous claim | Reason | Required correction | Source of authority |
|---|---|---|---|---|---|
| **C-1** | §3.3 "Inverse call/put settlement (BTC)" formulas | `settlement_btc = max(delivery_price − strike, 0) / delivery_price` for call and the symmetric put formula. | The formula is **the gross settlement cash flow to the option HOLDER** (long position), per Deribit spec lines 1–199. The draft never states the sign convention. A naive reader will apply the formula to a SHORT writer position without sign inversion, which propagates a wrong-sign error into every covered-call, CSP, long-BTC+short-put, collar and call-spread payoff. | Add an explicit "Long holder receives this BTC amount; the writer pays the negation" sentence. Rename the new functions in §7.3 from `payoff_inverse_call` / `payoff_inverse_put` to `settlement_inverse_call_holder` / `settlement_inverse_put_holder` to remove the naming ambiguity. The strategy-P&L function must negate the holder settlement for short writers and add the entry premium. | `authoritative_corrections.md` §4; reconciled audit §10.8; Deribit spec lines 1–199; `pillar_2_risk_validation_deepseek.md` §3.5 |
| **C-2** | §3.3 "Economic payoff in USD" derivation | `payoff_usd = settlement_btc × delivery_price = max(delivery_price − strike, 0)` for call. | The derivation conflates (a) the BTC-denominated settlement cash flow and (b) the USD-equivalent GROSS payoff. Algebraically correct as a coincidence when `delivery_price = S_T`, but the docstring does not state that this is the GROSS holder payoff (not the position P&L) and does not include the entry premium. A short-call writer's strategy P&L is `premium_received − gross_holder_payoff`, which is a fundamentally different number. | Replace the labelled "Economic payoff in USD" with "Gross settlement amount paid by the writer to the holder (USD-equivalent) — does NOT include entry premium; sign is positive for holder, negative for writer". Add the explicit identity: `strategy_payoff(strategy, S_T) = Σ quantity_i × entry_premium_i + Σ short_writer_quantity_i × (−settlement_holder_i) + long_holder_quantity_i × settlement_holder_i` for non-option legs, with economic payoff kept separate from venue settlement per AC-8. | AC-8; AGENTS.md §"Strategy classification and payoff integrity"; pillar 2 §3.5 |
| **C-3** | §3.4 CME table — "Settlement at expiry: Into 1 Bitcoin Futures at strike" | This conflates "futures delivery" with "cash settlement". The table row is correct but the section heading and the §5.1 `DeliveryPriceConvention.TWAP_0730_0800_UTC` named "TWAP" is also used for the CME weekly-option fix in §5.1 (`VWAP_0330_035959_LONDON`). | CME Ch. 350A options are auto-exercised into one CME Bitcoin Futures contract at the strike; that futures contract then settles to cash via BRR. The "settlement at expiry" of the option is therefore futures delivery, not cash. The current draft's `SettlementMechanism.FUTURES_DELIVERY_THEN_CASH` enum correctly captures this for CME but the §3.4 prose is ambiguous: "settle into 1 Bitcoin Futures at strike" can be read as physical (it is not). | In §3.4 add: "Option auto-exercises into a long (call) or short (put) CME Bitcoin Futures contract at the strike; that futures contract cash-settles to USD via the BRR/BRRNY/BVX fixing on the last trade date. There is no physical BTC delivery." Confirm in §5.2 the CME `option_on_futures` row is `futures_delivery_then_cash`. | CME Ch. 350A (`_text_cache/BTC_pending links/350A.txt`); AC-1 |
| **C-4** | §7.3 `price_inverse_btc` / `greeks_inverse_btc` signature with `forward: float` parameter | The functions take a `forward` parameter but the docstring says "re-derived from Deribit spec — NOT from reconciled audit §10.8". The Deribit inverse settlement uses `delivery_price` at expiry, NOT a forward curve. | Using a `forward` input silently assumes a risk-neutral pricing model that the draft never specifies. Without a defined model (e.g., `F = S · e^{(r−q)·T}`), `forward` is an undefined placeholder. This is exactly the kind of unspecified formula AC-4 prohibits. | Either: (a) state the explicit pricing formula in the docstring, with `forward` defined as `S · exp((r − q) · T)` and `q` as a new optional parameter, or (b) remove `forward` and derive internally from `S, r, q, T`. Cross-check the result against the Deribit spec example at line 22 (S_T=125k, K=100k, delivery=125k → 0.2 BTC holder settlement) at multiple intermediate times. | AC-4 (`authoritative_corrections.md` §2, §4); Deribit spec lines 1–199 |
| **C-5** | §19 D-5 marker | "Massive vs CryptoDataDownload as primary v1 historical source … **resolved by AC-5** — Massive primary, but brief not corrected". | D-5 is listed in the unresolved-decisions table, but the description itself admits AC-5 §5 already resolved it: **Massive is primary, CDD is fallback**. Listing a resolved decision as `TODO(decision_pending)` is an error of decision-tracking discipline; the only remaining work is a brief correction, not a decision. | Remove D-5 from the §19 table. Replace with a "Required brief correction" line item: "A2 brief (`agents/A2_data_vol.md` line 4) must be rewritten to make Massive the primary source per AC-5 §5 and `mandate_sanitized.md` §Data rules, with CDD as the explicitly-labelled fallback." Move it to §17.3 Required brief corrections. | AC-5 §5; `mandate_sanitized.md` §Data rules; reconciled audit §5 |
| **C-6** | §19 D-3 + §16.1 `primary_venue: str = "deribit"` | The `EngineConfig` defaults `primary_venue` to `"deribit"`, but the §19 table flags venue selection as `TODO(decision_pending: D-3)`. | Defaulting an unresolved decision in code is a resolution, not a marker. Once frozen, A2 will build Deribit-only ingestion paths and the CME/OTC venues become retrofit work. The build plan and pillar 4 both anticipate multi-venue design ("multi-venue" is one of the four D-3 options). | Make `primary_venue` an `Optional[str] = None` and add a `@field_validator` that raises `ConfigurationError` if `None` at the time A1/A2/A4 begin work. Move the default-only-for-development to a clearly-labelled `dev_default_venue` field. Carry D-3 in §19 as a true unresolved decision. | Build Plan §4; AC-1 |
| **C-7** | §11.1 `BacktestCycleResult` and §11.2 `MonteCarloResult` — no `hedge_cost_*` field anywhere | The CEO research mandate explicitly lists "rolling and hedge costs" and "delta or futures hedging where relevant" in the required analysis. The build plan §7 lists "delta hedging" as one of the three execution-rule parameters. The draft carries D-9 (hedge strategy) as unresolved but provides **no schema field** to capture the hedge cost line item. | Without a structured hedge-cost field, A3 backtests and A5 reports cannot distinguish "no hedge" (default), "static overlay" (zero hedge cost), or "active delta hedging" (non-zero cost line). The OOS and PBO results become uninterpretable because they conflate strategy returns with hedge P&L. | Add to `BacktestCycleResult`: `hedge_cost_usd: float`, `hedge_cost_btc: float`, `hedge_strategy: Literal["none", "static", "delta"]`. Add the same to `MonteCarloResult` (summed across paths). Add a test that `hedge_strategy="delta"` with zero hedge P&L movement flags `W-UNCALIBRATED-IMPACT` (already in §15.3) and a new `W-HEDGE-MODEL-UNSPECIFIED` warning if D-9 is unresolved at backtest time. | `ceo_strategy_research_mandate.md` §Required analysis; `mandate_sanitized.md` §Required analysis |

---

## 3. High-priority correction table

| # | Draft section | Issue | Required correction | Source of authority |
|---|---|---|---|---|
| **H-1** | §2.1 vs §9.1 — leg quantity convention | §2.1 says "Number of contracts (positive integer for long, negative for short; or unsigned with side)". §9.1 `Leg.quantity: float` is unsigned with `side: Literal["LONG", "SHORT"]`. The two clauses conflict. | Pick one convention. Adopt the unsigned-with-side convention from §9.1 (it matches the Pydantic BaseModel and is easier to serialise). Rewrite §2.1 to remove the "negative for short" branch. State explicitly: `quantity ≥ 0`; economic effect comes from `side`. | AC-1, internal consistency |
| **H-2** | §7.3 `payoff_inverse_call` / `payoff_inverse_put` docstrings | The function names say "payoff" but the bodies return the **settlement amount** to the holder. The names will mislead every downstream strategy-payoff implementation. | Rename to `settlement_inverse_call_holder` and `settlement_inverse_put_holder`. Update the §9.1 / §9.3 payoff computation to make the holder/writer sign explicit. | AC-8 |
| **H-3** | §6.5 missing historical options rule | "Premium is reconstructed from DVOL + spot using Black-Scholes/Black-76." | DVOL is a single index (annualised 30-day), not a term structure. The reconstruction is therefore ATM-only and ignores skew. Add: "Reconstruction is ATM at the relevant tenor using `dvol(T)` and `S`; skew is approximated flat; provenance = `MODEL_RECONSTRUCTED`; downstream ITM/touch probabilities and strike-specific payoffs must not be presented as observed." | AC-5 §5; pillar 2 §G-4 |
| **H-4** | §9.5 `breakeven(strategy) -> list[float]` | Returns a list of floats but does not specify (a) the unit (USD or BTC), (b) the convention for inverse-settled strategies, or (c) the convention for multi-leg strategies (covered call = 1 BE; collar = up to 2 BE; long-BTC+short-put = up to 2 BE per AGENTS.md line 64–65). | Add: returns all spot prices where strategy P&L crosses zero; unit is **USD** (the standard payoff numeraire) for USD-settled legs, with an additional per-leg `breakeven_btc: list[float]` for inverse-BTC legs; ordering is ascending; empty list if no crossing. Add tests for covered call (1 BE), collar (up to 2 BE), long-BTC+short-put (1 BE above K and conditional BE below K). | AGENTS.md §"Strategy classification and payoff integrity"; reconciled audit §16.4 |
| **H-5** | §9.4 `MtmPoint` — no discount-curve, rate, or numeraire fields | MTM of inverse options requires a BTC discount or forward; of linear options a USDC discount; of CME options a USD discount. A single `mtm_usd` / `mtm_btc` pair is insufficient. | Add: `rate_used: float`, `forward_used: float | None`, `discount_factor: float | None`, `numeraire: Literal["USD", "BTC", "USDC"]`. | AC-1; pillar 2 |
| **H-6** | §11.1 `BacktestResult.effective_acquisition_cost_per_btc: float` | The central output of the entire analysis, with **no formula, no unit field, no breakdown, no provenance**. | Replace with `effective_acquisition_cost: Pydantic BaseModel` containing `per_btc_usd: float`, `per_btc_btc: float`, `premium_component_usd: float`, `fee_component_usd: float`, `impact_component_usd: float`, `provenance: Provenance = Provenance.CALCULATED`, plus a docstring that defines the formula as: `effective_per_btc_usd = (notional_usd + total_fees_usd − total_premium_received_usd − seller_discount_usd + total_impact_cost_usd) / btc_quantity`, with each component itself a typed sub-object carrying its own provenance. | `ceo_strategy_research_mandate.md` §Required analysis; AC-1 |
| **H-7** | §12.2 `FeeBreakdown.fee_base: Literal["reference_notional", "executed_volume"]` with `TODO(decision_pending: D-1)` | A `Literal[...]` with two values is itself a partial resolution (it commits to the choice set). Marking it as decision_pending is inconsistent. | Make `fee_base: Literal["reference_notional", "executed_volume"] | None = None`. Add a validator that raises `ConfigurationError` if `None` at engine instantiation. Carry D-1 in §19 with status `decision_pending`. Same fix for `EngineConfig.fee_base` in §16.1. | AC-1, internal consistency |
| **H-8** | §13.1 golden vectors — no inverse-PUT vector; no inverse-BTC PRICER vector | The table has the inverse CALL settlement example (0.2 BTC) but is missing the symmetric PUT example and a pricing-model golden vector. The A1 brief says "≥10 new golden vectors from Haug tables"; the inverse side is half-done. | Add an inverse PUT vector: `S_T=80k, K=100k, delivery=80k → settlement_holder = max(100k−80k,0)/80k = 0.25 BTC`. Add a pricing-vector example from Deribit spec lines 16–56 with full inputs (S, K, r, σ, T) and expected outputs (price_usd, price_btc) for both call and put. Add a Black-76 put-side golden vector (mirror of the call vector at 1.7011 with parity check). | pillar 1 §4.6; AGENTS.md §Gotchas |
| **H-9** | §9.6 payoff boundary tests — "S ≫ K (materially above strike)" | The boundary is vague. "Materially above" is undefined; tests will not be comparable across strategies. | Replace with concrete points: for each strategy, the test set is `{0, K/2, K, S₀, 2·K}`. Cover-call test must additionally include `{S₀ + P}` where P is the premium received (the covered-call BE). Add these as `test_payoff_zero`, `test_payoff_half_strike`, `test_payoff_at_strike`, `test_payoff_at_entry_spot`, `test_payoff_double_strike`, `test_payoff_at_breakeven`. | AGENTS.md §"Strategy classification and payoff integrity" lines 64–65 |
| **H-10** | §14.3 reporting constraints — no schema for unresolved-decision visibility | "TODO(decision_pending: D-N) markers must render visibly in any table where unresolved decisions affect the number" — but no schema field is defined for this. | Add to every result BaseModel that depends on a parameter marked decision_pending: `pending_decision_refs: list[str] = Field(default_factory=list)` with values like `["D-1", "D-9"]`. The report renderer reads this field and emits a visible annotation. | AC-1; reconciled audit §5 |
| **H-11** | §16.1 `EngineConfig` — incomplete validation | Only `call_delta_target` and `risk_free_rate_pct` are validated. Many other fields lack sanity checks. | Add validators for: `seller_discount_pct + target_option_yield_pct + execution_fee_pct ≤ combined_target_discount_pct + ε`; `tranche_btc[1] ≤ btc_quantity`; `dte_target_days` overlaps `expiry_ladder_dte`; `strike_target_pct_above_spot` covers `call_delta_target` implied strikes; `iv_working_band_pct` reasonable range (10–200); `risk_free_rate_pct ≥ −5` and ≤ 50 (the current validator allows −1.0, but the mandate uses +4.0; document the range explicitly). | AC-4; pillar 2 |
| **H-12** | §12.3 `Tranche.execution_method: str` with example values `"block_rfq", "voice_broker", "otc", "screen"` | Free-form string for an enumerated choice set. | Replace with `execution_method: ExecutionMethod` Enum (`BLOCK_RFQ`, `VOICE_BROKER`, `OTC`, `SCREEN`, `RFQ_AUCTION`). | AC-1 |
| **H-13** | §12.1 `ImpactEstimate.provenance: Provenance = Provenance.ASSUMED` | The I-Star equations are textbook (Kissell §4, eq. 4.6–4.7); only the BTC-specific parameters are uncalibrated. Marking the entire estimate as ASSUMED is incorrect. | Split into component-level provenance: `i_star_bp_provenance`, `market_impact_bp_provenance`, `iv_giveup_vol_pts_provenance: Provenance.ASSUMED`. Aggregate provenance at the top level is a derived field, not a primary one. | AC-5; pillar 3 §6.2 |
| **H-14** | §11.4 `OOSValidationResult.cscv_n: int` with no default and no validator enforcing N ≥ 100 | The Bailey et al. constraint (N ≥ 100) is only in the docstring; an implementation can omit it. | Add `cscv_n: int = Field(ge=100)`; add a `cscv_s: int = Field(ge=8, le=64, default=16)` validator. Add a test `test_oos_cscv_n_minimum` that asserts N ≥ 100 at engine instantiation. | Pillar 2 §4.2; Bailey et al. (2015) §4 |

---

## 4. Medium / low corrections

| # | Draft section | Issue | Required correction |
|---|---|---|---|
| **M-1** | §2.2 `StrategyKind.COVERED_PUT` | "WARNING: COVERED_PUT requires short underlying + short put" inline comment. | Move the warning to the docstring of the enum member; do not mix inline warnings into an enum literal. |
| **M-2** | §3.5 timestamps | "stored as ISO-8601 strings" — pydantic `datetime` stores datetime objects; ISO-8601 is the serialisation form. | Reword: "Pydantic `datetime` fields, timezone-aware UTC; serialised to ISO-8601 with `Z` suffix when written to JSON/Parquet." |
| **M-3** | §4.2 source models | CME origin mixed with Deribit; no separate CME data API endpoint enumeration. | Add `cme_public_api` as a separate origin with the documented public endpoints (`get_product_info`, `get_trades`, `get_settlement`); keep `pillar_4_venue_standards/cme/` script under `cme`. |
| **M-4** | §5.2 OTC row | `contract_multiplier: float` with value "Negotiated". A string in a float field is a type error. | Change `contract_multiplier: float | None = None` and document "OTC contract size is set per-trade; no default". |
| **M-5** | §6.3 `HistoricalOptionBar.mark_iv: float | None` | No provenance for the mark IV itself. | Add `mark_iv_provenance: Provenance` (OBSERVED for Deribit book_summary history; MODEL_RECONSTRUCTED for CDD/VWAP-derived). |
| **M-6** | §6.4 fixture recording | "Parquet format with a SHA-256 manifest" — not specified per fixture. | Specify the manifest schema (path, sha256, retrieval date, venue, endpoint) and tie it to a `Manifest` BaseModel. |
| **M-7** | §7.2 `SettlementOptionQuote.premium_quoted: float` | Unclear unit. | Document: "In the option's quoted currency per the contract spec: BTC for Deribit inverse, USDC for Deribit linear, USD for CME, BTC or USD for OTC". |
| **M-8** | §8.1 `VolSurface` | No fit-method field, no fit-residual field, no SVI vs spline flag. | Add `method: Literal["spline", "svi", "ssvi", "raw"]` and `fit_rmse: float | None`. |
| **M-9** | §8.3 `ForwardCurve` | No interpolation method. | Add `interpolation: Literal["flat", "linear", "log_linear", "cubic"]`. |
| **M-10** | §9.2 `Strategy` | `notes: str | None` for decision-pending items. | Replace with structured `pending_decisions: list[DecisionRef]` carrying `{code: str, owner: str, impact: str}` (see H-10). |
| **M-11** | §11.2 `MonteCarloResult.pnl_distribution: list[float]` | No unit, no path index, no provenance per path. | Add `pnl_unit: Literal["USD", "BTC"]` and `path_provenance: Provenance = Provenance.SIMULATED`. |
| **M-12** | §11.3 `StressScenarioResult.path: list[float]` | For an instantaneous shock `path = None`; for a replay `path` is a list. Type ambiguity. | Split: `path: list[float] | None` is OK if `description` mentions "instantaneous" or "replay"; add a `shock_type: Literal["instantaneous", "replay", "regime_shift"]` enum to make it explicit. |
| **M-13** | §12.1 `estimate_impact` signature | Eight parameters in positional order. | Wrap parameters in a `KissellConfig` Pydantic model with the same fields; pass the config object. The pure pricing function signature remains parameter-driven per AC-4. |
| **M-14** | §13.5 QuantLib parity | `1e-6` tolerance on random draws is correct for BS but tight for Black-76 with extreme vol/T. | Loosen to `1e-4` for Black-76 only, document the choice in the test docstring. |
| **M-15** | §15.1 `EngineError` hierarchy | No `SettlementError`, no `VenueConfigurationError`. | Add `class SettlementError(EngineError)` for unsupported `SettlementMechanism × Venue` combinations (e.g., PHYSICAL_UNDERLYING on Deribit). |
| **M-16** | §17.2 dependency graph | A2 depends on network and on the A2 venue-rulebook ingestion side task from Build Plan §7. The graph does not show this. | Add a note: "A2 also depends on Deribit API network access from the Hetzner box and on the A2 venue-rulebook ingestion side task from Build Plan §7." |
| **M-17** | §19 D-9 | `owner: Mandate issuer` — fine, but the table does not state the consequence for backtest design. | Add "Consequence: A3 cannot compute delta-hedge P&L until D-9 is resolved; A3 must run two scenarios (no-hedge, static) by default and emit a W-HEDGE-MODEL-UNSPECIFIED warning". |
| **M-18** | §18 P0-7 | "Branch strategy documented; AGENTS.md updated ('Three commits on main')". | Make explicit: this is a TODO at the AGENTS.md layer, not a contracts layer change. Note that AGENTS.md currently still says "single commit" — flagged so the freeze gate catches it. |
| **M-19** | §13.6 `test_waterfall_fee_base_sensitivity` | Depends on D-1. | Parametrise: `pytest.mark.parametrize("fee_base", ["reference_notional", "executed_volume"])` and tag with `pytest.mark.xfail(reason="D-1 unresolved")` until D-1 is closed. |
| **M-20** | §14.2 `generate_demo_pack() -> None` | Returns None; no exit code. | Have it return an integer exit code (`0` success, `1` failure) and raise on any chart-generation error. |
| **M-21** | §6.1 `BookSummary.interest_rate: float` | "decimal" with no unit. | Confirm: "decimal, continuous compounding" (consistent with §3.1). |
| **M-22** | §3.3 Trading fee formula | "MIN(0.0003 BTC, 0.125 × OptionPrice) × Amount" — correct but `Amount` is not defined. | Document: `Amount` = number of contracts; quote is per-contract BTC premium. |
| **M-23** | §3.4 CME "5 Index point minimum tick ($25)" | Correct but conflates index points with USD. | Document: 1 index point = $5 for the underlying 5-BTC contract. |
| **M-24** | §1.3 binding constraints | Missing the bullet on the CEO mandate's "Hypotheses" list being testable claims. Listed in prose but not as a binding constraint bullet. | Add a bullet: "The CEO mandate §Hypotheses list is **parameterised** in `config/params.yaml` as default ranges; the engine must report when these ranges fail the implied premium/yield targets before any 'optimal structure' is presented." |
| **M-25** | §9.2 `Strategy.canonical` | Derived from legs but no classifier function signature. | Add `def classify(legs: list[Leg]) -> StrategyKind: ...` to the interfaces section. |

---

## 5. Missing CEO requirements

The CEO research mandate (`ceo_strategy_research_mandate.md`) and the sanitised mandate (`mandate_sanitized.md`) both enumerate required analyses. The following are inadequately covered by the draft:

| # | CEO requirement | Mandate source | Draft gap |
|---|---|---|---|
| **MR-1** | Missed-upside risk as an explicit metric | mandate §"Required quantitative analysis" | Not present as a field. The covered-call max profit cap (K − S₀ + P) implicitly captures missed upside above K, but no schema or invariant enforces its computation. |
| **MR-2** | Downside exposure as an explicit metric | mandate §"Required quantitative analysis" | Covered indirectly via payoff at S_T = 0, but no `max_drawdown_pct` separate from `BacktestResult.max_drawdown_pct` (which is the *realised* max drawdown, not the structural max loss). Add `structural_max_loss: float` to `Strategy` and `BacktestResult`. |
| **MR-3** | Bid/ask spread as an explicit cost line | mandate §"Required quantitative analysis"; build plan §"Required analyses" | `BookSummary.bid_price` and `ask_price` are stored, but `FeeBreakdown` does not have a `bid_ask_cost_btc` field. The cycle simulator and cycle report cannot show the bid/ask cost. |
| **MR-4** | Hedge costs as an explicit line item | mandate §"Required quantitative analysis" (`rolling and hedge costs`); D-9 | Not present in any result schema. See C-7. |
| **MR-5** | Out-of-sample validation as a required output | mandate §"Required quantitative analysis" | Covered via §11.4 `OOSValidationResult` — but no invariant requires OOS to be run before backtest results are presented. Add to the §13 test list `test_oos_runs_by_default`. |
| **MR-6** | Regime analysis as a required output | mandate §"Required quantitative analysis" | Covered via §11.5 `RegimeAnalysisResult`, but no regime taxonomy is specified. Add `RegimeTaxonomy` Enum with at minimum `{bull, bear, high_vol, low_vol, sideways}` and a `regime_classifier: Callable[[datetime, pd.Series], RegimeLabel]` interface. |
| **MR-7** | "Delta as direct assignment-probability estimate" treated as testable, not approved | mandate §"Hypotheses" | **Critical**: the mandate lists this as one of eight hypotheses to test; the draft §1.3 lists seven (omits the delta-as-assignment-probability hypothesis). The draft also does not require A3 to emit a metric comparing delta at entry to realised assignment frequency per cycle. Add `delta_vs_assignment_frequency: list[float]` to `BacktestResult` and a `test_delta_assignment_hypothesis` to §13. |
| **MR-8** | "Covered call as safest or optimal structure" treated as testable, not approved | mandate §"Hypotheses" | §1.3 includes "covered call being the safest or optimal structure" implicitly via the binding-constraints prose, but the §15.3 warning catalogue does not flag any "covered-call-is-best" claim as a hypothesis violation. Add `W-COVERED-CALL-OPTIMALITY-CLAIM` at ERROR level when a downstream report uses the words "optimal", "best", "safest" attached to any structure. |
| **MR-9** | "Strong-BTC-breakout stand-down" as a configurable parameter | mandate §"Hypotheses" | Carried as `stand_down_on_breakout: bool | None` in `EngineConfig`, but no schema defines what "breakout" means (e.g., 20-day high, DVOL-spike, realised-vol spike). Add `breakout_definition: BreakoutRule` with explicit inputs. |
| **MR-10** | "Selling only when IV is elevated" as a configurable parameter | mandate §"Hypotheses" | Carried as `sell_when_dvol_above: float | None` in §16.1, but `iv_working_band_pct` already constrains the working band. The relationship between the two parameters is not documented. Add a docstring or validator that distinguishes the "working band" (always run) from the "elevated-IV trigger" (conditional overlay). |
| **MR-11** | Configuration of the "10–15 delta, 30–45 DTE, 15–20% OTM" hypotheses as ranges | mandate §"Hypotheses" | `params.yaml` has these as `call_delta_target: [10, 15]`, `dte_target_days: [30, 45]`, `strike_target_pct_above_spot: [15, 20]`. The draft does not require A3 to compare the backtest outcome **against the implied premium/yield at the upper edge** of the range vs the lower edge — i.e., to verify that the range is internally consistent. The existing test `test_target_yield_requires_higher_delta_or_iv` shows 3%/cycle requires ~30–35Δ at IV 45%, contradicting the 10–15Δ working assumption; the draft should make this contradiction explicit in the §13 test description. |
| **MR-12** | Separation of observed vs simulated vs calculated vs assumed | mandate §"Required quantitative analysis" (`Clearly distinguish observed market data, calculated values, simulated values and business assumptions`) | Provenance enum covers the categories but the **rendering layer** (§14) does not enforce that every reported number carries a visible provenance annotation in the final output. Add a §13 test `test_report_every_number_has_provenance_annotation`. |

---

## 6. Incorrectly resolved business decisions

| # | Draft section | Apparent resolution | Why it is incorrectly resolved |
|---|---|---|---|
| **IDR-1** | §16.1 `fee_base: str = Field(default="reference_notional")  # TODO(decision_pending: D-1)` | Defaulted to `reference_notional` while flagged as unresolved. | Defaulting in code is a resolution. The downstream `FeeBreakdown` (§12.2) also defaults. Once Phase 1 implementation begins, switching fee base requires code change, not config. See C-style fix in H-7. |
| **IDR-2** | §16.1 `primary_venue: str = "deribit"` | Defaulted to `deribit` while flagged as unresolved (D-3). | Same pattern: defaulting in code is a resolution. A2 will build Deribit-only ingestion paths. Multi-venue architecture (the build plan intent) becomes retrofit work. |
| **IDR-3** | §16.1 `reference_spot_source: str = "config"` | Defaulted to `config` while flagged as unresolved (D-2). | The waterfall module already accepts the spot from `config/params.yaml`. "config" is therefore an implicit default that has been baked into the live waterfall without the D-2 owner explicitly deciding. |
| **IDR-4** | §19 D-5 | Marked as `decision_pending` but the description admits it is resolved by AC-5. | Decision-tracking discipline error. See C-5. |
| **IDR-5** | §19 D-7 | "Put-sleeve scope for first client presentation" — owner Mandate issuer / Francisco. | The mandate §"Presentation timing" states "Do not prepare the final client presentation or video yet. First … 4. independently verify the conclusions." D-7 implies the presentation is being prepared; the draft is therefore inconsistent with the mandate's explicit ordering. Add an explicit cross-reference to mandate §Presentation timing in the D-7 row. |
| **IDR-6** | §13.1 inverse-call golden vector | Asserts settlement = 0.2 BTC for S_T=125k, K=100k, delivery=125k. | This is the HOLDER settlement, not a strategy P&L. The test name is `settlement=0.2 BTC` (clear), but the §13.1 row label "Inverse call: S_T=125k, K=100k, delivery=125k → settlement=0.2 BTC" risks being lifted into a strategy-P&L assertion by downstream code. Add a column "Interpretation: gross settlement to long holder per 1 BTC contract; sign for writer = negative." |
| **IDR-7** | §12.2 `block_trade_fee_btc: float` cited at "Deribit: 0.03% (line 3717)" | Cites a specific Deribit fee line. | The line 3717 reference is plausible (Deribit Fee Schedule is at lines 3705–3759 per pillar 4) but the draft does not include the block-RFQ-fee distinction (block_rfq vs voice_broker vs standard block trade). All three are different fee schedules on Deribit. Add `block_trade_fee_source: Literal["standard_block", "block_rfq", "voice_broker"]`. |

---

## 7. Section-by-section acceptance table

| Section | Title | Status | Reason |
|---|---|---|---|
| §1 | Scope and authority hierarchy | **Accept** | Correctly inherits the AC mandate, identifies the freeze gate, lists all eight structures, correctly notes the override rule. |
| §1.3 | Binding constraints | **Accept with additions** | Add a bullet on the CEO hypotheses being testable (see M-24). |
| §2.1 | Leg terminology | **Conditional accept** | Resolve the unsigned-vs-signed quantity contradiction (H-1). |
| §2.2 | Canonical strategy classification | **Accept** | Enum is correct, COVERED_PUT warning is correct. Move inline warning to docstring (M-1). |
| §2.3 | Dual-preservation rule | **Accept** | |
| §3.1 | Base conventions | **Accept** | Vega/theta conventions match `pricing/black_scholes.py`. |
| §3.2 | Sign convention | **Accept** | |
| §3.3 | Deribit inverse settlement | **Conditional accept — C-1, C-2** | Formulas correct but sign convention and holder/writer distinction missing. |
| §3.4 | CME Bitcoin options on futures | **Conditional accept — C-3** | Prose ambiguity on futures-delivery vs cash-settle. |
| §3.5 | Timestamps | **Accept with M-2 rewording** | |
| §4.1 | Provenance enum | **Accept** | Covers all six provenance categories. |
| §4.2 | Source models | **Accept with M-3** | |
| §4.3 | Provenance on every datum | **Accept** | |
| §5.1 | Settlement decomposition | **Accept** | Implements AC-1 correctly with separate fields. |
| §5.2 | Venue/product combinations | **Accept with M-4** | OTC contract multiplier type fix. |
| §5.3 | Separation principle | **Accept** | Implements AC-8. |
| §6.1 | Live market data | **Accept** | |
| §6.2 | Historical spot data | **Accept** | |
| §6.3 | Historical option data | **Accept with M-5** | |
| §6.4 | Fixture recording | **Accept with M-6** | |
| §6.5 | Missing historical options rule | **Conditional accept — H-3** | DVOL-only ATM reconstruction is too narrow. |
| §7.1 | Existing preserved interface | **Accept** | OptionQuote preserved verbatim. |
| §7.2 | Settlement-aware quote extension | **Accept** | Wraps OptionQuote without modifying it; satisfies AC-3. |
| §7.3 | Pure function signatures | **Conditional accept — C-4, H-8** | `forward` parameter undefined; missing put-side golden vectors. |
| §7.4 | Compatibility rules | **Accept** | |
| §7.5 | QuantLib parity | **Accept with M-14** | Tolerance for Black-76 may need loosening. |
| §8.1 | Volatility surface | **Accept with M-8** | |
| §8.2 | Discount curve | **Accept** | |
| §8.3 | Forward curve | **Accept with M-9** | |
| §9.1 | Position leg | **Conditional accept — H-1** | |
| §9.2 | Strategy | **Accept with M-10, M-25** | |
| §9.3 | Payoff | **Conditional accept — C-2** | Gross settlement vs strategy P&L must be disambiguated. |
| §9.4 | Mark-to-market | **Conditional accept — H-5** | Needs rate/forward/numeraire fields. |
| §9.5 | Breakeven | **Conditional accept — H-4** | Unit and multi-leg rules missing. |
| §9.6 | Validation invariant — payoff at 5 boundary points | **Conditional accept — H-9** | Concrete test points needed. |
| §10.1 | Rolling | **Accept** | |
| §10.2 | Early close | **Accept** | |
| §10.3 | Exercise and settlement | **Accept** | |
| §11.1 | Backtest result | **Conditional accept — C-7, H-6, H-10** | No hedge-cost field; no provenance-tagged effective-cost breakdown. |
| §11.2 | Monte Carlo result | **Conditional accept — H-10, M-11** | |
| §11.3 | Stress test result | **Conditional accept — M-12** | |
| §11.4 | OOS validation result | **Conditional accept — H-14** | Add CSCV N ≥ 100 validator. |
| §11.5 | Regime analysis result | **Conditional accept — MR-6** | No regime taxonomy. |
| §12.1 | Market impact model | **Conditional accept — H-13, M-13** | |
| §12.2 | Fee model | **Conditional accept — H-7, IDR-7** | |
| §12.3 | Tranche scheduler | **Conditional accept — H-12** | Execution method as Enum. |
| §12.4 | Waterfall sensitivity mode | **Accept with M-19** | |
| §13.1 | Golden-vector tests | **Conditional accept — H-8** | Missing inverse PUT and inverse-BTC pricing vectors. |
| §13.2 | Strategy payoff tests | **Conditional accept — H-9** | |
| §13.3 | Classification integrity tests | **Accept** | |
| §13.4 | Provenance integrity tests | **Accept** | |
| §13.5 | QuantLib parity | **Accept with M-14** | |
| §13.6 | Waterfall tests | **Accept with M-19** | |
| §13.7 | Configuration tests | **Accept** | |
| §14.1 | Reporting principle | **Accept** | |
| §14.2 | Chart pack interface | **Accept with M-20** | |
| §14.3 | Report output constraints | **Conditional accept — H-10, MR-12** | Schema-level enforcement of pending-decision visibility and provenance annotation needed. |
| §15.1 | Error hierarchy | **Accept with M-15** | |
| §15.2 | Severity levels | **Accept** | |
| §15.3 | Warning catalogue | **Conditional accept — MR-8** | Add W-COVERED-CALL-OPTIMALITY-CLAIM. |
| §16.1 | Pydantic wrapper for params.yaml | **Conditional accept — H-11, C-6, IDR-1, IDR-2, IDR-3** | Validator coverage thin; defaults for unresolved decisions. |
| §16.2 | Validation at config boundary | **Accept** | |
| §17.1 | Ownership matrix | **Accept** | |
| §17.2 | Dependency graph | **Accept with M-16** | |
| §17.3 | Required brief corrections | **Conditional accept** | A2 brief correction listed but D-5 marker left in §19 (see C-5). A3 brief enrichment mentions transaction costs but the A3 brief at `agents/A3_scenarios.md` line 4 does not include them — the draft needs to extend the brief itself. |
| §18 | Phase-0 acceptance criteria | **Conditional accept — M-18** | |
| §19 | Unresolved human decisions | **Conditional accept — C-5, M-17** | |
| §20 | Source traceability matrix | **Accept** | |

---

## 8. Exact mandatory changes before freezing

The draft cannot freeze until the following **bound set** of changes is applied. Each is bounded and does not require a redesign.

1. **Add sign-convention and holder/writer disambiguation language to §3.3** (C-1, C-2). Two paragraphs of prose plus renaming the §7.3 functions from `payoff_inverse_*` to `settlement_inverse_*_holder`. No new schema.
2. **Clarify CME §3.4 prose** (C-3). Three sentences.
3. **Define `forward` in §7.3 inverse-BTC pricer** (C-4). Either state `F = S · exp((r − q) · T)` in the docstring and add `q` as an optional parameter, or remove `forward` and derive internally. Four lines.
4. **Move D-5 out of §19 and into §17.3** (C-5). One row relocation plus a brief correction directive to A2 (`agents/A2_data_vol.md` line 4). The decision is already resolved; the marker is wrong.
5. **Make `primary_venue` truly pending** (C-6, IDR-2). Change the `EngineConfig` field type to `Optional[str] = None` with a `ConfigurationError` validator. Two lines.
6. **Add hedge-cost line item to `BacktestCycleResult` and `MonteCarloResult`** (C-7, MR-4). Three new fields plus a `W-HEDGE-MODEL-UNSPECIFIED` warning code.
7. **Resolve leg-quantity convention** (H-1). Pick unsigned-with-side. Update §2.1 and §9.1 to be consistent. Five lines.
8. **Rename §7.3 inverse functions to remove "payoff"** (H-2). Two function renames plus docstring updates.
9. **Tighten §6.5 reconstruction rule** (H-3). Two sentences added to the docstring.
10. **Specify `breakeven` units and multi-leg behaviour** (H-4). Docstring update plus 2-3 test cases.
11. **Add discount-curve, rate, numeraire fields to `MtmPoint`** (H-5). Three fields.
12. **Decompose `effective_acquisition_cost_per_btc`** (H-6). Replace single float with a typed sub-model carrying provenance.
13. **Make `fee_base` truly pending** (H-7, IDR-1). `Literal | None = None` with validator.
14. **Add inverse-PUT and Black-76 put golden vectors + inverse-BTC pricing golden vector** (H-8). Three rows to §13.1.
15. **Specify exact payoff boundary points** (H-9). `{0, K/2, K, S₀, 2·K}` plus BE for covered call.
16. **Add `pending_decision_refs` field to result schemas** (H-10). One field per result model.
17. **Expand `EngineConfig` validators** (H-11). Five validators.
18. **Convert `execution_method` to Enum** (H-12). Enum definition.
19. **Split `ImpactEstimate` provenance to component level** (H-13). Five sub-fields.
20. **Validate CSCV N ≥ 100 in `OOSValidationResult`** (H-14). One field validator.
21. **Add missing-schema additions for CEO requirements MR-1 through MR-12** (§5 above). Twelve field additions across the result and config schemas.
22. **Add `W-COVERED-CALL-OPTIMALITY-CLAIM` to §15.3 warning catalogue** (MR-8). One row.
23. **Define `RegimeTaxonomy` Enum and `RegimeClassifier` interface** (MR-6). One Enum + one function signature.
24. **Add the `breakout_definition` and `iv_working_band_vs_elevated_IV_trigger` documentation** (MR-9, MR-10). Two docstring updates.

None of the above changes the scope of the engine or the architecture. They are additive corrections and clarifications.

---

## 9. Required regression and invariant tests

Beyond what the draft already lists in §13, the following tests must exist before freeze:

| Test | Purpose | Source of authority |
|---|---|---|
| `test_inverse_call_holder_settlement` | Assert `settlement_inverse_call_holder(125000, 100000) == 0.2` exactly | Deribit spec lines 16–56; pillar 1 §4.6 |
| `test_inverse_put_holder_settlement` | Assert `settlement_inverse_put_holder(80000, 100000) == 0.25` exactly | Deribit spec lines 16–56 |
| `test_inverse_call_writer_sign` | Assert writer cash flow = `−0.2 BTC × contracts × spot_value` | C-1 |
| `test_strategy_pnl_separated_from_settlement` | Long-BTC+short-put: at S_T=0, P&L = `−(S₀ + K − P)`; settlement to holder (long put leg absent here) only the short put's settlement cost applies | C-2, reconciled audit §10 |
| `test_payoff_at_breakeven_covered_call` | At S_T = S₀ + P, covered-call P&L = 0 | AGENTS.md §"Strategy classification and payoff integrity" |
| `test_payoff_at_double_strike_*` (one per strategy) | Slope and P&L at S_T = 2·K | H-9 |
| `test_breakeven_returns_usd_for_usd_settled` | For USD-settled strategies, breakeven list contains USD values | H-4 |
| `test_breakeven_returns_btc_for_inverse_settled` | For inverse-BTC strategies, additional `breakeven_btc` field is populated | H-4 |
| `test_long_btc_plus_short_put_classification` | Long BTC + short put → `LONG_BTC_PLUS_SHORT_PUT`, NOT `COVERED_PUT` | AGENTS.md line 61 |
| `test_label_mismatch_emits_warning` | When `business_label="Covered Put"` and canonical is `LONG_BTC_PLUS_SHORT_PUT`, W-CLASSIFY-MISMATCH is raised | §2.3, §15.3 |
| `test_provenance_on_every_settlement_result` | `SettlementResult` must carry `provenance: Provenance` | AC-5, H-10 |
| `test_effective_acquisition_cost_breakdown` | Sum of premium_component + fee_component + impact_component = `effective_per_btc_usd` | H-6 |
| `test_hedge_cost_field_present` | All `BacktestCycleResult` and `MonteCarloResult` carry `hedge_cost_*` fields | C-7, MR-4 |
| `test_oos_cscv_n_minimum` | `cscv_n ≥ 100` enforced | H-14 |
| `test_engine_config_rejects_unresolved_primary_venue` | `EngineConfig(primary_venue=None)` raises `ConfigurationError` | C-6 |
| `test_engine_config_rejects_unresolved_fee_base` | `EngineConfig(fee_base=None)` raises `ConfigurationError` | H-7 |
| `test_impact_estimate_provenance_per_component` | `iv_giveup_vol_pts_provenance == ASSUMED`, `i_star_bp_provenance == ASSUMED` | H-13 |
| `test_no_observed_label_on_simulated` | Provenance integrity | §13.4 |
| `test_no_observed_label_on_model_reconstructed` | Provenance integrity | §13.4 |
| `test_quantlib_bs_parity` | Hypothesis, 50 random draws, max abs diff < 1e-6 | §13.5 |
| `test_quantlib_black76_parity` | Hypothesis, 50 random draws, max abs diff < 1e-4 (loosened) | M-14 |
| `test_covered_call_not_marked_optimal` | When a downstream report includes the string "optimal" attached to a structure, `W-COVERED-CALL-OPTIMALITY-CLAIM` is raised | MR-8 |
| `test_delta_vs_assignment_frequency_reported` | `BacktestResult` carries a per-cycle `delta_vs_realised_assignment` field whose mean and std are surfaced | MR-7 |
| `test_breakout_definition_required` | `BreakoutRule` schema validated when `stand_down_on_breakout=True` | MR-9 |
| `test_oos_runs_by_default` | Engine instantiation requires OOS validation path to be configured | MR-5 |
| `test_existing_optionquote_unchanged` | `OptionQuote` still has exactly `(price, delta, gamma, vega, theta, strike)` | AC-3, AC-6 |
| `test_pure_functions_no_yaml_read` | `pricing/black_scholes.py` functions do not import or read `config/params.yaml` | AC-4 |

---

## 10. Final verdict

**READY AFTER REQUIRED CORRECTIONS**

The draft is the most thorough attempt to date at a Deribit-first contracts document for the engine. It correctly inherits the binding constraints from `authoritative_corrections.md`, preserves the existing tested `OptionQuote` dataclass by extension (not migration), implements the AC-1 settlement-field separation, and carries the unresolved human decisions as explicit markers (with two exceptions noted in C-5 and C-6). It does not prejudge any strategy and does not prepare client-facing material.

It is, however, not ready to freeze in its current form. Seven CRITICAL issues (mathematical sign ambiguity, default-resolution of unresolved decisions, missing hedge-cost schema, missing inverse-PUT golden vector, incorrect `forward` semantics on the inverse-BTC pricer, unresolved CME prose ambiguity, decision-tracking error on D-5) must be fixed; fourteen HIGH-priority additions and twelve CEO-requirement gaps must be closed; and approximately twenty-five MEDIUM/LOW corrections should be applied for consistency.

The corrections are bounded: they are prose clarifications, field additions, validator additions, function renames, and test additions. None requires a redesign, none alters the scope, and none weakens the binding constraints. After the changes in §8 above are applied and the tests in §9 are added, the draft will be suitable for freeze and will provide a defensible interface contract for the six parallel agents.

**Final verdict:** **READY AFTER REQUIRED CORRECTIONS**.
