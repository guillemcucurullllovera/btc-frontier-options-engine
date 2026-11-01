# Provenance

## Origin

This repository is a reviewed export of the first-party `btc_engine_frontier`
repository operated by the author.

| Field | Value |
|---|---|
| Originating repository | `btc/btc_engine_frontier` |
| Source branch | `main` |
| Source commit | `48a19bb9376e3e24c36cc1c30f075471413e4300` |
| Source commit date | 2026-08-13 |
| Original author of record | Guillem Carlos `<info@asymmetrica-investments.com>` |
| Export date | 2026-11-01 |

The export preserves the original commit history (69 commits, same authorship) for
all retained paths. Commits are rewritten only in the technical sense that paths
excluded from publication are removed from history; commit messages, timestamps and
authorship are unchanged.

The following paths were excluded from the published export because they are internal
build-orchestration material rather than part of the engine:

- `prompts/` — AI implementation prompts;
- `.opencode/`, `opencode.json`, `CLAUDE.md`, `AGENTS.md`,
  `FRONTIER_ORCHESTRATION.md`, `.latest_research_*` — agent orchestration and
  session markers;
- `docs/reports/external_reviews/` — third-party review transcripts.

No implementation, test, fixture, configuration or research report was altered by the
export. The repository name, `README.md`, `LICENSE`, `NOTICE`, `CLAIMS.md`,
`CONTRIBUTING.md`, `SECURITY.md`, `CITATION.cff`, `REPRODUCIBILITY.md` and the
packaging metadata were added or rewritten for standalone publication.

## Licence

On 2026-11-01 the portfolio owner explicitly confirmed authority to redistribute
and license the first-party code in this release. That confirmation supports the
first-party Apache-2.0 release; it does not transfer authorship or grant rights to
third-party code or exchange data. Original attribution above remains unchanged.

The CI remediation changes dependency metadata only: SciPy typing stubs are now
included in the pip-installable development extra, and the lockfile includes
patched certifi and urllib3 versions. No exchange dataset or implementation is
added or relicensed by that remediation. Independent exchange-data redistribution
permission remains unverified; the existing snapshot caveat below still applies.

The first-party code, tests, documentation and recorded research outputs are released
under the Apache License 2.0 (`LICENSE`). The original repository carried no licence
file; the rights holder has confirmed the right to redistribute this material.

## Third-party software

Direct dependencies declared in `pyproject.toml`:

| Dependency | Licence | Use |
|---|---|---|
| numpy | BSD-3-Clause | arrays and linear algebra |
| scipy | BSD-3-Clause | special functions, optimisation, integration |
| requests | Apache-2.0 | HTTP client for public exchange APIs |
| pydantic | MIT | typed configuration models |
| PyYAML | MIT | configuration parsing |
| arch | NCSA | GARCH / EGARCH estimation |
| statsmodels | BSD-3-Clause | diagnostics and regression utilities |

Test and development only:

| Dependency | Licence | Use |
|---|---|---|
| pytest | MIT | test runner |
| hypothesis | MPL-2.0 | property-based testing |
| QuantLib | BSD-3-Clause (QuantLib licence) | independent pricing oracle |
| pyarrow | Apache-2.0 | parquet fixtures |
| pandas | BSD-3-Clause | tabular fixtures |
| ruff | MIT | linter |
| mypy | MIT | type checker |

No GPL or AGPL dependency is required at runtime. No third-party source code is
vendored in this repository.

## Market data

`market_snapshots/` and `tests/fixtures/` contain values obtained from public,
unauthenticated Deribit and Binance market-data endpoints (index price, mark
implied volatility, instrument definitions, book summaries, spot bars). They are
recorded to make tests reproducible. They contain no account, counterparty, wallet or
order information, and their publication does not imply endorsement by either
exchange. Consult the relevant exchange terms before redistributing them further.

## Confidentiality

The repository was scanned before publication:

- `gitleaks git --log-opts=--all` over the complete published history: no findings;
- the repository's own `scripts/anonymisation_scan.py`: no findings;
- manual review for credentials, wallet addresses, absolute server paths in retained
  source, client identifiers and personal data.

No credentials, environment files, production databases, backtest caches or private
reference-library documents are included.

## Notes on retained operational scripts

`scripts/` is published as-is because it records how the research artefacts were
produced. A handful of one-off campaign runners contain absolute paths from the
originating host (for example under `/home/francisco/btc/`). They are not required to
install, import or test the engine, and they are not used by CI. No credential, `.env`
file or dataset from those paths is included.
