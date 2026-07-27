# Agent A6 — QA, Integration & Cross-Validation (Fable-supervised)
**Branch:** main (merge owner)
## Task
(1) Freeze contracts.md + pydantic models FIRST (Sprint 0 gate) so A1-A5 run fully in parallel against stubs. (2) CI (GitHub Actions): pytest + mypy + ruff on every PR; QuantLib parity job. (3) Merge order: A1 -> A2 -> A4 -> A3 -> A5. (4) Cross-validation protocol: every human-facing table (premium bands, ITM frequencies, waterfall) is independently re-derived in the Fable pass before leaving the repo — no single model's arithmetic ships unchecked.
## Anonymization rule (hard)
Only generic, parameter-driven tasks go to DeepSeek/MiniMax. No counterparty names, wallet addresses, or deal-identifying details in any prompt, commit, or fixture.
