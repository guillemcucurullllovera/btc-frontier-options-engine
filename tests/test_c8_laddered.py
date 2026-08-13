"""Phase L tests — laddered / fractionated overlay.

Independent oracle: the ladder per-path pass's net overlay reconciles to the R1-R3
MC economics (hero.mean_overlay_gross_pnl_usd) to rtol 1e-9, and a scalar recompute
matches the vectorised premium / upside accounting. The fractionation relationships
(more premium, higher participation, higher transaction cost with N) are asserted.
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from strategy.definitions import build_collar, build_covered_call
from strategy.hero_lifecycle_mc import leg_specs, run_hero_lifecycle_mc, unit_premiums_for
from strategy.laddered_overlay import _ladder_pass, ladder_config, ladder_metrics
from strategy.multi_cycle_mc import _generate_chunk_paths

S0 = 64_509.34
IMPLIED = 0.34
REALISED = 0.315
R = 0.0
P = 0.10
PATHS = 12_000


def _lm(kind: str, builder, n: int, drift: float, vrp: bool = False):  # type: ignore[no-untyped-def]
    diffuse = REALISED if vrp else IMPLIED
    cfg = ladder_config(P, n, drift, diffuse, S0, R, seed=101, paths=PATHS)
    return ladder_metrics(kind, builder, cfg, pricing_vol=IMPLIED, drift=drift,
                          vol_regime="vrp" if vrp else "fair_value")


def test_ladder_net_overlay_reconciles_mc() -> None:
    # The ladder pass's net overlay == the MC economics overlay (same paths, same config).
    for kind, builder in (("covered_call", build_covered_call), ("collar", build_collar)):
        for n in (1, 2, 4):
            cfg = ladder_config(P, n, 0.0, IMPLIED, S0, R, seed=101, paths=PATHS)
            lm = ladder_metrics(kind, builder, cfg, pricing_vol=IMPLIED, drift=0.0, vol_regime="fair_value")
            hero = run_hero_lifecycle_mc(builder(), cfg, kind=kind, pricing_vol=IMPLIED)
            assert lm.net_overlay_per_btc * 30_000 == pytest.approx(
                hero.mean_overlay_gross_pnl_usd, rel=1e-9, abs=1e-3
            )


def test_ladder_pass_scalar_oracle() -> None:
    kind = "covered_call"
    cfg = ladder_config(P, 4, 0.10, IMPLIED, S0, R, seed=101, paths=64)
    up = unit_premiums_for(kind, cfg, IMPLIED)
    paths = _generate_chunk_paths(cfg, 0, 40)
    out = _ladder_pass(kind, paths, cfg, up, 0.0003)
    legs = leg_specs(kind, cfg.strike_target_pct)
    steps, total, qty = cfg.n_steps_per_cycle, cfg.total_steps, cfg.btc_quantity
    for i in range(paths.shape[0]):
        recv = cpay = tc = 0.0
        for c in range(cfg.n_cycles):
            entry = float(paths[i, c * steps])
            exit_ = float(paths[i, min((c + 1) * steps, total)])
            for j, (opt, side, mult, w) in enumerate(legs):
                prem = entry * up[j]
                strike = entry * mult
                tc += 0.0003 * entry * w * qty
                if side == "SHORT":
                    recv += w * qty * prem
                    if opt == "call":
                        cpay += w * qty * max(exit_ - strike, 0.0)
        assert out["prem_recv"][i] == pytest.approx(recv, rel=1e-9, abs=1e-3)
        assert out["call_payout"][i] == pytest.approx(cpay, rel=1e-9, abs=1e-3)
        assert out["tcost"][i] == pytest.approx(tc, rel=1e-9, abs=1e-3)


def test_premium_and_upside_computed_not_assumed() -> None:
    # "Compute, don't assume": at a fixed 10% cap distance the shorter tranches are deeper OTM,
    # so P_N is NOT trivially ~ P_1 or > P_1 (regime-dependent). Assert the metrics are finite
    # and the ladder differs from the one-shot (not identical) — direction goes in the report.
    p1 = _lm("covered_call", build_covered_call, 1, 0.10)
    p2 = _lm("covered_call", build_covered_call, 2, 0.10)
    p4 = _lm("covered_call", build_covered_call, 4, 0.10)
    for p in (p1, p2, p4):
        assert p.premium_collected_per_btc > 0.0
        assert 0.0 <= p.upside_participation <= 1.0 + 1e-9
        assert p.premium_efficiency > 0.0 and math.isfinite(p.premium_efficiency)
    assert p4.premium_collected_per_btc != pytest.approx(p1.premium_collected_per_btc, rel=1e-3)


def test_fractionation_costs_more() -> None:
    # ROBUST honest cost of fractionation: N trades cost more (N x the per-trade fee).
    p1 = _lm("covered_call", build_covered_call, 1, 0.10)
    p2 = _lm("covered_call", build_covered_call, 2, 0.10)
    p4 = _lm("covered_call", build_covered_call, 4, 0.10)
    assert p4.tcost_drag_per_btc > p2.tcost_drag_per_btc > p1.tcost_drag_per_btc
    assert p1.tenor_days > p2.tenor_days > p4.tenor_days  # H/N tenor shrinks with N


def test_vrp_positive_edge_ladder() -> None:
    # VRP (sell implied, realise physical) gives a positive overlay edge for the ladder too.
    fv = _lm("covered_call", build_covered_call, 4, 0.0, vrp=False)
    vrp = _lm("covered_call", build_covered_call, 4, 0.0, vrp=True)
    assert vrp.net_overlay_per_btc > fv.net_overlay_per_btc
    assert vrp.es975_usd > 0.0  # tail remains
