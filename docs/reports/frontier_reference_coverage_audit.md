# Frontier Reference Coverage Audit (Stage 0)

Checkpoint: `92acecf` — chore: establish frontier audit orchestration
Produced: 2026-07-29, frontier Stage-0 reference application audit
Method: 23 parallel read-only audit passes (8 implementation modules, 9 external-review
corpora, 5 reference-library groups, 1 results/lineage group) plus a first-hand
line-by-line verification of every production module by the principal auditor.
No production file was modified. No research or Monte Carlo run was executed;
only small read-only numeric reproductions of specific pricing claims.

Companion Stage-0 artefacts:

- `frontier_reference_application_matrix.tsv` (440 source→requirement→code→test rows)
- `frontier_source_conflicts.md`
- `frontier_missing_sources.md`
- `frontier_source_to_code_traceability.md`

Authority hierarchy applied throughout: `authoritative_corrections.md` →
`contracts.md` → CEO mandate → sanitised mandate → build plan → official venue
documentation → textbooks/research → independent audits → generated reports.

---

## 1. Scope actually inspected

| Group | Inspected | Notes |
|---|---|---|
| Production source | all of `pricing/`, `engine/`, `strategy/`, `vol/`, `execution/`, `config/`, `research/`, `scripts/` (~10k lines) | line-by-line |
| Tests | all 6 test modules + fixtures | assertion-level coverage map vs contracts §13 |
| Requirements | all files under `docs/requirements/`, `contracts.md`, `AGENTS.md`, orchestration files | full |
| Official venue docs | `deribitfilesascopiedtxt.txt` (622 KB), `_text_cache/BTC_pending links/350A.txt`, `docs.deribit.com_llms.txt`, `pillar_4_venue_standards/deribit/api/` specs | cited lines verified against text |
| Textbooks/papers | `Textbooks/`, `books/`, `_text_cache/`, `papers/`, pillar directories | presence + cited-value verification |
| `BTC_pending links` | all ~129 numbered PDFs identified by content | content-identified, not filename-inferred |
| External reviews | Fable full-context (6 files), DeepSeek initial + reconciled + 4 fix reports + validation JSON/MD/console, MiniMax initial + validation consoles (incl. partial), phase0/1/2 reports + 5 independent reviews, 5 pillar studies + MiniMax gap audit, contracts review chain | every distinct finding extracted (679 total) |
| Results/lineage | all `results/research/*` run dirs, `.latest_research_*` pointers, `exports/fable_cross_validation_*`, `logs/` | manifests, parquets and pointers inspected |

## 2. Headline coverage verdict

**The authoritative requirement set (AC, contracts, mandates) is well specified
and internally consistent at the level of settlement decomposition, strategy
classification, payoff identities, provenance taxonomy and pending-decision
handling. The implementation conforms at the interface level but diverges from
the governing sources at the economic-accounting level in ways that invalidate
every existing research result.** The reference library contains the load-bearing
official sources (Deribit inverse spec, CME Ch. 350A) and they verify, but the
citation apparatus in `contracts.md` contains errors, several claimed primary
sources are not primary, and several required sources are absent.

### 2.1 What verifies cleanly (keep, do not regress)

- `authoritative_corrections.md` §1 settlement decomposition ↔ `engine/settlement.py`
  enums: exact conformance.
- Long-BTC-plus-short-put economic identity (slopes +1/+2, P&L at zero
  −(S₀+K−P), max loss S₀+K−P, breakevens): exactly implemented in
  `strategy/payoffs.py:207-231` and genuinely tested (`tests/test_a3.py:158-208`).
  The mislabelled "Covered Put" source diagram is handled correctly
  (`strategy/definitions.py:209-217` forces `LONG_BTC_PLUS_SHORT_PUT`).
- `pricing/black_scholes.py`: Hull-consistent formulas; golden values 10.4506 /
  5.5735 / delta 0.6368 reproduce numerically (citation labels are wrong — see
  conflicts §C-7 — but the numbers are correct).
- Deribit citations behind contracts §3.3 verified against
  `deribitfilesascopiedtxt.txt`: 0.2 BTC worked example (line ~22), index
  underlying (85), BTC quote/margin/settlement (115/121/203), 1 BTC multiplier
  (135), TWAP 07:30–08:00 delivery (187), European cash auto-exercise (191),
  trading fee `MIN(0.0003 BTC, 0.125×OptionPrice)×Amount` (3572-3574), delivery
  fee 0.015% capped 12.5% (3755).
- CME Ch. 350A: 5-BTC multiplier, European auto-exercise into futures, BRR
  settlement verified (located partly in Ch. 5/350 companions; see conflicts).
- `vol/history.py` Massive spot provider: typed bars, OBSERVED provenance,
  retry/backoff, dedup, monotonicity checks (pagination gap noted below).
- `execution/waterfall.py` mandate arithmetic; `config/models.py` EngineConfig
  validator structure per contracts §16.1 with D-1/D-2/D-3 truly `None`.

### 2.2 Where implementation diverges from governing sources (fatal for results)

Full detail and independent verification live in the Stage-1 deliverables
(`frontier_consensus_findings.json`, FRF-001…FRF-038). The divergences that
gate everything else:

1. **Strikes/legs frozen at construction** — no per-cycle reselection
   (`strategy/backtest.py:368`; `strike_pct_above` dead). Result premiums are
   intrinsic-dominated ($11.3B "premium" on ~$2.0B notional in a completed run).
2. **Synthetic GBM baseline vs observed-data strategies** in the same
   comparison table (`research/runner.py:393` vs `:395`; −56.2% synthetic vs
   −4.61% actual window).
3. **Settlement/inventory double-counting and ledger non-reconciliation**
   (`strategy/backtest.py:418-459`): cash settlement + physical-style BTC
   credit + collateral consumption applied together; inverse legs hit both
   ledgers; identity gap $11.45B vs $225.6M reported P&L.
4. **Lifecycle calendar defects**: one day dropped per cycle
   (`backtest.py:548`), index-arithmetic DTE, full premium on truncated final
   cycle, per-leg expiries ignored.
5. **Constant 45% vol across the whole "empirical" window**
   (`research/runner.py:339`); no historical DVOL ingestion exists anywhere;
   contracts §6.5 reconstruction unimplemented in practice.
6. **Requested 2023 window silently truncated to 2024-07-29** with no coverage
   gate (verified in `data_manifest.json` of the accepted run).
7. **Stress double-counts the shock** (`strategy/stress.py:100-101,139`);
   collar flash-crash sign flipped (+$463M reported vs −$291M floor).
8. **Drawdown/Sharpe/touch computations invalid** (`backtest.py:488-570`).
9. **OOS/CSCV/PBO/DSR pseudo-implementation, null in all real runs**
   (`strategy/regimes.py:194-304`).
10. **Execution sensitivity output is a config echo**
    (`runner.py:514-521,631-635`).
11. **Inverse pricer numeraire error** (spurious e^{−rT}; numerically
    reproduced: deep-ITM call 0.996718 BTC vs required 1.0) and **Black-76 put
    theta sign error** — latent (mandate strategies are built OTC-USD) but
    blocking for venue-true analysis.
12. **Provenance/reporting controls**: hardcoded false "Option data: Deribit
    (observed)" attribution, no provenance annotations, warning catalogue
    unimplemented, several category mislabels.

### 2.3 Reference-library integrity

- **Load-bearing official sources present and usable**: Deribit inverse spec
  and fee schedule; Deribit OpenAPI/AsyncAPI specs (cover every endpoint
  `vol/client.py` uses, including `get_volatility_index_data`); CME Ch. 350A
  text cache; CME rulebook chapters relevant to BTC.
- **Not primary / wrong**: the "ISDA Digital Asset Derivatives Definitions"
  PDF is a law-firm client memo, not the ISDA booklet; one cited
  `openapi.json` is a Mintlify "Plant Store" sample; SR 11-7 (2011) sits
  unmarked beside its 2026 successor SR 26-2; cached Ch. 350A is dated
  2023-05-19 while sibling chapters are 2026-06-03.
- **Unusable extractions**: `_text_cache` Glasserman (615 B), Cartea (0 B);
  Natenberg / Mastering Bitcoin / Programming Bitcoin EPUBs are ~114 B
  placeholders.
- **Duplicates / noise**: 17 md5-identical duplicate sets in
  `BTC_pending links/`; ~60 of ~78 unique documents there are CME chapters
  irrelevant to BTC (livestock, dairy, FX, palm oil); `pillar_5_fable_bundle`
  duplicated as directory + tarball; the bundle's superseded pre-correction A1
  brief still contains the forbidden USD/index inverse approximation.
- **Empty canonical locations**: `docs/venue_rules/`, `docs/data/`,
  `docs/model_validation/`, `official_docs/deribit/`,
  `private_reference_library/notes/`, `internal_material/`,
  `pillar_5_internal_materials/`, and the `papers/` + pillar-1..3 taxonomy
  directories are empty or near-empty despite being cited as context.
- **Citation errors in `contracts.md`** (numerics unaffected — verified): the
  10.4506/5.5735 golden vector is printed in neither Hull nor Haug; ATM delta
  0.6368 is not Haug §2.1's printed example; put-call parity is Hull §11.4 not
  §15.8; Bailey et al. state "N ≫ 10", not the claimed "N ≥ 100"; §5.2 sources
  the Deribit linear mechanism to fee-schedule lines; §3.4 lists BVX (a
  volatility-futures fixing) among CME BTC settlement fixings; BRRNY absent
  from `DeliveryPriceConvention`.

### 2.4 External-review corpus status

| Corpus | Findings extracted | Status after independent verification |
|---|---|---|
| Fable full-context (F-01…F-43 + aux) | 169 | Highest quality; every critical claim re-verified against code, all confirmed (minor numeric corrections only) |
| DeepSeek initial + reconciled | 113 | Largely pre-implementation planning findings; §10.8 inverse formulas and related constructs remain superseded by AC |
| MiniMax initial | 77 | Fee-base and hypothesis-gap findings stand; its inverse-settlement modelling (physical delivery, combined enum, mixed denominators) is AC-superseded/rejected |
| DeepSeek validation (DSV-01…21) | 21 | Confirmed; caveat: executed against a non-canonical checkout (DSV-20) — claims re-verified here against the canonical repo |
| MiniMax validation consoles | 9 | Confirms baseline cluster; transcript truncated — OOS/MC/stress checks not in evidence |
| DeepSeek fix reports (4) | 64 | Generated self-certifications; fix claims **not** accepted as truth; several admissions (zero MC variance, exit-0-no-output, placeholder gate rows) treated as evidence |
| Phase 0/1/2 reports + reviews | 126 | Governance chain shows A3 merged against NOT-READY verdict and a weakened no-look-ahead test |
| Pillar studies + gap audit | 100 | Requirement inputs; several pillar claims never carried into contracts (execution benchmark, tranche venue-minimums, MC stochastic-dominance outputs, stress probability weights); Pillar 4's "CME American-style" claim is wrong (350A: European) |

## 3. Matrix summary

`frontier_reference_application_matrix.tsv`: 440 rows.

| Authority level | Rows | | Implementation status | Rows |
|---|---|---|---|---|
| 1 authoritative corrections | 18 | | implemented | 110 |
| 2 contracts | 120 | | partial | 106 |
| 3 CEO mandate | 10 | | divergent | 79 |
| 4 sanitised mandate | 3 | | missing | 59 |
| 5 build plan | 2 | | not_applicable | 56 |
| 6 official venue docs | 71 | | unknown | 30 |
| 7 textbooks/research | 42 | | | |
| 8 audits | 46 | | | |
| 9 generated | 128 | | | |

Row-level dispositions use the fixed vocabulary
(`keep_authoritative`, `use_as_evidence_only`, `supersede`, `deduplicate`,
`obsolete`, `needs_primary_source`, `needs_business_decision`,
`integrate_stage2`, `integrate_stage3`, `no_action`).

## 4. Duplicated, obsolete, contradictory, unauthoritative sources (dispositions)

| Item | Disposition |
|---|---|
| `docs/reports/reconciled_initial_audit.md` §10.8 inverse formulas, PHYSICAL_USD enum, Pydantic-OptionQuote migration | superseded by AC §§1,3,4 — never implement |
| MiniMax initial-audit inverse settlement model (physical delivery / combined enum / mixed denominators) | rejected as guidance; retained as evidence |
| 17 duplicate PDF sets in `BTC_pending links/` + `pillar_5_fable_bundle.tar.gz` | deduplicate (record keeper copy) |
| ~60 non-BTC CME chapters | obsolete for this engine; retain archived, exclude from authority claims |
| SR 11-7 (2011) | mark superseded by SR 26-2 |
| Cached CME 350A (2023-05-19) | needs current-version refresh before D-3 CME work |
| Charles Law memo mislabelled as ISDA Definitions | unauthoritative as ISDA source; needs_primary_source |
| Mintlify "Plant Store" `openapi.json` | mislabelled; real Deribit specs exist adjacent |
| Fable-bundle superseded A1 brief (forbidden inverse approximation) | superseded; annotate to prevent reuse |
| Generated result folders (`results/research/*`), `.latest_research_*` pointers, DeepSeek synthesis | use_as_evidence_only; synthesis claims retraction list in Stage 1; pointers currently reference failed/empty runs |
| `docs/architecture/contracts_draft.md`, `contracts_candidate.md` | obsolete (superseded by frozen contracts.md); retain for history |

## 5. Where an official primary source must replace current reliance

See `frontier_missing_sources.md` for the complete list. The blocking subset:

1. **Historical DVOL series (official Deribit)** — currently a constant 0.45
   assumption. Blocks all historical premium reconstruction (contracts §6.5).
2. **Pre-2024-07-29 BTC spot history** (paid Massive tier or approved vendor
   archive, else explicit re-scope) — decision D-11.
3. **Inverse-option pricing verification anchor** — official worked settlement
   example + documented no-arbitrage identity (price_BTC×S = Black-76 USD);
   contracts §13.1 rows are still "TBD".
4. **ISDA Digital Asset Derivatives Definitions booklet** (actual).
5. **CF Benchmarks BRR/BRRNY methodology** (contracts §3.4 references them
   with no cached source; BRRNY missing from the delivery-convention enum).
6. **Current CME Ch. 350A** (2026 revision) and the block-minimums workbook in
   usable text form.
7. **FINMA guidance and Binance VIP-OTC documentation** — required by the
   build plan §4, absent from the library.
8. **Observed historical Deribit option chains** (vendor archive, optional per
   build plan §4) — or an explicit recorded statement that v1 proceeds on
   reconstruction only.
9. **Usable text extractions** of Glasserman, Cartea, Natenberg (current
   caches are placeholders).

## 6. Stage-0 gate statement

Stage-0 outputs are complete and internally consistent with the Stage-1
deliverables. Nothing in this audit modifies production implementation. The
matrix, conflicts and missing-sources files are the binding input to the
Stage-1 repair specification; no historical research or large Monte Carlo may
run until the Stage-1 acceptance tests (see `frontier_acceptance_tests.md`)
pass.
