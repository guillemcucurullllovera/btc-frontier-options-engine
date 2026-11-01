# BTC Frontier Options Engine

Structure, price, calibrate and risk-analyse option overlays on a large BTC holding,
priced off Deribit inverse options. The engine is a layered research system: every
value carries a provenance tag (`OBSERVED`, `CALCULATED`, `ASSUMED`, `P-ESTIMATED`,
`Q-CALIBRATED`), and every client-facing number is generated from configuration
rather than hard-coded.

This repository is the engine of record exported from the originating private
repository. See [`PROVENANCE.md`](PROVENANCE.md) for the exact source commit and the
reviewed export procedure.

## What is implemented

| Layer | Modules | Content |
|---|---|---|
| Data | `vol/client.py`, `vol/history.py`, `vol/binance.py`, `vol/snapshot.py` | Deribit public API client (spot, DVOL, chain, book summary), archived surface snapshots, Binance spot history, provenance tagging |
| Surface | `vol/svi.py`, `vol/surface.py`, `vol/chain_surface.py`, `vol/rnd.py` | SVI / SSVI fits with no-arbitrage checks and a risk-neutral density |
| Pricing | `pricing/cf/`, `pricing/inverse.py`, `pricing/black_scholes.py`, `pricing/black76.py`, `pricing/payoff.py` | Characteristic-function stack (Heston, Bates, SVJJ, rough Heston), COS and saddlepoint pricers, Deribit inverse-BTC settlement formulas, Black-76 |
| Calibration | `vol/calibrate.py`, `vol/model_selection.py`, `vol/jumps.py`, `vol/svcj_mcmc.py` | Calibration and model selection, jump estimation, SVCJ MCMC |
| Monte Carlo | `strategy/monte_carlo.py`, `strategy/svjj_sim.py`, `strategy/hero_lifecycle_mc.py`, `strategy/multi_cycle_mc.py` | GBM, Merton and Kou jump-diffusion, SVJJ simulation, antithetic variates, multi-cycle lifecycle paths |
| Strategy | `strategy/definitions.py`, `strategy/definitions_multileg.py`, `strategy/laddered_overlay.py`, `strategy/strategy_grid.py`, `strategy/backtest*.py` | Covered call, cash-secured put, long BTC plus short put, call spread, collar, delta-solved strike ladders, backtest and reprice gates |
| Risk | `risk/tail.py`, `risk/cvar_frontier.py`, `risk/svjj_tails.py`, `risk/extrapolation_guard.py`, `strategy/deflated_sharpe.py` | VaR/ES, CVaR frontier, tail extrapolation guards, deflated Sharpe, PBO/DSR overfitting diagnostics |
| Execution | `execution/impact.py`, `execution/tranches.py`, `execution/waterfall.py`, `execution/fees.py` | Kissell I-Star market impact, tranche scheduler over the DTE ladder, fee waterfall and sensitivity |
| Core | `engine/`, `config/` | Provenance-tagged data models, settlement engine, fixture loading, typed configuration |

`contracts.md` is the frozen interface specification the modules implement.
`agents/` retains the original per-module implementation briefs.

## Quickstart

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
```

Or with pip:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

No network access is required for the test suite: all exchange inputs are recorded
fixtures under `tests/fixtures/` and `market_snapshots/`. Network-marked tests are
opt-in (`--run-network`).

### Running an experiment

```bash
.venv/bin/python -m execution.waterfall        # fee/economic waterfall at reference spot
.venv/bin/python -m vol.dvol_feed              # live Deribit public data (network)
.venv/bin/python -m vol.reprice_gate           # per-tenor repricing gate on fixtures
.venv/bin/python -m research.runner            # research pipeline
```

## Test status

Measured on the export commit with Python 3.12.15:

```
917 passed, 6 skipped in 469.65s
```

The skipped tests are network-marked or expected-failure markers tied to frozen
business decisions; `pyproject.toml` enables `--strict-markers`, and CI fails on an
unknown marker.

## Layout

```
config/            typed configuration and the parameter file of record
engine/            provenance-tagged models, settlement, fixtures
vol/               data acquisition, surfaces, calibration, dividends/jumps
pricing/           characteristic functions, inverse options, payoffs
strategy/          payoff definitions, backtests, Monte Carlo, overfitting checks
risk/              tail risk, CVaR, extrapolation guards
execution/         impact, tranching, fee waterfall
research/          experiment runner and manifests
tests/             unit, property, golden-vector and acceptance tests
docs/              architecture, requirements, evidence and research reports
market_snapshots/  recorded public exchange snapshots used for replay
```

## Evidence and claims

`CLAIMS.md` maps each README-level claim to a test or a committed artefact.
`docs/reports/` contains the original research and validation reports; where a report
is superseded by `contracts.md` or `docs/requirements/authoritative_corrections.md`,
the latter wins. The engine is research software: it is not investment advice, and
no output is a forecast of returns.

## Licence

Apache License 2.0. See `LICENSE` and `NOTICE`. Third-party dependencies and their
licences are listed in `PROVENANCE.md`.
