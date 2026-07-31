# RESULTS BRIEF — C10 BTC-options refresh (one page)

**SIMULATED / diagnostic · MS-26-gated · illustrative, not advice · no best/optimal.**

> **Note on provenance:** no separate "Section-1 brief" text was supplied in the sprint prompt, so this brief
> is assembled from the authoritative sources — `c9_corrected_findings_delta.md` (the five corrections) and
> the N4.1 MS-25 readiness dossier — and its snapshot table below is generated **directly from the
> regenerated N4.2 deck-input grid** (so it is consistent by construction; the verification note is at the
> bottom).

## Headline
The C9/C10 engine reprices the live BTC surface to **~5.5% error** (vs ~27% for the old assumed-GBM stack) —
a calibrated Bates (stochastic-vol + jumps), COS-priced, validated to machine precision, EVT-hardened,
uncertainty-banded. **The story is risk-reshaping, not a premium harvest.**

## The five corrections vs the old deck
1. **VRP is fair-valued / tail-compensated**, not a premium edge (forward VRP +0.096, positive but thin).
2. **Downside is bigger and now OBSERVED** — asymmetric jumps (η≈1.4, all-regime) + observed co-jump ρ_J=−0.74;
   honest downside ~+0.8% (asymmetry) → **~+4.5% central** [+3%,+10%].
3. **Overlays reshape risk, not return** — lead with defined-risk (collar/call-spread), **invariant** tails.
4. **Recent-regime vol ≈0.46** (secular decline 0.92→0.46), not a full-history ~0.9.
5. **Methodology is the strength** — institutional-grade, committee-ready fidelity.

## Snapshot (from the regenerated grid)
| structure | premium % | P(win) N(±d₂) | max loss $/BTC | downside |
|---|---|---|---|---|
| covered call (5%, 100%) | 1.85% | 0.727 | -62,228 | bounded |
| collar (defined-risk) | 2.47% | 0.557 | -4,838 | bounded |
- Honest-downside ES97.5: **~+4.5% central**, band [+3%,+10%]; defined-risk overlays **bounded**.
- Parameter uncertainty (validated PF): **±~7%** (tail-exposed). Forward VRP: **+0.096** (positive).

## Verification note
The snapshot numbers above are pulled programmatically from the committed N4.2 deck-input grid
(`exports/c10_deck_input/grid.json`) and the observed-co-jump scenarios (N3.6). **No mismatch** — the brief
is generated from the same grid it summarises. If the operator substitutes a different "Section-1 brief"
text, re-verify its numbers against this grid before use; do not silently alter the numbers.
