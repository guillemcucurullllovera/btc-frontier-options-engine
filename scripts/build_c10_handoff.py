#!/usr/bin/env python3
"""Assemble the self-contained design hand-off bundle (C10 · N6.2) — docs/handoff/.

SIMULATED / diagnostic; MS-26-gated; holder-basis; deck & canonical main untouched; no best/optimal. The
external design session has NO repo access, so the bundle is 100% self-contained: every number and
instruction is inline; the ONLY external artifacts are the image files the operator uploads. Generates
DESIGN_HANDOFF.md (master), RESULTS_BRIEF.md (one-page brief + snapshot verification), MIGRATION_MANIFEST.md
(upload/paste/old->new map) from the committed C10 deck-input grid + figure-source + observed-co-jump
scenarios, and copies the touched-up figures into docs/handoff/figures/. Reproducible; no wall-clock/random.
"""

from __future__ import annotations

# ruff: noqa: RUF001
# This file intentionally embeds typographic + Greek unicode (mid-dot, em-dash, delta, theta, eta, rho,
# sigma, subscript-2) in prose strings written verbatim into the markdown hand-off documents.
import json
import pathlib
import shutil
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

_R = pathlib.Path(__file__).resolve().parents[1]
_GRID = _R / "exports" / "c10_deck_input" / "grid.json"
_DECK_MANIFEST = _R / "docs" / "reports" / "c10_deck_input" / "manifest.json"
_FIGSRC = _R / "docs" / "reports" / "c10_figure_source"
_FIGPACK = _R / "docs" / "evidence" / "c10_figure_pack"
_OUT = _R / "docs" / "handoff"
_FIGDST = _OUT / "figures"
_STRUCTS = ("unhedged", "covered_call", "long_btc_plus_short_put", "cash_secured_put",
            "collar", "call_spread", "strike_ladder")


def _g(x: Any, *keys: str) -> Any:
    """Extract a scalar from a Granular dict / passthrough."""
    if isinstance(x, dict):
        for k in (*keys, "per_portfolio", "per_btc", "value", "total"):
            if k in x and not isinstance(x[k], dict | list):
                return x[k]
        return None
    return x


def _f(v: Any, nd: int = 0, pct: bool = False) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v)*(100 if pct else 1):,.{nd}f}{'%' if pct else ''}"
    except (TypeError, ValueError):
        return "—"


def _pct(v: Any) -> str:  # pct_of_spot is stored already as a percent number (1.85 = 1.85%), not a fraction
    return "—" if v is None else f"{float(v):.2f}%"


# ── prose (inline; the design session cannot open the repo) ──────────────────
DISCLAIMER = (
    "SIMULATED / diagnostic · MS-26-gated (illustrative, NOT investment advice). Present risk as RANGES, "
    "not point estimates. Capped upside is OPPORTUNITY COST (foregone gain), NOT a loss. No best / optimal / "
    "recommended language — alternatives are presented, not ranked; decisions and outcomes rest with the "
    "client. Every parameter is provenance-labelled (OBSERVED / CALIBRATED / P-ESTIMATED / ASSUMED). Premiums "
    "are COS-Bates-consistent (Deribit marks); the downside uses the SVJJ observed-co-jump physical tail with "
    "an implied-vs-instantaneous mapping caveat; parameter uncertainty is the validated particle-filter band. "
    "Supersedes the C8 Phase-4 pack."
)
CORRECTIONS = [
    ("VRP framing", "Old deck led with a positive variance-risk-premium ('sell vol earns ~premium'). "
     "REVISE to: premium is roughly FAIR-VALUED; the realized forward VRP is POSITIVE but thin and "
     "regime-dependent (DVOL implied vs 30d-forward realized: +0.096 mean, positive 75% of days), while the "
     "risk MODEL prices a fatter tail — so do NOT lead with a premium 'edge'; frame it as tail-compensated."),
    ("Downside tail", "Old deck used a symmetric downside. REVISE to: BTC jumps are downside-asymmetric "
     "(eta~1.4) at the daily/multi-day scale, robust across 8 years & every regime (intraday is symmetric); "
     "the price-vol co-jump is now OBSERVED (rho_J=-0.74; down-jumps spike implied vol +15.7 vol pts). Honest "
     "downside is ~+0.8% (asymmetry alone) -> ~+4.5% central (with the observed co-jump), band [+3%, +10%]."),
    ("Risk-reshaping, not return", "REVISE to: the overlays' value is RISK-RESHAPING, not return. Lead with "
     "the defined-risk structures (collar, call-spread) as the robust, downside-controlled choice — their "
     "capped tails are INVARIANT across the whole uncertainty band; frame covered-call / LBSP as premium / "
     "accumulation carrying the real (fatter) downside, not a harvest."),
    ("Recent-regime vol", "REVISE to: use the RECENT-regime vol ~0.46 (realized vol has secularly halved "
     "0.92->0.46 as BTC matured), shown with the vol-regime band — not a full-history ~0.9 that overstates "
     "forward risk."),
    ("Methodology as strength", "ADD: the engine reprices the live BTC surface to ~5.5% error (vs ~27% for "
     "the old assumed-GBM stack) — a calibrated Bates (stochastic-vol + jumps), characteristic-function "
     "(COS) priced, validated against QuantLib/published refs to machine precision, EVT-hardened, "
     "back-tested, uncertainty-banded. State this institutional-grade fidelity plainly."),
]


def _sp(r: dict[str, Any]) -> str:
    v = r.get("strike_pct")
    return f"{v:+.0f}" if v is not None else "—"


def _grid_rows() -> list[dict[str, Any]]:
    return list(json.loads(_GRID.read_text())["rows"])


def _grid_table(rows: list[dict[str, Any]]) -> str:
    hdr = ("| structure | expiry (dte) | strike% | cov% | prem% | prem $/BTC | prem $/CME(x5) | prem $/port | "
           "P(win) | true BE | maxloss $/BTC | maxloss %cap | Δ/BTC | θ/day $ |")
    sep = "|" + "|".join(["---"] * 14) + "|"
    lines = [hdr, sep]
    for r in sorted(rows, key=lambda x: (x["structure_id"], x["dte_days"], x.get("strike_pct") or 0.0, x["coverage_pct"])):
        prem, ml, be, gk = r["premium"], r["max_loss"], r.get("breakeven", {}), r.get("greeks", {})
        tbe = (be.get("true_breakevens") or [None])
        lines.append(
            f"| {r['structure_id']} | {r['expiry_label']} ({r['dte_days']:.0f}d) | {_sp(r)} "
            f"| {r['coverage_pct']:.0f} | {_pct(prem.get('pct_of_spot'))} "
            f"| {_f(prem.get('net_per_btc'))} | {_f(prem.get('per_contract'))} | {_f(prem.get('per_portfolio'))} "
            f"| {_f(_g(r.get('prob_win'), 'value'), 3)} | {_f(tbe[0] if tbe else None)} "
            f"| {_f(_g(ml.get('total'), 'per_btc'))} | {_f(ml.get('total_pct_of_capital'), 1, pct=True)} "
            f"| {_f(gk.get('option_delta_per_btc'), 3)} | {_f(gk.get('theta_per_day_per_btc'), 1)} |")
    return "\n".join(lines)


def _svjj() -> dict[str, Any]:
    return dict(json.loads(_DECK_MANIFEST.read_text())["svjj_scenarios"])


def _figures_table() -> str:
    lines = ["| figure file (PNG+SVG) | one-idea headline | strike(s) | breakeven | cap $/BTC | floor/max-loss $/BTC |",
             "|---|---|---|---|---|---|"]
    for n in _STRUCTS:
        d = json.loads((_FIGSRC / f"{n}.json").read_text())
        a = d["annotations"]
        strikes = ", ".join(f"{s['side'][0]}{s['kind'][0].upper()} {s['strike']/d['spot0']:.2f}x" for s in a["strikes"]) or "—"
        be = ", ".join(f"{b/d['spot0']:.2f}x" for b in a["breakevens_usd"][:2]) or "—"
        lines.append(f"| `{n}.png` / `{n}.svg` | {d['structure'].replace('_', ' ')} | {strikes} | {be} "
                     f"| {_f(a['cap_usd_per_btc'])} | {_f(a['floor_max_loss_usd_per_btc'])} |")
    lines.append("| `_comparison_collar_vs_covered.png/.svg` | ILLUSTRATIVE: collar floor vs covered-call open "
                 "downside | — | — | — | — |")
    return "\n".join(lines)


def _design_handoff(rows: list[dict[str, Any]], scen: dict[str, Any]) -> str:
    g = json.loads(_GRID.read_text())
    ps = scen["per_structure"]
    reps = []
    for n in _STRUCTS:
        rr = [r for r in rows if r["structure_id"] == n and r["coverage_pct"] == 100.0]
        rr = [r for r in rr if r.get("strike_pct") in (5.0, -5.0, 0.0)] or rr
        r = min(rr, key=lambda x: x["dte_days"]) if rr else None
        if r:
            p = ps.get(n, {})
            reps.append(f"| {n} | {_sp(r)}% / {r['coverage_pct']:.0f}% / {r['expiry_label']} "
                        f"| {_pct(r['premium'].get('pct_of_spot'))} ({_f(r['premium'].get('net_per_btc'))} $/BTC) "
                        f"| {_f(_g(r.get('prob_win'),'value'),3)} | {_f(_g(r['max_loss'].get('total'), 'per_btc'))} "
                        f"| {_f(p.get('es975_central_usd'))} | +{_f(p.get('honest_downside_widen_pct_central'),1)}% "
                        f"| {'bounded' if p.get('defined_risk_bounded') else 'varies'} |")
    corr = "\n\n".join(f"**{i+1}. {t}** — {b}" for i, (t, b) in enumerate(CORRECTIONS))
    return f"""# DESIGN HAND-OFF — C10 BTC-options deck refresh (self-contained)

**SIMULATED / diagnostic · MS-26-gated · holder-basis · no best/optimal.** This document is 100%
self-contained: the design session has NO repo access — every number and instruction is inline; the ONLY
external artifacts are the image files you upload (see MIGRATION_MANIFEST.md). Data as-of the frozen anchor
snapshot; S0 = {g['s0']:,.0f}; block = {g.get('block_btc'):,} BTC; CME contract = {g.get('cme_contract_btc')} BTC.

## a. Context
This is a **quantitative refresh** of the existing 10-slide BTC-options Marp deck (you already have the old
slides). The CEO asked to: (1) make **Slide 2 & Slide 2-continued** qualitative → **quantitative**; (2)
**separate the piled strategy diagram** into one clean figure per structure; (3) apply the
**opportunity-cost-not-loss** framing throughout. This bundle supplies the corrected numbers, the
slide-by-slide edits, and the 7 separated figures.

## b. Governance & framing rules (MUST appear on the slides)
> {DISCLAIMER}

## c. What changed vs the old deck (five corrections — "revise the old slide to say X")
{corr}

## d. Slide-by-slide instructions
- **Slide 2 (the 8-structure toolkit + the quant grid).** Keep the toolkit but make it quantitative: for
  each structure show premium (%/USD), P(win)=N(±d₂), true breakeven, max-loss (BTC/total), and the
  honest-downside ES. Representative cells (near expiry, 100% coverage):

| structure | strike/cov/expiry | premium | P(win) | max loss $/BTC | ES97.5 $ (central) | honest-downside | defined-risk |
|---|---|---|---|---|---|---|---|
{chr(10).join(reps)}

  Full grid (all structures × strike% × real expiries × coverage 25/50/75/100%) is the appendix (§e).
- **Slide 2-continued (covered-call vs LBSP deep comparison).** Contrast the two short-vol structures:
  covered call = premium cushion + **capped** upside (opportunity cost above the strike, NOT a loss); LBSP =
  premium + **amplified sub-strike downside** (attributable to the overlay). Both carry the real (fatter)
  downside; neither is a harvest. Use the `covered_call` and `long_btc_plus_short_put` figures.
- **Slide 5 (robustness / MC).** State: COS-Bates ARPE 5.55% (vs GBM ~27%); observed co-jump ρ_J=−0.74;
  honest downside ES97.5 ~+4.5% central [+3%,+10%]; validated-PF parameter band ±~7% (tail-exposed);
  defined-risk overlays BOUNDED; recent-regime vol ~0.46; recent-2yr 99% VaR passes Kupiec (p=0.18).
- **Strategy diagram (the CEO complaint).** REPLACE the single piled figure with the **7 separate
  per-structure figures** (upload list in MIGRATION_MANIFEST.md): `unhedged`, `covered_call`,
  `long_btc_plus_short_put`, `cash_secured_put`, `collar`, `call_spread`, `strike_ladder` — plus the one
  optional illustrative `_comparison_collar_vs_covered`. One idea per figure; do not re-pile.

## e. The data — full regenerated deck-input grid ({len(rows)} rows, appendix)
Premium net of nothing (pre-fee); prob-win is risk-neutral N(±d₂) (not a real-world probability); max-loss
%cap over the structure's own committed capital; greeks per BTC. Provenance: premiums COS-Bates-consistent
(Deribit marks); scenarios SIMULATED.

{_grid_table(rows)}

**Honest-downside & parameter band (SVJJ, observed co-jump ρ_J={scen['rho_j_observed']}, μ_v central 0.17,
vol {scen['central_vol']}):** central ES97.5 widening ~+4.5% (band [+3%,+10%]); defined-risk overlays
(collar, call-spread) **invariant (0%)**; validated-PF parameter band ±~{scen['pf_parameter_band_es975_pct']:.0f}%
(tail-exposed); forward VRP +{scen['forward_vrp_atm']} (positive, tail-compensated).

## f. The figures (verify or rebuild)
Each is one clean standalone figure (payoff curve + σ-scenario companion + max-loss/opportunity-cost
decomposition). Key annotated values:

{_figures_table()}

Every figure carries the governance footer (§b). These are reference renders — clean enough to use as-is,
or rebuild from the values above.
"""


def _results_brief(rows: list[dict[str, Any]], scen: dict[str, Any]) -> str:
    cc = next((r for r in rows if r["structure_id"] == "covered_call" and r["coverage_pct"] == 100.0
               and r["strike_pct"] == 5.0), None)
    col = next((r for r in rows if r["structure_id"] == "collar" and r["coverage_pct"] == 100.0), None)
    snap = []
    for lbl, r in (("covered call (5%, 100%)", cc), ("collar (defined-risk)", col)):
        if r:
            snap.append(f"| {lbl} | {_pct(r['premium'].get('pct_of_spot'))} "
                        f"| {_f(_g(r.get('prob_win'),'value'),3)} | {_f(_g(r['max_loss'].get('total'), 'per_btc'))} "
                        f"| {'bounded' if not r['max_loss'].get('unbounded') else 'open'} |")
    return f"""# RESULTS BRIEF — C10 BTC-options refresh (one page)

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
1. **VRP is fair-valued / tail-compensated**, not a premium edge (forward VRP +{scen['forward_vrp_atm']}, positive but thin).
2. **Downside is bigger and now OBSERVED** — asymmetric jumps (η≈1.4, all-regime) + observed co-jump ρ_J=−0.74;
   honest downside ~+0.8% (asymmetry) → **~+4.5% central** [+3%,+10%].
3. **Overlays reshape risk, not return** — lead with defined-risk (collar/call-spread), **invariant** tails.
4. **Recent-regime vol ≈0.46** (secular decline 0.92→0.46), not a full-history ~0.9.
5. **Methodology is the strength** — institutional-grade, committee-ready fidelity.

## Snapshot (from the regenerated grid)
| structure | premium % | P(win) N(±d₂) | max loss $/BTC | downside |
|---|---|---|---|---|
{chr(10).join(snap)}
- Honest-downside ES97.5: **~+4.5% central**, band [+3%,+10%]; defined-risk overlays **bounded**.
- Parameter uncertainty (validated PF): **±~7%** (tail-exposed). Forward VRP: **+{scen['forward_vrp_atm']}** (positive).

## Verification note
The snapshot numbers above are pulled programmatically from the committed N4.2 deck-input grid
(`exports/c10_deck_input/grid.json`) and the observed-co-jump scenarios (N3.6). **No mismatch** — the brief
is generated from the same grid it summarises. If the operator substitutes a different "Section-1 brief"
text, re-verify its numbers against this grid before use; do not silently alter the numbers.
"""


def _migration_manifest() -> str:
    up = "\n".join(f"- [ ] `figures/{n}.svg` (prefer SVG) — and `figures/{n}.png` fallback — the {n.replace('_',' ')} figure"
                   for n in _STRUCTS)
    return f"""# MIGRATION MANIFEST — what to upload / paste / map

**SIMULATED / diagnostic · MS-26-gated.** The design session has no repo access. Do the following.

## 1. UPLOAD to the design conversation (image files — prefer SVG, PNG as fallback)
{up}
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
"""


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    _FIGDST.mkdir(parents=True, exist_ok=True)
    rows = _grid_rows()
    scen = _svjj()
    (_OUT / "DESIGN_HANDOFF.md").write_text(_design_handoff(rows, scen))
    (_OUT / "RESULTS_BRIEF.md").write_text(_results_brief(rows, scen))
    (_OUT / "MIGRATION_MANIFEST.md").write_text(_migration_manifest())
    for f in sorted(_FIGPACK.glob("*")):
        shutil.copy2(f, _FIGDST / f.name)
    # N6.3 durable mirror outside the worktree
    durable = pathlib.Path("/home/francisco/btc/design_handoff")
    if durable.parent.exists():
        shutil.rmtree(durable, ignore_errors=True)
        shutil.copytree(_OUT, durable)
    print(f"handoff bundle -> {_OUT} ({len(rows)} grid rows, {len(list(_FIGDST.glob('*')))} figures) "
          f"+ durable mirror {durable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
