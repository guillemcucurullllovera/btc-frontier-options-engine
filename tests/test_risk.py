"""C8 R2 tests — EVT/GPD tail estimation and CVaR loss-budget frontier.

Independent oracles: GPD fit recovers a known shape/scale; EVT/empirical/CF
agree for a light-tailed sample; ES >= VaR (coherence); CVaR matches the
mean-of-tail definition and the Rockafellar-Uryasev optimum; the frontier's
admissible set is monotone in the budget.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest
from scipy.stats import genpareto

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from risk.cvar_frontier import (
    Candidate,
    build_frontier,
    efficient_frontier,
    empirical_cvar,
    ru_cvar,
)
from risk.tail import (
    compare_tail_methods,
    cornish_fisher_tail,
    empirical_tail,
    evt_gpd_tail,
)


def _normal_pnl(n: int = 200_000, mu: float = 0.0, sigma: float = 1e6) -> np.ndarray:
    return np.random.default_rng(7).normal(mu, sigma, n)


# ── EVT / tail ──────────────────────────────────────────────────────────────


def test_gpd_recovers_known_shape() -> None:
    # Losses with an injected GPD tail: the POT fit recovers the shape within tolerance.
    rng = np.random.default_rng(11)
    body = rng.normal(0, 1.0, 180_000)
    xi_true, beta_true = 0.25, 2.0
    tail = 3.0 + genpareto.rvs(xi_true, loc=0.0, scale=beta_true, size=20_000, random_state=rng)
    losses = np.concatenate([body, tail])
    est = evt_gpd_tail(-losses, confidence=0.99, threshold_quantile=0.90)
    assert est.method == "evt_gpd"
    assert est.xi is not None and abs(est.xi - xi_true) < 0.06
    assert est.es >= est.var > 0.0  # coherence


def test_tail_methods_agree_for_normal() -> None:
    pnl = _normal_pnl(sigma=1e6)
    cmp = compare_tail_methods(pnl, confidence=0.975)
    var_emp = cmp["empirical"].var
    # EVT and Cornish-Fisher VaR are within ~8% of the empirical VaR for a normal sample.
    assert cmp["evt_gpd"].var == pytest.approx(var_emp, rel=0.08)
    assert cmp["cornish_fisher"].var == pytest.approx(var_emp, rel=0.08)
    for e in cmp.values():
        assert e.es >= e.var  # ES (coherent) is at least VaR for every method


def test_cornish_fisher_matches_normal_quantile() -> None:
    # For a (near-)normal sample, CF VaR ~ mean + sigma*z_0.975 (skew/kurt ~ 0).
    pnl = _normal_pnl(sigma=1.0)
    est = cornish_fisher_tail(pnl, confidence=0.975)
    assert est.var == pytest.approx(1.959964, abs=0.03)  # z_0.975


def test_empirical_es_is_mean_beyond_var() -> None:
    pnl = _normal_pnl(sigma=1e6)
    est = empirical_tail(pnl, confidence=0.95)
    losses = -pnl
    expected = float(np.mean(losses[losses >= est.var]))
    assert est.es == pytest.approx(expected, rel=1e-12)


# ── CVaR frontier ────────────────────────────────────────────────────────────


def test_ru_cvar_equals_mean_of_tail() -> None:
    pnl = _normal_pnl(sigma=1e6)
    var, cvar = ru_cvar(pnl, beta=0.95)
    losses = -pnl
    tail_mean = float(np.mean(losses[losses >= var]))
    assert cvar == pytest.approx(tail_mean, rel=1e-3)   # RU optimum == mean-of-tail
    assert empirical_cvar(pnl, 0.95) == pytest.approx(cvar, rel=1e-12)
    assert cvar >= var  # CVaR >= VaR always


def _candidates() -> list[Candidate]:
    return [
        Candidate("A_lowrisk", "collar", expected_pnl=10.0, cvar=100.0),
        Candidate("B_mid", "covered_call", expected_pnl=30.0, cvar=250.0),
        Candidate("C_high", "long_btc_short_put", expected_pnl=45.0, cvar=600.0),
        Candidate("D_dominated", "x", expected_pnl=5.0, cvar=300.0),  # dominated by A and B
    ]


def test_efficient_frontier_excludes_dominated() -> None:
    eff = {c.label for c in efficient_frontier(_candidates())}
    assert "D_dominated" not in eff
    assert {"A_lowrisk", "B_mid", "C_high"} <= eff


def test_frontier_admissible_monotone_in_budget() -> None:
    cands = _candidates()
    budgets = [50.0, 150.0, 300.0, 700.0]
    pts = build_frontier(cands, budgets)
    # Admissible set grows with the budget; the efficient point's expected P&L is non-decreasing.
    sizes = [len(p.admissible) for p in pts]
    assert sizes == sorted(sizes)
    assert pts[0].admissible == []                       # budget 50 admits nothing
    assert set(pts[2].admissible) == {"A_lowrisk", "B_mid", "D_dominated"}  # CVaR<=300
    assert pts[2].efficient_label == "B_mid"             # max expected among admissible
    assert pts[3].efficient_label == "C_high"            # budget 700 admits the high-risk one
    exp = [p.efficient_expected for p in pts if p.efficient_expected is not None]
    assert exp == sorted(exp)
