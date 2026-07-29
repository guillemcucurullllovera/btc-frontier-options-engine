# Frontier Stage 0/1 Resume Handoff

Checkpoint: `92acecf` (branch `main`). Produced at the close of Stage 1.
Audience: the next fresh Opus integration session (Stage 2).

## 1. Where this left off

Stage 0 and Stage 1 are **complete**. Nine deliverables exist and are
internally consistent. No production code was modified; nothing was committed.

Stage 0 (reference application audit):
- `docs/reports/frontier_reference_coverage_audit.md`
- `docs/reports/frontier_reference_application_matrix.tsv` (440 rows, 14 columns)
- `docs/reports/frontier_source_conflicts.md`
- `docs/reports/frontier_missing_sources.md`
- `docs/reports/frontier_source_to_code_traceability.md`

Stage 1 (consensus + repair spec):
- `docs/reports/frontier_consensus_matrix.md`
- `docs/reports/frontier_consensus_findings.json` (38 findings, parses)
- `docs/reports/frontier_repair_specification.md` (dependency-ordered WP-A1…WP-C10)
- `docs/reports/frontier_acceptance_tests.md` (AT-001…AT-033 with DET/HR/MC flags)
- `docs/reports/frontier_stage01_resume_handoff.md` (this file)

**Stage 2 is NOT started.** Do not begin implementation from this session.

## 2. Work already done — DO NOT REPEAT

- **The 23-agent Stage-0 evidence fan-out is complete.** Raw agent digests are
  under the session scratchpad (`stage0/*.json`); merged evidence is in
  `merged_matrix.tsv`, `merged_conflicts.txt`, `merged_missing.txt`,
  `merged_review_findings.json`. 679 raw reviewer findings were consolidated into
  38 FRF-ids. Do not re-run this sweep.
- **Adversarial verification is complete for 21 findings** (workflow
  `wf_5b802c24`, 7 clusters). Verdicts: 11 CONFIRMED, 10
  CONFIRMED_WITH_CORRECTIONS, 0 REFUTED. Four clusters aborted on an account
  spend limit; those findings (FRF-004, 007, 014, 018, 019, 020, 023, 025, 026,
  029, 030, 031, 032, 035, 036, plus reviewer-only 037/038) were instead
  verified **first-hand by direct file:line inspection** and are marked as such
  in each finding's `verification` block. **Do not re-launch the failed
  verification clusters** — the findings are already substantiated.
- Every production module was read line-by-line this session; the coverage
  audit and traceability doc reflect first-hand reads, not filename inference.

## 3. Candidate repair branches (record only — DO NOT INTEGRATE in Stage 1)

Three isolated candidate-repair branches were prepared off `92acecf` and an
independent MiniMax pre-merge review exists. They are recorded here for the
fresh Stage-2 integration session and were **not** integrated during Stage 1.

| Branch | Tip | Owner area | Pre-merge verdict |
|---|---|---|---|
| `sprint/core-repair` | `f75e148` | A1 deterministic pricing core | **Conditionally merge-ready** |
| `sprint/data-repair` | `8743811` | A2 data / provenance | **Must NOT merge as-is** — useful portions require correction |
| `sprint/execution-repair` | `fda2a1b` | A4 execution | **Must NOT merge as-is** — useful portions require correction |

Independent pre-merge review (read it before integrating):
`/home/francisco/btc/premerge_review/minimax_premerge_review.md` (348 lines).

### 3.1 Conclusions to preserve (from the pre-merge review, corroborated here)

- **`f75e148` is conditionally merge-ready.** It correctly implements the two
  A1 pricing fixes this audit accepted: the inverse-BTC discount
  `exp(−rT)→exp(−qT)` (FRF-015) and the Black-76 put-theta sign (FRF-016), and
  strengthens several payoff tests (toward FRF-023). Merge **only** after:
  (a) the **versioned `contracts.md` correction** to the contradictory
  inverse-pricing text §7.3/§13.1 (WP-A2 / FRF-037 / conflict C-2.2) — do not
  resolve the code/contract divergence by reverting the pricing fix; (b)
  **stronger independent inverse-price tests** (calls AND puts over a parameter
  grid; deep-ITM limits; invalid-input rejection — AT-015); (c) correcting the
  candidate report's overstated payoff-completeness claims.
- **`8743811` must not merge as-is.** It routes the unhedged baseline to
  observed spot (partial FRF-002) and adds a coverage gate (partial FRF-009),
  but leaves material defects: provenance mixing / provenance-by-shape,
  static/misleading attribution (FRF-017), a too-weak baseline test (50-pt
  tolerance vs the required 1e-9 — AT-002), leaky OOS slicing (FRF-028),
  internally inconsistent fee/EAC accounting (FRF-013/014), a coverage gate that
  passes silently on missing metadata, and an additive `DataManifest`
  persistence-schema change with no version/migration. Its candidate report's
  mypy claim was found factually wrong in the review environment.
- **`fda2a1b` must not merge as-is.** It adds useful component arithmetic and
  monotonicity tests, but **changes frozen public Pydantic schemas**
  (`FeeBreakdown.fee_base`, `Tranche`/`TrancheSchedule`, `WaterfallSensitivity`)
  without migration, **invents two unsupported fee-base alternatives**,
  **silently defaults the unresolved D-1** (violates FRF-035), hard-codes spot
  `65000`/discount `0.975`/venue/liquidity assumptions, does not honour the
  requested tranche count, uses `datetime.now()` (non-deterministic), and does
  **not** persist the sensitivity output (FRF-012 unfixed).
- **A2 and A4 have a semantic overlap in fee accounting and execution
  sensitivity.** Merged together they still emit the config-echo
  `execution_sensitivity.parquet` (FRF-012 unfixed) and two inconsistent fee
  treatments. The Stage-2 integration must produce **one fee ledger, fee counted
  exactly once per strategy, no silent D-1 default**, and **one** place that
  persists numeric execution sensitivity.
- **The inverse-pricing correction requires an explicit versioned contract
  correction and stronger independent tests** before it is trusted (WP-A2 +
  AT-015). The venue source establishes settlement, not the full pre-expiry mark
  formula; the no-arbitrage identity `price_BTC × S = Black-76 USD` (q=0) is the
  verification anchor and must be tested independently for calls and puts.

### 3.2 Recommended Stage-2 integration order (from the review, aligned to the repair spec)

1. Land the Phase-A preconditions first: WP-A1 (restore the no-look-ahead
   assertions), WP-A2 (versioned inverse-pricing + citation contract amendment),
   WP-A3 (confidentiality disclosure + scan hardening).
2. Integrate the two A1 formula fixes from `f75e148` with the contract amendment
   and stronger independent tests (WP-B4 / AT-015 / AT-016).
3. Unify fee semantics before combining any A2/A4 portions (WP-B7): two D-1
   variants only, no silent default, one component ledger.
4. Fix structured provenance end-to-end (WP-C3): spot/IV/premium/simulation/
   fallback stay separate; reporting consumes the manifest, not static strings.
5. Make OOS lifecycle-safe (WP-C4): complete-cycle fold containment; do not
   claim CSCV/PBO repaired until the real method exists.
6. Repair A4 schemas/scheduler (WP-B13 + execution WPs): remove hard-codes,
   enforce requested quantity/count, deterministic UTC schedule start,
   provenance on costs.
7. Wire and persist numeric execution sensitivity once (WP-C6), then test row
   counts and tranche reconciliation through the runner.
8. Only then re-run focused tests → full `pytest/mypy/ruff/anonymisation/diff-check`.

## 4. Accepted blocking findings (critical/high that gate Stage 2)

Critical/high findings with `blocking.stage2=true`: **FRF-001, FRF-002,
FRF-003, FRF-004, FRF-005, FRF-006, FRF-007, FRF-013, FRF-014, FRF-015,
FRF-018, FRF-020, FRF-023, FRF-036** (14). Additional criticals that block
historical research / large MC rather than deterministic sign-off: FRF-008,
FRF-009, FRF-022. Full per-finding blocking flags are in
`frontier_consensus_findings.json` and the acceptance-test blocking summary.

## 5. Unresolved business decisions (mandate issuer)

Carried from contracts §19 plus three newly registered:

- **D-1** fee base (reference vs executed notional) — $243,750 swing; engine
  emits both variants until resolved.
- **D-2** reference spot source; **D-3** primary venue (determines which
  settlement/fee model is "real"); **D-4/D-7** put-sleeve scope; **D-8** DVOL
  triggers; **D-9** hedge model.
- **D-10 (new)** maximum acceptable-loss budget — absent from every
  authoritative source.
- **D-11 (new)** historical data procurement (paid Massive tier / vendor archive)
  vs re-scoping the window to 2024-07…2026-07.
- **D-12 (new)** whether a cash-settled outcome (esp. CSP) counts as
  "acquisition" via a discretionary post-settlement BTC purchase.

## 6. Missing primary sources (must precede the dependent work)

Blocking subset (full list in `frontier_missing_sources.md`): MS-1 official
historical DVOL series; MS-2 pre-2024-07 BTC spot history; MS-9/MS-10 inverse
pricing verification anchor (worked example + documented no-arbitrage identity);
MS-6 actual ISDA Digital Asset Derivatives Definitions; MS-4/MS-5 CF Benchmarks
BRR/BRRNY methodology and current CME Ch. 350A. Approvals still needed: MS-25
objective function, MS-26 simulation methodology, MS-27 third-round independent
review of any "final fix".

## 7. Residual uncertainty

- FRF-038 (confidentiality) is single-source and was deliberately not re-opened
  to avoid reproducing the flagged content — treat as reported until the owner
  confirms.
- FRF-037's non-Deribit sub-claims (ISDA memo, md5 duplicates, EPUB
  placeholders, empty directories) rest on the library audit agents; the Deribit
  line-citations and contracts golden vectors were re-verified first-hand.
- Medium/low findings not covered by an independent agent verdict (FRF-025,
  FRF-026, FRF-029) are first-hand-confirmed but were not adversarially
  re-refuted; they are sound but carry lower independent-verification weight than
  the agent-verified set.
- The pre-merge review's own test runs (green focused tests on the branches) do
  not override the economic/contract defects; do not treat branch test-greenness
  as sufficiency.

## 8. Is the fresh Opus integration session ready to begin?

**Yes — Stage 2 is ready to begin**, subject to these gates being honoured:
Stage 0 and Stage 1 are complete and internally consistent; the repair spec is
dependency-ordered; the acceptance tests are implementation-ready with explicit
DET/HR/MC blocking. Start with Phase A (WP-A1/A2/A3), then the deterministic
foundation. Do not merge `8743811` or `fda2a1b` as-is; extract only corrected,
source-backed portions. Do not run historical research or large Monte Carlo
until their acceptance-test sets pass (and MS-26 for MC). Do not present any
strategy as best/optimal until an objective function (MS-25) is approved.
