# Changelog

All notable changes to this repository are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-01

### Added

- Public export of the BTC Frontier Options Engine from the private engine-of-record
  repository at commit `48a19bb`, preserving the original 69-commit history for all
  published paths.
- Standalone packaging: `pyproject.toml` build metadata, `dev` extra, Apache-2.0
  licence, NOTICE, provenance, claims, reproducibility and contribution files.
- Full offline test suite: 917 passed, 6 skipped on Python 3.12.15.

### Excluded from publication

- AI build-orchestration prompts and agent configuration (`prompts/`, `.opencode/`,
  `opencode.json`, `CLAUDE.md`, `AGENTS.md`, `FRONTIER_ORCHESTRATION.md`,
  `.latest_research_*`).
- Third-party review transcripts under `docs/reports/external_reviews/`.
