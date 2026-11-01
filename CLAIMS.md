# Claims

Every quantitative or capability claim in the README is listed here with the test or
committed artefact that demonstrates it. A claim without evidence is marked
`unsupported` and must not be repeated elsewhere.

| # | Claim | Evidence | Status |
|---:|---|---|---|
| 1 | The full test suite passes offline: 917 passed, 6 skipped (Python 3.12.15) | `tests/`, measured 2026-11-01 | verified |
| 2 | Deribit inverse-BTC option prices and settlement match published golden vectors and remain self-consistent | `tests/test_inverse_deribit_golden.py`, `tests/test_inverse_consistency.py` | verified |
| 3 | The SVI/SSVI surface fit respects no-arbitrage constraints on the recorded chain | `tests/test_surface_svi.py`, `tests/test_calibration.py` | verified |
| 4 | The SVI surface reprices the observed chain within 2.5% (~97.6%) on the traded ~1-month tenor, scored per tenor rather than averaged | `tests/test_reprice_gate_per_tenor.py`, `vol/reprice_gate.py` | verified |
| 5 | Characteristic-function pricers agree with the Haug golden table and with QuantLib within the documented tolerances | `tests/test_haug_goldens.py`, `tests/test_cf_characteristic_functions.py`, `tests/test_cf_numerical_invariance.py` | verified |
| 6 | The COS pricer converges to the reference price as the truncation range and term count increase | `tests/test_cos_pricer.py` | verified |
| 7 | Monte Carlo estimators report consistent standard errors and variance reduction from antithetic variates | `tests/test_mc_statistics.py` | verified |
| 8 | Backtest outputs are accompanied by PBO/DSR/deflated-Sharpe overfitting diagnostics | `strategy/deflated_sharpe.py`, `tests/test_client_numbers_regression.py`, `tests/test_phase0.py` | verified |
| 9 | Execution cost uses the Kissell I-Star market-impact formulation with explicit, provenance-tagged parameters | `execution/impact.py`, `tests/test_a3.py`, `tests/test_frontier_acceptance.py` | verified |
| 10 | Fee and economic waterfall outputs cover spot and fee-base sensitivities | `execution/waterfall.py`, `tests/test_client_numbers_regression.py` | verified |
| 11 | The test suite does not require network access | `pyproject.toml` (`network` marker), `tests/test_research_runner.py` fixture checks | verified |
| 12 | The engine produces a positive expected return on any strategy | — | **unsupported** |
| 13 | The options overlay is suitable for a specific investor | — | **unsupported** |

Claims 12 and 13 are deliberately marked unsupported: the engine computes structure
economics and risk under stated assumptions, not forecasts or advice.

## Status definitions

- **verified** — a test or reproducible check demonstrates the claim.
- **measured** — an experiment produced the number, with a manifest and checksum.
- **unsupported** — no evidence. It may not be presented as a result.

## Rules

1. No claim without a number, a test, or an explicit limitation.
2. No hardware, speed or return advantage claim without a dated benchmark and a scope
   statement.
3. A falsified claim is moved to `retracted` and a correction is issued; it is not
   deleted.
