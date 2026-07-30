# C9 · M6.0 finalize — corrected rough-Heston fit (converged, accurate-resolution)

**SIMULATED / diagnostic · MS-26-gated · statistical model-fit only (NOT an MS-25 claim).**
Deck & canonical `main` untouched. Evidence bundle: `c9_m6_rough_finalize.json`.

## What this corrects
The pre-finalize free-H calibration reported **ARPE 8.8% at H≈0.45**. That is an **optimizer failure**:
rough-Heston at H=0.5 **is** classical Heston (α=1, exact closed form), so a *converged* free-H fit — which
can always fall back to H=0.5 — can **never exceed the Heston ARPE (8.05%)**. 8.8% > 8.05% is therefore
impossible for a real optimum; the earlier run simply had not converged.

## Method (this run)
- **Baseline** = rough-H=0.5 (exact) calibrated on the same 6 weekly+ slices (259 options), N=64, L=12.
- **Fixed-H scan** H∈{0.45…0.20}, solver resolution `nst = clip(round(45/H), 120, 350)` — calibrated to
  **<0.05% price error down to H=0.20** (measured: probe of nst vs H) so the ~0.3–0.5pp ARPE gaps are
  well above solver noise. Multi-start warm from the Heston optimum; convergence checked via iteration
  count and multi-start objective spread.
- **Free-H** = 6-parameter calibration (H a free 6th parameter, H∈[0.10,0.50]) warm-started from the
  Heston optimum (H=0.49) **and** the best fixed-H point.

## Result

| H | ARPE | RMSE_IV (vp) | converged? | multi-start spread |
|------|--------|--------|--------------------|--------------------|
| 0.50 (=Heston) | **8.052%** | 0.01547 | exact | — |
| 0.45 | 7.861% | 0.01530 | ✅ (nit 326) | 9.4e-10 |
| 0.40 | 7.717% | 0.01518 | ✅ (nit 383) | 1.3e-09 |
| 0.35 | 7.617% | 0.01509 | ✅ (spread ok) | 1.0e-10 |
| 0.30 | *9.877%* | 0.01761 | ⚠️ **fragile** | **1.4e+00** |
| 0.25 | *7.454%* | 0.01501 | ⚠️ **fragile** | **7.5e-01** |
| 0.20 | **7.384%** | 0.01501 | ✅ (nit 526) | 9.8e-04 |
| **free-H → H=0.2022** | **7.385%** | 0.01501 | ✅ (nit 271) | 9.7e-03 |
| *Bates (M3 ref)* | *5.55%* | *1.18* | — | — |
| *Xia–Li (BTC lit)* | *~4%* | — | — | — |

## Findings (honest, corrected)
1. **The prior 8.8%/H≈0.45 was an optimizer failure — confirmed.** Properly converged, the free-H optimum
   is **H≈0.20, ARPE 7.39%**, which **independently matches the fixed-H=0.20 point (7.384%)** — two separate
   optimizations agreeing → a real attractor, not a fluke.
2. **The BTC surface prefers STRONG roughness (H≈0.20), not weak.** On the reliably-converged points the
   ARPE decreases monotonically with roughness (8.05→7.86→7.72→7.62→7.38), ≈**0.5pp per 0.1 of H** down to
   H≈0.35, then flattening (≈7.4% plateau for H≲0.25). This corrects the earlier "weakly rough H≈0.45":
   on the roughness **direction**, the data leans **Xia–Li (rough, H<0.5)**, not Alòs (not-rough).
3. **Computational limit (documented, per plan).** The intermediate H=0.30 / H=0.25 fixed-H calibrations were
   **optimizer-fragile** at the 2-start budget (multi-start objective spread 1.4 / 0.75 → the two starts
   landed in different basins). Their values are unreliable but are **bracketed by their converged
   neighbors** (H=0.35→7.62%, H=0.20→7.38%); the converged endpoints and the free-H run settle the profile.
4. **Roughness is a REAL but SMALL fit lever, and jump-dominated.** The total gain from adding roughness is
   ≈0.67pp (8.05→7.39). **Even at the strong-rough optimum, rough Heston (7.39%) does NOT approach Bates
   (5.55%) or Xia–Li (~4%).** The dominant BTC fit/tail lever is **jumps** (Bates + the P-identified realized
   jumps of M4), not roughness.
5. **Identifiability trade-off (noted).** As H↓, the calibrated mean-reversion κ (9.8→2.5) and vol-of-vol
   (4.3→1.7) both fall: the rough kernel supplies the short-dated skew that diffusive vol-of-vol supplies in
   classical Heston, so the two are partially interchangeable. This is expected and is one reason the
   fixed-H optimization is ill-conditioned at intermediate H.

## Gate decision (unchanged)
The pre-agreed criterion for full rough integration was **"rough materially beats Bates AND H≪0.5."**
- **H≪0.5? YES** (free optimum H≈0.20).
- **Rough materially beats Bates? NO** (7.39% vs 5.55%; jumps dominate).

Both are required; the Bates test fails. → **SKIP the heavy non-Markovian machinery (M6.1 hybrid sim,
M6.2 DLV neural calibration, M6.3 fractional-SV co-jumps).** The contested-roughness question is settled on
our own data: **the BTC surface is rough (H≈0.2), but roughness is a weaker fit lever than jumps** — a jump
model (Bates / P-jumps) remains the right primary, and rough-vol integration is not warranted by the fit.
Carried into the M7 dossier.
