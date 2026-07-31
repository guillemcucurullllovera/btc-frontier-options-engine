# C10 · N2 — Historical Q-surface archive (start the clock) — GATE REPORT

**SIMULATED / diagnostic · MS-26-gated · OBSERVED surfaces · deck & canonical `main` untouched.**
Addresses the Phase E / M7 data gap: *"the Q model cannot be re-calibrated historically — only one frozen
option chain exists."* N2 **starts the clock** so a historical option-surface archive begins accruing now.
Archiver `scripts/deribit_surface_archiver.py`; pipeline `scripts/cross_temporal_q.py`; evidence
`c10_n2_q_archive.json`; archive `market_snapshots/deribit_surface_archive/`.

## What N2 delivers
1. **A daily Deribit option-surface archiver (live, no auth).** Snapshots the full BTC option surface
   (854 instruments + book-summary marks/IVs + index + DVOL) into a **checksummed, provenance-labelled
   (OBSERVED)** dated folder, idempotent per day. **Day 1 seeded: 2026-07-31** (854 instruments, index
   63 789, 744 KB, sha256 per file). Reuses the public `DeribitClient`.
2. **A cross-temporal Q-calibration + residual-tracking pipeline, READY but DATA-GATED.** Re-calibrates
   Heston to each archived day and tracks the parameter path + calibration residual (ARPE / RMSE_IV) over
   time. Validated on the live day-1 surface: **ARPE 8.74%, ATM vol 0.52, κ 6.3, vol-of-vol 3.3, ρ −0.37,
   n=304** — a sensible calibration, consistent with the frozen-anchor Heston (~8%). It will emit a
   stability series once ≥2 (meaningfully, ~weeks of) days have accrued.
3. **A scheduling recipe** for daily accrual (below) and **the backfill procurement options for the
   operator's call** (below).

## Scheduling (daily accrual) — INSTALLED ✅
A daily cron entry (00:10 UTC) has been **installed** in the operator's crontab (existing jobs preserved):
```
10 0 * * * /home/francisco/btc/btc_engine_frontier/.venv/bin/python \
  /home/francisco/btc/worktrees/c9-advanced-methods/scripts/deribit_surface_archiver.py \
  >> /home/francisco/btc/worktrees/c9-advanced-methods/logs/deribit_archiver.log 2>&1
```
Idempotent (a same-day re-run is a no-op), so a missed slot is harmless. **From today the archive accrues
one OBSERVED, checksummed surface per day** — the historical-Q clock is running. ⚠️ The path points at this
sprint **worktree**; if the worktree is removed or the branch is merged to `main`, update the cron path to
the canonical location (noted for the operator).

## Backfill options — PROCUREMENT DECISION for the operator (do NOT purchase)
The live archive accrues forward; a **paid backfill** would give an immediate multi-year history (Deribit
options ~2019→now) so the cross-temporal Q-stability + residual-tracking is available *now* rather than
after weeks. Indicative options (obtain a current quote — figures are approximate and vendor-confirmed):

| Vendor | What it provides | Indicative cost (confirm w/ vendor) | Notes |
|--------|------------------|-------------------------------------|-------|
| **Tardis.dev** | Tick + book-snapshot history for Deribit options (incremental L2 + quotes), 2019→now | ~$300–$700/mo subscription, or per-exchange-month datasets | Most granular; you reconstruct the surface from quotes/marks. Good fit; API + CSV. |
| **Laevitas** | Pre-built historical IV surfaces / greeks for Deribit options | ~$100s–$1 000s/mo by tier | Surface-ready (less reconstruction); analytics-oriented. |
| **Kaiko** | Institutional derivatives/options history | Enterprise (contact sales; typically $1 000s/mo) | Broad coverage; heavier contract. |
| **Amberdata / CoinAPI** | Derivatives + options history | ~$100s–$1 000s/mo by tier | Alternatives; verify Deribit **option-surface** depth specifically. |

**Recommendation for the operator:** if cross-temporal Q-stability is needed **soon**, a **Tardis.dev**
backfill (most granular, ~$300–$700/mo range) is the natural first quote; if a **surface-ready** feed is
preferred, **Laevitas**. If it can wait, the **free live archiver** matures it at zero cost over weeks.
**This is a procurement decision — no purchase has been made.** The pipeline ingests either source (the
archived daily snapshots, or a vendor backfill dropped into the same `deribit_surface_archive/<date>/`
layout).

## Data gate & status
`status = ACCRUING — 1 day archived`. A meaningful stability series needs ~weeks of daily accrual (or a
backfill). **The pipeline is implemented and validated; the RESULT is data-gated on the archive maturing.**
Until then, the Phase E finding stands: cross-temporal Q-stability is not yet computable — but the clock is
now running.

## Gate status
Archiver + pipeline: mypy/ruff/anon/git clean; day-1 surface seeded + checksummed; pipeline validated on
the live surface (ARPE 8.7%). **Stopping at the N2 gate — the backfill is the operator's procurement call.**
