# C8 R1-R3 Improvement Pass — Review Gate Report (SIMULATED / diagnostic)

Snapshot as of **2026-07-30T10:43:16.778096+00:00**; S0 **64,509.34**. Implied ATM IV **0.3402** (28AUG26, ~29d); realised vol **0.3152** [OBSERVED (massive spot history, 30d close-to-close, sqrt365)]; **variance-risk-premium spread +0.0250**; DVOL 0.3589; r 0.0 (observed (deribit interest_rate)).

Full-grid MC: 7 structures, drift band [-0.1, 0.0, 0.1] (ASSUMED, 0=no-view anchor), 2 vol regimes (fair-value / VRP), 3 seeds, 20,000 paths/config, GBM, 29d x 12 rolling cycles. total_non_finite=0. evidence sha256 `c31ec09eafe0cca46eeb3d42`.

> The VRP case sells options at the live implied IV while spot diffuses at the OBSERVED realised vol — the honest edge (implied > realised), not an assumed drift. The crash-risk tail remains (Alexander-Imeraj; Sinclair). MS-26 pending; no ranking/optimality claim.

## 1. Full-grid drift-band table (drift 0 shown; VRP vs fair-value; +/- bootstrap SE)

| Structure | regime | mean P&L +/- SE | VaR95 +/- SE (%cap) | ES97.5 +/- SE (%cap) | prob-loss +/- SE | overlay P&L |
|---|---|---|---|---|---|---|
| covered_call | fair_value | -9,530,238 +/- 3,937,964 | 793,307,453 +/- 4,972,362 (41.0%) | 995,914,830 +/- 6,444,177 (51.5%) | 0.560 +/- 0.004 | -227,763 |
| covered_call | vrp | 30,589,291 +/- 3,752,052 | 724,982,194 +/- 4,963,010 (37.5%) | 926,307,910 +/- 6,385,284 (47.9%) | 0.527 +/- 0.004 | 39,940,342 |
| long_btc_plus_short_put | fair_value | -8,664,455 +/- 5,926,806 | 1,217,729,819 +/- 8,026,248 (62.9%) | 1,565,651,972 +/- 11,498,949 (80.9%) | 0.554 +/- 0.003 | 638,020 |
| long_btc_plus_short_put | vrp | 45,692,085 +/- 5,472,252 | 1,088,630,725 +/- 7,790,996 (56.3%) | 1,427,947,648 +/- 11,246,513 (73.8%) | 0.520 +/- 0.003 | 55,043,135 |
| collar | fair_value | -9,500,915 +/- 3,456,344 | 664,948,846 +/- 3,863,245 (34.4%) | 829,085,693 +/- 4,364,406 (42.8%) | 0.571 +/- 0.004 | -198,440 |
| collar | vrp | -1,584,027 +/- 3,341,256 | 646,387,680 +/- 3,559,463 (33.4%) | 811,395,407 +/- 4,417,923 (41.9%) | 0.559 +/- 0.004 | 7,767,024 |
| partial_overlay | fair_value | -9,416,356 +/- 4,265,425 | 834,706,430 +/- 5,535,645 (43.1%) | 1,040,020,787 +/- 6,304,275 (53.7%) | 0.565 +/- 0.004 | -113,881 |
| partial_overlay | vrp | 10,619,120 +/- 4,000,095 | 776,213,427 +/- 5,552,307 (40.1%) | 978,734,529 +/- 6,244,303 (50.6%) | 0.548 +/- 0.004 | 19,970,171 |
| cash_secured_put | fair_value | -9,038,381 +/- 1,626,755 | 415,151,980 +/- 3,662,038 (21.5%) | 581,662,300 +/- 5,604,950 (30.1%) | 0.508 +/- 0.003 | 638,020 |
| cash_secured_put | vrp | 45,366,734 +/- 1,495,295 | 332,303,532 +/- 3,418,423 (17.2%) | 488,915,820 +/- 5,300,447 (25.3%) | 0.414 +/- 0.003 | 55,043,135 |
| call_spread | fair_value | -9,198,141 +/- 934,991 | 255,846,586 +/- 3,007,830 (13.2%) | 432,999,141 +/- 6,529,281 (22.4%) | 0.458 +/- 0.004 | 478,260 |
| call_spread | vrp | 8,740,431 +/- 891,002 | 224,343,894 +/- 3,084,599 (11.6%) | 388,785,745 +/- 5,974,522 (20.1%) | 0.403 +/- 0.004 | 18,416,832 |
| strike_ladder | fair_value | -9,420,058 +/- 3,827,091 | 774,371,314 +/- 4,785,766 (40.0%) | 976,177,217 +/- 6,410,012 (50.4%) | 0.559 +/- 0.004 | -117,583 |
| strike_ladder | vrp | 30,716,231 +/- 3,635,143 | 705,691,175 +/- 4,748,707 (36.5%) | 905,908,328 +/- 6,372,358 (46.8%) | 0.524 +/- 0.004 | 40,067,282 |

Full drift band {-0.10,0,+0.10} x both regimes per structure is in the evidence JSON. The VRP overlay is positive (earns implied-minus-realised); fair-value overlay ~ 0 (no edge). prob-of-loss stays BTC-inherent (dominated by the holding leg) even with the VRP edge.

## 2. EVT tail comparison — long_btc_plus_short_put@5% (drift 0, VRP) (ES is the coherent headline)

| Method | VaR97.5 | ES97.5 | %cap (ES) | GPD xi | threshold | n_exceed |
|---|---|---|---|---|---|---|
| empirical | 1,245,970,418 | 1,428,698,889 | 73.8% | - | - | - |
| evt_gpd | 1,251,146,613 | 1,433,969,067 | 74.1% | -0.231 | 883,595,597 | 4000 |
| cornish_fisher | 1,235,731,119 | 1,414,387,400 | 73.1% | - | - | - |

EVT/GPD fits the far tail (peaks-over-threshold, McNeil QRM Ch.5); Cornish-Fisher is the moment-based cross-check; ES (coherent) is the headline. The three methods agree closely. The GPD shape xi=-0.231 here is negative — a bounded tail under this GBM diffusion; a jump-diffusion (Merton) or the real market's crash risk, for which the VRP compensates, would fatten it.

## 3. CVaR loss-budget efficient frontier (beta=0.95, drift 0, VRP) — admissible set, not a ranking

| Loss budget (%cap) | # admissible | admissible structures | max-expected point | its E[P&L] |
|---|---|---|---|---|
| 20% | 3 | call_spread@10%, call_spread@5%, cash_secured_put@10% | cash_secured_put@10% | 22,496,917 |
| 30% | 5 | call_spread@10%, call_spread@5%, cash_secured_put@10%, cash_secured_put@5%, collar@5% | cash_secured_put@5% | 45,366,734 |
| 40% | 7 | call_spread@10%, call_spread@5%, cash_secured_put@10%, cash_secured_put@5%, collar@10%, collar@5%, covered_call@5% | covered_call@5% | 49,006,123 |
| 50% | 14 | call_spread@10%, call_spread@5%, cash_secured_put@10%, cash_secured_put@5%, collar@10%, collar@15%, collar@5%, covered_call@10%, covered_call@15%, covered_call@5%, partial_overlay@10%, partial_overlay@15%, partial_overlay@5%, strike_ladder@10% | covered_call@5% | 49,006,123 |
| 60% | 15 | call_spread@10%, call_spread@5%, cash_secured_put@10%, cash_secured_put@5%, collar@10%, collar@15%, collar@5%, covered_call@10%, covered_call@15%, covered_call@5%, long_btc_plus_short_put@10%, partial_overlay@10%, partial_overlay@15%, partial_overlay@5%, strike_ladder@10% | covered_call@5% | 49,006,123 |

Pareto-efficient candidates (the frontier): cash_secured_put@10%, cash_secured_put@5%, covered_call@5%, long_btc_plus_short_put@3%.
The client's **D-10 loss budget** selects a point on this frontier; the engine only draws it (no single pick — MS-25/MS-26/D-10 open). Collars enter at the tightest budgets (floored tail).

## 4. Discipline

All outputs SIMULATED/diagnostic; pending_decision_refs D-1, D-4, D-7, D-9, D-10, MS-25, MS-26 carried; VRP-vs-fair-value and the full drift band shown (never a single flattering case); no best/optimal/preferred/winning language; no claim requiring MS-25/MS-26/CSCV-PBO-DSR; every figure traces to the frozen snapshot. Tier-0 T0-1 (GARCH sqrt365) and T0-5 (q=0 provenance) fixed; DSR/PBO (T0-2/3) remain gated (no PBO/DSR number shown). **Review gate — Phase 5 packaging not started.**
