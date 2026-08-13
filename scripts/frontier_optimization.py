#!/usr/bin/env python3
"""C9 · CVaR efficient-frontier optimization over holder-inclusive overlay structures.

DIAGNOSTIC / SIMULATED. Consumes the Phase-1 SVJJ P&L arrays (strategy_figures/svjj_pnl_arrays.npz),
builds the (median P&L vs CVaR95) efficient frontier PER REGIME over the fixed structure set, then
parameter-sweeps the key knobs (covered-call strike & coverage, collar put-floor, ladder rungs,
covered-call-spread width, tenor) by repricing option legs (Black-Scholes at the OBSERVED ATM IV,
r=0 -- the exact Phase-1 frozen-Q marking convention, validated to reproduce the fixed arrays) on the
EXACT terminal spots recovered from the just_holding array (common random numbers vs the fixed
candidates). Applies the APPROVED objective (maximize median P&L / CVaR95 s.t. CVaR95 <= budget) to
select the objective-optimal structure per regime.

The frontier is DRAWN; the objective (median/CVaR95) selects the point. No unqualified 'optimal'.

Writes strategy_figures/frontier.json.
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass, asdict

import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from risk.cvar_frontier import ru_cvar  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARR = ROOT / "strategy_figures" / "svjj_pnl_arrays.npz"
OUT = ROOT / "strategy_figures" / "frontier.json"

S0 = 63401.86
BLOCK = 30000.0
NOTIONAL = S0 * BLOCK  # ~$1.902B long-BTC notional
REGIMES = ["risk_neutral", "bear_current", "stress", "bull", "sideways"]
TENORS = {"28AUG26": (31, 0.3653), "25SEP26": (59, 0.3702)}  # label -> (dte_days, atm_iv)
PRIMARY = "28AUG26"
BETA = 0.95
# Named loss-budget caps as a fraction of long-BTC notional (stand-ins for the client D-10 budget).
NAMED_CAPS = {"2.5pct": 0.025, "5pct": 0.05, "7.5pct": 0.075, "10pct": 0.10,
              "15pct": 0.15, "20pct": 0.20, "30pct": 0.30}


def bs(S: float, K: float, T: float, iv: float, kind: str) -> float:
    """Black-Scholes premium/BTC at r=0 (frozen-Q ATM-IV mark; Phase-1 convention)."""
    d1 = (np.log(S / K) + 0.5 * iv * iv * T) / (iv * np.sqrt(T))
    d2 = d1 - iv * np.sqrt(T)
    if kind == "call":
        return float(S * norm.cdf(d1) - K * norm.cdf(d2))
    return float(K * norm.cdf(-d2) - S * norm.cdf(-d1))


def metrics(pnl: np.ndarray) -> tuple[float, float, float]:
    """(median USD, CVaR95 loss USD, mean USD)."""
    med = float(np.median(pnl))
    _, cvar = ru_cvar(pnl, beta=BETA)
    return med, float(cvar), float(np.mean(pnl))


# ── parametric overlay families (holder-inclusive: long block + option legs) ──
# Each returns total-USD P&L on the 30k block given terminal spots ST (per-BTC leg then * BLOCK).

def pnl_covered_call(ST, holding, T, iv, strike_pct, coverage):
    K = S0 * (1.0 + strike_pct / 100.0)
    prem = bs(S0, K, T, iv, "call")
    overlay = coverage * (prem - np.maximum(ST - K, 0.0))
    return holding + BLOCK * overlay


def pnl_collar(ST, holding, T, iv, call_pct, put_pct, coverage=1.0):
    Kc = S0 * (1.0 + call_pct / 100.0)
    Kp = S0 * (1.0 + put_pct / 100.0)
    pc = bs(S0, Kc, T, iv, "call")
    pp = bs(S0, Kp, T, iv, "put")
    overlay = coverage * ((pc - np.maximum(ST - Kc, 0.0)) - (pp - np.maximum(Kp - ST, 0.0)))
    return holding + BLOCK * overlay


def pnl_strike_ladder(ST, holding, T, iv, rungs_pct, cov_each):
    overlay = np.zeros_like(ST)
    for pct in rungs_pct:
        K = S0 * (1.0 + pct / 100.0)
        prem = bs(S0, K, T, iv, "call")
        overlay = overlay + cov_each * (prem - np.maximum(ST - K, 0.0))
    return holding + BLOCK * overlay


def pnl_cc_spread(ST, holding, T, iv, short_pct, long_pct, coverage=1.0):
    Ks = S0 * (1.0 + short_pct / 100.0)
    Kl = S0 * (1.0 + long_pct / 100.0)
    ps = bs(S0, Ks, T, iv, "call")
    pl = bs(S0, Kl, T, iv, "call")
    overlay = coverage * ((ps - np.maximum(ST - Ks, 0.0)) - (pl - np.maximum(ST - Kl, 0.0)))
    return holding + BLOCK * overlay


def pnl_protective_ladder(ST, holding, T, iv, call_cov, call_pct, put_pct):
    Kc = S0 * (1.0 + call_pct / 100.0)
    Kp = S0 * (1.0 + put_pct / 100.0)
    pc = bs(S0, Kc, T, iv, "call")
    pp = bs(S0, Kp, T, iv, "put")
    overlay = call_cov * (pc - np.maximum(ST - Kc, 0.0)) - (pp - np.maximum(Kp - ST, 0.0))
    return holding + BLOCK * overlay


@dataclass
class Cand:
    label: str
    family: str
    params: dict
    tenor: str
    median: float
    cvar: float
    mean: float
    ratio: float  # median / cvar (objective)
    swept: bool


def build_candidates(d, regime):
    """Fixed (from arrays) + swept (repriced) candidates for a regime, across both tenors."""
    cands: list[Cand] = []
    fixed_names = ["covered_call", "collar", "strike_ladder", "covered_call_spread",
                   "long_btc_plus_short_put", "cash_secured_put", "ladder_L1_entry",
                   "ladder_L2_tenor", "ladder_L3_protective", "ladder_L5_adaptive"]
    for ten in TENORS:
        for nm in fixed_names:
            arr = d[f"{nm}__{regime}__{ten}"]
            med, cvar, mean = metrics(arr)
            cands.append(Cand(f"FIXED:{nm}", nm, {"tenor": ten}, ten, med, cvar, mean,
                              med / cvar if cvar > 0 else float("nan"), False))
    # just_holding benchmark (both tenors)
    for ten in TENORS:
        arr = d[f"just_holding__{regime}__{ten}"]
        med, cvar, mean = metrics(arr)
        cands.append(Cand("BENCHMARK:just_holding", "just_holding", {"tenor": ten}, ten,
                          med, cvar, mean, med / cvar if cvar > 0 else float("nan"), False))

    # ── swept knobs (repriced on recovered terminal spots; CRN with fixed) ──
    for ten, (dte, iv) in TENORS.items():
        T = dte / 365.0
        jh = d[f"just_holding__{regime}__{ten}"]
        ST = jh / BLOCK + S0
        holding = jh

        # covered call: strike x coverage
        for sp in [2, 3, 4, 5, 6, 8, 10]:
            for cov in [0.25, 0.50, 0.75, 1.0]:
                p = pnl_covered_call(ST, holding, T, iv, sp, cov)
                med, cvar, mean = metrics(p)
                cands.append(Cand(f"SWEEP:covered_call(+{sp}%,{int(cov*100)}%)", "covered_call",
                                  {"strike_pct": sp, "coverage": cov, "tenor": ten}, ten,
                                  med, cvar, mean, med / cvar if cvar > 0 else float("nan"), True))

        # collar: call strike x put floor (includes tight floors -> low-risk frontier anchor)
        for cp in [2, 3, 4, 5, 6, 8]:
            for pp in [-3, -5, -8, -10, -12, -15, -20]:
                p = pnl_collar(ST, holding, T, iv, cp, pp)
                med, cvar, mean = metrics(p)
                cands.append(Cand(f"SWEEP:collar(call+{cp}%/put{pp}%)", "collar",
                                  {"call_pct": cp, "put_pct": pp, "tenor": ten}, ten,
                                  med, cvar, mean, med / cvar if cvar > 0 else float("nan"), True))

        # strike ladder: rung sets x coverage-per-rung
        rung_sets = {
            "4/8/12/16": [4, 8, 12, 16], "3/6/9/12": [3, 6, 9, 12], "5/10/15/20": [5, 10, 15, 20],
            "4/6/8/10": [4, 6, 8, 10], "4/8": [4, 8], "3/5/7": [3, 5, 7], "2/4/6/8": [2, 4, 6, 8],
        }
        for name, rungs in rung_sets.items():
            for tot_cov in [0.5, 0.75, 1.0]:
                cov_each = tot_cov / len(rungs)
                p = pnl_strike_ladder(ST, holding, T, iv, rungs, cov_each)
                med, cvar, mean = metrics(p)
                cands.append(Cand(f"SWEEP:strike_ladder({name},tot{int(tot_cov*100)}%)", "strike_ladder",
                                  {"rungs_pct": rungs, "cov_total": tot_cov, "tenor": ten}, ten,
                                  med, cvar, mean, med / cvar if cvar > 0 else float("nan"), True))

        # covered-call spread: short strike x width
        for ss in [3, 4, 5]:
            for width in [3, 5, 7, 9]:
                p = pnl_cc_spread(ST, holding, T, iv, ss, ss + width)
                med, cvar, mean = metrics(p)
                cands.append(Cand(f"SWEEP:cc_spread(+{ss}%/+{ss+width}%)", "covered_call_spread",
                                  {"short_pct": ss, "long_pct": ss + width, "tenor": ten}, ten,
                                  med, cvar, mean, med / cvar if cvar > 0 else float("nan"), True))

        # protective ladder: call coverage x call strike x put floor
        for cc in [0.40, 0.50, 0.667, 0.75]:
            for cpct in [4, 5, 6]:
                for ppct in [-8, -10, -12, -15]:
                    p = pnl_protective_ladder(ST, holding, T, iv, cc, cpct, ppct)
                    med, cvar, mean = metrics(p)
                    cands.append(Cand(
                        f"SWEEP:protective_ladder({int(cc*100)}%call+{cpct}%/put{ppct}%)",
                        "protective_ladder",
                        {"call_cov": cc, "call_pct": cpct, "put_pct": ppct, "tenor": ten}, ten,
                        med, cvar, mean, med / cvar if cvar > 0 else float("nan"), True))
    return cands


def frontier_points(cands, n_budgets=24):
    """(median vs CVaR) frontier: sweep loss budgets; at each, admissible set + median-maximizer."""
    cvars = np.array([c.cvar for c in cands])
    lo, hi = float(cvars.min()), float(cvars.max())
    budgets = np.linspace(lo, hi, n_budgets)
    pts = []
    for b in budgets:
        adm = [c for c in cands if c.cvar <= b]
        if not adm:
            pts.append({"loss_budget": float(b), "n_admissible": 0, "admissible_families": [],
                        "median_max_label": None, "median": None, "cvar": None,
                        "objective_label": None, "objective_ratio": None})
            continue
        best_med = max(adm, key=lambda c: c.median)
        # objective within budget: max median/cvar among admissible with positive cvar
        obj = max(adm, key=lambda c: (c.ratio if np.isfinite(c.ratio) else -1e18))
        fams = sorted({c.family for c in adm})
        pts.append({
            "loss_budget": float(b), "n_admissible": len(adm), "admissible_families": fams,
            "median_max_label": best_med.label, "median": best_med.median, "cvar": best_med.cvar,
            "objective_label": obj.label, "objective_ratio": obj.ratio,
            "objective_median": obj.median, "objective_cvar": obj.cvar,
        })
    return pts, (lo, hi)


def main():
    d = np.load(ARR)
    out = {
        "provenance": "DIAGNOSTIC / SIMULATED. SVJJ physical paths (Phase-1 seed 20260810, n_paths=300000, "
                      "antithetic, CRN within regime). Option legs marked Black-Scholes at OBSERVED ATM IV, "
                      "r=0 (frozen-Q convention; validated to reproduce the fixed-candidate arrays exactly). "
                      "Sweep reprices legs on the EXACT terminal spots recovered from just_holding (CRN vs "
                      "fixed). The frontier is DRAWN; the APPROVED objective (median/CVaR95) selects the point.",
        "objective": "maximize risk-adjusted return = median P&L / CVaR95 (beta=0.95), s.t. CVaR95 <= "
                     "loss-budget cap. Frontier reported across a budget sweep; objective-selected point = "
                     "admissible structure with the highest median/CVaR95 per regime.",
        "calibration": {"s0": S0, "block_btc": BLOCK, "r": 0.0, "beta": BETA,
                        "tenors": {k: {"dte_days": v[0], "atm_iv": v[1]} for k, v in TENORS.items()},
                        "primary_tenor": PRIMARY, "n_paths": 300000},
        "regimes": {},
    }

    out["notional_usd"] = NOTIONAL
    out["ratio_objective_note"] = (
        "median/CVaR95 is MONOTONE toward lower CVaR: an unconstrained ratio-max collapses to a near-locked "
        "collar (tight call cap + tight put floor ~ a cash-like box, ratio->~1 in risk_neutral). It is therefore "
        "CAP-INVARIANT (the min-CVaR admissible point wins at any budget) and is reported as a corner, NOT as a "
        "recommended overlay. The DECISION-RELEVANT selection is the frontier's MEDIAN-MAXIMIZER at the client's "
        "loss-budget cap, which actually spends the budget. Both are reported per regime and per named cap.")
    out["median_maximizer_note"] = (
        "The median-maximizer at a fixed CVaR cap pushes the SHORT-CALL strike toward ATM: a richer call "
        "premium both lifts the median AND is received in the crash states, cushioning the CVaR tail -- so a "
        "lower-strike short call Pareto-dominates a higher-strike one at equal put floor. Taken to the limit "
        "this becomes a premium-grab / near-forward-sale. 'objective_selected_featured_band' re-runs the "
        "selection constrained to short-call strike >= +4% (the client's featured upside band) for a "
        "deployable pick. CSP (cash_secured_put) is a SEPARATE accumulation sleeve on its own basis; where it "
        "appears in a head-to-head it is a cross-sleeve reference, not a like-for-like overlay swap.")

    def _c(c):
        return {"label": c.label, "family": c.family, "params": c.params, "tenor": c.tenor,
                "median_usd": c.median, "cvar95_usd": c.cvar, "mean_usd": c.mean,
                "ratio_median_over_cvar": c.ratio, "swept": c.swept}

    print(f"{'regime':13} {'median-max @10% cap (191M)':40}{'median$':>13}{'cvar$':>13}{'ratio':>7}")
    for reg in REGIMES:
        cands = build_candidates(d, reg)
        pts, (lo, hi) = frontier_points(cands)
        finite = [c for c in cands if np.isfinite(c.ratio)]
        prim = [c for c in finite if c.tenor == PRIMARY]

        def fixed_pt(fam):
            m = [c for c in cands if c.label == f"FIXED:{fam}" and c.tenor == PRIMARY]
            return m[0] if m else None
        cc = fixed_pt("covered_call"); co = fixed_pt("collar")

        # named loss-budget-cap selection table (median-maximizer = decision-relevant; ratio-max = corner)
        cap_table = []
        for cap_name, frac in NAMED_CAPS.items():
            cap = frac * NOTIONAL
            adm = [c for c in prim if c.cvar <= cap]
            if not adm:
                cap_table.append({"cap": cap_name, "cap_usd": cap, "n_admissible": 0,
                                  "median_maximizer": None, "ratio_max_corner": None})
                continue
            mm = max(adm, key=lambda c: c.median)
            rm = max(adm, key=lambda c: c.ratio)
            cap_table.append({"cap": cap_name, "cap_usd": cap, "cap_pct_notional": frac,
                              "n_admissible": len(adm),
                              "median_maximizer": _c(mm), "ratio_max_corner": _c(rm)})

        # headline decision-relevant selection: median-maximizer at 10% notional cap
        cap10 = 0.10 * NOTIONAL
        adm10 = [c for c in prim if c.cvar <= cap10]
        sel = max(adm10, key=lambda c: c.median) if adm10 else max(prim, key=lambda c: c.median)
        # featured-band-constrained pick: short-call strike >= +4% (client's featured upside band),
        # median-maximizer at 10% cap -- avoids the near-ATM premium-grab boundary.
        def call_ok(c):
            k = c.params.get("call_pct", c.params.get("strike_pct", 99))
            return k is None or k >= 4
        adm10_fb = [c for c in adm10 if call_ok(c)]
        sel_fb = max(adm10_fb, key=lambda c: c.median) if adm10_fb else None
        # unconstrained ratio corner (any tenor + primary)
        corner_prim = max(prim, key=lambda c: c.ratio)

        def dominates(a, b):
            return a.median >= b.median and a.cvar <= b.cvar and (a.median > b.median or a.cvar < b.cvar)

        # head-to-head: best median achievable at the SAME CVaR budget as cc / as collar
        def median_max_at(cap):
            adm = [c for c in prim if c.cvar <= cap]
            return max(adm, key=lambda c: c.median) if adm else None
        mm_at_cc = median_max_at(cc.cvar)
        mm_at_co = median_max_at(co.cvar)

        ref = {}
        for fam in ["covered_call", "collar", "cash_secured_put", "ladder_L1_entry",
                    "ladder_L3_protective", "strike_ladder", "covered_call_spread",
                    "long_btc_plus_short_put", "ladder_L5_adaptive"]:
            c = fixed_pt(fam)
            if c:
                ref[fam] = {"label": c.label, "median_usd": c.median, "cvar95_usd": c.cvar,
                            "mean_usd": c.mean, "ratio_median_over_cvar": c.ratio}

        # Pareto-efficient set (median up, cvar down), primary tenor
        eff = [c for c in prim if not any(
            (o.median >= c.median and o.cvar <= c.cvar and (o.median > c.median or o.cvar < c.cvar))
            for o in prim if o.label != c.label)]
        eff.sort(key=lambda c: c.cvar)

        out["regimes"][reg] = {
            "cvar_range_usd": [lo, hi],
            "frontier_points": pts,
            "loss_budget_cap_selection": cap_table,
            "objective_selected_decision_relevant": {
                "rule": "median-maximizer among admissible (CVaR95 <= 10% notional = $190.2M cap)",
                **_c(sel)},
            "objective_selected_featured_band": {
                "rule": "median-maximizer at 10% cap with short-call strike >= +4% (client featured band; "
                        "avoids the near-ATM premium-grab boundary)",
                **(_c(sel_fb) if sel_fb else {"label": None})},
            "ratio_max_corner": {
                "rule": "unconstrained argmax median/CVaR95 (min-risk corner; NOT recommended)",
                **_c(corner_prim)},
            "fixed_reference_points": ref,
            "beats_plain_covered_call": {
                "compare_at": "same CVaR budget as the covered call",
                "cc": _c(cc),
                "best_median_at_cc_cvar": _c(mm_at_cc) if mm_at_cc else None,
                "median_uplift_usd": (mm_at_cc.median - cc.median) if mm_at_cc else None,
                "pareto_dominates_cc": bool(mm_at_cc and dominates(mm_at_cc, cc)),
            },
            "beats_collar": {
                "compare_at": "same CVaR budget as the fixed collar (call+5/put-10)",
                "collar": _c(co),
                "best_median_at_collar_cvar": _c(mm_at_co) if mm_at_co else None,
                "median_uplift_usd": (mm_at_co.median - co.median) if mm_at_co else None,
                "pareto_dominates_collar": bool(mm_at_co and dominates(mm_at_co, co)),
                "collar_ratio": co.ratio, "best_ratio": corner_prim.ratio,
            },
            "top10_by_median_at_10pct_cap": [
                _c(c) for c in sorted(adm10, key=lambda c: c.median, reverse=True)[:10]],
            "efficient_set_primary_tenor": [_c(c) for c in eff],
        }

        print(f"{reg:13} {sel.label:40}{sel.median:13.0f}{sel.cvar:13.0f}{sel.ratio:7.3f}")

    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nWROTE {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
