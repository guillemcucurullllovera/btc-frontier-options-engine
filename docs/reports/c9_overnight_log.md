# C9 Advanced-Methods — Autonomous Overnight Run Log

**Started:** 2026-07-31 (overnight, autonomous — Phases A–F without inter-phase orchestrator approval).
**Branch:** `sprint/c9-advanced-methods` · **Discipline:** SIMULATED/diagnostic, MS-26-gated; deck & canonical
`main` untouched; commit only to the sprint branch. Self-gate after each phase (`pytest -q`, `mypy .`,
`ruff check .`, anonymisation scan, `git diff --check`); green → commit + proceed; red → fix, else revert
that phase's uncommitted changes, document, skip to the next independent phase.

This log is written as the run proceeds. The morning-first summary is `c9_overnight_report.md`.

---

## DECISIONS-LOG
Choices that would normally go to the orchestrator. Each: the honest, conservative default + reasoning.
Nothing forced — results are reported as the data gives them.

| # | Phase | Decision | Reasoning |
|---|-------|----------|-----------|
| D1 | A | Fixed-H scan solver resolution = `nst = clip(round(45/H), 120, 350)` | Measured (probe): nst=250 gives <0.05% price error down to H=0.20 — far below the ~0.3–0.5pp ARPE gaps under test. So the strong-roughness gap can be closed at accurate resolution; the M6.0b "computational-limit" fallback is only needed for the fragile *intermediate* points (D3), not the endpoints. |
| D2 | A | Compare rough-at-H vs Heston at IDENTICAL settings (same N, L, slices, starts, maxiter) | The canonical "Heston 8.08%" was at N=192; the rough scan must use the same COS/optimizer budget as its own H=0.5 baseline, or the comparison is confounded. Baseline recomputed here as rough-H=0.5 (exact closed form) → 8.05% (matches 8.08%). |
| D3 | A | Report the corrected free-H optimum as **H≈0.20 (strong rough), ARPE 7.39%** — NOT the earlier "weakly rough H≈0.45" | Converged free-H (7.385%) independently matches fixed-H=0.20 (7.384%) — two separate optimizations agree → real attractor. The earlier "8.8%/H≈0.45" was an optimizer failure (8.8% > Heston 8.05% is impossible for a converged free-H). The fragile intermediate points H=0.30/0.25 (multi-start spread 1.4/0.75) are documented as the computational limit and reported as *unreliable*, bracketed by converged neighbors — not silently dropped. |
| D4 | A | Verdict UNCHANGED (skip heavy sim) despite the roughness-direction correction | Gate criterion = "rough beats Bates AND H≪0.5" (both required). H≪0.5 now holds, but rough 7.39% still ≫ Bates 5.55% → the Bates test fails → skip. The BTC surface IS rough (leans Xia-Li), but roughness is a weaker fit lever than jumps. Honest: this corrects my pre-compaction "closer to Alòs" to "rough direction, but jump-dominated." |
| D5 | B | Commit daily bars in full + all meta (force-add past the root `market_snapshots/` ignore, matching the existing snapshot pattern); leave the 16/31 MB hourly/1m raw arrays uncommitted | Repo-friendly: the large intraday arrays are reproducible via `scripts/fetch_binance_history.py` + the committed sha256. Daily (808 KB), all three `meta.json`, and derived estimates ARE committed. |
| D6 | B | Label Binance BTCUSDT OBSERVED with a prominent basis caveat (not a new provenance class) | It IS observed exchange data. The USDT-vs-Deribit-index difference is a *levels* basis; log-RETURNS (the estimation input) are an excellent BTC/USD proxy. Caveat recorded in every `meta.json` + the provider docstring. |
| D7 | B | Report the downside jump asymmetry as a LONG-HISTORY (sample-length) effect, correcting M4.6 — the data drove this | Same detector (α=0.05): full 2017-2026 η=1.42 vs last-2yr η=1.09. The M4.6 "symmetric daily" was a 2yr-window artifact (missed the crashes). Not forced — reported as the multi-frequency + multi-window evidence gives it. The Phase D risk model should carry η≈1.4-1.5, not the symmetric 2yr estimate. |
| D8 | B | Daily GARCH is the vol anchor; hourly GARCH unconditional (168%) flagged UNRELIABLE; 1m λ flagged microstructure-inflated | Honesty: hourly persistence is near-integrated (0.997) → unstable unconditional; 1m λ is FP-rate × 130k obs. Reported for completeness with explicit caveats, not used as anchors. |
| D9 | C | Report the SVCJ MCMC as NON-CONVERGENT on real BTC (R̂≫1) and keep the particle filter as the operational tool | Exactly the pre-authorised fallback. The sampler is *validated on simulated data* (recovers params, vol corr 0.85); on the 8.5yr real series R̂ up to 9.4 (κ) from weak SV identification + regime non-stationarity (PPC kurtosis 19). Not forced — reported as-is. The one robust signal (ρ_J≪0, R̂ 1.17) IS carried forward. |
| D10 | C | Trust the recovery test over the point estimates — it caught a real bug | The simulate→recover validation exposed a determinant error in the bivariate log-density (2× vol-level bias, vol-corr 0.09→0.85 after fix). Lesson logged: never report MCMC posteriors without a recovery gate. |
| D11 | D | Propagate parameter uncertainty by bootstrapping Phase B realized jumps + drawing P-vol from the estimator spread; use the SVCJ posterior only qualitatively | Phase C did not converge, so sampling its posterior directly would be dishonest. The well-founded uncertainty sources are the jump bootstrap (Phase B identifies jumps well) and the genuine P-vol estimator disagreement (0.42–0.77). ρ_J<0 is carried qualitatively. |
| D12 | D | Flag that the symmetric-normal jump block cannot represent the η=1.42 downside SIZE asymmetry → the LBSP/downside tail is if anything UNDERSTATED | Honesty: at α=0.05 the empirical jump mean ≈0 (asymmetry is in size, not mean); the block widens the tail via larger jumps + vol, not a downward mean. Reported as a limitation; the qualitative conclusions (defined-risk robustness, more-negative VRP) are unaffected. Faithful downside needs an asymmetric/co-jump block (future work). |
| D13 | E | Q model NOT re-calibrated across history (data gap) — only P re-estimated; VRP-stability uses the frozen Q | We hold ONE frozen option chain, not historical surfaces — Q-smile re-calibration is impossible without a historical Deribit surface archive. Documented as a data gap (flagged for M7); the feasible, honest analysis is P-stability + VRP-vs-frozen-Q across windows. |
| D14 | E | Report vol roughness as a STRUCTURAL (regime-independent) property from the realized-variance side | H ∈ [0.02, 0.10] in every window (2019+) via GJR on hourly-built daily RV — an independent confirmation of Phase A's Q-surface H≈0.20. RV noise biases H down (noted); the "rough in all regimes" conclusion is robust and not forced. |

---

## Phase log

### Phase A — M6.0 finalize ✅
Corrected, converged rough-Heston fit. Full evidence: `c9_m6_rough_finalize.md` (+ `.json`).

**Corrected result:** free-H optimum **H≈0.20 (strong roughness), ARPE 7.39%** (matches fixed-H=0.20 =
7.384%). Fixed-H profile (reliably-converged points) decreases monotonically with roughness:
Heston/H=0.5 **8.05%** → 7.86 → 7.72 → 7.62 → **7.38** at H=0.20 (~0.5pp/0.1H, flattening below H≈0.25).
Intermediate H=0.30/0.25 optimizer-fragile (documented limit). **Prior 8.8%/H≈0.45 = optimizer failure,
confirmed.**

**Verdict (unchanged): rough does NOT beat Bates (7.39% vs 5.55%) → SKIP heavy sim M6.1–6.3.** Correction
vs pre-compaction: the surface IS rough (H≈0.2, leans Xia-Li), but roughness is a weaker fit lever than
jumps. Identifiability: as H↓, calibrated κ (9.8→2.5) and vol-of-vol (4.3→1.7) fall (rough kernel ⇄
diffusive vol-of-vol).

New/changed: `docs/reports/c9_m6_rough_finalize.{md,json}`; corrected `tests/test_rough_calibration.py`
docstring + added `test_rough_finalize_not_worse_than_heston` (anti-regression for the optimizer-failure).
**Gate: 836 passed / 3 skipped, mypy clean (115 files), ruff clean, anon clean, git diff --check clean.
Committed `aabc909`.** Tracker M6.0a/b/c → ✅; M6.1–6.3 → SKIP.

### Phase B — Binance data + physical re-estimation ✅
Full evidence: `c9_binance_reestimation.md` (+ `.json`). New: `vol/binance.py` (provider, ms/µs/s-safe),
`scripts/fetch_binance_history.py`, `scripts/binance_reestimation.py`, `tests/test_binance_provider.py`,
`tests/test_binance_reestimation.py`; snapshots `market_snapshots/binance_history/{1d,1h,1m}/`.

**Data:** 3 270 daily (2017-08→2026-07, vs M4.6's 728), 66 378 hourly (2019→now), 129 599 1-min (last 90d).
OBSERVED, checksummed, basis-caveat labelled; frozen Q anchor untouched.

**MATERIAL FINDING (jump picture):** the downside jump asymmetry is a **long-history / daily-scale** effect,
NOT a high-frequency one. Same detector (α=0.05): full-history **η=1.42** (40 jumps) vs last-2yr **η=1.09**
(10 jumps); at 1-min jumps are symmetric microstructure (η=0.98). **Corrects M4.6** — its "symmetric daily"
(η≈1.04) was a 2-year-window artifact (missed 2018 / Mar-2020 / 2021 / 2022 crashes). The asymmetry is in
jump *size* (fewer but bigger down-moves). Vol level higher over the long history (realized 0.68 / GARCH
uncond 0.77 / UKF 0.52 / PF 0.61). Q-vs-P: Q 0.50 vs full-history P 0.77 → negative long-run VRP
(reinforces M5.4's regime-dependent VRP sign). Honesty flags: 1m λ microstructure-inflated; hourly GARCH
unconditional (168%, persistence 0.997) unreliable → daily GARCH is the anchor.

**Gate: 844 passed / 3 skipped, mypy clean (120 files), ruff clean, anon clean, git diff --check clean.
Committed `ad98a53`.**

### Phase C — M4.4b SVCJ MCMC (Eraker–Johannes–Polson) ✅ *(implemented + validated; real-data convergence PARTIAL)*
Full evidence: `c9_svcj_mcmc.md` (+ `.json`). New: `vol/svcj_mcmc.py` (SVCJ Gibbs/Metropolis with data
augmentation; even/odd vectorised latent-V Metropolis), `scripts/svcj_btc_estimation.py`,
`tests/test_svcj_mcmc.py`. Resolves the M4.4b "BLOCKED-ON-SOURCE".

**Sampler VALIDATED** on simulated data (EJP Appendix-C recovery): all 10 params' 90% CIs cover truth,
latent-vol corr ≈ 0.85. The recovery test caught a real determinant bug (2× vol-level bias; corr
0.09→0.85 after fix). **On real BTC (8.5yr, 9k×3): does NOT converge** (all-R̂<1.1 = False; κ R̂=9.4,
ρ R̂=4.0; PPC kurtosis 19) — weak SV identification (EJP) + constant-param misspecification across regimes.
**→ PF (M4.4a) stays the operational tool** (honest, pre-authorised fallback). **One robust signal: ρ_J
strongly negative (−2.30, R̂ 1.17) → leveraged co-jumps (vol spikes ⇔ price drops)** — corroborates Phase
B's downside tail as a contemporaneous price–vol co-jump. θ⇒vol 41.9%, latent-vol path 51% (consistent).

**Gate: 848 passed / 3 skipped, mypy clean (123 files), ruff clean, anon clean, git diff --check clean.
Committed `fefd646`.**

### Phase D — Risk re-derivation w/ parameter uncertainty + campaign MC ✅
Full evidence: `c9_risk_uncertainty.md` (+ `.json`). New: `strategy/bates_risk.py::parameter_uncertainty_band`,
`scripts/risk_uncertainty_campaign.py`, `tests/test_risk_uncertainty.py`. **Campaign: 6 000 000 paths
(30 draws × 200k), seed-stable ✅, 0 non-finite ✅.**

Enriched downside jumps (Phase B: λ 4.47/yr, std 0.137, η 1.42) + parameter-uncertainty propagation
(bootstrap jumps + P-vol draws over the estimator spread; SVCJ posterior used qualitatively). **Findings:**
(1) tail metrics of tail-exposed structures swing **±15–18%** under P-parameter uncertainty (not precise);
(2) **defined-risk structures (collar ES 5 734, call-spread 776) are INVARIANT to the parameter draw** —
capped by construction → the robust choice under uncertainty; (3) the **VRP moves more negative** under the
richer estimate (LBSP −693→−1057; every short-premium overlay's carry falls) → selling vol less attractive,
compounding M5.4. Honesty flag (D12): the symmetric-normal block can't capture the η=1.42 downside *size*
asymmetry → the downside tail is if anything understated (ρ_J<0 points the same way).

**Gate: 851 passed / 3 skipped, mypy clean (125 files), ruff clean, anon clean, git diff --check clean.
Committed `b46b580`.**

### Phase E — Cross-temporal robustness ✅
Full evidence: `c9_cross_temporal.md` (+ `.json`). New: `scripts/cross_temporal_stability.py`,
`tests/test_cross_temporal.py`. 6 contiguous regime windows (2017–2026); per window: realized vol, GARCH,
jump λ/η, SV-MLE vol, **roughness H** (GJR on hourly-built daily RV), VRP vs frozen Q.

**Stability verdict:** (1) **STRUCTURAL — roughness H ∈ [0.02, 0.10] in every regime** (vol rough always;
independent confirmation of Phase A's Q-surface H≈0.20); (2) **SECULAR — realized vol halves 0.92→0.46** over
the sample (non-stationary; use the recent ~0.46, not a full-history average); (3) **REGIME-DEPENDENT** — jump
downside η strongest in crash windows (2019-20 1.56, 2020-21 1.42) vs calm (recent 0.92), and the **VRP is
negative in every window but shrinks toward neutral (−0.55→−0.09)** — structurally negative long-run,
near-neutral now (resolves the VRP-sign question cross-temporally; consistent with M5.4 / Phase D).
**Data gap (D13):** Q-smile cannot be re-calibrated historically (one frozen chain) — flagged for M7.

Gate: *(appended after self-gate)*
