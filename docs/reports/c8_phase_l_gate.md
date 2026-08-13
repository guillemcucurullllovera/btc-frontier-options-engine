# C8 Phase L — Laddered Overlay + Review Fixes (Gate Report; SIMULATED / diagnostic)

Snapshot as of **2026-07-30T10:43:16.778096+00:00**; S0 **64,509.34**. Per-tenor ATM IV: 28AUG26 **0.3402**, 25SEP26 **0.3619**; realised **0.3152** (VRP spread +0.0250); r 0.0 (observed (deribit interest_rate)). Additive to R1-R3 (unchanged). 15,000 paths/config.

## 1. One-shot vs laddered — covered call & collar (fixed 10% cap; N=1 one-shot; drift 0 = choppy)

| Structure | N | tenor | premium %spot | upside given up/BTC | participation | efficiency | ITM freq | tcost/BTC | ES97.5 %cap +/- SE |
|---|---|---|---|---|---|---|---|---|---|
| covered_call | 1 | 56d | 2.22% | 1,042 | 0.669 | 1.376 | 0.197 | 19 | 23.8% +/- 0.24 |
| covered_call | 2 | 28d | 1.61% | 808 | 0.754 | 1.285 | 0.128 | 39 | 24.5% +/- 0.24 |
| covered_call | 4 | 14d | 0.96% | 437 | 0.878 | 1.415 | 0.058 | 77 | 25.2% +/- 0.24 |
| collar | 1 | 56d | 2.22% | 1,042 | 0.669 | 0.273 | 0.197 | 39 | 10.1% +/- 0.00 |
| collar | 2 | 28d | 1.61% | 808 | 0.754 | 0.341 | 0.128 | 77 | 18.6% +/- 0.04 |
| collar | 4 | 14d | 0.96% | 437 | 0.878 | 0.508 | 0.058 | 155 | 23.4% +/- 0.19 |

**Upside participation by regime (VRP), covered call, N=1 -> 4** (fraction of unhedged upside retained):

| regime | N=1 | N=2 | N=4 |
|---|---|---|---|
| trend_down | 0.688 | 0.760 | 0.880 |
| choppy_flat | 0.669 | 0.754 | 0.878 |
| trend_up | 0.649 | 0.745 | 0.875 |

**Honest finding (computed, not assumed):** at a *fixed* 10% cap distance, laddering (N=4, 14d tranches) RETAINS MORE upside and has LOWER assignment, but collects LESS premium (shorter tenors are deeper OTM) and costs ~4x the transaction fee — the operator's 'same ~2% premium' does NOT hold. To collect equal premium you must sell closer strikes, which raises assignment. A single sharp intra-cycle gap is still fully capped inside its tranche. Full drift band x both vol regimes in JSON.

## 2. REVIEW FIX 1 — CVaR frontier on a consistent total-portfolio (holder) basis

Every row = the 30,000-BTC holding + the structure (a CSP/call-spread on the holding ADDS exposure), so VaR/ES are comparable — the standalone CSP/call-spread no longer falsely appear as tightest-budget.

| Loss budget %cap | # admissible | admissible structures | max-expected point | E[P&L] |
|---|---|---|---|---|
| 30% | 5 | collar@5%, collar_ladder_N2, collar_ladder_N4, covered_call_ladder_N2, covered_call_ladder_N4 | covered_call_ladder_N2 | -2,904,613 |
| 40% | 7 | collar@10%, collar@5%, collar_ladder_N2, collar_ladder_N4, covered_call@5%, covered_call_ladder_N2, covered_call_ladder_N4 | covered_call@5% | 49,396,798 |
| 50% | 13 | call_spread@10%, call_spread@5%, collar@10%, collar@5%, collar_ladder_N2, collar_ladder_N4, covered_call@10%, covered_call@5%, covered_call_ladder_N2, covered_call_ladder_N4, partial_overlay@10%, partial_overlay@5%, strike_ladder@10% | covered_call@5% | 49,396,798 |
| 60% | 15 | call_spread@10%, call_spread@5%, cash_secured_put@10%, collar@10%, collar@5%, collar_ladder_N2, collar_ladder_N4, covered_call@10%, covered_call@5%, covered_call_ladder_N2, covered_call_ladder_N4, long_btc_plus_short_put@10%, partial_overlay@10%, partial_overlay@5%, strike_ladder@10% | covered_call@5% | 49,396,798 |
| 70% | 17 | call_spread@10%, call_spread@5%, cash_secured_put@10%, cash_secured_put@5%, collar@10%, collar@5%, collar_ladder_N2, collar_ladder_N4, covered_call@10%, covered_call@5%, covered_call_ladder_N2, covered_call_ladder_N4, long_btc_plus_short_put@10%, long_btc_plus_short_put@5%, partial_overlay@10%, partial_overlay@5%, strike_ladder@10% | covered_call@5% | 49,396,798 |

Pareto-efficient on the holder basis: collar_ladder_N2, collar_ladder_N4, covered_call_ladder_N2, covered_call@5%. The collar (floored tail) and laddered overlays enter at the tightest budgets; D-10 selects the point (not a ranking).

## 3. REVIEW FIX 2 — EVT tail, GBM vs Merton (jump-diffusion) — LBSP@5%, drift 0, VRP

| Model | method | ES97.5 %cap | GPD xi |
|---|---|---|---|
| GBM | empirical | 73.8% | - |
| GBM | evt_gpd | 74.1% | -0.231 |
| GBM | cornish_fisher | 73.1% | - |
| Merton | empirical | 88.6% | - |
| Merton | evt_gpd | 88.8% | -0.213 |
| Merton | cornish_fisher | 88.3% | - |

GBM GPD xi=-0.231 (bounded tail); Merton GPD xi=-0.213. The jump-diffusion's heavier tail raises ES — crypto crash risk is not understated. The VRP is compensation for exactly this jump/crash risk (Alexander-Imeraj; McNeil QRM Ch.5).

## 4. Discipline

All SIMULATED/diagnostic; additive (R1-R3 unchanged); pending_decision_refs D-1, D-4, D-7, D-9, D-10, MS-25, MS-26 carried; laddered overlay is another admissible configuration (no ranking/optimality — MS-25); no MS-25/MS-26/CSCV claim; snapshot-cited. **Gate — packaging not started.**
