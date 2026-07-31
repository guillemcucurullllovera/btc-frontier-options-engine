"""C9 · Phase D — parameter-uncertainty-propagated risk band.

SIMULATED / diagnostic; MS-26-gated; holder-basis; frozen Q anchor untouched. Locks the decision-relevant
structure of the band: it is seed-stable and finite; the DEFINED-RISK structures (collar, call_spread)
have their tail metric invariant to the parameter draw (capped by construction), while the TAIL-EXPOSED
structures (long_btc + short put) swing materially. Campaign-scale numbers live in the report/JSON.
"""

from __future__ import annotations

import math

from strategy.bates_risk import (
    ParamDraw,
    PhysicalRiskConfig,
    parameter_uncertainty_band,
)

_DRAWS = (
    ParamDraw(p_vol=0.40, jump_lam=4.0, jump_mean=-0.005, jump_std=0.10),
    ParamDraw(p_vol=0.52, jump_lam=4.5, jump_mean=0.000, jump_std=0.14),
    ParamDraw(p_vol=0.65, jump_lam=5.0, jump_mean=-0.010, jump_std=0.18),
    ParamDraw(p_vol=0.58, jump_lam=4.2, jump_mean=-0.003, jump_std=0.12),
)


def _band(structures: tuple[str, ...]) -> dict[tuple[str, str], tuple[float, float, float]]:
    cfg = PhysicalRiskConfig(n_paths=30_000, n_steps=45)
    rows = parameter_uncertainty_band(cfg, _DRAWS, structures=structures, n_boot=30)
    return {(r.structure, r.metric): (r.central, r.q05, r.q95) for r in rows}


def test_band_finite_and_complete() -> None:
    b = _band(("unhedged", "collar", "long_btc_plus_short_put"))
    metrics = {"mean_pnl", "prob_loss", "es975", "cvar95", "vrp_carry"}
    for s in ("unhedged", "collar", "long_btc_plus_short_put"):
        assert {m for (ss, m) in b if ss == s} == metrics
    assert all(all(math.isfinite(x) for x in v) for v in b.values())


def test_seed_stable() -> None:
    b1 = _band(("collar", "long_btc_plus_short_put"))
    b2 = _band(("collar", "long_btc_plus_short_put"))
    for key in b1:
        assert b1[key] == b2[key]                          # identical draws -> identical band (reproducible)


def test_defined_risk_invariant_tail_exposed_varies() -> None:
    """Collar's ES is capped (invariant to the draw); the LBSP's ES swings materially."""
    b = _band(("collar", "long_btc_plus_short_put"))
    c_cen, c_lo, c_hi = b[("collar", "es975")]
    l_cen, l_lo, l_hi = b[("long_btc_plus_short_put", "es975")]
    collar_width = (c_hi - c_lo) / max(abs(c_cen), 1.0)
    lbsp_width = (l_hi - l_lo) / max(abs(l_cen), 1.0)
    assert collar_width < 0.02                             # defined-risk tail invariant to parameters
    assert lbsp_width > 0.10                               # tail-exposed swings >10% across the draws
    assert l_cen > c_cen                                   # and the LBSP tail is far larger than the collar's
