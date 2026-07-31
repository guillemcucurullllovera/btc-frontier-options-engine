# MIGRATION MANIFEST — what to upload / paste / map

**SIMULATED / diagnostic · MS-26-gated.** The design session has no repo access. Do the following.

## 1. UPLOAD to the design conversation (image files — prefer SVG, PNG as fallback)
- [ ] `figures/unhedged.svg` (prefer SVG) — and `figures/unhedged.png` fallback — the unhedged figure
- [ ] `figures/covered_call.svg` (prefer SVG) — and `figures/covered_call.png` fallback — the covered call figure
- [ ] `figures/long_btc_plus_short_put.svg` (prefer SVG) — and `figures/long_btc_plus_short_put.png` fallback — the long btc plus short put figure
- [ ] `figures/cash_secured_put.svg` (prefer SVG) — and `figures/cash_secured_put.png` fallback — the cash secured put figure
- [ ] `figures/collar.svg` (prefer SVG) — and `figures/collar.png` fallback — the collar figure
- [ ] `figures/call_spread.svg` (prefer SVG) — and `figures/call_spread.png` fallback — the call spread figure
- [ ] `figures/strike_ladder.svg` (prefer SVG) — and `figures/strike_ladder.png` fallback — the strike ladder figure
- [ ] `figures/_comparison_collar_vs_covered.svg` (+ `.png`) — the ONE illustrative comparison.

## 2. PASTE (text — fully self-contained)
- [ ] `DESIGN_HANDOFF.md` — the master (context, governance, five corrections, slide-by-slide, full data
      grid, figure values).
- [ ] `RESULTS_BRIEF.md` — the one-page brief.

## 3. Old-slide → new-content map
| old slide | new content |
|---|---|
| Slide 2 (qualitative toolkit) | quantitative grid — premium / P(win) / breakeven / max-loss / honest-downside (HAND-OFF §d, §e) |
| Slide 2-continued | covered-call vs LBSP deep comparison (HAND-OFF §d) + the two figures |
| the single PILED strategy diagram | the **7 separate per-structure figures** (§1 above) — one idea each, NOT re-piled |
| Slide 5 (robustness/MC) | corrected robustness stats (HAND-OFF §d Slide-5) |
| all slides | governance footer + opportunity-cost-not-loss framing (HAND-OFF §b) |

## Durable copy
This bundle is also mirrored to the durable path `/home/francisco/btc/design_handoff/` (outside the
ephemeral sprint worktree) so it survives worktree removal.
