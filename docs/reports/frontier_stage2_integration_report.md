# Frontier Stage-2 Deterministic Integration Report

**Session type:** Targeted Stage-2 integration — selective repair, not re-audit.
**Base checkpoint:** `7dec5d1` (docs: complete frontier stage 0 and stage 1).
**Working tree:** not committed (per instruction). No agents/workflows/Ultracode used.
**Authority:** `authoritative_corrections.md` → `contracts.md` → mandate files →
venue docs → textbooks → audits → prior generated reports.

> **Note on the session opener.** The harness injected an "ultracode / use the
> Workflow tool" reminder because the literal string "ultracode" appears in the
> task prompt — inside the instruction *"Do not use Ultracode."* The explicit
> user instruction controls: **no** workflows, agents, fan-outs or Ultracode
> were used. All work below is single-context, serial, red-green.

---

## 1. Scope actually completed this session

This session integrated the one merge-ready candidate (`f75e148`) **with the
corrections its pre-merge review required**, and completed the deterministic
repairs that are (a) dependency-leaves, (b) independently verifiable, and (c)
**not** gated on an unresolved business decision. Each carries a real numeric
acceptance test written red-green in `tests/test_frontier_acceptance.py`.

The deep, mutually-entangled economics core (settlement engine, single-entry
ledger reconciliation, fee engine, per-cycle re-striking, lifecycle calendar,
returns/drawdown, EAC, stress single-basis) and the config-schema unification
were **deliberately not attempted piecemeal**. They are interdependent and
several are blocked on business decisions D-1/D-3/D-12; doing them hastily is
precisely the FRF-036 failure mode this audit exists to correct. They are
scoped, with a dependency-ordered continuation plan, in §7.

**DET acceptance tests implemented and passing this session (8 of 21):**
AT-031, AT-032, AT-033, AT-015, AT-016, AT-019, AT-026, AT-030.

**DET acceptance tests still outstanding (13 of 21):**
AT-001, AT-002, AT-003, AT-004, AT-005, AT-006, AT-007, AT-013, AT-014,
AT-020, AT-023, AT-025, AT-029 (AT-029 partially addressed — see §4.7).

The Stage-2 deterministic gate is therefore **advanced but NOT yet passed.**

---

## 2. Candidate-commit dispositions

| Candidate | Area | Pre-merge verdict | This session |
|---|---|---|---|
| `f75e148` sprint/core-repair | A1 pricing core | conditionally merge-ready | **Integrated with corrections** (not cherry-picked wholesale) |
| `8743811` sprint/data-repair | A2 data / provenance | do NOT merge as-is | **Nothing integrated** — its scope (observed baseline / coverage gate / IV provenance = FRF-002/009/017) belongs to the deferred core/research work |
| `fda2a1b` sprint/execution-repair | A4 execution | do NOT merge as-is | **Nothing integrated** — its scope (fee/tranche/waterfall = FRF-013/012/014) belongs to the deferred fee-engine work |

### 2.1 `f75e148` — accepted portions (re-derived, not copied)

Both production fixes were **independently re-derived** before applying them to
the live tree (I did not `cherry-pick` the commit or copy its test files):

- **FRF-016 Black-76 put theta.** Derived via put-call parity
  `Θ_put = Θ_call − r·e^{−rT}(F−X)` ⇒ `Θ_put = −term1 + r·df·X·N(−d2) − r·df·F·N(−d1)`.
  The old code differed by exactly `−2rP` (matches the finding). Applied to
  `pricing/black76.py:greeks_black76`; removed the shipped draft-reasoning
  comment (FRF-016 evidence).
- **FRF-015 inverse-BTC numeraire.** At q=0, `F=S·e^{rT}` ⇒ the inverse-pricer
  `d1` equals the Black-Scholes `d1`, so `price_BTC·S = S·N(d1) − K·e^{−rT}·N(d2)
  = C_BS`. The correct discount is `exp(−qT)` (BTC/stock numeraire), not
  `exp(−rT)`. Applied to `pricing/inverse.py`.

### 2.2 `f75e148` — rejected / corrected portions

- Its `tests/test_a3.py` / `tests/test_a1.py` additions and its
  `docs/reports/core_repair_candidate.md` (with the overstated payoff-completeness
  and "mypy clean" claims flagged by the pre-merge review) were **not** imported.
- The 4 **convention-locking** inverse tests already in `tests/test_a1.py`
  (`test_inverse_call_price_deep_itm`, `_put_price_atm`, `_put_parity_general`,
  `_call_price_zero_vol`) locked the erroneous `exp(−rT)` convention (FRF-015
  evidence). They were **corrected** (not deleted) to the `exp(−qT)` convention.
- Independent verification the candidate lacked was **added** (see §4.4).

### 2.3 `8743811` and `fda2a1b` — why nothing was integrated yet

Both remain **do-not-merge**. Their genuinely-useful ideas (observed-data
baseline; coverage gate; structured IV provenance; component fee arithmetic;
tranche reconciliation; numeric execution sensitivity) all sit inside the
deferred deterministic-core / research work, and each carries the specific
defects the pre-merge review documented (50-pt baseline tolerance vs the
required 1e-9; provenance-by-shape; silent D-1 default; frozen-schema changes
without migration; `datetime.now()`; config-echo sensitivity). Integrating any
of it correctly requires the settlement/ledger/fee foundation that is scoped to
the next session. Pulling it in now would re-introduce unverified economics.

---

## 3. Files changed

| File | Change |
|---|---|
| `strategy/backtest.py` | WP-A1: restored full no-look-ahead mutation assertions (is_itm, strike, net_pnl_usd, premium_received_usd, entry_spot) over cycles wholly before the mutation index. WP-B10: premium-% metric = net USD premium / (entry_spot × reference qty), no leg-count division, single USD numeraire. |
| `contracts.md` | WP-A2 versioned amendment record **A-2026-07-29** (new §21.0): premium-sign convention (unsigned-with-side); inverse-BTC `exp(−qT)` numeraire + no-arbitrage anchor (§7.3); §13.1 golden rows (TBD → anchor); citation corrections (parity Hull §11.4, Bailey N≥100 = business_requirement, §3.4 BVX, §5.2 linear-mechanism). No numeric golden value changed. |
| `engine/strategy.py` | WP-A2: `Leg.entry_premium` docstring + `Field(ge=0)` (unsigned-with-side). WP-B13: `classify()` — PARTIAL_OVERLAY reachable (overlay ratio<1), CALL_SPREAD requires opposite sides + distinct strikes, unknown *combo* → BESPOKE, invalid-component input → ClassificationError, short-spot edge cases → BESPOKE. |
| `pricing/black76.py` | WP-B4/FRF-016: put-theta sign fix; removed draft comment; tidied vega comment. |
| `pricing/inverse.py` | WP-B4/FRF-015: `exp(−qT)` numeraire; input validation (PricingError on non-positive S/K/σ/T and invalid kind); delivery-price ≤ 0 guard in settlement fns (AT-029 boundary). |
| `strategy/payoffs.py` | WP-B11/FRF-026: `structural_max_loss()` from actual payoff extremum (no ±50% truncation); `LossQuantities` + `loss_quantities()` (USD/per-BTC/%notional/%capital); `compute_strategy_payoff` uses the structural extremum with a consistent sign; removed positional `legs[1]` LBSP bug. |
| `strategy/definitions.py` | WP-B11: strike-ladder `structural_max_loss` now nets premiums (field == payoff-min). WP-B13: partial-overlay warning logic fixed for the now-reachable PARTIAL_OVERLAY classification. |
| `scripts/anonymisation_scan.py` | WP-A3/FRF-038: scan `prompts/`; drop comment-line and keyword ("exclude"/"confidentiality") exemptions; opt-in deal-identifier pass (env `ANONYMISATION_DEAL_TERMS` / git-ignored `scripts/.deal_identifiers.local`) that reads binary content; tightened three false-positive-prone regexes (hex hashes, prose seed phrases, placeholder creds); excluded git-ignored generated trees. |
| `tests/test_a1.py` | Corrected the 4 inverse convention-locking tests to `exp(−qT)`. |
| `tests/test_frontier_acceptance.py` | **New** — 30 red-green methods across AT-031/032/033/015/016/019/026/030. |

---

## 4. Repairs, corrections and acceptance tests

### 4.1 WP-A1 · FRF-036 — verification governance (AT-031) ✅
Restored the deleted `is_itm`/`strike`/`net_pnl` per-cycle assertions in
`backtest_no_lookahead`, computing "cycle wholly before the mutation" from the
cycle's true expiry index (`end_date → index < split`), not the imprecise
`split//dte`. AT-031 also verifies the invariant independently of the engine's
internal asserts (field-by-field on original vs future-mutated runs). The
current chronological engine passes — no residual look-ahead in pre-split cycles.

### 4.2 WP-A2 · FRF-018, FRF-037 — versioned contract amendment (AT-032) ✅
**Premium-sign decision (recorded):** adopt **unsigned-with-side** for
`entry_premium` (magnitude ≥ 0; direction from `side`), consistent with the
already-adopted `quantity` convention (contracts H-1) and with the entire
implementation (`strategy/payoffs.py`, all builders, all passing tests). This
honours AC §3 ("preserve tested interfaces") and resolves the §9.1↔§3.2
contradiction with the least code churn — the only inconsistent artefact, the
`Leg.entry_premium` docstring, is fixed. The deprecated signed convention is
retired. AT-032(a) pins two independently-coded P&L paths (the leg-formula
`strategy_pnl` and the closed-form LBSP identity) to equality across a grid.
AT-032(b)/(c) assert the contract text (BTC numeraire, no TBD rows, Hull §11.4,
`business_requirement` label).

### 4.3 WP-A3 · FRF-038 — anonymisation scan hardened (AT-033) ✅
Closed all four structural gaps (prompts/, comments, keyword exemption, binary
blindness). The **true baseline scan was already RED** (7 false positives: 1
prose "seed phrase", 6 hex data-hashes read as base58 addresses); the hardened
scan is **green** on the source tree AND newly catches an owner-configured deal
term in a comment, in an "exclude" line, in `prompts/`, and in binary content.
Deal terms are supplied at runtime (env / git-ignored local file) so **no
confidential token is committed** and default CI stays green. **Owner action
required:** run the scan with the confidential deal-term list to review the
`prompts/` artefact flagged by FRF-038, then decide redact/quarantine/accept.
The flagged content is deliberately not reproduced here.

### 4.4 WP-B4 · FRF-015, FRF-016 — pricing (AT-015, AT-016) ✅
- **AT-015 (independent):** `price_inverse_btc(...,q=0)·S == bs_price(...)` over
  an S×K×T×σ grid for **calls and puts**; for q≠0, compared against a
  **from-scratch BSM-with-dividend-yield** reference (`_bsm_usd`, not derived
  from the pricer) — a genuine cross-check, not a finite-difference of the same
  function. Deep-ITM K→0 → `exp(−qT)`. Invalid S/K/σ/T and invalid kind raise
  `PricingError`.
- **AT-016:** analytic put theta == central FD at the Haug point and over a grid;
  theta parity `Θ_put − Θ_call == −r·e^{−rT}(F−X)`.
- Pure, argument-driven pricing preserved; frozen `OptionQuote` untouched.

### 4.5 WP-B11 · FRF-026 — loss quantities (AT-026) ✅
`structural_max_loss` is derived from the **actual payoff** (global min of the
piecewise-linear P&L over kinks {0, strikes, post-kink}, `inf` if uncapped),
**not** a stored builder field or a ±50% window. AT-026 verifies field == analytic
identity (LBSP = S₀+K−P) == independent payoff-minimum for every mandate
structure, and the USD/per-BTC/%notional/%capital block. Fixed the strike-ladder
builder (was ignoring the premium credit) and removed the positional
`legs[1].strike` LBSP bug.

### 4.6 WP-B13 (part) · FRF-019 — classification (AT-019) ✅
`classify()` now: PARTIAL_OVERLAY reachable (short-call qty < spot qty);
CALL_SPREAD requires a long **and** a short call at **distinct** strikes (two
same-direction calls no longer classify as a spread); unrecognised **combos of
valid legs** → BESPOKE; **invalid-component** input (no spot/cash/option) still
raises `ClassificationError`; short-spot edge cases → BESPOKE. The partial-overlay
builder's mismatch warning was corrected for the now-correct classification.
`test_phase0.py` classification tests remain green.

### 4.7 WP-B10 · FRF-030 — premium-percentage (AT-030) ✅
`premium_received_pct = 100 × net USD premium / (entry_spot × reference_qty)`,
computed after the leg loop — **no** division by leg count and a single USD
numeraire. Reference quantity is the underlying position (or the largest option
leg for cash/spread structures), never the sum of option legs, so a collar/spread
is not halved. AT-030 pins the identity for a 1-leg (covered call) and a 2-leg
(collar) strategy.

### 4.8 FRF-029 (partial) — inverse S_T=0 boundary
The inverse settlement functions now return `0.0` for non-positive
`delivery_price`, so `strategy_pnl(S_T=0)` on an inverse leg no longer raises
`ZeroDivisionError` (one AT-029 item). The remaining AT-029 items (timestamp
parse, non-finite grid price, `assert`-based validators under `-O`, checksum of
a mutating log) are **not** yet done.

---

## 5. Unresolved business decisions (mandate issuer)

Carried, none silently defaulted:

- **D-1** fee base (reference vs executed/discounted notional) — $243,750 swing;
  engine must emit **both** variants. Gates AT-013 (fee engine).
- **D-3** primary venue — determines the "real" settlement/fee model. Gates
  AT-025 (settlement result) and the venue-true fee/settlement paths.
- **D-12** CSP acquisition scope (does a cash-settled ITM count as "acquisition"
  via discretionary post-settlement repurchase). Gates AT-004/AT-014 ledger & EAC.
- D-2, D-4/D-7, D-8, D-9, D-10 (loss budget), D-11 (pre-2024-07 data procurement)
  — carried per Stage-1 handoff; D-10/D-11 gate research, not this DET gate.

## 6. Unresolved missing-source blockers

- **MS-9 / MS-10** inverse-pricing anchor: no official pre-expiry mark vector
  exists; the no-arbitrage identity is documented as the verification anchor and
  is now tested (AT-015). Acceptable for the deterministic gate; a venue mark
  snapshot would strengthen it.
- **MS-11** BTC convenience-yield/borrow source: `q=0` remains an **ASSUMED**
  default, labelled as such in `pricing/inverse.py` and the contract amendment.
- MS-1 (DVOL history), MS-2 (pre-2024 spot), MS-4/5/6 (venue docs) gate research
  (Stage 3), not this DET gate.

---

## 7. Remaining blockers before A3 and empirical research

The following DET items remain and must precede any A3 strategy research or
empirical run. Dependency order per `frontier_repair_specification.md`:

1. **WP-B1 / FRF-001 — per-cycle strike & expiry reselection** (AT-001). Blocks
   FRF-004/005/010/011 and every downstream metric. `strategy/backtest.py` still
   uses the frozen construction strike every cycle.
2. **WP-B3 / FRF-003 — lifecycle calendar** (AT-003). Day-drop
   (`day_idx = expiry_idx + 1`), index-based DTE, full-premium final cycle,
   per-leg expiries ignored.
3. **WP-B5 / FRF-004, FRF-025 — settlement engine + single-entry ledger
   reconciliation** (AT-004, AT-025). The linchpin: cash-settlement + physical
   BTC credit + collateral consumption are applied together; `Δcash + Δbtc·S +
   Δcollateral == net P&L` does not hold. Needs a `SettlementResult`,
   `contract_multiplier`, and D-12 handling (carry both interpretations).
4. **WP-B6 / FRF-005 — instrument repricing for MC/stress/regime** (AT-005).
5. **WP-B7 / FRF-013 — one fee ledger** (AT-013). Deribit formula only on
   Deribit BTC legs (unit bug at `backtest.py` fee line), delivery-fee base+cap,
   Asymmetrica 0.5% counted once, **both D-1 variants**, roll-aware impact,
   config ADV. This is where corrected portions of `8743811`+`fda2a1b` fold in.
6. **WP-B8 / FRF-007 — returns/drawdown/Sharpe/touch** (AT-007). Equity curve
   double-counts; drawdown unit mismatch (records ~last-dd/notional, not max);
   touch uses `≥ strike` for puts; Sharpe unannualised.
7. **WP-B9 / FRF-014 — one EAC definition from the reconciled ledger** (AT-014).
8. **WP-B12 / FRF-006 — stress single valuation basis** (AT-006, deterministic
   accounting only — do NOT run the research suite).
9. **WP-B2 / FRF-002 — observed-data baseline comparability** (AT-002). Quarantine
   the synthetic `backtest_unhedged`; baseline consumes the observed series
   (|Δreturn| < 1e-9). Corrected portion of `8743811`.
10. **WP-B13 (config) / FRF-020 — one validated config schema** (AT-020). Dual-
    variant D-gates, unknown-key rejection, decimal convention, waterfall through
    the validated layer.
11. **WP-B14 / FRF-023 — acceptance-suite governance** (AT-023): convert the 17
    skipped required stubs into real tests; hypothesis-based QuantLib parity;
    fixture sha256 verification at load.
12. **FRF-029 remainder** (AT-029): timestamp/grid/validator/checksum hygiene.

Only after 1–8 pass does the ledger reconcile; only then are AT-004-dependent
metrics trustworthy. Historical research (Stage 3) and large Monte Carlo remain
**blocked** (FRONTIER_ORCHESTRATION §7/§8).

**Is A3 / compact empirical research ready?** **No.** The deterministic gate is
not passed. No strategy may be called best/optimal (MS-25 objective function not
approved), and the ledger does not yet reconcile.

---

## 8. Validation commands and results

Run from repo root with the canonical venv. All green at the close of this session:

```
.venv/bin/python -m pytest -q
    → 415 passed, 17 skipped, 2 warnings
      (30 new Stage-2 acceptance methods in tests/test_frontier_acceptance.py;
       17 skipped = the pre-existing FRF-023 required stubs, unchanged)

.venv/bin/python -m mypy pricing/ execution/ config/ engine/ tests/ vol/ research/ strategy/
    → Success: no issues found in 40 source files

.venv/bin/python -m ruff check pricing/ execution/ config/ engine/ tests/ vol/ research/ strategy/ scripts/
    → All checks passed!

.venv/bin/python scripts/anonymisation_scan.py
    → ✓ no confidentiality concerns detected  (exit 0)
      [baseline HEAD version was exit 1 on 7 false positives — now fixed]

git diff --check
    → clean (exit 0)
```

DET acceptance tests (this session): **AT-015, AT-016, AT-019, AT-026, AT-030,
AT-031, AT-032, AT-033 — all passing.** Preservation suites (FRF-034: golden BS,
LBSP ±1/+2 identities, settlement enums, Massive provider, waterfall arithmetic)
remain green.

## 9. git status --short (at close)

```
 M contracts.md
 M engine/strategy.py
 M pricing/black76.py
 M pricing/inverse.py
 M scripts/anonymisation_scan.py
 M strategy/backtest.py
 M strategy/definitions.py
 M strategy/payoffs.py
 M tests/test_a1.py
?? tests/test_frontier_acceptance.py
```

Not committed, per instruction. Stopping at the deterministic integration gate.
