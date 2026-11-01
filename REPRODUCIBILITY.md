# Reproducibility

## Environment

| Item | Value |
|---|---|
| Python | 3.12 (tested with 3.12.15) |
| Dependency manager | `uv` (recommended) or `pip` |
| OS tested | macOS arm64 |
| Network required | no, for the test suite |

## Install

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

## Run

```bash
.venv/bin/python -m pytest                 # full offline suite
.venv/bin/python -m vol.reprice_gate       # per-tenor repricing gate
.venv/bin/python -m execution.waterfall    # economic waterfall
```

## Test result at export

```
917 passed, 6 skipped in 469.65s (Python 3.12.15, 2026-11-01)
```

The skipped tests are network-marked (`--run-network` enables them) or marked
expected-failure pending a frozen business decision. `pyproject.toml` sets
`--strict-markers`, so an unregistered marker fails the run.

## Determinism

- Monte Carlo paths are seeded from `engine`/`config` seeds; tests assert seeded
  reproducibility.
- Exchange inputs are frozen fixtures under `tests/fixtures/` and
  `market_snapshots/`; no test fetches live data.
- The reprice gate asserts exact regression anchors for the recorded snapshot.

## Data

No bulk market data is downloaded during install or test. The recorded snapshots are
committed as JSON/CSV fixtures and are sufficient for every offline test. Live data
commands (`vol.dvol_feed`) use public, unauthenticated Deribit endpoints and are not
part of CI.

## Known limits

- The engine prices and risks a *proposed* structure under stated assumptions. It does
  not predict returns and is not investment advice.
- Calibration quality depends on the recorded surface; the committed gate is the
  honest, measured ~97.6% on the traded ~1-month tenor, not a tenor-averaged figure.
- Business decisions that were unresolved at the source freeze (fee base, reference
  price source, put-sleeve consent) remain explicit configuration variants and
  xfail-tagged tests; see `contracts.md` §D.
