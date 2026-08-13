"""Decision-grade tail statistics with bootstrap SE / CI for the SVJJ Monte Carlo (ENG3 / A5).

NEW isolated module; canonical main untouched. A VaR/ES/CVaR figure without sampling uncertainty is
not decision-grade (SR 11-7). ``strategy/svjj_sim.simulate_svjj_terminal`` already wires the SVJJ
(price + vol co-jump) tail model into the MC; ``risk/cvar_frontier.ru_cvar_ci`` already gives a
bootstrap CI for CVaR at a single level. This module generalizes that to the FULL tail panel
(VaR + ES + CVaR at every confidence level) and adds the decision-grade comparison the mandate needs:
**is the SVJJ tail statistically distinguishable from the GBM tail, given the Monte-Carlo error?**

All estimators are seeded (deterministic) and operate in LOSS space (loss = -P&L, so tail figures are
positive loss magnitudes). Provenance: SIMULATED (physical-measure SVJJ dynamics).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArr = npt.NDArray[np.float64]


@dataclass(frozen=True)
class TailStat:
    metric: str                 # "VaR" | "ES" | "CVaR"
    level: float                # confidence beta (e.g. 0.95, 0.99)
    estimate: float             # loss magnitude (USD)
    se: float                   # bootstrap standard error
    ci_lo: float                # percentile-bootstrap CI
    ci_hi: float
    ci_level: float
    n_boot: int
    n_paths: int


def _var_es(losses: FloatArr, beta: float) -> tuple[float, float]:
    """VaR_beta (loss quantile) and ES_beta (mean loss beyond VaR) in loss space."""
    var = float(np.percentile(losses, 100.0 * beta))
    tail = losses[losses >= var]
    es = float(np.mean(tail)) if tail.size else var
    return var, es


def _cvar(losses: FloatArr, beta: float) -> float:
    """Rockafellar-Uryasev CVaR = VaR + mean(max(loss-VaR,0))/(1-beta)."""
    var = float(np.percentile(losses, 100.0 * beta))
    return var + float(np.mean(np.maximum(losses - var, 0.0))) / (1.0 - beta)


def tail_panel(
    pnl: FloatArr, levels: tuple[float, ...] = (0.95, 0.99),
    n_boot: int = 600, ci_level: float = 0.95, seed: int = 20260813,
) -> list[TailStat]:
    """VaR / ES / CVaR at each ``level`` with seeded nonparametric-bootstrap SE + percentile CI.

    One resampling pass feeds every metric so the CIs are mutually consistent. Deterministic in
    ``seed``. Returns a flat list (metric x level), losses in USD.
    """
    losses = -np.asarray(pnl, dtype=np.float64)
    n = losses.size
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))

    lo_q, hi_q = 100.0 * (1.0 - ci_level) / 2.0, 100.0 * (1.0 + ci_level) / 2.0
    out: list[TailStat] = []
    for beta in levels:
        pt_var, pt_es = _var_es(losses, beta)
        pt_cvar = _cvar(losses, beta)
        bvar = np.empty(n_boot)
        bes = np.empty(n_boot)
        bcvar = np.empty(n_boot)
        for b in range(n_boot):
            s = losses[idx[b]]
            bvar[b], bes[b] = _var_es(s, beta)
            bcvar[b] = _cvar(s, beta)
        for metric, pt, draws in (("VaR", pt_var, bvar), ("ES", pt_es, bes), ("CVaR", pt_cvar, bcvar)):
            out.append(TailStat(
                metric=metric, level=beta, estimate=pt,
                se=float(np.std(draws, ddof=1)),
                ci_lo=float(np.percentile(draws, lo_q)),
                ci_hi=float(np.percentile(draws, hi_q)),
                ci_level=ci_level, n_boot=n_boot, n_paths=n,
            ))
    return out


@dataclass(frozen=True)
class TailGap:
    """Decision-grade comparison of one tail metric between two models (a - b, loss space)."""

    metric: str
    level: float
    a_estimate: float           # e.g. SVJJ ES
    b_estimate: float           # e.g. GBM ES
    gap: float                  # a - b (positive => model a has the FATTER tail)
    gap_se: float               # sqrt(se_a^2 + se_b^2) (independent seeds)
    gap_z: float                # gap / gap_se
    resolved: bool              # |z| >= 1.96 => the tail difference is statistically resolved


def compare_tails(a: list[TailStat], b: list[TailStat]) -> list[TailGap]:
    """Pairwise (metric, level) gap a-b with a combined SE and a decision-grade resolution flag.

    ``a`` and ``b`` must be tail panels from INDEPENDENT seeds (the SE combine assumes independence).
    ``resolved=True`` means the two models' tails differ by more than ~2 combined standard errors —
    the difference is decision-grade, not Monte-Carlo noise.
    """
    b_by = {(t.metric, t.level): t for t in b}
    out: list[TailGap] = []
    for ta in a:
        tb = b_by.get((ta.metric, ta.level))
        if tb is None:
            continue
        gap = ta.estimate - tb.estimate
        gap_se = float(np.hypot(ta.se, tb.se))
        z = gap / gap_se if gap_se > 0 else 0.0
        out.append(TailGap(
            metric=ta.metric, level=ta.level, a_estimate=ta.estimate, b_estimate=tb.estimate,
            gap=gap, gap_se=gap_se, gap_z=z, resolved=abs(z) >= 1.96,
        ))
    return out
