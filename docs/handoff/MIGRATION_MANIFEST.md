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
- [ ] `DESIGN_HANDOFF.md` — the master (context, governance + standalone-framing + dual-objective rules,
      editing corrections, **all-10-slides** slide-by-slide, full data grid, figure values).
- [ ] `RESULTS_BRIEF.md` — the one-page brief.

## 3. Old-slide → new-content map (all 10 slides)
| old slide | new content (HAND-OFF §d) |
|---|---|
| Slide 00 Title | re-anchored reference-basis line — live spot $63,402 + deal reference $65,000 |
| Slide 00b Team | unchanged (no numbers) |
| Slide 1 Opportunity | value decomposition recomputed at live ($1.90B notional, effective $60,631/BTC, 4.37%, ≈$83.1M) + deal-ref column |
| Slide 2 Strategy | **dual-objective**: accumulation → LBSP; protection → collar/defined-risk (objective-conditional) |
| Slide 2b Choice framework | the quantitative grid — premium / P(win) / breakeven / max-loss / honest-downside |
| the single PILED strategy diagram | the **7 separate per-structure figures** (§1 above) — one idea each, NOT re-piled |
| Slide 3 How it works | current engine — Bates/SVJJ, COS, live DVOL + arb-free SVI/SSVI surface, UKF/PF, EVT; 881 tests |
| Slide 4 What it produces | 3 objective cases recomputed at live, as ranges, honest-but-capped downside |
| Slide 5 How it is tested | Bates/SVJJ physical sim, 8-yr Binance history, EVT-hardened, PF ±7%, seed-stable |
| Slide 6 How it is used | pricing/vol dimension → live DVOL + Bates/SVJJ (COS); workflow + 11 dims unchanged |
| Slide 7 Portfolio | block basis re-anchored ($1.90B live / $1.95B deal ref); Bates/SVJJ harness |
| all slides | governance footer + opportunity-cost-not-loss + **standalone (no before/after) framing** (§b) |

## Notes for the design session
- **"floor" is reserved for the defined-risk structures** (collar, call spread) — a bounded floor. Covered
  call / LBSP / CSP / unhedged have **no floor**; they show a max-loss-to-spot-0 (e.g. covered call
  ≈ −$62,228/BTC). Figures and table cells share ONE reference config so their numbers agree.
- Present the current engine as **THE definitive system** — no "we used to / previously / upgraded" wording.

## Durable copy
This bundle is also mirrored to the durable path `/home/francisco/btc/design_handoff/` (outside the
ephemeral sprint worktree) so it survives worktree removal.
