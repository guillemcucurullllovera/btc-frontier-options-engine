# Frontier Reviewer Consensus Matrix (Stage 1)

Checkpoint: `92acecf`. Companion to `frontier_consensus_findings.json` (the
machine-readable form, one object per FRF-id with full evidence, repair
requirement, acceptance test, dependencies, blocking status and per-finding
verification block).

This matrix reconciles the independent reviews — Fable full-context, DeepSeek
(initial/reconciled/validation/fix reports), MiniMax (initial/validation),
the phase-0/1/2 reports and reviews, the pillar studies, and the principal
auditor's own first-hand inspection — against the actual code, tests,
contracts, authoritative corrections and primary sources.

**No finding was accepted merely because reviewers repeated it.** Each was
re-tested against the implementation. 21 findings were independently
re-verified by adversarial skeptic agents that re-opened every cited file:line
at `92acecf` and attempted refutation; the remaining findings were verified
first-hand by the principal auditor by direct file:line inspection during
Stage 0 (the adversarial cluster covering them aborted on an account spend
limit and was not re-run, per instruction). Two findings (FRF-037, FRF-038)
rest partly or wholly on reviewer extraction and are flagged accordingly.

## 1. Classification vocabulary (as applied)

| Class | Count | Meaning |
|---|---|---|
| accepted | 23 | Finding stands as written after independent verification |
| accepted_with_correction | 12 | Finding stands; a specific claim (line number, sign, magnitude, scope) was corrected during verification |
| superseded | 1 | Higher-authority source already overrides it (FRF-031) |
| rejected | 1 | Contradicted by higher-authority source (FRF-032) |
| unresolved_pending_business_decision | 1 | Requires the mandate issuer (FRF-035) |
| duplicate | 0 | (folded into their primary FRF-id during consolidation) |
| unresolved_pending_source | 0 as a standalone class | (carried inside accepted findings whose repair needs a primary source — see the `residual` field and `frontier_missing_sources.md`) |

Verification-verdict distribution (independent, where present): 11 CONFIRMED,
10 CONFIRMED_WITH_CORRECTIONS, 0 REFUTED, across the 21 agent-verified
findings.

## 2. Consensus matrix

Reviewer codes: Fable = Fable full-context+aux; DS = DeepSeek initial/reconciled;
DS-val = DeepSeek validation; DS-fix = DeepSeek fix reports; MM = MiniMax initial;
MM-val = MiniMax validation; Phase = phase-0/1/2 reports; Pillar = pillar studies;
Auditor = principal auditor first-hand. Verify: agent = independent adversarial
re-verification; first-hand = principal auditor direct file:line; reviewer* =
rests partly/wholly on reviewer extraction (see the finding's verification block).

| ID | Sev | Originating reviewers | Class | Verify | Title |
|---|---|---|---|---|---|
| FRF-001 | critical | Fable+DS-val+DS-fix+Auditor | accepted+corr | agent | Strikes/legs frozen at construction; no per-cycle reselection |
| FRF-002 | critical | Fable+DS-val+MM-val+Auditor | accepted | agent | Synthetic-GBM baseline vs observed-data strategies in one table |
| FRF-003 | critical | Fable+Auditor | accepted+corr | agent | Lifecycle calendar: dropped day, index-DTE, truncated-cycle premium, per-leg expiry ignored |
| FRF-004 | critical | Fable+DS-val+Auditor | accepted | first-hand | Settlement/inventory double-count; ledger does not reconcile |
| FRF-005 | critical | Fable+Auditor | accepted | agent | MC/stress/regime consume static ~2.4× builder premiums |
| FRF-006 | critical | Fable+Auditor | accepted | agent | Stress double-counts the shock (payoff + full MTM); sign flips |
| FRF-007 | critical | Fable+DS-val+Auditor | accepted | first-hand | Drawdown/Sharpe/touch computationally invalid |
| FRF-008 | critical | Fable+DS+Auditor | accepted | agent | Vol layer unwired; constant 45% IV; no DVOL ingestion |
| FRF-009 | critical | Fable+MM-val+DS-fix+Auditor | accepted | agent | 2023 window silently truncated to 2024-07-29; no coverage gate |
| FRF-010 | high | Fable+DS-val+Phase+Auditor | accepted | agent | OOS/CSCV/PBO/DSR pseudo-implementation; null in all runs |
| FRF-011 | high | Fable+DS-val+Auditor | accepted | agent | Regime = static payoff at window-end; avg_dvol mislabelled |
| FRF-012 | high | Fable+DS-val+Auditor | accepted | agent | Execution-sensitivity output is a config echo |
| FRF-013 | high | Fable+Auditor | accepted+corr | agent | Fee model wrong/incomplete; 0.5% absent; venue fees mis-applied |
| FRF-014 | high | Fable+DS-val+MM-val+DS-fix+Auditor | accepted | first-hand | EAC: three definitions; per-BTC where zero BTC acquired |
| FRF-015 | high | Fable+Auditor | accepted | agent | Inverse pricer spurious e^{−rT} discount |
| FRF-016 | medium | Fable+Auditor | accepted | agent | Black-76 put theta sign error |
| FRF-017 | high | Fable+DS-val+Auditor | accepted+corr | agent | Provenance/reporting controls violated; false "Deribit (observed)" |
| FRF-018 | high | Fable+Auditor | accepted | first-hand | Frozen-interface premium sign contradiction (engine vs payoffs) |
| FRF-019 | medium | Fable+Auditor | accepted | first-hand | classify() defects (unreachable overlay, spread bug, no BESPOKE) |
| FRF-020 | high | Fable+Auditor | accepted | first-hand | Config fragmentation; validated EngineConfig unused; unit clash |
| FRF-021 | high | Fable+DS-val+DS-fix+Auditor | accepted+corr | agent | MC single-expiry, last-model-wins, CSP capital, unlabeled drift |
| FRF-022 | critical | Fable+DS-val+DS-fix+Auditor | accepted+corr | agent | Existing results unusable; synthesis fabricated claims; pointers broken |
| FRF-023 | high | Fable+Auditor | accepted | first-hand | Tests enforce interfaces not economics; 17 skipped required stubs |
| FRF-024 | medium | Fable+Auditor | accepted | agent | Surface guesses strikes; in-sample GARCH; 252 vs 365; dead Ljung-Box |
| FRF-025 | medium | Pillar+Auditor | accepted | first-hand | SettlementResult absent; multiplier ignored; TWAP vs close; OTC-only |
| FRF-026 | medium | Fable+MM+Auditor | accepted | first-hand | Loss quantities absent/inconsistent; structural_max_loss default 0.0 |
| FRF-027 | medium | Fable+Auditor | accepted+corr | agent | "Replay" stress = synthetic bridges; no settlement-basis shock |
| FRF-028 | medium | Fable+Auditor | accepted+corr | agent | OOS folds leak (train cycles settle into test); config divergence |
| FRF-029 | medium | Auditor | accepted | first-hand | Hygiene: now()-fallback timestamps, NaN→0 grid, assert validators, checksum-of-mutating-log |
| FRF-030 | medium | Fable+DS-val+Auditor | accepted | first-hand | premium_received_pct divides by leg count; numeraire mix |
| FRF-031 | high | DS+MM | **superseded** | first-hand | Reconciled §10.8 inverse formulas / PHYSICAL_USD enum (AC overrides) |
| FRF-032 | medium | MM | **rejected** | first-hand | MiniMax physical-delivery inverse model (AC + venue doc override) |
| FRF-033 | high | Fable+MM+Auditor | accepted+corr | agent | Covered-call-optimality / 3%@10-15Δ hypotheses; no enforcement control |
| FRF-034 | low | Fable+Auditor | accepted+corr | agent | Verified-correct components to preserve (regression guard) |
| FRF-035 | high | Fable+DS+MM+Auditor | **pending-decision** | first-hand | Business decisions D-1..D-9 + new D-10/D-11/D-12 |
| FRF-036 | critical | Fable+Phase+Auditor | accepted | first-hand | Governance: weakened no-look-ahead test; merge vs NOT-READY verdict |
| FRF-037 | high | Auditor | accepted+corr | reviewer* | Library/citation integrity; mis-cited goldens; non-primary sources |
| FRF-038 | high | (internal-materials audit) | accepted+corr | reviewer* | Confidentiality: one recorded prompt carries firm-identifying info |

## 3. Independent reconciliation notes (why not just "reviewers agreed")

- **Confirmed by re-execution of the run's own artefacts, not by opinion:**
  FRF-002 (−56.2% synthetic vs −4.61% observed recomputed from the run's
  `_spot_data_dump.csv`), FRF-003 (23 dropped transitions summing to
  −12,985 USD/BTC ≈ $389.6M reproduced to the cent from that same csv),
  FRF-001 (`nunique(strike)=1` across 24 cycles; premium $11.34B vs $1.95–2.00B
  notional), FRF-005 (VaR95 gap exactly 1,500×30,000 = $45.0M).
- **Corrections applied during verification** (hence `accepted_with_correction`):
  FRF-001 dead-parameter line is 274–275 not 274,282; FRF-003 the dropped-day
  bias is path-dependent and in the surviving window *overstates* long-BTC P&L
  (not "understates"); FRF-013 the delivery-fee branch only fires for
  BTC-settled legs (latent for the current OTC-USD strategies — the OTC-hitting
  bug is the trading-fee unit error at `backtest.py:402`); FRF-017 the
  `W-CLASSIFY-MISMATCH` string *is* assigned to a field but never consumed;
  FRF-021 only backtest-derived aggregate columns are bit-identical across the
  36 robustness runs (MC tail metrics do vary by seed); FRF-022 the pre-gate MC
  runs *predate* the commit that introduced the §8 gate, so the breach is
  retroactive — the operative claim is that they are ungated and unusable.
- **Superseded/rejected against higher authority, not deferred to reviewer
  count:** FRF-031 (reconciled §10.8 inverse formulas, PHYSICAL_USD enum) is
  superseded by `authoritative_corrections.md` §§1,3,4; FRF-032 (MiniMax's
  physical-delivery inverse model and combined settlement enum) is rejected
  against AC §1 and the verified Deribit spec (cash-settled in BTC, lines
  191/203). Both remain retained as evidence; neither may re-enter the code.
- **DeepSeek fix reports and the DeepSeek synthesis were treated as evidence,
  never as truth:** their self-certified "all blocking resolved" claims are
  contradicted by the still-present roll dead-code, pseudo-CSCV, stress
  double-count and unreconciled ledger (FRF-036). The synthesis's own internal
  contradictions are catalogued in `frontier_source_conflicts.md` §C-3.4.
- **Single-source / not-first-hand:** FRF-038 rests solely on the
  internal-materials audit pass and was deliberately not re-opened to avoid
  reproducing the flagged content; it is routed to the owner for confidential
  review and must be treated as reported, not independently confirmed. FRF-037's
  Deribit line-citations and contracts golden vectors were re-verified
  first-hand; its ISDA-memo / md5-duplicate / EPUB-placeholder / empty-directory
  sub-claims were not each re-opened.

## 4. Duplicate consolidation

The 679 raw reviewer findings were consolidated into 38 FRF-ids. Notable
many-to-one folds (each independently verified against the code, not merely
counted):

- FRF-001 ← Fable F-01, DS-val DSV-09, DS-fix intrinsic-domination, res-lineage strike-nunique.
- FRF-002 ← Fable F-02, DSV-01/02/03, MMV-01..07.
- FRF-004 ← Fable F-14, DSV-17 (ledger identity), DSV-18 (negative cash).
- FRF-010 ← Fable F-08, DSV-06, phase-2 CSCV reviews, pillar-2 C-1/C-3, lib_papers Bailey deviation.
- FRF-013 ← Fable F-10/F-11, plus the venue-fee unit and delivery-fee-base sub-findings.
- FRF-017 ← Fable F-25, DSV-05, plus the four provenance-category mislabels.
- FRF-022 ← Fable F-29/F-32/F-38/F-42, DSV-15/20/21, DS-fix placeholder-rows/exit-0.

## 5. Cross-reference to candidate repair branches (evidence, not integration)

The independent MiniMax pre-merge review of the three candidate branches
(`sprint/core-repair` @ f75e148, `sprint/data-repair` @ 8743811,
`sprint/execution-repair` @ fda2a1b) maps onto this matrix as follows and is
recorded for the fresh integration session (see
`frontier_stage01_resume_handoff.md`; **not integrated during Stage 1**):

| Branch | Findings it (partially) addresses | Pre-merge verdict |
|---|---|---|
| f75e148 | FRF-015 (inverse e^{−rT}→e^{−qT}), FRF-016 (Black-76 put theta); stronger payoff tests toward FRF-023 | conditionally merge-ready — needs the FRF-037/C-2.2 versioned contract amendment + independent inverse tests |
| 8743811 | FRF-002 (baseline routing) partially; adds a coverage gate toward FRF-009 | reject-as-is — leaves FRF-017, FRF-014, FRF-013, FRF-010/028, FRF-012 open; introduces provenance-by-shape and baseline-only fee asymmetry |
| fda2a1b | FRF-013 arithmetic partially; I-Star sensitivity | reject-as-is — changes frozen schemas, defaults D-1 (violates FRF-035), hard-codes spot/discount, does not persist sensitivity (FRF-012) |

A2 (8743811) and A4 (fda2a1b) have a **material semantic overlap in fee
accounting and execution-sensitivity persistence**: merged together they still
produce the config-echo `execution_sensitivity.parquet` (FRF-012 unfixed) and
two inconsistent fee treatments. This is a Stage-2 integration constraint, not a
new finding.
