# Frontier Source-to-Code Traceability (Stage 0)

Checkpoint: `92acecf`. Row-level detail lives in
`frontier_reference_application_matrix.tsv` (440 rows). This document is the
narrative trace from each governing source to requirements, code, tests and
verification status. "VERIFIED" means the cited source text was read and the
claim checked against it during this audit; "MISMATCH" entries are enumerated
in `frontier_source_conflicts.md`.

Status vocabulary: implemented / partial / divergent / missing (per matrix).

---

## 1. `docs/requirements/authoritative_corrections.md` (authority 1)

| AC § | Requirement | Code | Tests | Status |
|---|---|---|---|---|
| §1 | Settlement decomposed into separate venue/product/mechanism/currency/exercise/multiplier/delivery fields; no combined enum | `engine/settlement.py:18-71` | `test_phase0.py:536-585` | **implemented** (VERIFIED exact) |
| §1 | Economic payoff separate from venue settlement and discretionary inventory | `strategy/payoffs.py` (payoff) vs `strategy/backtest.py:418-472` (settlement) | none enforcing separation | **divergent** — backtest conflates cash settlement with physical-style inventory (FRF-004) |
| §1 | Physical delivery only when contract requires | `strategy/backtest.py:447-459` | none | **divergent** (FRF-004) |
| §2 | Pure pricing functions; no params.yaml reads; config layer injects | `pricing/*` | `test_phase0.py:328`, `test_a1.py:516` | **implemented** (VERIFIED by grep + tests) |
| §2 | Golden tests independent of business config | `tests/test_a1.py`, `test_engine.py` | same | **implemented** |
| §3 | OptionQuote frozen dataclass preserved; Pydantic only at boundaries | `pricing/black_scholes.py:16-23`; Pydantic in `engine/`, `config/` | `test_phase0.py:315` | **implemented** |
| §4 | Inverse-BTC formulas re-derived from official docs, dimensional analysis, unit tests; reconciled §10.8 forbidden | `pricing/inverse.py` | `test_a1.py:169-290` | **partial/divergent** — settlement functions correctly re-derived from the venue doc (VERIFIED); the *pricing* discount is a numeraire error (e^{−rT}; FRF-015); §10.8 correctly absent (VERIFIED) |
| §5 | Massive primary; Deribit owns DVOL/chain; CDD explicit fallback; missing options = model_reconstructed | `vol/history.py`, `research/runner.py` | `test_vol.py:460-539`, `test_research_runner.py` | **partial** — spot hierarchy implemented; DVOL never ingested (FRF-008); CDD fallback mislabelled MODEL_RECONSTRUCTED (FRF-017) |
| §6 | This document prevails over audits; venue docs over textbooks | Stage-0/1 classification applied | — | **implemented in audit process** (FRF-031/032 supersessions) |

## 2. `contracts.md` (authority 2) — section-by-section

| § | Interface | Code | Status |
|---|---|---|---|
| §2.2 | StrategyKind + classify() from legs only | `engine/strategy.py:22-173` | **partial** — COVERED_PUT guard correct (VERIFIED); PARTIAL_OVERLAY unreachable, CALL_SPREAD same-direction bug, BESPOKE never returned (FRF-019) |
| §2.3 | Dual-label preservation + W-CLASSIFY-MISMATCH | `engine/strategy.py:87`, `strategy/definitions.py:214-217` | **partial** — fields exist; engine never emits warnings; test asserts None (FRF-019/023) |
| §3.1 | Units/conventions (decimals, T years, vega/theta conventions) | `pricing/black_scholes.py` | **implemented** (VERIFIED) |
| §3.2 | Holder/writer sign convention + strategy P&L formula | `strategy/payoffs.py:88-119` | **implemented** for the formula; premium sign doc contradiction FRF-018 |
| §3.3 | Deribit inverse settlement values | `pricing/inverse.py:43-63` | **implemented** — all cited venue lines VERIFIED (0.2 BTC example line ~22; TWAP 187; fees 3572-3574, 3755) |
| §3.4 | CME options on futures terms | none (no CME leg path exercised) | **missing** in engine; source verified with citation corrections (BRR only; Ch. 350A vintage 2023) |
| §4.1/4.2 | Provenance enum + Origin labels | `config/models.py:21-51` | **implemented** enum-exact; enforcement gaps FRF-017 |
| §5.1/5.2 | SettlementSpec + venue/product matrix | `engine/settlement.py:58-71`, `strategy/definitions.py:46-128` | **partial** — spec exact; only the OTC-USD row is ever used by mandate strategies (FRF-025) |
| §6.1-6.3 | Market/historical data models | `engine/data_models.py` | **partial** — models present; provenance defaults violate "explicit" rule (FRF-017) |
| §6.4 | Fixture manifest SHA-256 | `engine/data_models.py:21-40`, `vol/fixture_recorder.py` | **partial** — manifest written; never verified at load (FRF-023) |
| §6.5 | DVOL+BS ATM reconstruction, MODEL_RECONSTRUCTED, no skew claims | none in runner (flat 0.45) | **missing** (FRF-008) |
| §7.1/7.3 | OptionQuote + pure signatures incl. Black-76, grid, inverse | `pricing/*` | **implemented** signatures; inverse pricing numerics divergent (FRF-015); Black-76 put theta sign (FRF-016) |
| §7.2 | SettlementOptionQuote | absent | **missing** |
| §7.5 | QuantLib hypothesis parity 50 draws | `tests/test_a1.py:540-640` fixed lists | **partial** (FRF-023) |
| §8.1-8.3 | VolSurface / DiscountCurve / ForwardCurve | `vol/surface.py` (partial), others absent | **partial/missing** — surface guesses strikes; svi/ssvi silently degrade; zero production consumers (FRF-024) |
| §9.1-9.2 | Leg / Strategy / DecisionRef | `engine/strategy.py:44-92` | **implemented**; premium sign doc conflict (FRF-018); structural_max_loss default 0.0 (FRF-026) |
| §9.3-9.5 | PayoffPoint / strategy_payoff / breakeven | `strategy/payoffs.py` | **partial** — identities correct incl. LBSP +1/+2 (VERIFIED); payoff_usd vs contract wording ambiguity; breakeven_btc absent; max_loss sign/truncation issues (FRF-026) |
| §9.6/§13.2 | Six boundary-point tests per strategy | `test_phase0.py:643-668`, `test_a3.py:119-208` | **partial** — full set only for covered call + LBSP identities; S_T=0 untestable for inverse legs (ZeroDivision, FRF-029) |
| §10.1-10.2 | Roll / EarlyClose | `strategy/backtest.py:44-51` RollPolicy accepted, never executed | **missing** (dead code; FRF-001/003 cluster) |
| §10.3 | SettlementResult | absent | **missing** (FRF-004/025) |
| §11.1 | BacktestCycleResult / EffectiveAcquisitionCost decomposition | `strategy/backtest.py:69-157` | **divergent** — fields exist; EAC formula and denominators diverge (FRF-014); premium_pct wrong (FRF-030) |
| §11.2 | MonteCarloResult | `strategy/monte_carlo.py:62-105` | **partial** — VaR/ES loss-space implemented; pnl_unit absent; CSP capital wrong; overwrite bug in runner (FRF-021) |
| §11.3 | StressScenarioResult | `strategy/stress.py` | **divergent** — double-count, excursion, replay mislabels (FRF-006/027) |
| §11.4 | OOSValidationResult + Bailey CSCV | `strategy/regimes.py:57-389` | **divergent** — pseudo-CSCV/DSR, null outputs (FRF-010) |
| §11.5 | RegimeAnalysisResult per-regime backtests | `strategy/regimes.py:121-191` | **divergent** (FRF-011) |
| §12.1 | KissellConfig / ImpactEstimate provenance | `execution/impact.py` | **implemented** structurally; iv_giveup hardcoded; aggregate provenance auto-CALCULATED from ASSUMED inputs (FRF-013) |
| §12.2 | FeeBreakdown | `execution/impact.py:132-152` | **partial** — passive container; nothing computes venue fees per schedule; dead in backtest (FRF-013) |
| §12.3 | Tranche scheduler exact-sum | `execution/tranches.py` | **implemented** (sum-exact verified by tests); venue-minimum constraints absent (pillar gap); zero pipeline consumers |
| §12.4 | Waterfall sensitivity | `execution/waterfall.py:102-129` | **implemented** at function level; discarded by runner (FRF-012) |
| §13 | 27 required tests | `tests/*` | **partial** — coverage map in `code_tests` evidence; 17 permanently-skipped stubs; hasattr-only invariants (FRF-023) |
| §14 | Reporting provenance/pending-decision rendering | `research/reporting.py` | **divergent** (FRF-017) |
| §15 | Error taxonomy + warning catalogue | `engine/errors.py` (exact) + no W-* infrastructure | **partial** (FRF-017) |
| §16 | EngineConfig + load_validated_config gates | `config/models.py`, `config/loader.py` | **implemented** as written but **unusable/unused** in production (FRF-020) |
| §17.3 | A1-A4 brief corrections | `agents/A*.md` | **partial** — A2 line-4 Massive correction never applied (C-2.7) |
| §19 | D-1..D-9 pending decisions | `config/models.py:115-126`, reporting | **partial** — carried in config/reports; new D-10/D-11/D-12 registered in Stage 1 |
| §20/§21 | Traceability + correction matrices | this audit | **partial** — several citations corrected (C-2.3-C-2.6) |

## 3. Official venue documentation (authority 6)

| Source | Used for | Verification |
|---|---|---|
| `private_reference_library/deribitfilesascopiedtxt.txt` | inverse settlement formulas, fees, delivery convention, contract terms | **VERIFIED** at lines ~15-30 (0.2 BTC example), 85, 115, 121, 135, 187, 191, 203, 233, 239-249, 3572-3574, 3755. Implementation deviates at delivery-fee base/cap (FRF-013) and delivery price (close vs TWAP, MS-13) |
| `_text_cache/BTC_pending links/350A.txt` (CME Ch. 350A) | CME option terms | **VERIFIED with corrections** — BRR only (no BRRNY/BVX in text); multiplier/fixing details partly in Ch. 5/350; cached vintage 2023-05-19 (MS-5) |
| `pillar_4_venue_standards/deribit/api/specs/deribit_openapi.json` (+asyncapi) | endpoints used by `vol/client.py` | **VERIFIED** — covers `get_index_price`, `get_instruments`, `get_book_summary_by_currency`, `get_volatility_index_data`; note one adjacent `openapi.json` is a Mintlify sample (C-6.4); contracts §4.2 endpoint list omits `get_volatility_index_data` |
| `docs.deribit.com_llms.txt` | supplementary venue docs | present, sampled |
| CME rulebook chapters (`BTC_pending links/`) | Ch. 5, 350, 350A, 450, 451 relevant; ~60 chapters irrelevant | content-identified; duplicates flagged |

## 4. Textbooks and research (authority 7)

| Source | Claim in contracts/code | Verification |
|---|---|---|
| Haug (text cache) | Black-76 golden 1.7011 (F=X=19, σ=0.28, T=0.75, r=0.10) | **VERIFIED** (independently recomputed 1.70105); put theta formula basis for FRF-016 |
| Hull (text cache) | BS golden 10.4506/5.5735; parity §15.8; delta 0.6368 | values **numerically correct**; citations **MISMATCH** (not printed in Hull/Haug as claimed; parity is Hull §11.4) — C-2.5 |
| Bailey et al. (SSRN, in library) | CSCV S=16, N≥100 | **MISMATCH** on N≥100 attribution (paper: N≫10) — C-2.6; implementation not Bailey at all (FRF-010) |
| Kissell (text cache) | I-Star eq. 4.6/4.7 form | **VERIFIED** functional form; parameters uncalibrated ASSUMED (MS-12) |
| McNeil et al. | VaR/ES definitions | consistent with loss-space implementation (`monte_carlo.py:217-261`) |
| Glasserman / Cartea / Natenberg | MC methods, execution, vol trading | caches unusable (MS-14-16) |
| Almgren-Chriss paper | impact modelling | present, unused (informational) |

## 5. Mandates (authority 3-5)

| Requirement | Code/artefact | Status |
|---|---|---|
| Compare 8+ structures without prejudging | `strategy/definitions.py` builds all; comparison layer | **partial** — built and compared, but comparison numbers invalid (FRF-001..014); no "optimal" language in outputs (verified) with guard unimplemented (FRF-033) |
| 2.5%+2.5%+0.5% separated economics | `execution/waterfall.py` | **implemented** at waterfall; 0.5% missing from research EAC (FRF-013) |
| Hypotheses tested not assumed (10-15Δ, 30-45 DTE, 3%/cycle, delta≈assignment, IV triggers, breakout stand-down) | config ranges + `test_engine.py:63` | **partial** — ranges configurable; delta-vs-assignment recorded but built on frozen strikes; IV/breakout triggers unimplemented in backtest (D-8; FRF-001 cluster) |
| Confidentiality | `scripts/anonymisation_scan.py` | **partial** — scan gaps + one historical prompt exception (FRF-038) |
| Presentation timing (no client materials yet) | respected in repo | **implemented** (research_report disclaimer present; retraction list required for synthesis — FRF-022) |

## 6. Audits and generated reports (authority 8-9)

All audit findings are traced into `frontier_consensus_findings.json` with
per-finding classification (accepted / accepted_with_correction / superseded /
rejected / duplicate / unresolved). Generated fix reports and result folders
are traced as evidence-only; none is treated as a validated conclusion. The
run-registry disposition for every `results/research/*` directory is in the
Stage-1 repair specification §Run registry.
