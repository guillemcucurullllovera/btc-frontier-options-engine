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
Gate: *(appended after self-gate)*
