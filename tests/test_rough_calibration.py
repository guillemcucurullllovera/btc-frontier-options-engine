"""C9 · M6.0b/finalize — rough-Heston calibration integration (evidence-gated bake-off).

SIMULATED / diagnostic; MS-26-gated; statistical model-fit only (NOT an MS-25 claim).

The full-surface rough-vs-Bates fit + the calibrated Hurst H are reported in the finalize gate report
(`docs/reports/c9_m6_rough_finalize.md`). CORRECTED converged result (M6.0 finalize): a warm-started
free-H calibration settles at H ~ 0.20 (STRONG roughness), ARPE ~ 7.4% — the fixed-H profile decreases
monotonically with roughness (Heston/H=0.5 8.05% -> 7.86 -> 7.72 -> 7.62 -> 7.38 at H=0.20). The
pre-finalize free-H "8.8% at H~0.45" was an OPTIMIZER FAILURE: rough-H=0.5 IS classical Heston, so a
converged free-H can never exceed the Heston ARPE. Even at the strong-rough optimum, rough (7.4%) does
NOT approach Bates (5.55%) or Xia-Li (~4%) -> jumps dominate; skip the heavy non-Markovian sim.

These tests verify that the rough-Heston model plugs into the M2 vectorised calibration pipeline and
reprices the chain (the machinery), and that a converged rough fit is not materially worse than the
classical-Heston baseline (the anti-regression for the optimizer-failure artifact), at a minimal budget.
"""

from __future__ import annotations

import math
import pathlib
from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
import pytest

from pricing.cf.cos import cos_call
from pricing.cf.rough_heston import RoughHeston
from vol.calibrate import _model_call_slice, calibrate_generic
from vol.chain_surface import ingest_chain_slices
from vol.snapshot import load_snapshot

_SNAP = load_snapshot(pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures")
_SLICES = ingest_chain_slices(_SNAP.instruments, _SNAP.book_summaries, datetime(2026, 7, 30, tzinfo=UTC))


def test_rough_slice_pricer_matches_cos() -> None:
    """The vectorised (generic) slice pricer prices a rough-Heston smile like the M1 COS pricer."""
    m = RoughHeston(0.0, 0.0, 0.15, 1.5, 0.20, 0.6, -0.3, H=0.3, n_steps=150)
    strikes = np.array([55_000.0, 60_000.0, 66_000.0])
    vec = _model_call_slice(m, 60_000.0, strikes, 0.25, N=160, L=14.0)
    for i, K in enumerate(strikes):
        assert vec[i] == pytest.approx(cos_call(m, 60_000.0, float(K), 0.25, N=160, L=14.0), abs=1e-3)


def test_rough_calibrates_through_pipeline() -> None:
    """Rough Heston (fixed H) plugs into calibrate_generic and reprices the chain (integration)."""
    core = [s for s in _SLICES if s.T >= 21.0 / 365.0][:2]

    def build(p: np.ndarray) -> RoughHeston:
        return RoughHeston(0.0, 0.0, float(p[0]), float(p[1]), float(p[2]), float(p[3]),
                           float(p[4]), 0.45, 40)

    lb = np.array([1e-3, 0.1, 1e-3, 1e-2, -0.95])
    ub = np.array([4.0, 20.0, 4.0, 20.0, 0.95])
    seed = np.array([0.13, 9.0, 0.25, 4.0, -0.36])
    g = calibrate_generic(build, lb, ub, [seed], core, t_floor=0.0, N=64, L=12.0,
                          n_starts=1, maxiter=120)
    assert math.isfinite(g.arpe) and 0.0 < g.arpe < 0.5     # a finite, sane fit (coarse budget)
    assert g.n_options >= 10
    assert all(math.isfinite(x) for x in g.params)


def test_rough_finalize_not_worse_than_heston() -> None:
    """M6.0 finalize anti-regression: a converged rough (H<0.5) fit is NOT materially worse than the
    classical-Heston (H=0.5) baseline on the same slices/budget.

    This locks the invariant the pre-finalize "free-H 8.8%" violated: since rough-H=0.5 IS classical
    Heston, a warm-started rough calibration can always fall back to it, so its ARPE cannot exceed the
    Heston ARPE (up to optimizer slack). On the full surface rough in fact IMPROVES the fit modestly
    (8.05% -> 7.4%); here, on a 2-slice mini-budget, we assert only the one-sided bound.
    """
    core = [s for s in _SLICES if s.T >= 21.0 / 365.0][:2]
    lb = np.array([1e-3, 0.1, 1e-3, 1e-2, -0.95])
    ub = np.array([4.0, 20.0, 4.0, 20.0, 0.95])
    seed = np.array([0.13, 6.0, 0.25, 3.0, -0.34])

    def build_h(H: float) -> Callable[[np.ndarray], RoughHeston]:
        def _b(p: np.ndarray) -> RoughHeston:
            return RoughHeston(0.0, 0.0, float(p[0]), float(p[1]), float(p[2]), float(p[3]),
                               float(p[4]), H, 90)
        return _b

    heston = calibrate_generic(build_h(0.5), lb, ub, [seed], core, t_floor=0.0, N=48, L=12.0,
                               n_starts=1, maxiter=200)   # H=0.5 -> exact closed-form Heston
    rough = calibrate_generic(build_h(0.4), lb, ub, [seed], core, t_floor=0.0, N=48, L=12.0,
                              n_starts=1, maxiter=200)
    assert rough.arpe <= heston.arpe + 0.01              # rough at least as good as Heston (+slack)
