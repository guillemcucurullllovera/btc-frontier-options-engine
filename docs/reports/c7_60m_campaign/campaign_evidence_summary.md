# C7 Post-Remediation 60M Campaign — Evidence Summary (SIMULATED / DIAGNOSTIC)

Generated: 2026-07-30T07:25:36.996556+00:00

> **Provenance & governance.** Every number here is SIMULATED (Monte Carlo).
> Volatility, drift and jump parameters are ASSUMED/uncalibrated. Per
> FRONTIER_ORCHESTRATION.md §8 this is a diagnostic run only: **no strategy is
> ranked, preferred or called optimal**, and no convergence is claimed from the
> path-count tiers. MS-25 (objective function) and MS-26 (simulation methodology)
> remain unresolved. D-1=reference_notional and D-12=cash_settled are UNRESOLVED
> business decisions (alternative variants emitted by run_c7_fasttrack_suite).

## Campaign structure
- Model: Merton (single). Seeds: [101, 211, 307, 401, 503, 601, 701, 809, 907, 1009, 1103, 1201].
- Tiers (paths/seed): [500000, 1500000, 3000000].
- Strategies (shared paths): ['cash_secured_put', 'collar', 'covered_call', 'lbsp', 'partial_50', 'unhedged'].
- Distinct configs: 36  |  Aggregate simulated paths: 60,000,000 (expected 60,000,000, reconciles=True).

## Cross-seed variance validation
- Cross-seed dispersion of ES95 is non-zero for hedged strategies: **True** (the prior campaign's fatal defect was zero cross-seed variance).

## Seed-mean outcome (USD) and tail risk by strategy x tier

| strategy | tier | mean_outcome_usd (seed-mean ± seed-std) | ES95 (seed-mean ± std) | P(loss) seed-mean |
|---|---|---|---|---|
| cash_secured_put | 500,000 | -38,808,575 ± 295,852 | 520,475,570 ± 1,100,443 | 0.5015 |
| cash_secured_put | 1,500,000 | -38,800,000 ± 208,631 | 520,284,936 ± 361,386 | 0.5016 |
| cash_secured_put | 3,000,000 | -38,829,996 ± 107,580 | 520,676,272 ± 260,206 | 0.5016 |
| collar | 500,000 | 165,882,508 ± 560,163 | 943,602,073 ± 745,098 | 0.4965 |
| collar | 1,500,000 | 165,654,230 ± 363,137 | 943,621,971 ± 591,414 | 0.4965 |
| collar | 3,000,000 | 165,708,136 ± 312,282 | 943,692,979 ± 375,296 | 0.4964 |
| covered_call | 500,000 | 136,823,932 ± 724,059 | 1,142,235,915 ± 890,593 | 0.5125 |
| covered_call | 1,500,000 | 136,604,230 ± 499,838 | 1,142,168,790 ± 746,399 | 0.5125 |
| covered_call | 3,000,000 | 136,628,139 ± 361,774 | 1,142,482,499 ± 481,191 | 0.5124 |
| lbsp | 500,000 | 163,553,387 ± 776,026 | 1,532,457,691 ± 1,915,999 | 0.5184 |
| lbsp | 1,500,000 | 163,281,762 ± 510,611 | 1,532,380,867 ± 826,077 | 0.5185 |
| lbsp | 3,000,000 | 163,375,012 ± 438,777 | 1,532,996,915 ± 623,588 | 0.5184 |
| partial_50 | 500,000 | 164,717,947 ± 655,931 | 1,176,907,043 ± 1,052,081 | 0.5118 |
| partial_50 | 1,500,000 | 164,467,996 ± 432,589 | 1,176,851,801 ± 672,000 | 0.5118 |
| partial_50 | 3,000,000 | 164,541,574 ± 371,308 | 1,177,100,529 ± 472,399 | 0.5117 |
| unhedged | 500,000 | 192,611,962 ± 636,468 | 1,230,688,495 ± 1,129,066 | 0.5132 |
| unhedged | 1,500,000 | 192,331,761 ± 414,876 | 1,230,696,759 ± 597,189 | 0.5132 |
| unhedged | 3,000,000 | 192,455,008 ± 403,593 | 1,230,923,677 ± 463,470 | 0.5132 |

## Files
- Aggregate: `aggregate_results/aggregate_by_strategy_tier.csv`
- Seed-level: `aggregate_results/seed_level_metrics.csv`
- Configuration summary: `evidence/configuration_summary.json`
- Source-to-number: `evidence/source_to_number_traceability.csv`

*Not decision evidence. For internal diagnostic review only.*