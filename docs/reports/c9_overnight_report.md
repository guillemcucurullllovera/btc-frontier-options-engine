# C9 Autonomous Overnight Run — Morning Report

**Run:** 2026-07-31, autonomous, Phases A–F self-gated (no inter-phase approval). **Branch:**
`sprint/c9-advanced-methods`. **Discipline held throughout:** SIMULATED/diagnostic, MS-26-gated; deck &
canonical `main` untouched; commit only to the sprint branch; every phase self-gated
(`pytest`/`mypy`/`ruff`/anon/`git diff --check`) before commit. **All six phases completed and committed.**
Detailed running log + full DECISIONS-LOG: `c9_overnight_log.md`. Dossier + MS-26 recommendation:
`c9_completion_report.md`.

---

## Status: ALL PHASES COMPLETE ✅ — nothing skipped, nothing left broken

| Phase | What | Commit | Gate |
|-------|------|--------|------|
| **A** | M6.0 finalize — corrected rough fit, low-H closed | `aabc909` | 836 pass |
| **B** | Binance history + multi-frequency physical re-estimation | `ad98a53` | 844 pass |
| **C** | M4.4b SVCJ MCMC (Eraker-Johannes-Polson) — resolves BLOCKED-ON-SOURCE | `fefd646` | 848 pass |
| **D** | Risk re-derivation w/ parameter uncertainty + 6M-path campaign | `b46b580` | 851 pass |
| **E** | Cross-temporal robustness (6 regime windows) | `0d39a07` | 854 pass |
| **F** | Dossier + completion report + MS-26 sign-off recommendation | *(this commit)* | — |

Every gate: mypy clean, ruff clean, anonymisation clean, `git diff --check` clean. Suite grew 835 → **854**
passed / 3 skipped (+19 tests across A–E; F is docs-only). No phase failed; no phase skipped; the tree was
never left broken.

## Material findings (what the operator needs to know)

1. **Rough vol is REAL but does not beat jumps (Phase A + E).** Corrected the pre-run "H≈0.45/8.8%" (an
   optimizer failure): the *converged* free-H optimum is **H≈0.20 (strongly rough), ARPE 7.4%** — but even
   strong-rough does **not** approach Bates (5.55%). Phase E independently confirms roughness from the
   realized-variance side (**H≈0.02-0.10 in every regime**). **Verdict: BTC vol is genuinely rough, but
   jumps are the dominant fit/tail lever → the heavy rough integration (M6.1-6.3) stays SKIPPED.**

2. **The downside jump asymmetry is a LONG-HISTORY effect, not a high-frequency one (Phase B).** With the
   *same* detector, the full 2017-2026 daily history is downside-asymmetric (**η=1.42**) while the last 2yr
   is symmetric (η=1.09); at 1-minute jumps are symmetric microstructure. **The M4.6 "symmetric daily"
   picture was a 2-year-window artifact** that missed the crashes. The downside tail is real and lives at
   the daily/multi-day scale.

3. **The SVCJ MCMC does NOT converge on real BTC (Phase C) — reported honestly.** Validated on simulated
   data (recovers params, vol-corr 0.85; the recovery gate caught a real bug), but on the 8.5-yr series
   R̂ up to 9.4 (weak SV identification + regime non-stationarity). **The particle filter remains the
   operational tool.** One robust signal survives: **ρ_J≪0 → leveraged co-jumps (vol spikes ⇔ price drops)**,
   corroborating the downside tail.

4. **Risk is fatter, UNCERTAIN, and the VRP is thin-to-negative (Phase D + E).** Enriched (larger) jumps +
   vol widen the tail; tail-metrics carry a **±15-18% parameter-uncertainty band**. **Defined-risk overlays
   (collar, call-spread) are INVARIANT to that uncertainty** (capped by construction) — the robust choice.
   The **VRP moves more negative** under the richer estimate and is **negative in every historical regime but
   shrinks toward neutral (−0.55→−0.09)** — structurally negative long-run, near-neutral now.

5. **Vol is non-stationary (Phase E):** realized vol **halves 0.92→0.46** over the sample. Use the
   recent-regime ~0.46, not a full-history average.

## Skipped / not-done, with reasons (honest)
- **M6.1-6.3 (rough integration)** — **evidence-gated SKIP**: rough (7.4%) does not beat Bates (5.55%).
- **SVCJ decision-grade parameters** — **not delivered as decision-grade**: non-convergent on real data
  (R̂≫1); PF fallback used, per the pre-authorised rule. *(Sampler itself validated on simulation.)*
- **Historical Q re-calibration (Phase E)** — **data gap**: only one frozen option chain exists; documented,
  flagged for M7 (needs a historical Deribit surface archive).
- **Faithful downside-jump representation** — **future work**: the symmetric-normal block understates the
  η downside; an asymmetric/co-jump block is the fix.

## Commit ledger (overnight)
```
0d39a07 Phase E — cross-temporal robustness
b46b580 Phase D — risk re-derivation with parameter uncertainty + campaign MC
fefd646 Phase C — M4.4b SVCJ MCMC (resolves BLOCKED-ON-SOURCE)
ad98a53 Phase B — Binance history + multi-frequency physical re-estimation
aabc909 M6.0 finalize — corrected rough fit, low-H closed; skip heavy sim
```
New modules: `vol/binance.py`, `vol/svcj_mcmc.py`; scripts: `fetch_binance_history`, `binance_reestimation`,
`svcj_btc_estimation`, `risk_uncertainty_campaign`, `cross_temporal_stability`; risk:
`bates_risk.parameter_uncertainty_band`. Data: `market_snapshots/binance_history/{1d,1h,1m}` (daily + meta
committed; large intraday arrays reproducible via script + sha256).

## DECISIONS-LOG
14 orchestrator-level decisions were taken autonomously and logged with reasoning in `c9_overnight_log.md`
(§DECISIONS-LOG) — solver resolution (D1), like-for-like baselines (D2), the corrected roughness verdict
(D3-D4), data-commit policy & basis labelling (D5-D6), the long-history jump-asymmetry call (D7-D8), the
SVCJ non-convergence honesty + recovery-gate lesson (D9-D10), parameter-uncertainty sourcing +
downside-understatement flag (D11-D12), and the Q-historical data gap + structural-roughness cross-check
(D13-D14). Nothing was forced; results are reported as the data gave them.

## Bottom line
The C9 advanced-methods engine is a **validated, materially higher-fidelity, honestly-caveated** replacement
for the GBM/Merton stack — **recommended for MS-26 (diagnostic) sign-off by the operator** for its validated
core (`c9_completion_report.md` §6), with the research-tier items (SVCJ params, rough integration, historical
Q) carried as documented future work. **No decision-grade (MS-25) or best/optimal claim is made.** Deck and
canonical `main` remain untouched.
