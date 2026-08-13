# C7 Post-Remediation 60M Campaign — Committed Compact Evidence

SIMULATED / DIAGNOSTIC ONLY. Not decision evidence. No ranking/optimality/convergence claim.
MS-25 (objective function) and MS-26 (simulation methodology) are unresolved.

- `campaign_evidence_summary.md` — committee-facing summary + cross-seed variance validation.
- `aggregate_by_strategy_tier.csv` — 18 (strategy, tier) groups with cross-seed mean/std/min/max.
- `configuration_summary.json` — seeds, tiers, model, aggregate-path reconciliation (60,000,000).
- `evidence_checksums.json` — sha256 of the evidence outputs.

Full outputs (raw per-config results, seed-level metrics, per-config checksums, manifest, logs)
are stored OUTSIDE git under `/home/francisco/btc/post_remediation_60m_campaign/`, regenerable
via `scripts/run_c7_campaign.py` (12 seeds x 3 tiers x single Merton, 6 strategies on shared
paths) and `scripts/aggregate_c7_campaign.py`. Raw path arrays are never materialised
(store_paths=False).
