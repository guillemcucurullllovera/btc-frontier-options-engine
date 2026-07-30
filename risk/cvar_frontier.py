"""CVaR loss-budget efficient frontier (Rockafellar-Uryasev) over the structure grid.

DIAGNOSTIC / SIMULATED (consumes simulated P&L; gated on D-10 loss budget + MS-25
objective + MS-26 methodology). This is NOT a ranking or a single pick: for each
loss budget it reports the ADMISSIBLE set of structures (CVaR <= budget) and the
Pareto-efficient frontier of (CVaR, expected outcome). The client's D-10 loss
budget selects a point; the engine only draws the frontier.

CVaR (Rockafellar-Uryasev 2000): CVaR_b(L) = min_a [ a + (1/(1-b)) E[(L-a)+] ],
whose discrete optimum is the mean of the worst (1-b) fraction of losses.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Candidate:
    label: str
    structure: str
    expected_pnl: float          # mean terminal P&L (higher is better)
    cvar: float                  # CVaR loss magnitude at the frontier's beta (lower is better)
    strike_pct: float | None = None
    coverage_pct: float = 100.0
    note: str = ""


@dataclass(frozen=True)
class FrontierPoint:
    loss_budget: float
    admissible: list[str]                 # candidate labels with CVaR <= budget
    efficient_label: str | None           # max expected-P&L among admissible (the frontier point)
    efficient_expected: float | None
    efficient_cvar: float | None


def ru_cvar(pnl: np.ndarray, beta: float = 0.95) -> tuple[float, float]:
    """Rockafellar-Uryasev VaR + CVaR (loss magnitudes) from a P&L sample.

    Returns (VaR_beta, CVaR_beta). CVaR is evaluated at the RU optimum a* = VaR_beta:
    CVaR = a* + (1/(1-beta)) * mean(max(loss - a*, 0)) = mean of the worst-(1-beta) losses.
    """
    if not 0.0 < beta < 1.0:
        raise ValueError(f"beta must be in (0,1), got {beta}")
    losses = -np.asarray(pnl, dtype=np.float64)
    var = float(np.percentile(losses, 100.0 * beta))
    excess = np.maximum(losses - var, 0.0)
    cvar = var + float(np.mean(excess)) / (1.0 - beta)
    return var, cvar


def empirical_cvar(pnl: np.ndarray, beta: float = 0.95) -> float:
    """Mean of the worst (1-beta) fraction of losses (equals ru_cvar's CVaR)."""
    return ru_cvar(pnl, beta)[1]


def efficient_frontier(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Pareto-efficient set: no other candidate has CVaR <= and expected >= (one strict).

    Returned sorted by ascending CVaR (the frontier, low-risk to high-risk).
    """
    eff: list[Candidate] = []
    for c in candidates:
        dominated = any(
            (o.cvar <= c.cvar and o.expected_pnl >= c.expected_pnl
             and (o.cvar < c.cvar or o.expected_pnl > c.expected_pnl))
            for o in candidates if o.label != c.label
        )
        if not dominated:
            eff.append(c)
    eff.sort(key=lambda c: (c.cvar, -c.expected_pnl))
    return eff


def build_frontier(
    candidates: Sequence[Candidate], loss_budgets: Sequence[float],
) -> list[FrontierPoint]:
    """For each loss budget: the admissible set (CVaR <= budget) and the max-expected point.

    An admissible set, NOT a ranking — the D-10 budget selects the point.
    """
    points: list[FrontierPoint] = []
    for budget in loss_budgets:
        admissible = [c for c in candidates if c.cvar <= budget]
        admissible.sort(key=lambda c: c.label)
        if admissible:
            best = max(admissible, key=lambda c: c.expected_pnl)
            points.append(FrontierPoint(
                loss_budget=budget,
                admissible=[c.label for c in admissible],
                efficient_label=best.label,
                efficient_expected=best.expected_pnl,
                efficient_cvar=best.cvar,
            ))
        else:
            points.append(FrontierPoint(budget, [], None, None, None))
    return points
