# Frontier Source Conflicts (Stage 0)

Checkpoint: `92acecf`. Companion to `frontier_reference_coverage_audit.md`.
190 raw conflict records were collected across the 23 audit passes; after
deduplication they resolve into the conflict classes below. Each entry states
the two sides, the resolution under the authority hierarchy
(`authoritative_corrections.md` → `contracts.md` → mandates → official venue
docs → textbooks → audits → generated reports), and financial materiality.

Legend: **[M]** = financially material.

---

## C-1. Authoritative sources vs implementation (resolution: source wins; repair the code)

| # | Conflict | Resolution |
|---|---|---|
| C-1.1 **[M]** | `contracts.md:823-824` EAC formula (notional + fees − premium − discount + impact; no settlement term) vs `strategy/backtest.py:591-597` (adds −total_payout, folds impact into fees, mixed denominators) | Contract wins; single ledger-derived EAC (FRF-014) |
| C-1.2 **[M]** | `contracts.md §10.3` SettlementResult (0.015% delivery fee capped 12.5%, provenance) vs `strategy/backtest.py:435` (0.00015 × settlement BTC, no cap, no model) and absence of SettlementResult anywhere | Contract + venue doc win (FRF-004/013/025) |
| C-1.3 **[M]** | AC `§1` "physical BTC delivery only when the contract explicitly requires it" + `definitions.py` OTC legs cash-settled vs `strategy/backtest.py:458-459` crediting physical-style BTC inventory on cash-settled ITM short puts | AC wins (FRF-004) |
| C-1.4 **[M]** | `contracts.md §6.5` premium reconstruction "from DVOL + spot", MODEL_RECONSTRUCTED vs `research/runner.py:339` flat config vol 0.45 driving all premiums | Contract wins; DVOL pipeline required (FRF-008) |
| C-1.5 **[M]** | `ceo_strategy_research_mandate.md` "0.5% execution fee modelled separately" vs backtest/EAC containing no Asymmetrica fee (dead `FeeBreakdown`) | Mandate wins (FRF-013) |
| C-1.6 **[M]** | `contracts.md §11.4` Bailey CSCV (C(S,S/2), rank logit, DSR) vs `strategy/regimes.py:194-304` (random s//2 shuffles, ratio-of-means clamped logit, invented DSR) | Contract + paper win (FRF-010) |
| C-1.7 **[M]** | `contracts.md §11.5` per-regime `BacktestResult` vs `strategy/regimes.py:131,181` single terminal payoff at segment end | Contract wins (FRF-011) |
| C-1.8 **[M]** | `contracts.md §14.3/§15.3` provenance annotation on every number + warning catalogue vs `research/reporting.py` (no provenance column, zero W-* emissions repo-wide) | Contract wins (FRF-017) |
| C-1.9 **[M]** | `contracts.md §11.3` max_adverse_excursion = worst intra-scenario drawdown vs `strategy/stress.py:119,141` abs(final P&L)/abs favourable excursions | Contract wins (FRF-006) |
| C-1.10 **[M]** | `contracts.md §3.1` decimal conventions + `params.yaml` percent units (2.5) vs `research_nightly.yaml` decimals (0.025) under identical `*_pct` key names, both consumed in one run | Contract wins; single validated schema (FRF-020) |
| C-1.11 **[M]** | `config/research_nightly.yaml` impact.adv_btc=25000 / spread_bps / iv_giveup echoed into `resolved_config.yaml` vs `strategy/backtest.py:294,400` hardcoded ADV heuristic and spread; `execution/impact.py:128` hardcoded iv_giveup=1.0 | Config keys must be consumed or rejected (FRF-020/013) |
| C-1.12 **[M]** | `contracts.md §6.2/6.3` provenance/origin explicit, no defaults vs `engine/data_models.py:126-147` defaulting provenance=OBSERVED and origins | Contract wins (FRF-017) |
| C-1.13 **[M]** | `config/models.py` Provenance semantics (CDD is OBSERVED vendor data; SIMULATED for synthetic) vs `research/runner.py:376-380` (CDD fallback → MODEL_RECONSTRUCTED) and `strategy/scenarios.py:27` (synthetic bridges → MODEL_RECONSTRUCTED) | Taxonomy wins (FRF-017/027) |
| C-1.14 **[M]** | `FRONTIER_ORCHESTRATION.md §8` (large MC forbidden pre-gate) vs `results/research/empirical-robustness-20260729T005618Z` (36 runs, 0.5M–3M paths, 2026-07-29) | Orchestration wins; runs demoted to diagnostic-at-best (FRF-022) |
| C-1.15 **[M]** | `contracts.md §13.3` W-CLASSIFY-MISMATCH must be raised vs `tests/test_phase0.py:453` asserting `classification_warning is None` on a mismatch; engine never emits the warning | Contract wins (FRF-019/023) |
| C-1.16 | `contracts.md:584` VolSurface methods incl. svi/ssvi vs `vol/surface.py:105` silently coercing to "raw" | Contract wins or amend contract (FRF-024) |
| C-1.17 **[M]** | `contracts.md §13.5` hypothesis 50-draw QuantLib parity vs fixed 10/8-case lists with skipif | Contract wins (FRF-023) |
| C-1.18 **[M]** | `contracts.md §12.4`/`§16` execution-sensitivity outputs vs `research/runner.py:514-521,631-635` config echo | Contract wins (FRF-012) |

## C-2. Internal contradictions inside authoritative documents (resolution: versioned contracts amendment)

| # | Conflict | Resolution |
|---|---|---|
| C-2.1 **[M]** | `contracts.md §9.1` Leg premium "PAID (positive) or RECEIVED (negative)" vs `contracts.md §3.2` SHORT formula `(−settlement + entry_premium)` which requires positive-received; `strategy/payoffs.py:97-106` follows §3.2, `engine/strategy.py:55-61` documents §9.1 | Amend to one convention; property test both entry paths (FRF-018) |
| C-2.2 **[M]** | `contracts.md §7.3` inverse-pricer sketch (`exp(−rT)·E[…]`, garbled `N(d1')·Φ(d1')`) vs AC §4 (full numeraire specification required) — the freeze candidate itself embeds the under-specification AC forbids; the implemented e^{−rT} discount is numerically wrong (deep-ITM 0.9967 vs 1.0) | AC wins; re-derive and amend §7.3 (FRF-015) |
| C-2.3 | `contracts.md §3.4` "BRR/BRRNY/BVX fixing" vs CME 350A text (BRR only; BRRNY belongs to BRRNY-settled products, BVX to volatility futures); `DeliveryPriceConvention` lacks BRRNY | Amend §3.4 to venue text; add BRRNY only with primary source (FRF-037) |
| C-2.4 | `contracts.md §5.2` sources Deribit linear mechanism to fee-schedule lines 3606-3805 | Re-cite to the actual linear-options spec section (FRF-037) |
| C-2.5 | `contracts.md §13.1` "Hull/Haug" 10.4506/5.5735 and delta 0.6368 citations; put-call parity "Hull §15.8" | Values verified correct; citations amended (computed standard vectors; parity Hull §11.4) (FRF-037) |
| C-2.6 | `contracts.md §11.4` "N ≥ 100 per Bailey" vs paper's "N ≫ 10" | Keep threshold as explicit business_requirement; fix attribution (FRF-037) |
| C-2.7 | `contracts.md §17.3` ordered A2-brief line-4 rewrite (Massive primary) — never applied to `agents/A2_data_vol.md` | Apply the ordered correction (Stage 2 docs task) |
| C-2.8 | Contracts M-13 "eight parameters" vs §12.1 KissellConfig nine fields | Editorial amendment |

## C-3. Generated results vs their own data (resolution: results are invalid evidence; retraction list in Stage 1)

| # | Conflict |
|---|---|
| C-3.1 **[M]** | `strategy_comparison.csv` unhedged −56.198% vs the same run's `_spot_data_dump.csv` observed window return −4.61% (synthetic baseline beside observed strategies) |
| C-3.2 **[M]** | `backtest_results.parquet` summed cycle P&L vs the same parquet's ledger equity (cash_usd_end + btc_inventory_end×S_end): +$389.6M gap per long-BTC strategy; four headline sign flips; DSV-17 identity gap $11.45B vs $225.6M |
| C-3.3 **[M]** | `stress_results.parquet` collar flash-crash +$462,986,132 vs settlement floor −$291.0M (double-count, sign flip) |
| C-3.4 **[M]** | `final_empirical_research_synthesis_deepseek.md`: "BTC declined 56%" vs observed −4.61%; CSP strike simultaneously ~$74,750 / "15% OTM" / "85% of spot"; premium +67.46%/notional (~2.8%/cycle) vs its own ~1.07-1.1%/cycle statement; CSP "strictly positive in all stress" vs its own listed −$1,633M flash-crash; drawdown 1.776 vs "177.6%" units; bear-regime −81.1% BTC beside +$699M unhedged P&L; non-existent regime rows |
| C-3.5 **[M]** | `data_manifest.json` requested_start 2023-01-01 vs actual_start 2024-07-29 (run accepted, marked completed); OOS train window mostly outside delivered data |
| C-3.6 | `.latest_research_baseline` (git-tracked) → FAILED run with VALIDATION_GATE errors; `.latest_research_intensive` → empty aborted dir, while the completed 003308Z runs exist unpointed; export bundle ships the empty intensive dir |
| C-3.7 | `data_manifest.json` "observed" provenance beside a SIMULATED synthetic baseline inside the same run outputs |
| C-3.8 | Run manifests record `output_dir`/`config_path`/`cache_path` from a non-canonical checkout (matches DSV-20 validation caveat) |
| C-3.9 | `run_status.json` "completed" for nightly-20260728T222057Z with no data_manifest and missing parquets; placeholder rows written to satisfy existence gates |
| C-3.10 | `independent_validation_deepseek_console.log` 11.57% vs CSV 11.26% covered-call total (two aggregation conventions) |

## C-4. Audit-vs-audit and audit-vs-AC (resolution: AC/venue docs win; findings reclassified)

| # | Conflict | Resolution |
|---|---|---|
| C-4.1 | MiniMax initial models inverse short-put assignment as **physical BTC delivery**; recommends combined settlement enum {physical_usd, cash_usd, inverse_btc}; mixes /S₀ and /S_T denominators | Rejected — AC §1/§4 + Deribit spec (cash-settled BTC, lines 191/203) (FRF-032) |
| C-4.2 | Reconciled audit §10.8 inverse formulas; PHYSICAL_USD enum; Pydantic OptionQuote migration | Superseded by AC §§1,3,4 (FRF-031) |
| C-4.3 | DeepSeek initial "married put written from the long side" vs reconciled C-DS-2 (phrase forbidden) | Reconciled correction stands |
| C-4.4 | DeepSeek initial internally inconsistent fee-base swing ($9.75M vs $240k); D-1 figure also differs across pillar-2/contracts ($243,750) vs MiniMax gap audit ($240k) | Contracts figure ($243,750 on the 2.5%-discount executed base) is the computed one; carry as the D-1 reference |
| C-4.5 | DeepSeek initial "persistent positive skew" as fact vs reconciled C-DS-4 (observed data or explicit assumption) | Reconciled correction stands |
| C-4.6 | Pillar 4 claims CME BTC options are American-style vs CME 350A (European, auto-exercise) | Venue doc wins; pillar claim rejected |
| C-4.7 | MiniMax initial frames hard-coded pricing literals as "wire params into pricing" vs AC §2 (pricing stays pure; config layer injects) | AC wins; remediation direction corrected |
| C-4.8 | MiniMax initial internal sign inconsistency on LBSP max loss ("K_put − P₀ − S₀" vs "loss = S₀ − K + premium") | Both wrong/inconsistent; authoritative identity S₀+K−P governs (FRONTIER_ORCHESTRATION §5.1) |
| C-4.9 | Fable findings JSON LBSP max-loss $122,000 (placeholder P=1500) vs Fable audit §7 $122,779 (model-fair P=721) | Same identity, different premium input; identity confirmed; premium input must be labelled |

## C-5. Process/governance conflicts

| # | Conflict | Resolution |
|---|---|---|
| C-5.1 **[M]** | Build plan §2 "no single model's arithmetic ships" + phase2 NOT-READY verdict vs A3 merged with self-certified fix report; no-look-ahead mutation assertions deleted after detecting genuine look-ahead | Process repair precondition for Stage 2 (FRF-036) |
| C-5.2 | `AGENTS.md` "params.yaml is the single source of truth" vs three config surfaces (raw params.yaml, unusable validated loader, research_nightly.yaml) | FRF-020 |
| C-5.3 | `mandate_sanitized.md §Confidentiality` vs one recorded external-model prompt containing firm-identifying information (details withheld here deliberately) | FRF-038; owner decision on the artefact |

## C-6. Reference-library internal conflicts

| # | Conflict | Resolution |
|---|---|---|
| C-6.1 | Cached CME 350A (created 2023-05-19) vs sibling chapters (2026-06-03) | Refresh before CME work (needs_primary_source) |
| C-6.2 | "ISDA Digital-Asset-Derivatives-Definitions.pdf" is a law-firm memo | needs_primary_source |
| C-6.3 | SR 11-7 (2011) unmarked beside SR 26-2 (2026) | mark superseded |
| C-6.4 | One pillar-4 `openapi.json` is a Mintlify "Plant Store" sample beside genuine Deribit specs | annotate; cite only `deribit_openapi.json` |
| C-6.5 | Fable-bundle superseded A1 brief still contains the forbidden USD/index inverse approximation | annotate superseded; never reuse |

---

## Resolution rule applied

Where any generated report (authority 9) conflicts with observed run data, the
run data wins as evidence and the report claim is listed for retraction
(Stage 1). Where any audit (authority 8) conflicts with AC/contracts/venue
docs (authority 1/2/6), the audit finding is classified superseded or rejected
in `frontier_consensus_findings.json` and must not silently re-enter the
implementation. No conflict in this file was resolved by choosing a
financially material interpretation silently; the three that require the
mandate issuer are carried as D-1 (fee base), D-11 (data procurement) and
D-12 (CSP acquisition scope) in the Stage-1 deliverables.
