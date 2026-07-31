# C10 · N4.5 — Per-structure figure spec (ONE clean figure per structure)

**SIMULATED / diagnostic · MS-26-gated · holder-basis · deck & `main` untouched · no best/optimal.**
Directly resolves the CEO's *"all-piled-in-1 → separate"* complaint: **one standalone, legible figure per
structure — never all overlaid on a single busy panel.** Figure-source data (the exact series) is in
`docs/reports/c10_figure_source/{structure}.json`; this file is the SPEC. **Rendering is N5, not N4** —
N4.5 delivers source + spec only.

## Clarity principles (apply to every figure — "clear on the eye")
1. **One idea per figure.** Each structure gets its **own** figure whose single idea is *its expiry P&L vs
   spot*. Do **not** overlay multiple structures on one panel (the complaint). The σ-bars and the
   max-loss/opportunity-cost decomposition are **lightweight companions** to that one figure, not a
   competing 4-panel pile.
2. **Minimal ink.** One P&L curve + one faint "hold BTC" reference line + a zero line. No gridlines beyond a
   faint zero; no chartjunk; direct labels over legends where possible.
3. **Consistent axes & scale across the set** so the 7 figures read as one family: same **x** = spot
   (0.45–1.75 × S₀, S₀=63,402), a shared **y** within each *scale group* (below) so magnitudes are
   comparable at a glance; annotate S₀ and the strikes as light vertical guides.
4. **Legible labels**, colourblind-safe, light/dark-aware — follow the `dataviz` skill palette/validator at
   render time (N5). Label the **breakeven**, **cap** (max P&L), and **floor/max-loss** directly on the
   curve; shade the **opportunity-cost** region (foregone gain above the cap) distinctly from any loss.
5. **Honest attribution on the figure**: capped upside is **opportunity cost (foregone gain), NOT a loss**;
   sub-floor loss is the true max loss. Defined-risk structures show the **flat capped floor** visibly.

## Scale groups (shared y-axis within a group)
- **Wide** (holder-basis, large downside): `unhedged`, `long_btc_plus_short_put`, `covered_call`,
  `cash_secured_put`, `strike_ladder` — y ≈ [−65k, +50k] USD/BTC.
- **Defined-risk** (tight, capped): `collar` (floor −5,734), `call_spread` (floor −776) — y ≈ [−7k, +5k];
  a **zoomed** y makes their capped floor legible (annotate that the y-scale differs, with a small inset
  showing them on the wide scale for context).

## Per-structure figures (source: `c10_figure_source/<name>.json`)
Each figure = **the annotated expiry payoff curve** (series `payoff_curve.spot` vs `payoff_curve.pnl_usd_per_btc`,
with the faint `unhedged_reference`), plus a **σ-scenario mini-bar** (5 bars at ±2σ/±1σ/0, `sigma_scenario_bars`)
and a **max-loss/opportunity-cost callout** (`max_loss_opportunity_decomp`).

| structure | one-idea headline | annotate: breakeven / cap / floor (USD/BTC) | figure note |
|-----------|-------------------|---------------------------------------------|-------------|
| **unhedged** | the baseline: hold BTC, linear P&L | BE ~63,243 / cap open / floor −34,871 | reference line for all others |
| **covered_call** | premium cushion, capped upside | BE ~61,658 / cap +4,987 / floor −33,054 | shade opportunity-cost above the short strike |
| **long_btc + short_put** | amplified downside for premium | BE ~61,341 / cap +49,540 / floor −64,583 | steepest sub-strike loss (attributable) |
| **cash_secured_put** | acquire-lower, premium income | BE ~58,171 / cap +1,989 / floor −29,712 | no holding leg; loss = assignment |
| **collar** | **defined-risk**: floored downside | BE ~62,926 / cap +3,776 / **floor −5,734 (flat)** | zoomed y; show the capped floor clearly |
| **call_spread** | **defined-risk**: tight credit spread | BE ~65,780 / cap +492 / **floor −776 (flat)** | zoomed y; smallest footprint |
| **strike_ladder** | staged capped upside | BE ~62,292 / cap +7,430 / floor −33,781 | ladder of short-call strikes as guides |

## What each figure must carry (checklist for N5)
- [ ] The P&L curve + faint hold-BTC reference + zero line (minimal ink).
- [ ] Direct labels: **breakeven** point, **cap** (max P&L), **floor/max-loss**; strikes as light guides.
- [ ] **σ-scenario mini-bars** (recent-regime vol 0.46, σ_h≈0.161) as a small companion, same colour family.
- [ ] **Opportunity-cost** region shaded distinctly (foregone gain), labelled "opportunity cost, not a loss".
- [ ] **Defined-risk** structures: the flat capped floor visibly annotated (their decision-relevant feature).
- [ ] Consistent axes within the scale group; provenance/footer: *SIMULATED / holder-basis / no best-optimal;
      premiums COS-Bates-consistent; downside per the SVJJ observed-co-jump tail (N3.6)*.
- [ ] **Seven separate figures** — never a single piled panel.

## Companion: the honest-downside band (from N4.2, per figure footnote)
Each structure's figure may carry a one-line footnote with its **SVJJ honest-downside ES97.5** (central +≈4%,
band [+3%,+10%]; defined-risk **bounded**) from `docs/reports/c10_deck_input/slide2_continued_honest_downside.md`
— so the clean payoff figure and the risk number travel together without cluttering the payoff panel.
