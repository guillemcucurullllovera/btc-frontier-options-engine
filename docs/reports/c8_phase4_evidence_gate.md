# C8 Phase 4 — Evidence & Deck-Input Pack Gate Report

**Status:** Phase 4 complete; gated for orchestrator review before Phase 5.
**Scope:** evidence & deck-input pack only — **no slides built, no HTML/Marp touched.**
Every number traces to a computed source + the frozen snapshot
`market_snapshots/2026-07-30T104316Z/` (as of 2026-07-30T10:43:16Z, S0 64,509.34).

---

## 1. Gates

| Gate | Result |
|---|---|
| `pytest` | **608 passed, 3 skipped** |
| `mypy .` | clean (64 source files, strict) |
| `ruff check .` | clean |
| anonymisation | clean |
| every figure traces to computed source + snapshot | ✅ (checksummed manifest) |

New code: `scripts/export_c8_evidence_pack.py`. Deck-input packs committed under `docs/evidence/`;
bulk grid CSV/JSON git-ignored under `exports/` (regenerable, checksummed).

---

## 2. File manifest (`docs/evidence/c8_evidence_manifest.json`)

| File | Committed | sha256 (12) | Contents |
|---|---|---|---|
| `docs/evidence/c8_slide2_data_pack.md` | yes | `6c82837ab60e` | Slide-2/2-continued computed comparative matrix + hero highlights |
| `docs/evidence/c8_slide5_mc_pack.md` | yes | `8f6d0d7097c7` | Slide-5 MC drift-band diagnostic (SIMULATED) |
| `docs/evidence/c8_disclaimer.md` | yes | `5bba4be1e3b5` | structure-specific attribution disclaimer |
| `docs/evidence/c8_evidence_manifest.json` | yes | — | this manifest (files + checksums + snapshot cite) |
| `exports/c8_evidence_pack/grid.json` | git-ignored | `096f8503d546` | full 210-row grid (all fields, both views) |
| `exports/c8_evidence_pack/grid_summary.csv` | git-ignored | `ff824a71c53f` | 210 rows: one per grid cell (scalar metrics + σ totals) |
| `exports/c8_evidence_pack/grid_scenarios.csv` | git-ignored | `5e4ad07197c8` | 4,200 rows: grid cell × view × mode × σ (leg-decomposed) |

MC provenance: `docs/reports/c8_hero_mc_manifest.json` (drift-band SHA-256 `15dcba7d…`).

---

## 3. Grid (all structures at parity, standalone + total-portfolio views)

The full **210-row** grid (7 structure families → 8 canonical kinds incl. partial_overlay; strike% ×
both real expiries × coverage {25/50/75/100}%) is emitted as CSV + JSON. Each row carries premium,
prob-win (RN N(d2)), 3-way max-loss, breakevens (pct-OTM + true), greeks + theta, opportunity-cost,
the D-1 fee (both bases, separate), and σ-scenarios in **both** the standalone and total-portfolio
views. `grid_scenarios.csv` is the long form (holding / option / total per BTC, %-of-portfolio).

---

## 4. Slide-2 computed comparative matrix (28AUG26, 100% coverage, representative strike)

The computed successor to the qualitative choice matrix (full pack in `c8_slide2_data_pack.md`):

| Structure | prem %spot | prob-win | max-loss/BTC (hold + opt = total) | %cap | attractive when |
|---|---|---|---|---|---|
| Covered call 5% **[hero]** | 1.66% | 0.732 | −64,509 + **+1,068** = −63,441 | −98.3% | neutral-to-mildly-bullish; premium prioritised over uncapped upside |
| Long BTC + short put 5% **[hero]** | 1.87% | 0.687 | −64,509 + **−59,796** = −124,305 | −192.7% | willing to add BTC on a dip (amplified downside) for premium |
| Collar 5%/10%-floor | 0.68% | 0.732 | −64,509 + **+58,437** = **−6,072** | **−9.4%** | downside protection prioritised; some upside/premium given up |
| Cash-secured put 5% | 1.87% | 0.687 | net acq ≈ 59,796; max-loss −59,796 | −98.0% | acquire below spot, funded by premium, cash set aside |
| Call spread 5%/10% (credit) | 0.96% cr | 0.732 | defined-risk −2,379/BTC | (defined) | defined-risk, option-only bullish, no spot |
| Strike ladder 5/10/15% | 0.89% | 0.732 | −63,939/BTC | −99.1% | graduated upside participation across strikes |

`unhedged_baseline` is retained as an internal benchmark only (never featured/recommended). Hero
highlights sweep the full strike ladder for both heroes (in the pack). Attribution is explicit:
covered-call overlay is a **non-negative cushion** (+1,068/BTC at worst case); LBSP overlay goes
**negative below strike**; the collar's value is the **collapsed tail** (−9.4% of capital).

---

## 5. Slide-5 MC diagnostic (SIMULATED — not decision evidence; MS-26 pending)

Drift band {−0.10, 0, +0.10} (ASSUMED; neutral 0 = no-view anchor), 14,400,000 simulated paths;
reconciles=True, cross-seed variance non-zero, 0 non-finite. % of $1.935B capital (drift 0 shown;
full band in `c8_slide5_mc_pack.md`):

| Archetype (role) | prob-loss | VaR95 | ES97.5 | maxDD | P&L mean | P&L p5 | P&L p95 |
|---|---|---|---|---|---|---|---|
| covered_call (premium) | 0.572 | 42.7% | 53.7% | 28.7% | −$29.9M | −$825.8M | +$1,011.1M |
| long_btc_short_put (accumulation) | 0.568 | 66.6% | 85.6% | 43.0% | −$43.4M | −$1,289.7M | +$1,552.0M |
| collar (protection) | 0.564 | **32.3%** | **40.1%** | **22.8%** | −$1.9M | −$624.2M | +$861.4M |

Made plain (diagnostic, not ranking): **prob-of-loss is BTC-inherent** (~0.57 for every archetype at
drift 0 — the shared holding leg, near-zero P&L at drift 0 by vol drag); **the collar's value is the
collapsed tail**. Holding-vs-overlay decomposed in the pack. MC EAC relabelled as a diagnostic
rolling-programme effective cost (distinct from Slide-1 acquisition EAC).

---

## 6. Disclaimer text (`docs/evidence/c8_disclaimer.md`)

> Full risk analysis of alternative option overlays on the client's existing 30,000-BTC holding.
> Attribution is structure-specific: the covered call's overlay is a non-negative premium cushion
> (down-scenario losses are inherent to holding BTC, not attributable to the overlay); Long BTC +
> short put's overlay adds incremental downside below the strike (that sub-strike loss IS
> attributable to the advised structure). Capped upside is opportunity cost (foregone gain), not a
> loss. Alternatives are presented, not ranked; investment decisions and their outcomes rest with the
> client.

---

## 7. presentation_master_brief.md update

`/home/francisco/btc/presentation_master_brief.md` gained a snapshot-cited **§14 "C8 Computed
Figures"** section that supersedes the illustrative placeholders for the corresponding numbers
(matrix, drift-band MC, anchors, expiries, disclaimer). Numbers only — **no slides built, no
HTML/Marp touched**; illustrative vs computed kept distinct per the brief's own discipline.

---

## 8. Discipline

Every visible figure traces to a computed source + the frozen snapshot; `pending_decision_refs`
(D-1, D-4, D-7, D-9, D-10, MS-25, MS-26) carried through the grid, MC and packs; **both D-1 fee
bases** and the **drift band** shown, never a single pick; no best/optimal/preferred/safest/winning
language; no claim requiring MS-25 (ranking/objective), MS-26 (approved sim methodology) or
CSCV/PBO/DSR. **Phase 5 (whole-system gates + handover) does not begin until this gate is reviewed.**
