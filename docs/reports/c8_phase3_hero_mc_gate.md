# C8 Phase 3 — Hero Rolling-Lifecycle MC Gate Report

**Status:** Phase 3 complete; gated for orchestrator review before Phase 4.
**Nature:** DIAGNOSTIC / SIMULATED only. Per FRONTIER_ORCHESTRATION §8 and the pending MS-26
(approved simulation methodology), these outputs are labelled SIMULATED and are **not decision
evidence**. No ranking, optimality, or convergence claim is made (MS-25 also pending).

Built off the committed anchor `market_snapshots/2026-07-30T104316Z/` (t0 = 2026-07-30T10:43Z).

---

## 1. Gates

| Gate | Result |
|---|---|
| `pytest` | **606 passed, 3 skipped** (+10 Phase-3 tests) |
| `mypy .` | clean (63 source files, strict) |
| `ruff check .` | clean |
| anonymisation | clean |
| **reconciles** | **True** — 60/60 configs completed |
| **cross-seed variance non-zero** | **True** — every (hero, strike, model) group |
| **non-finite outputs** | **0** |
| base-metric reconciliation to the C7 engine | rtol **1e-9** (tested, both heroes) |
| scalar-vs-vectorized oracle (extended metrics) | exact (P&L, max-DD, ITM, touch, leg split) |

New code: `strategy/hero_lifecycle_mc.py`, `scripts/run_c8_hero_campaign.py`,
`tests/test_c8_hero_mc.py`. The C7 module (`strategy/multi_cycle_mc.py`) is reused unchanged —
its 596-test suite is not regressed; the extended metrics live in the new Phase-3 module whose
independent per-path economics double as the reconciliation oracle.

---

## 2. Calibration (to the live snapshot — not the ASSUMED 0.45)

| Input | Value | Provenance |
|---|---|---|
| Volatility | **0.3402** (28AUG26 ATM IV, ~28.9d) | calibrated, snapshot (coherence guard a: near-tenor ATM IV) |
| DVOL (reported) | 0.3589 | OBSERVED (deribit) — headline only, not the scaler |
| Risk-free r | **0.0** | OBSERVED (deribit interest_rate) |
| Initial spot S0 | 64,509.34 | OBSERVED (deribit index) |
| Drift | 0.10 | **ASSUMED** (SIMULATED) — not a return forecast; surfaced |
| Cadence / cycles | **29d × 12** | real ~29-day monthly re-strike lifecycle |
| Capital base | 1,935,280,200 (30,000 × S0) | reference notional |

The rolling lifecycle re-strikes every cycle at `entry × (1 ± strike_target_pct)` — the "timeline…
and so forth" monthly roll. GBM and Merton (jump-diffusion) are run separately.

---

## 3. Chosen path count

Right-sized to a this-week timeline (not another full 60M): **2 heroes × 3 strike tiers × 2 models
× 5 seeds = 60 configs × 50,000 paths = 3,000,000 simulated paths**. Each config = 12 cycles ×
29 daily steps. Deterministic per (seed, config); antithetic diffusion. Runtime ≈ 75 s.

Strike tiers: covered_call {5, 10, 15}% OTM calls; long_btc_plus_short_put {3, 5, 10}% OTM puts.
Seeds {101…105}. (Paths depend only on spot/vol/drift/model/seed, not strike.)

---

## 4. Per-hero Slide-5 metric set (mean across seeds × strikes × models; SIMULATED)

Presented at parity, factually, with **no ranking** (MS-25 pending). VaR95 = −(5th-percentile P&L);
ES97.5 = mean loss in the worst 2.5% tail; % of the 1.935B capital base.

| Metric | Covered Call | Long BTC + Short Put |
|---|---|---|
| probability-of-loss | 0.468 | 0.462 |
| VaR95 (USD / % cap) | 735,101,747 / 38.0% | 1,143,649,738 / 59.1% |
| ES97.5 (USD / % cap) | 966,662,723 / 49.9% | 1,533,668,130 / 79.2% |
| EAC (USD/BTC) | 66,903 | 64,433 |
| max drawdown mean (USD / % cap) | 514,768,168 / 26.6% | 768,132,850 / 39.7% |
| max drawdown p95 (USD) | 971,532,018 | 1,532,194,493 |
| ITM frequency (per cycle) | 0.195 | 0.263 |
| touch frequency (per cycle) | 0.329 | 0.467 |

**BTC-inherent vs overlay decomposition** (carried into the MC):

| Leg | Covered Call | Long BTC + Short Put |
|---|---|---|
| holding (BTC-inherent) mean P&L | +194,095,853 | +194,095,853 |
| overlay (advised, pre-fee) mean P&L | −62,125,334 | +11,960,818 |
| structuring fee (D-1, separate) | 9,676,401 | 9,676,401 |

The holding leg is identical (both hold the same 30,000 BTC); the tail-risk and drawdown metrics
are dominated by the BTC-inherent leg, with the overlay modifying them (the covered-call short
calls give back upside under the assumed bull drift; the short puts collect net premium but add
downside). This is a diagnostic decomposition, not a recommendation.

---

## 5. Reconciliation & integrity

- **Base P&L distribution** (mean/median/std/p5/p1) reconciles to `strategy.multi_cycle_mc`
  (the C7 engine) to **rtol 1e-9** for both heroes — same deterministic paths, independently
  re-implemented economics (`test_base_reconciles_c7_engine`).
- **Extended per-path metrics** (max drawdown, ITM/touch counts, holding/overlay split, EAC)
  reconcile a vectorised pass against an independent scalar single-path oracle
  (`test_scalar_oracle_matches_vectorized`).
- **Determinism** (same seed → identical), **cross-seed variance non-zero**, **0 non-finite**
  asserted at test scale and confirmed on the 3M-path campaign.

---

## 6. Coherence guards & decision-gate discipline

- **(a) Per-tenor σ:** vol calibrated to the near-tenor (28AUG26) ATM IV for the ~29d cadence;
  DVOL is headline only. **(b)** Phase-1 realised vol already computed over tenor-matched windows
  (~29d, ~57d).
- Grid/MC are **unhedged (D-9)** — greeks shown (deterministic grid), no delta-hedge P&L applied.
- **D-10 loss-budget-neutral:** the full loss spectrum is presented across strikes × models × seeds;
  no single budget assumed.
- **D-4/D-7 scope-neutral:** both heroes analysed as alternatives; neither presented as the
  committed live trade.
- **Drift = 0.10 is ASSUMED** (SIMULATED), surfaced — not a forecast.
- `pending_decision_refs = (D-1, D-4, D-7, D-9, D-10, MS-25, MS-26)` attached to every result.
  No claim requiring MS-25 (ranking/objective), MS-26 (approved sim methodology), or CSCV/PBO/DSR
  is made.

Campaign evidence: `<anchor>/c8_hero_mc_campaign.json` (per-config results + cross-seed aggregate;
git-ignored bulk, regenerable via `scripts/run_c8_hero_campaign.py`).

---

## 7. What Phase 4 / Phase 5 consume

Phase 4 emits the evidence & deck-input pack (grid CSV+JSON, Slide-2 / Slide-2-continued data pack,
σ-scenario tables, the Slide-5 MC metric tables above, disclaimer, updated
`presentation_master_brief.md` figures). Phase 5 runs the whole-system gates + handover.
**Phase 3 does not begin Phase 4 until this gate is reviewed.**
