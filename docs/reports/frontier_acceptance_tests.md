# Frontier Acceptance Tests (Stage 1)

Checkpoint: `92acecf`. Companion to `frontier_repair_specification.md` and
`frontier_consensus_findings.json`. Each test is implementation-ready: it states
name, category, fixture/data, exact invariant, expected result, tolerance,
affected module, governing source, and the three blocking flags:

- **DET** — blocks deterministic repair sign-off (Stage 2 gate).
- **HR** — blocks historical research (Stage 3).
- **MC** — blocks large Monte Carlo.

A test blocks a gate when the corresponding finding does. Tests are written
red-green: they must be shown failing at `92acecf` (or on the unrepaired module)
before the repair and passing after. Golden/preservation suites (FRF-034) must
stay green throughout. Fixtures are deterministic and offline; no test may
require live network or a large simulation.

Run harness: `.venv/bin/python -m pytest -q`. Small labelled diagnostic
simulations are permitted only where a test explicitly needs a fixed-seed path
and are not decision evidence.

---

## Phase-A / preconditions

### AT-031 — no-look-ahead mutation integrity (FRF-036)
- **Category:** regression/governance. **DET:✔ HR:✔ MC:✔**
- **Fixture:** any deterministic spot+iv series; a copy mutated only after a split index.
- **Invariant:** for every cycle entirely before the split, `is_itm`, `strike`,
  `net_pnl_usd`, `premium_received_usd` and `entry_spot` are identical between
  original and future-mutated runs.
- **Expected:** exact equality (`==`). **Module:** `strategy/backtest.py:backtest_no_lookahead`.
- **Source:** FRONTIER_ORCHESTRATION §11; Build plan §2.

### AT-032 — contract-amendment consistency (FRF-018, FRF-037)
- **Category:** contract/interface. **DET:✔ HR:✖ MC:✖**
- **Invariant:** (a) the two documented premium-entry conventions produce identical
  strategy P&L on a fixed strategy; (b) `contracts.md` §7.3/§13.1 inverse text
  contains the BTC-numeraire `exp(−qT)` statement and no "TBD" golden rows;
  (c) corrected citations present (parity §11.4; Bailey threshold labelled
  business_requirement).
- **Expected:** P&L delta < 1e-9; text assertions pass. **Module:** `strategy/payoffs.py`, `contracts.md`.
- **Source:** contracts §9.1, AC §4.

### AT-033 — anonymisation scan hardened (FRF-038)
- **Category:** confidentiality control. **DET:✔ HR:✖ MC:✖**
- **Fixture:** a synthetic file containing a firm-identifying token in a comment
  and in a line containing the word "exclude".
- **Invariant:** the scan flags both; it scans `prompts/` and binary content.
- **Expected:** non-zero exit / flagged findings. **Module:** `scripts/anonymisation_scan.py`.
- **Source:** mandate_sanitized §Confidentiality; AGENTS.md.

---

## Phase-B / deterministic economics (all block DET; most block HR/MC)

### AT-001 — per-cycle strike reselection (FRF-001)
- **Category:** lifecycle. **DET:✔ HR:✔ MC:✔**
- **Fixture:** observed-style spot series spanning a > `strike_pct_above` move (e.g. 60k→110k), dte=30.
- **Invariant:** for a `strike_pct_above` policy, each cycle's strike ≈
  `entry_spot × (1+strike_pct_above)` (or the delta-target strike); across N
  cycles `nunique(strike) == N` when spot moves each cycle.
- **Expected:** every cycle strike within 0.5% of the targeting rule; not a
  single frozen strike. **Module:** `strategy/backtest.py`.
- **Source:** FRONTIER_ORCHESTRATION §6; CEO mandate §Hypotheses.

### AT-002 — baseline comparability (FRF-002)
- **Category:** baseline. **DET:✔ HR:✔ MC:✔**
- **Fixture:** a fixed observed spot series.
- **Invariant:** unhedged baseline total return equals the observed
  buy-and-hold return of that same series (same calendar, same cost model); no
  synthetic path is used in full mode; every comparison row shares identical
  start/end/checksum/provenance.
- **Expected:** |baseline_return − observed_return| < 1e-9. **Module:** `research/runner.py`, `strategy/backtest.py`.
- **Source:** FRONTIER_ORCHESTRATION §6; contracts §1.1. **Note:** the `8743811`
  50-pt tolerance test is NOT acceptable for this gate.

### AT-003 — lifecycle calendar contiguity (FRF-003)
- **Category:** lifecycle. **DET:✔ HR:✔ MC:✖**
- **Fixture:** contiguous daily bars; a second series with an interior gap.
- **Invariant:** no calendar day is dropped between consecutive cycles
  (Σ cycle spot-P&L == total spot move over the window for a pure long-BTC leg);
  final cycle priced at true remaining T; each option leg settles at its own
  `expiry_timestamp` (ladder legs settle at 30/37/44, not one index).
- **Expected:** dropped-day count = 0; ladder produces 3 distinct settlement bars.
- **Module:** `strategy/backtest.py`, `strategy/definitions.py:build_strike_ladder`.
- **Source:** FRONTIER_ORCHESTRATION §6; contracts §9.1 (per-leg expiry).

### AT-004 — ledger reconciliation identity (FRF-004)
- **Category:** ledger. **DET:✔ HR:✔ MC:✔**
- **Fixture:** 1-BTC covered call and 1-BTC long-BTC+short-put over ~12 cycles.
- **Invariant:** per cycle and cumulatively, `Δcash + Δ(btc_inventory·S) +
  Δcollateral == net_pnl_usd`; a cash-settled ITM short put does NOT also credit
  physical BTC; CSP collateral is re-reserved each cycle.
- **Expected:** reconciliation residual < 1e-6 × notional. **Module:** `strategy/backtest.py:418-499`.
- **Source:** AC §1; contracts §5.3/§10.3.

### AT-025 — settlement result & multiplier (FRF-025)
- **Category:** settlement. **DET:✔ HR:✖ MC:✖**
- **Invariant:** a `SettlementResult` is produced per settled leg with provenance;
  `contract_multiplier` is applied (CME 5-BTC leg settles 5× a 1-BTC Deribit leg
  at equal terms); delivery-price convention honoured (TWAP proxy labelled
  MODEL_RECONSTRUCTED).
- **Expected:** exact multiplier scaling; provenance present. **Module:** `engine/settlement`, `strategy/backtest.py`.
- **Source:** contracts §10.3, §5.2; Deribit spec line 187.

### AT-005 — instruments repriced for MC/stress/regime (FRF-005)
- **Category:** premium integrity. **DET:✔ HR:✖ MC:✔**
- **Invariant:** the premium seen by MC/stress/regime for a leg equals the
  pricing-layer premium at the evaluation spot/vol/T (not the static builder
  1500); builder placeholder premiums carry ASSUMED provenance and are rejected
  by evaluators.
- **Expected:** |eval_premium − repriced_premium| < 1e-6; VaR95 no longer differs
  from a repriced baseline by exactly premium×quantity. **Module:** `strategy/{monte_carlo,stress,regimes,comparison}.py`.
- **Source:** AGENTS.md (no hard-coded premium); contracts §1.3.

### AT-006 — stress single valuation basis (FRF-006)
- **Category:** stress. **DET:✔ HR:✖ MC:✔**
- **Fixture:** collar, flash-crash-to-30k scenario.
- **Invariant:** scenario P&L uses ONE basis (settlement OR MTM, never payoff+MTM);
  a hedged collar's flash-crash P&L is negative (bounded near its structural
  floor), not positive; `max_adverse_excursion` = worst signed intra-scenario
  loss; no pricing exception is swallowed to 0.
- **Expected:** collar flash-crash P&L < 0 and within tolerance of the analytic
  floor. **Module:** `strategy/stress.py:apply_scenario`.
- **Source:** FRONTIER_ORCHESTRATION §6; contracts §11.3.

### AT-007 — return/drawdown/Sharpe/touch validity (FRF-007)
- **Category:** metrics. **DET:✔ HR:✔ MC:✖**
- **Fixture:** a controlled V-shaped spot path with a known drawdown.
- **Invariant:** max drawdown computed on the ledger equity curve equals the
  known value (the controlled path's true 0.2495, not 0.0485); Sharpe annualised
  with explicit rf and cycle frequency; put "touch" uses spot ≤ strike; baseline
  drawdown is consistent with its P&L (no 0% beside −56%).
- **Expected:** drawdown within 1e-6 of analytic; touch direction correct.
- **Module:** `strategy/backtest.py:488-570`. **Source:** FRONTIER_ORCHESTRATION §6.

### AT-013 — fee engine correctness (FRF-013)
- **Category:** fees. **DET:✔ HR:✔ MC:✖**
- **Invariant:** Deribit trading fee `MIN(0.0003 BTC, 0.125×premium)×contracts`
  applied only to Deribit BTC legs; delivery fee 0.015% capped at 12.5% of option
  value; OTC legs incur no Deribit venue fee; the 0.5% Asymmetrica fee appears
  exactly once per strategy on the D-1 base with BOTH variants emitted; impact
  charged only on incremental re-execution.
- **Expected:** both D-1 variants reproduce the mandate fee figures
  ($9,750,000 and $9,506,250); no unit mismatch on OTC legs. **Module:** `strategy/backtest.py`, `execution/impact.py`, `execution/waterfall.py`.
- **Source:** CEO mandate; Deribit spec 3572-3574/3755; contracts §12.2. **Decision:** D-1.

### AT-014 — effective acquisition cost single definition (FRF-014)
- **Category:** EAC. **DET:✔ HR:✔ MC:✖**
- **Invariant:** EAC computed from the reconciled ledger; component sum
  (premium+fee+impact+discount+spread) reconciles to `per_btc_usd`; denominator =
  actual BTC held at end; a zero-BTC strategy returns EAC = n/a with reason.
- **Expected:** component identity residual < 1e-6; CSP with 0 assignments → n/a.
- **Module:** `strategy/backtest.py:579-613`, `strategy/comparison.py`.
- **Source:** contracts §11.1. **Decision:** D-12.

### AT-015 — inverse pricing numeraire & no-arbitrage (FRF-015)
- **Category:** pricing. **DET:✔ HR:✖ MC:✖**
- **Fixture:** parameter grid over S,K,r,σ,T for calls AND puts, q=0 and q≠0.
- **Invariant:** at q=0, `price_inverse_btc × S == Black-Scholes USD price`;
  deep-ITM call → 1.0 BTC (not 0.9967); `delivery_price ≤ 0` and non-positive
  S/K/σ/T and invalid kind raise the project error taxonomy.
- **Expected:** parity |Δ| < 1e-6 (q=0); deep-ITM within 1e-6 of the K/F limit;
  errors raised. **Module:** `pricing/inverse.py`. **Source:** AC §4; contracts §7.3/§13.1.
- **Note:** must be independent (not a finite-difference of the same function).

### AT-016 — Black-76 put theta (FRF-016)
- **Category:** pricing. **DET:✔ HR:✖ MC:✖**
- **Invariant:** `greeks_black76` put theta matches a central finite-difference of
  `price_black76` and satisfies the parity relation to the call theta.
- **Expected:** |analytic − FD| < 1e-4 on the Haug point and a random grid.
- **Module:** `pricing/black76.py`. **Source:** Haug §1.1.3.

### AT-030 — premium-percentage metric (FRF-030)
- **Category:** premium. **DET:✔ HR:✔ MC:✖**
- **Invariant:** `premium_received_pct` is net USD premium / (entry spot ×
  reference quantity), with no division by leg count; multi-leg (collar,
  spread) reports the full net, plus per-leg breakdown.
- **Expected:** collar/spread pct not halved; numeraire consistent. **Module:** `strategy/backtest.py:345-404`.
- **Source:** contracts §11.1.

### AT-026 — loss quantities (FRF-026)
- **Category:** downside. **DET:✔ HR:✖ MC:✖**
- **Invariant:** `structural_max_loss` per strategy equals the analytic extremum
  from leg identities (LBSP = S₀+K−P) and equals the minimised `strategy_pnl`
  over boundary points; report emits loss in USD, per-BTC, %notional, %capital.
- **Expected:** field == analytic == payoff-minimum within 1e-6. **Module:** `strategy/payoffs.py`, `engine/strategy.py`.
- **Source:** CEO mandate §downside; contracts §9.2. **Decision:** D-10 (budget).

### AT-019 — classification integrity (FRF-019)
- **Category:** classification. **DET:✔ HR:✖ MC:✖**
- **Invariant:** partial overlay (ratio<1) → PARTIAL_OVERLAY; long BTC + short put
  → LONG_BTC_PLUS_SHORT_PUT (never COVERED_PUT); two same-direction calls →
  not CALL_SPREAD; unknown combo → BESPOKE; label≠canonical raises
  W-CLASSIFY-MISMATCH.
- **Expected:** full §13.3 matrix incl. negatives passes. **Module:** `engine/strategy.py:classify`.
- **Source:** contracts §2.2; AGENTS.md.

### AT-020 — configuration integrity (FRF-020)
- **Category:** config. **DET:✔ HR:✔ MC:✖**
- **Invariant:** one validated config schema drives research runs; percent vs
  decimal is unambiguous; unknown/unconsumed keys are rejected; D-1/D-2/D-3
  remain pending (dual-variant outputs, no silent default); `waterfall` reads
  through the validated layer.
- **Expected:** malformed/ambiguous config rejected; every declared key consumed.
- **Module:** `config/*`, `research/runner.py`, `execution/waterfall.py`.
- **Source:** AGENTS.md; contracts §16.

### AT-029 — hygiene invariants (FRF-029)
- **Category:** robustness. **DET:✔ HR:✖ MC:✖**
- **Invariant:** unparseable timestamp raises (not now()); non-finite grid price
  raises PricingError; config validators raise ValueError under `python -O`;
  checksum excludes the still-appending log; inverse-leg `strategy_pnl(S_T=0)`
  does not raise ZeroDivisionError.
- **Expected:** each edge raises/handles as specified. **Module:** `vol/history.py`, `pricing/grid.py`, `config/models.py`, `research/runner.py`, `strategy/payoffs.py`.

### AT-023 — economic-invariant coverage exists (FRF-023)
- **Category:** meta/test-governance. **DET:✔ HR:✔ MC:✔**
- **Invariant:** AT-001…AT-030 are implemented as real numeric assertions; no
  required test remains an `assert False` stub; QuantLib parity is hypothesis-
  based (≥50 draws) covering inverse & grid; fixtures are sha256-verified at load.
- **Expected:** zero skipped required tests; parity property test present.
- **Module:** `tests/*`, `engine/fixture_loader.py`. **Source:** contracts §13/§21.6.

---

## Phase-C / research subsystem (block HR and/or MC)

### AT-008 — DVOL-driven premiums (FRF-008)
- **Category:** data provenance. **DET:✖ HR:✔ MC:✔**
- **Invariant:** in full mode `iv_history` derives from an observed DVOL series
  (not a flat 0.45 constant); premiums from §6.5 reconstruction carry
  MODEL_RECONSTRUCTED, flat-vol premiums carry ASSUMED and mark the run diagnostic.
- **Expected:** non-constant IV series; correct provenance labels. **Module:** `vol/`, `research/runner.py:339`.
- **Source:** contracts §6.5; AC §5. **Missing source:** MS-1.

### AT-009 — coverage gate (FRF-009)
- **Category:** lineage. **DET:✖ HR:✔ MC:✔**
- **Invariant:** a run whose actual coverage differs from requested beyond
  tolerance fails or is explicitly relabelled; missing coverage metadata fails
  (does not silently pass); pagination retrieves the full requested range.
- **Expected:** truncated-window run does not complete as "full-window". **Module:** `vol/history.py`, `research/runner.py`.
- **Source:** FRONTIER_ORCHESTRATION §5.4/§6. **Decision:** D-11.

### AT-017 — provenance & reporting controls (FRF-017, FRF-033)
- **Category:** reporting. **DET:✖ HR:✔ MC:✔**
- **Invariant:** attribution lines derive from the run manifest (no hardcoded
  "Deribit (observed)"); every reported number carries provenance; the §15.3
  warnings fire (incl. W-COVERED-CALL-OPTIMALITY-CLAIM on any "optimal/best"
  attached to a structure); CDD=observed/fallback, synthetic=SIMULATED; MR-11
  delta/yield gap reported.
- **Expected:** false-attribution test fails at 92acecf, passes after; warnings emitted.
- **Module:** `research/reporting.py`, `research/runner.py`. **Source:** contracts §14.3/§15.3.

### AT-010 — real CSCV/PBO/DSR (FRF-010)
- **Category:** OOS. **DET:✖ HR:✔ MC:✔**
- **Invariant:** CSCV over an N-configuration performance matrix uses C(S,S/2)
  symmetric combinations and a rank logit; DSR is the Bailey–López de Prado
  statistic (skew/kurtosis/trials-corrected); insufficient data returns a typed
  verdict, not a silent null.
- **Expected:** on a synthetic overfit matrix PBO→high; on an honest one PBO→low.
- **Module:** `strategy/regimes.py:194-389`. **Source:** contracts §11.4; Bailey et al.

### AT-028 — OOS fold containment (FRF-028)
- **Category:** OOS. **DET:✖ HR:✔ MC:✖**
- **Invariant:** a cycle is counted in a fold only if its full lifecycle
  (entry→settlement) lies inside the fold; boundary-crossing cycles are excluded;
  an embargo ≥ DTE separates train and test.
- **Expected:** no cycle settles outside its assigned fold. **Module:** `research/runner.py:404-458`.

### AT-011 — per-regime backtest (FRF-011)
- **Category:** regime. **DET:✖ HR:✔ MC:✖**
- **Invariant:** regime metrics come from the repaired cycle backtest run within
  each window (re-struck legs, window-local data), not a single terminal payoff;
  `avg_dvol` is observed DVOL or is renamed `realized_vol`.
- **Expected:** regime P&L varies with in-window path, not just endpoints. **Module:** `strategy/regimes.py`.

### AT-012 — execution-sensitivity persisted (FRF-012)
- **Category:** execution. **DET:✖ HR:✔ MC:✖**
- **Invariant:** `execution_sensitivity.parquet` contains computed numeric rows =
  the Cartesian product of configured axes (spot offset × fee base [× spread/ADV
  where configured]), not stringified config; tranche totals reconcile to the
  configured BTC quantity.
- **Expected:** row count == product of axes; values numeric. **Module:** `research/runner.py:514-521,631-635`, `execution/waterfall.py`.

### AT-021 — Monte Carlo methodology (FRF-021)
- **Category:** MC. **DET:✖ HR:✖ MC:✔**
- **Invariant:** MC is multi-cycle consistent with the repaired lifecycle
  (re-strike + per-cycle repricing along each path); results are model-keyed (GBM
  and Merton both persisted, no overwrite); CSP capital = strike notional;
  drift/jump params carry ASSUMED provenance with sensitivity output.
- **Expected:** GBM and Merton rows both present and distinct; CSP capital ≠ 0.
- **Module:** `strategy/monte_carlo.py`, `research/runner.py`. **Precondition:** MS-26 approved sim spec.

### AT-024 — vol analytics (FRF-024)
- **Category:** vol. **DET:✖ HR:✔ MC:✖**
- **Invariant:** surface parses actual strikes from instrument names; GARCH
  forecast is out-of-sample; annualisation uses 365; Ljung-Box returns real
  statistics; single DVOL client with decimal convention.
- **Expected:** surface fit RMSE measured on held-out quotes (not ~0). **Module:** `vol/surface.py`, `vol/garch.py`, `vol/dvol_feed.py`.

### AT-027 — stress replay realism (FRF-027)
- **Category:** stress. **DET:✖ HR:✔ MC:✖**
- **Invariant:** `shock_type="replay"` scenarios consume observed historical
  windows; synthetic bridges are `shock_type="synthetic"`/SIMULATED; settlement
  shock models delivery-price basis vs spot.
- **Expected:** replay path == an observed window; labels correct. **Module:** `strategy/scenarios.py`, `strategy/stress.py`. **Decision:** D-11 (pre-2024 windows).

### AT-022 — results governance gates (FRF-022)
- **Category:** governance. **DET:✖ HR:✔ MC:✔**
- **Invariant:** value-plausibility gates reject a completed run whose premium
  exceeds a configured %-of-notional bound or whose ledger fails AT-004; the CLI
  exits non-zero on missing outputs; `.latest_*` pointers reference only
  gate-passing runs; manifests carry git SHA + environment + per-file checksums.
- **Expected:** an implausible-premium or unreconciled run cannot be marked
  completed. **Module:** `research/runner.py:_validate_results`, run registry.
- **Source:** FRONTIER_ORCHESTRATION §6/§8.

---

## Blocking summary

| Gate | Tests that must pass |
|---|---|
| **Deterministic repair (Stage 2)** | AT-031, AT-032, AT-033, AT-001, AT-002, AT-003, AT-004, AT-005, AT-006, AT-007, AT-013, AT-014, AT-015, AT-016, AT-019, AT-020, AT-023, AT-025, AT-026, AT-029, AT-030 |
| **Historical research (Stage 3)** | all DET tests that carry HR + AT-008, AT-009, AT-010, AT-011, AT-012, AT-017, AT-022, AT-024, AT-027, AT-028 |
| **Large Monte Carlo** | all DET/HR tests that carry MC + AT-021, plus approved simulation methodology (MS-26) and a reconciled ledger (AT-004) |

No historical research runs until the HR set passes. No large Monte Carlo until
the MC set passes AND MS-26 is approved. No "best/optimal" claim until an
objective function (MS-25) is approved and supported by evidence.
