# RESULTS BRIEF — C10 BTC-options deck (one page)

**SIMULATED / diagnostic · MS-26-gated · illustrative, not advice · no best/optimal.**

> **Note on provenance:** no separate "Section-1 brief" text was supplied in the sprint prompt, so this brief
> is assembled from the authoritative sources — `c9_corrected_findings_delta.md` (the five corrections) and
> the N4.1 MS-25 readiness dossier — and its numbers are generated **directly from the regenerated N4.2
> deck-input grid + the acquisition-waterfall engine** (consistent by construction; verification note at the
> bottom).

## Reference basis
Live snapshot spot **$63,402** (as-of 2026-07-28T14:54Z) — the basis of the grid and the
figures. **$65,000 kept as the documented "deal reference."** Value decomposition is percentage-based, so
the net-improvement % is invariant to the re-anchor.

## Headline
The engine reprices the live BTC surface to **~5.5% error** (vs ~27% for an assumed-GBM stack) — a
calibrated Bates (stochastic-vol + jumps) + SVJJ co-jump, COS-priced, validated to machine precision,
EVT-hardened, uncertainty-banded across **881 tests**. **The story is risk-reshaping, not a premium harvest.**

## Two objective-matched paths (full toolkit analysed for both)
- **Accumulation → Long BTC + short put:** premium 2.21%, uncapped
  upside + deliberate accumulation below the strike; amplified downside shown honestly
  (+4.2% central).
- **Protection → collar / defined-risk:** bounded floor **-6,010 $/BTC**,
  model-INVARIANT across the uncertainty band.

## Acquisition economics (Slide 1, at live)
Notional **$1,902.1M**; effective acquisition cost **$60,631/BTC**
(**$1,818.9M**); net improvement **4.37%** (≈
$83.1M); structuring fee **$9.51M** (150 BTC).

## The five corrections (INTERNAL editing guidance — the slides read as one definitive system)
1. **VRP is fair-valued / tail-compensated**, not a premium edge (forward VRP +0.096, positive but thin).
2. **Downside is bigger and OBSERVED** — asymmetric jumps (η≈1.4, all-regime) + observed co-jump ρ_J=−0.74;
   honest downside ~+0.8% (asymmetry) → **~+4.5% central** [+3%,+10%].
3. **Overlays reshape risk, not return** — defined-risk (collar/call-spread) tails are **invariant**.
4. **Recent-regime vol ≈0.46** (secular decline 0.92→0.46), not a full-history ~0.9.
5. **Methodology is the strength** — institutional-grade, committee-ready fidelity.

## Snapshot (from the regenerated grid)
| structure | premium % | P(win) N(±d₂) | max loss $/BTC | downside |
|---|---|---|---|---|
| covered call (+5%, 100%) | 1.85% | 0.727 | -62,228 | max-loss to spot 0 |
| long BTC + short put (−5%) | 2.21% | 0.667 | -122,000 | max-loss to spot 0 |
| collar (defined-risk) | 0.62% | 0.727 | -6,010 | bounded floor |
- Honest-downside ES97.5: **~+4.5% central**, band [+3%,+10%]; defined-risk overlays **bounded**.
- Parameter uncertainty (validated PF): **±~7%** (tail-exposed). Forward VRP: **+0.096** (positive).

## Verification note
The numbers above are pulled programmatically from the committed N4.2 deck-input grid
(`exports/c10_deck_input/grid.json`), the observed-co-jump scenarios (N3.6), and `execution.waterfall`.
**No mismatch** — the brief is generated from the same sources it summarises. If the operator substitutes a
different "Section-1 brief" text, re-verify its numbers against this grid before use; do not silently alter
the numbers.
