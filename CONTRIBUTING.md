# Contributing

## Licence and DCO

Contributions are accepted under the Apache License 2.0. Every commit must be signed
off under the Developer Certificate of Origin 1.1:

```bash
git commit -s -m "feat: ..."
```

The sign-off certifies that you have the right to contribute the code. There is no
Contributor License Agreement.

## Development

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/mypy pricing/ execution/ config/ engine/ vol/ risk/ strategy/
```

Before opening a pull request:

1. Add a test that fails without the change.
2. Run the full suite, the linter and the strict type check.
3. Update `CHANGELOG.md` and, if the change affects a claim, `CLAIMS.md`.
4. Keep the change focused; one logical change per pull request.

## Commit messages

Conventional Commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`,
`perf:`. The subject is imperative and at most 72 characters. The body explains why,
not what.

## Research integrity

- A price, calibration or risk number in a document must point to the test or
  committed artefact that produced it.
- Do not weaken a gate to make it pass. If the honest measured value is worse than a
  previously published claim, change the claim and record the correction.
- Market data must come from public, unauthenticated endpoints and carry a provenance
  tag. Do not commit account data, order data, counterparty data or anything obtained
  under an NDA.
- AI assistance is permitted for drafting, refactoring and test generation. The author
  is responsible for every line, and AI-generated numerical code must be checked
  against an independent oracle.

## Reporting a problem

For security issues, follow `SECURITY.md` rather than opening a public issue. For
incorrect results, open an issue with the command, the fixture, the observed output
and the expected output.
