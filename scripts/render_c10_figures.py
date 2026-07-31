#!/usr/bin/env python3
"""Render the SEPARATE, clean, one-per-structure reference figures (C10 · N5) — PNG + SVG.

SIMULATED / diagnostic; MS-26-gated; holder-basis; deck & canonical main untouched; no best/optimal.
Renders ONE standalone figure per structure (7) from the N4.5 figure-source JSONs + c10_figure_spec.md:
an annotated expiry payoff curve (P&L vs spot; strike/spot/breakeven/cap/floor labelled) with a slim
sigma-scenario companion strip and a max-loss / opportunity-cost callout — one idea per figure, NEVER a
piled multi-panel. Clarity-first: validated dataviz palette (series-1 blue payoff; status-red loss fill,
labelled; hatched opportunity-cost region; single-hue sigma bars, sign by position), minimal ink,
recessive axes, direct labels, colorblind-safe. DETERMINISTIC (Agg, fixed hashsalt, no wall-clock/random).
These are REFERENCE renders for the design session, not final deck slides. Output: docs/evidence/c10_figure_pack/.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

_SRC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "reports" / "c10_figure_source"
_OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "evidence" / "c10_figure_pack"

# validated dataviz palette (light surface) — roles, not raw taste
C_SURFACE, C_INK, C_MUTED, C_GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e2e1dd"
C_PAYOFF, C_LOSS, C_STRIKE = "#2a78d6", "#d03b3b", "#9a9992"      # series-1 blue / status-red / muted guide
_WIDE = ("unhedged", "covered_call", "long_btc_plus_short_put", "cash_secured_put", "strike_ladder")
_DEFINED = ("collar", "call_spread")
_TITLE = {
    "unhedged": "Unhedged — hold BTC (baseline)",
    "covered_call": "Covered call — premium cushion, capped upside",
    "long_btc_plus_short_put": "Long BTC + short put — amplified downside for premium",
    "cash_secured_put": "Cash-secured put — acquire lower, premium income",
    "collar": "Collar — defined-risk: floored downside",
    "call_spread": "Call spread (credit) — defined-risk, tight",
    "strike_ladder": "Strike ladder — staged capped upside",
}
_FOOTER = ("SIMULATED / diagnostic · MS-26-gated · holder-basis · illustrative, not advice · no best/optimal.\n"
           "Premiums COS-Bates-consistent; downside per the SVJJ observed co-jump. Reference render, not a slide.")


def _setup() -> None:
    mpl.rcParams.update({
        "svg.hashsalt": "c10-figure-pack", "figure.facecolor": C_SURFACE, "axes.facecolor": C_SURFACE,
        "savefig.facecolor": C_SURFACE, "font.family": "DejaVu Sans", "font.size": 10,
        "axes.edgecolor": C_MUTED, "axes.linewidth": 0.8, "text.color": C_INK,
        "axes.labelcolor": C_INK, "xtick.color": C_MUTED, "ytick.color": C_MUTED, "svg.fonttype": "none",
    })


def _fmt_k(x: float) -> str:
    return f"{x/1000:+.0f}k" if abs(x) >= 1000 else f"{x:+.0f}"


def _render(name: str, d: dict[str, Any], y_lim: tuple[float, float]) -> None:
    s0 = d["spot0"]
    pc = d["payoff_curve"]
    spot = [x / s0 for x in pc["spot"]]                      # x in multiples of spot
    pnl = pc["pnl_usd_per_btc"]
    a = d["annotations"]
    dec = d["max_loss_opportunity_decomp"]

    fig = plt.figure(figsize=(7.2, 5.4))
    gs = GridSpec(2, 1, height_ratios=[3.1, 1.0], hspace=0.42, left=0.11, right=0.97, top=0.90, bottom=0.13)
    ax = fig.add_subplot(gs[0])
    ax.axhline(0, color=C_GRID, lw=1.0, zorder=1)
    ax.plot(spot, [x - s0 for x in pc["spot"]], color=C_MUTED, lw=1.1, ls=(0, (4, 3)), zorder=2,
            label="hold BTC (reference)")
    ax.plot(spot, pnl, color=C_PAYOFF, lw=2.2, zorder=4, label=name.replace("_", " "))
    # loss region (P&L<0), status-red faint + labelled (never colour-alone)
    ax.fill_between(spot, pnl, 0, where=[p < 0 for p in pnl], color=C_LOSS, alpha=0.10, zorder=1)
    # opportunity-cost wedge (foregone gain vs holding, above spot) — hatched, labelled
    ax.fill_between(spot, pnl, [x - s0 for x in pc["spot"]],
                    where=[(u - s0) - p > 1 and x > 1.0 for x, p, u in zip(spot, pnl, pc["spot"], strict=True)],
                    facecolor="none", hatch="////", edgecolor=C_MUTED, lw=0.0, alpha=0.55, zorder=1)
    # guides: spot ref + strikes
    ax.axvline(1.0, color=C_MUTED, lw=0.8, ls=":", zorder=2)
    ax.annotate("spot", (1.0, y_lim[1]), xytext=(0, -2), textcoords="offset points", ha="center",
                va="top", fontsize=8, color=C_MUTED)
    for st in a["strikes"]:
        xr = st["strike"] / s0
        ax.axvline(xr, color=C_STRIKE, lw=0.8, ls=":", zorder=2)
        ax.annotate(f"{st['side'][0]}{st['kind'][0].upper()} {xr:.2f}x", (xr, y_lim[0]), xytext=(2, 2),
                    textcoords="offset points", ha="left", va="bottom", fontsize=7.5, color=C_STRIKE)
    # cap / floor / breakeven direct labels
    ax.annotate(f"cap {_fmt_k(a['cap_usd_per_btc'])}", (spot[-1], a["cap_usd_per_btc"]), xytext=(-2, 12),
                textcoords="offset points", ha="right", va="bottom", fontsize=8.5, color=C_PAYOFF)
    # floor/max-loss label sits in the empty loss triangle (left, wide part), clear of the rising curve
    ax.annotate(f"max loss {_fmt_k(a['floor_max_loss_usd_per_btc'])}",
                (spot[0] + 0.06 * (spot[-1] - spot[0]), a["floor_max_loss_usd_per_btc"] * 0.36),
                ha="left", va="center", fontsize=8.5, color=C_LOSS)
    for be in a["breakevens_usd"][:2]:
        ax.plot([be / s0], [0], "o", ms=6, color=C_INK, zorder=5)
        ax.annotate(f"BE {be/s0:.2f}x", (be / s0, 0), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=8, color=C_INK)
    ax.set_xlim(spot[0], spot[-1])
    ax.set_ylim(*y_lim)
    ax.set_ylabel("P&L at expiry (USD / BTC)")
    ax.set_title(_TITLE[name], fontsize=12.5, color=C_INK, loc="left", pad=8)
    ax.legend(loc="upper left", frameon=False, fontsize=8.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda v, _p: _fmt_k(v))
    # opportunity-cost label placed inside the hatched wedge, clear of the right-side cap label; the
    # zoomed defined-risk plots (wedge fills the top) get an upper-left placement, wide plots a mid placement.
    if dec.get("max_opportunity_cost_usd_per_btc", 0) > 1:
        pos, ha, va = ((1.13, y_lim[1] * 0.88), "left", "top") if name in _DEFINED \
            else ((1.48, y_lim[1] * 0.60), "center", "center")
        ax.annotate(f"opportunity cost {_fmt_k(dec['max_opportunity_cost_usd_per_btc'])}/BTC\n"
                    "(foregone gain, NOT a loss)", pos, ha=ha, va=va, fontsize=7.6, color=C_MUTED)

    # slim sigma-scenario companion (single hue, sign by position, value-labelled)
    axb = fig.add_subplot(gs[1])
    bars = d["sigma_scenario_bars"]
    xs = [f"{b['sigma']:+d}σ" if b["sigma"] else "spot" for b in bars]  # noqa: RUF001
    ys = [b["pnl_usd_per_btc"] for b in bars]
    axb.axhline(0, color=C_GRID, lw=1.0)
    axb.bar(xs, ys, color=C_PAYOFF, width=0.6, zorder=3)
    for x, y in zip(xs, ys, strict=True):
        axb.annotate(_fmt_k(y), (x, y), xytext=(0, 3 if y >= 0 else -3), textcoords="offset points",
                     ha="center", va="bottom" if y >= 0 else "top", fontsize=7.5, color=C_MUTED)
    axb.set_title("P&L across ±σ spot scenarios (vol 0.46, 45d)", fontsize=9, color=C_MUTED, loc="left")  # noqa: RUF001
    axb.set_yticks([])
    axb.spines[["top", "right", "left"]].set_visible(False)
    axb.margins(y=0.30)

    fig.text(0.11, 0.010, _FOOTER, fontsize=6.2, color=C_MUTED, ha="left", va="bottom", linespacing=1.4)
    for ext, meta in (("png", {"Software": "c10-figure-pack"}),
                      ("svg", {"Date": None, "Creator": "c10-figure-pack"})):
        fig.savefig(_OUT / f"{name}.{ext}", dpi=150, metadata=meta)
    plt.close(fig)


def _render_comparison(datas: dict[str, dict[str, Any]]) -> None:
    """N5.2 — the ONE optional illustrative comparison: collar floor vs covered-call open downside."""
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    fig.subplots_adjust(left=0.11, right=0.97, top=0.88, bottom=0.24)
    ax.axhline(0, color=C_GRID, lw=1.0)
    for name, col, lbl in (("covered_call", C_LOSS, "covered call (open downside)"),
                           ("collar", C_PAYOFF, "collar (floored downside)")):
        d = datas[name]
        s0 = d["spot0"]
        ax.plot([x / s0 for x in d["payoff_curve"]["spot"]], d["payoff_curve"]["pnl_usd_per_btc"],
                color=col, lw=2.2, label=lbl)
    ax.set_xlim(0.45, 1.75)
    ax.set_xlabel("spot (x initial)")
    ax.set_ylabel("P&L at expiry (USD / BTC)")
    ax.set_title("Illustrative — collar floor vs covered-call open downside",
                 fontsize=11.5, color=C_INK, loc="left", pad=8)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda v, _p: _fmt_k(v))
    fig.text(0.11, 0.015, _FOOTER, fontsize=6.2, color=C_MUTED, ha="left", va="bottom", linespacing=1.4)
    ax.text(0.5, 0.965, "illustrative side-by-side · separate from the 7 per-structure figures",
            transform=ax.transAxes, ha="center", va="top", fontsize=7.5, color=C_MUTED)
    for ext, meta in (("png", {"Software": "c10-figure-pack"}),
                      ("svg", {"Date": None, "Creator": "c10-figure-pack"})):
        fig.savefig(_OUT / f"_comparison_collar_vs_covered.{ext}", dpi=150, metadata=meta)
    plt.close(fig)


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    _setup()
    datas = {p.stem: json.loads(p.read_text()) for p in _SRC.glob("*.json")}
    wide_floor = min(datas[n]["annotations"]["floor_max_loss_usd_per_btc"] for n in _WIDE)
    wide_cap = max(datas[n]["annotations"]["cap_usd_per_btc"] for n in _WIDE)
    wide_ylim = (wide_floor * 1.12, wide_cap * 1.12)
    for name, d in datas.items():
        if name in _DEFINED:
            fl, cp = d["annotations"]["floor_max_loss_usd_per_btc"], d["annotations"]["cap_usd_per_btc"]
            pad = 0.35 * (cp - fl)
            _render(name, d, (fl - pad, cp + pad))          # zoomed y for the defined-risk structures
        else:
            _render(name, d, wide_ylim)
    _render_comparison(datas)
    manifest = {
        "provenance": "SIMULATED / diagnostic; MS-26-gated; holder-basis; deterministic render; no best/optimal",
        "rendered_from": "docs/reports/c10_figure_source/*.json + docs/reports/c10_figure_spec.md",
        "note": "Reference renders for the design session, NOT final deck slides. One clean figure per structure.",
        "figures": [{"file": f"{n}.{{png,svg}}", "structure": n, "shows": _TITLE[n],
                     "source_json": f"docs/reports/c10_figure_source/{n}.json"} for n in datas],
        "comparison_figure": {"file": "_comparison_collar_vs_covered.{png,svg}",
                              "shows": "ILLUSTRATIVE: defined-risk collar floor vs covered-call open downside",
                              "note": "separate from the 7 per-structure figures; illustrative only"},
        "footer_text": _FOOTER,
    }
    (_OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"rendered {len(datas)} per-structure figures + 1 comparison (PNG+SVG) + manifest to {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
