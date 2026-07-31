# C10 · N5 — Figure-pack (separate, clean, one-per-strategy reference figures)

**SIMULATED / diagnostic · MS-26-gated · holder-basis · deck & `main` untouched · no best/optimal.**
Renders the **separate** per-structure reference figures the CEO asked for ("all-piled-in-1 → separate").
Rendered from N4.5's `c10_figure_source/*.json` + `c10_figure_spec.md`. Output (committed):
`docs/evidence/c10_figure_pack/` — PNG + SVG per structure + `manifest.json`. **Reference renders for the
external design session, NOT final deck slides** (clean enough to use as-is if needed). No slides built.

## What was rendered
- **7 standalone per-structure figures** (PNG+SVG): `unhedged`, `covered_call`, `long_btc_plus_short_put`,
  `cash_secured_put`, `collar`, `call_spread`, `strike_ladder`. Each = **one idea per figure**: the annotated
  expiry payoff curve (P&L vs spot; **strike / spot / breakeven / cap / floor** all directly labelled), a
  **slim σ-scenario companion** (±2σ/±1σ/0 at vol 0.46, sign by bar position), and the **max-loss /
  opportunity-cost decomposition** (floor label = max loss; hatched wedge + label = *foregone gain, NOT a
  loss*) — never a piled multi-panel.
- **1 illustrative comparison** (`_comparison_collar_vs_covered.*`): defined-risk collar floor vs
  covered-call open downside — clearly separate from the 7, clearly labelled illustrative (N5.2).
- `manifest.json`: filename → structure → what it shows → source JSON, + the provenance/disclaimer footer.

## Clarity (dataviz method, validated)
- **Palette** = validated dataviz roles: series-1 blue payoff line; muted dashed "hold BTC" reference;
  faint **status-red** loss fill (labelled, never colour-alone); **hatched** opportunity-cost wedge
  (texture, print/CVD-safe); single-hue σ-bars with sign by position; recessive grey axes/guides.
  Colour-carrying marks validated (blue↔red ΔE high; the amber/status cases carry direct labels).
- **Minimal ink**, direct labels (no number on every point), one clean idea per figure; consistent axes and
  **scale groups** per the spec (wide vs zoomed defined-risk). Reviewed each figure for label collisions.
- **Deterministic render** (Agg, fixed `svg.hashsalt`, metadata `Date=None`, no wall-clock/random) —
  verified byte-identical across runs; a `pytest.importorskip`-guarded smoke-test (`test_n5_figures.py`)
  renders all 7 + manifest and asserts deterministic output.
- Every figure carries a provenance/disclaimer footer: *SIMULATED / diagnostic · MS-26-gated · holder-basis ·
  no best/optimal; premiums COS-Bates-consistent; downside per the SVJJ observed-co-jump tail (N3.6);
  reference render, not a deck slide.*

matplotlib is a **render-time** dependency (installed into the venv, not the core lock); the committed
PNG/SVG are the deliverable and the smoke-test skips gracefully where matplotlib is absent.
