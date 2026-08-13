# C8 Phase 2 — Deterministic Strategy-Grid Gate Report

**Status:** Phase 2 complete; gated for orchestrator review before Phase 3.
**Discipline:** independent oracle reconciled to rtol 1e-9; `pytest`/`mypy .`/`ruff`/
anonymisation green; leg decomposition on every cell; no best/optimal/preferred/safest
language; multi-leg framing conventions documented and surfaced (not silently chosen).

Built off the committed promoted anchor `market_snapshots/2026-07-30T104316Z/`
(t0 = 2026-07-30T10:43:16Z, S0 = 64,509.34, r = 4.0% from `config/params.yaml`).

---

## 1. Gates

| Gate | Result |
|---|---|
| `pytest` | **586 passed, 3 skipped** (+18 Phase-2 oracle tests) |
| `mypy .` | clean (59 source files, strict) |
| `ruff check .` | clean |
| anonymisation | clean |
| Independent oracle reconciliation | premium / scenario P&L per leg / max-loss reconcile to **rtol 1e-9**; breakevens to 1e-7 (root-finder) |

New code: `strategy/strategy_grid.py` (engine), `scripts/build_strategy_grid.py` (driver),
`tests/test_c8_strategy_grid.py` (oracle). The grid JSON regenerates deterministically from the
committed anchor (`python scripts/build_strategy_grid.py`) and is not itself committed.

---

## 2. Grid schema

**Axes:** `{8-structure toolkit + 2 heroes} × strike% × the two real listed expiries × coverage
{25,50,75,100}%`. Each row prices at its own listed `mark_iv`. **170 rows** off the anchor.

Structures (all first-class, identical analytical treatment):

| structure_id | canonical kind(s) | hero | holding | cash | strike% swept |
|---|---|---|---|---|---|
| unhedged_baseline | (reference) | — | ✓ | — | n/a (1 row/expiry) |
| covered_call | covered_call (100%), **partial_overlay (<100%)** | ✓ | ✓ | — | calls {1.5,3,5,10,15} |
| long_btc_plus_short_put | long_btc_plus_short_put | ✓ | ✓ | — | puts {3,5,10} |
| cash_secured_put | cash_secured_put | — | — | ✓ | puts {3,5,10} |
| collar | collar | — | ✓ | — | calls {1.5,3,5,10,15} (put fixed 5%) |
| call_spread | call_spread | — | — | — | adjacent call widths |
| strike_ladder | partial_overlay | — | ✓ | — | rungs {5,10,15} (internal) |

`partial_overlay` is not a separate builder — it is the covered_call family at coverage < 100%,
and `classify()` assigns the PARTIAL_OVERLAY kind automatically, keeping it first-class.

**Per-row fields:** option legs (kind/side, requested %OTM + listed strike, own IV + provenance,
instrument, premium/BTC); premium (net /BTC, %spot, /contract, /portfolio + CEO 2% / deck 2.5%
markers); prob-win (risk-neutral N(d2), measure label, delta-proxy); max-loss 3-way (holding /
option / cash / total at the worst-case spot, %notional, %capital, capital, unbounded flag);
breakevens (a: strike %OTM, b: true terminal breakevens); greeks (option delta/gamma/vega/theta
per BTC, theta/day, total position delta); risk-reward (premium-to-max-loss, upside/downside over
±2σ); σ-normalised scenarios instantaneous + terminal (5 σ-steps, leg-decomposed, 3 granularities,
%-of-portfolio); a 5-point premium/theta decay series; attractive-when tag; disclaimer.

**Three granularities everywhere:** per-BTC (of the 30,000 block) / per CME 5-BTC contract /
per portfolio (30,000 BTC = 6,000 contracts).

---

## 3. Modeling frame + leg attribution (locked)

The client already HOLDS 30,000 BTC (spot acquired at t0). Every cell decomposes into:

- **Holding (BTC) leg** — `30,000 × (S − S0)`, MTM from t0 spot; the client's inherent exposure.
  Coverage-independent. Present for covered_call, LBSP, collar, strike_ladder, unhedged.
- **Cash/collateral leg** — cash-secured put only; P&L 0, but sets the effective net price.
- **Option leg(s)** — `coverage × 30,000 × Σ(premium ± payoff)`; the advised component.
- **Total** = holding + option (+ cash), reported separately in every cell.

Attribution is explicit and honest:
- **Covered call:** the overlay leg is a **non-negative premium cushion** in down-scenarios;
  the downside is BTC-inherent (holding leg). Verified per-row in tests.
- **Long BTC + short put:** the overlay leg goes **negative below the strike** — incremental,
  advised downside (slope +2 below strike, not the CEO's flat ×2). Verified per-row.
- **Cash-secured put / call spread:** no long-BTC leg — framed on their own terms (CSP = acquisition
  at an effective net price K − P; call spread = defined-risk, option-only).

The disclaimer reflects this and does **not** claim LBSP's sub-strike zone is "not attributable to
our advice."

---

## 4. Sample slice (28AUG26, 5% OTM, 100% coverage) — leg decomposition

**HERO 1 — Covered Call** (short call K=68,000, iv 0.3262):
- premium **1,126.90/BTC** (1.747% spot; /contract 5,634; /portfolio 33,806,946)
- prob-win **0.7209** [risk-neutral P(S_T<K)=N(−d2)], delta-proxy 0.6893
- max loss 3-way at S_T=0: holding **−64,509/BTC**, option **+1,127/BTC** (cushion), total **−63,382/BTC** = −(S0−P); −98.3% capital
- breakeven (true) 63,382 = S0−P; greeks: opt Δ −0.311, θ/day +38.26, total pos Δ 0.689
- terminal scenarios /BTC: −2σ **−11,221** (opt +1,127) · −1σ −5,047 · 0σ +1,127 · +1σ +4,618 · +2σ **+4,618** (capped)

**HERO 2 — Long BTC + Short Put** (short put K=61,000, iv 0.3679):
- premium **1,144.94/BTC** (1.775% spot); prob-win **0.6982** [P(S_T>K)=N(d2)]
- max loss 3-way at S_T=0: holding −64,509, option **−59,855** (advised downside), total **−124,364/BTC** = −(S0+K−P); −192.8% capital (exceeds BTC value — amplified downside, flagged)
- breakeven 63,364 = S0−P; terminal below-strike slope **+2.0** (verified); option leg negative below strike (verified)

**NON-HERO — Cash-Secured Put** (short put K=61,000, iv 0.3679):
- premium **1,144.94/BTC**; **effective net acquisition price 59,855 = K − P**
- no holding leg; max loss total −59,855/BTC = −(K−P); −98.1% of cash collateral (1,830,000,000)
- terminal: −2σ −7,693 · 0σ +1,145 · +2σ +1,145 (put expires OTM, premium kept)

---

## 5. Independent oracle (rtol 1e-9)

The grid's primary computation is an explicit closed-form leg decomposition. Two independent
oracles reconcile it (`tests/test_c8_strategy_grid.py`, 18 tests):

1. **Premium + instantaneous reprice** — a self-contained `math.erf`-based Black-Scholes, distinct
   from the scipy pricer the grid uses. Every option leg's premium reconciles to rtol 1e-9.
2. **Terminal scenario P&L / max-loss / breakevens** — the separately-written strategy engine
   (`strategy.payoffs`: `strategy_pnl`, `structural_max_loss`, `breakeven_points`) over an
   equivalently-constructed `Strategy`. Terminal totals and 3-way max-loss reconcile to 1e-9;
   breakevens to 1e-7 (brentq).

Additional property tests: full-toolkit parity (all 7 builders + partial_overlay kind present);
covered-call `q(S0−P)` and LBSP `q(S0+K−P)` identities; LBSP slope +2 below strike; covered-call
capped above strike (slope 0 at 100% coverage); overlay-leg attribution signs; greeks signs (short
call negative delta, positive theta, negative vega); prob-win labelled risk-neutral, never 80%.

---

## 6. Coherence guards (both honoured)

- **(a) Per-tenor σ:** scenario scaling uses each expiry's OWN ATM IV — 28AUG26 ATM_IV 0.3402
  (σ_h 0.0957) vs 25SEP26 ATM_IV 0.3619 (σ_h 0.1429). DVOL 35.89% is headline only, not the scaler.
  Verified in tests (`test_per_tenor_sigma_differs`).
- **(b) Realised-vs-implied per tenor:** Phase 1 already computes realised vol over windows matching
  each tenor (~29d, ~57d) plus the 30d DVOL window.

Time dimension: t0 = the execution-date anchor; DTE and greeks from t0. Per-row greeks (Δ/θ/vega)
and a 5-point premium/theta decay series make the option's time-evolution legible. The rolling
multi-cycle lifecycle is Phase 3; ATM here is a price threshold swept by the moneyness scenarios.

---

## 7. Surfaced for orchestrator — documented conventions, not business gates

These are grid-construction choices for multi-leg / parameter framing; all are labelled in the
grid's `framing_notes`. Flagging for confirmation (easy to change):

1. **Collar sweep:** short call over strike% {1.5,3,5,10,15}, protective long put fixed at 5% OTM.
2. **Call spread:** short call over strike%, long call at the next adjacent width (1.5/3, 3/5,
   5/10, 10/15).
3. **Strike ladder:** equal-weighted short calls at {5,10,15}% OTM at a single expiry (the existing
   multi-DTE ladder builder is a Phase-3 lifecycle concern; single-cycle here).
4. **Pricing bridge:** linear-USD Black-Scholes with Deribit `mark_iv` and USD r = 4.0%
   (`config/params.yaml`). Deribit options are inverse/BTC-settled; CME linear/USD. The bridge is
   an approximation the brief §2.7 sanctions; r is a config parameter (a variant is trivial to emit
   if a different rate is preferred).
5. **CSP / call-spread %-of-notional** uses block×S0 as the common denominator (no holding leg);
   %-of-capital uses the structure's own committed capital (cash collateral / defined risk).

**Pending business/methodology gates NOT resolved:** D-1 fee base, D-4/D-7 put-sleeve scope, D-9
hedge model, D-10 loss budget, MS-25 objective, MS-26 sim methodology, CSCV/PBO/DSR.

---

## 8. Comparative "choice matrix" framing

Each structure carries an "attractive when…" market-condition tag (a factual condition, not a
recommendation) — the computed successor to the qualitative Slide-2-continued choice matrix. All 8
remain first-class in the tests and (Phase 4) the evidence pack; they are not reduced to the two
heroes.

---

## 9. What Phase 3 consumes

`multi_cycle_mc` runs both heroes (covered_call, long_btc_plus_short_put) with the live-IV inputs
established here, across seeds × tiers, surfacing prob-of-loss / VaR / ES / EAC to complement this
deterministic grid — the rolling, re-strike-at-each-expiry lifecycle.

---

## 10. Post-approval amendment (orchestrator-directed, test-first)

Applied before Phase 3; gates re-verified (pytest **596p/3s**, mypy 60 files, ruff, anon clean;
+10 amendment tests; independent oracle extended to the new fields). Grid is now **210 rows**.

1. **Collar floor → 10% OTM** (deck Slide-4 ≈ −10%), short call still swept; a labelled **5%-floor
   variant** is also emitted (collar rows: 5 calls × 2 floors × 2 expiries × 4 coverage = 80).
2. **Call spread confirmed CREDIT** — SHORT lower strike / LONG higher strike (premium-generating);
   asserted per-row (`short.strike < long.strike`, net premium > 0).
3. **Strike ladder** stays single-expiry equal-weight {5,10,15}%; multi-DTE ladder is Phase 3.
4. **Risk-free r** now sourced **per-leg from Deribit `interest_rate` (OBSERVED)** where the book
   exists, else 4% config (ASSUMED, labelled per leg). On the anchor all listed legs resolve to
   **r = 0.0 OBSERVED** — more consistent with Deribit's own `mark_iv` forward; the covered-call
   5%-OTM premium moves 1,126.90 → **1,068.16/BTC**. `r_provenance` recorded on every leg + the grid.
5. **%-denominators labelled** per cell: `max_loss.notional_basis` (portfolio notional = 30,000×S0)
   and `max_loss.capital_basis` (BTC value / cash collateral / defined risk).
6. **Opportunity-cost field** added: `max(0, unhedged_total − structure_total)` on the total-portfolio
   view at +σ (net of premium — the brief's gross `max(0,S_T−K)·q` differs by the premium; noted).
   Covered-call 5% OTM: +1σ 1,615/BTC, +2σ 7,789/BTC. LBSP: 0 (matches/beats unhedged upside).
7. **Total-portfolio comparability**: every row emits BOTH a standalone view and a total-portfolio
   view (30,000-BTC holding + structure), so cash-secured put / call spread are comparable to
   holding-inclusive structures. Reconciled to the engine (`test_portfolio_view_reconciles_engine`).
   `unhedged_baseline` flagged `benchmark_only` (never featured/recommended).
8. **Structuring fee (D-1)**: a SEPARATE `FeeBlock` per row, **pre-fee grid** (never in scenario
   P&L), with both D-1 bases — reference-notional **$9,750,000** (0.5%×30,000×65,000) and
   executed-volume (0.5%×coverage×30,000×S0). References D-1.

**Decision-gate discipline honoured:** overlay grid is pre-structuring-fee (D-1 both variants
emitted separately); unhedged (D-9 — greeks shown, no delta-hedge P&L); full loss spectrum across
structures × strikes × coverage (D-10 neutral, no assumed budget); every structure analysed at
parity as scope-neutral (D-4/D-7 — none presented as the committed live trade).
**`pending_decision_refs` = (D-1, D-4, D-7, D-9, D-10, MS-25, MS-26)** attached to the grid and
every row. No claim requiring MS-25 (ranking/objective), MS-26 (approved sim methodology), or
CSCV/PBO/DSR is made. **Phase 3 does not begin until reviewed.**
