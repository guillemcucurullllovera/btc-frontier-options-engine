"""C9 · M3.2 / M3.3 — penalized model selection over {BS, Heston, Bates, VG, CGMY} + validation.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. This is STATISTICAL model-fit
selection (which model reprices the observed market best), which is legitimate and DISTINCT from
strategy ranking — NOT an MS-25 "best strategy" claim.

Oracles: the AIC/BIC formulas and the parsimony-within-tolerance rule are unit-tested against
hand-built fits; the live-snapshot selection orders the five models and shows Bates reprices better
than Heston; the ordering is stable on a second, independent snapshot.
"""

from __future__ import annotations

import math
import pathlib
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

from vol.chain_surface import ingest_chain_slices
from vol.model_selection import (
    ModelFit,
    _aic_bic,
    build_specs,
    calibrate_spec,
    select_models,
    select_parsimonious,
)
from vol.snapshot import load_snapshot

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_REF = datetime(2026, 7, 30, tzinfo=UTC)
_SNAP = load_snapshot(_ROOT / "tests" / "fixtures")
_SLICES = ingest_chain_slices(_SNAP.instruments, _SNAP.book_summaries, _REF)
# One live-snapshot selection, reused (expensive: five calibrations).
_SEL = select_models(_SLICES, N=130, n_starts=2, maxiter=1800)


def _fit(name: str, k: int, arpe: float, ssr: float = 1.0) -> ModelFit:
    aic, bic = _aic_bic(ssr, 200, k)
    return ModelFit(name, k, [], 0.0, 0.0, 0.0, arpe, 0.0, aic, bic, 200, 0.0)


# ── unit: AIC/BIC + parsimony rule ────────────────────────────────────────────


def test_aic_bic_formula() -> None:
    n, k, ssr = 200, 5, 4.0
    aic, bic = _aic_bic(ssr, n, k)
    ll = n * math.log(ssr / n)
    assert aic == pytest.approx(ll + 2 * k)
    assert bic == pytest.approx(ll + k * math.log(n))
    assert bic > aic                         # BIC penalises complexity more (ln n > 2 for n>7)


def test_parsimony_prefers_simpler_within_tolerance() -> None:
    """A 5-param model within tolerance beats a marginally-better 8-param one (Hirsa §7.5)."""
    fits = [_fit("Bates", 8, arpe=0.058), _fit("Heston", 5, arpe=0.062),
            _fit("CGMY", 4, arpe=0.19), _fit("BS", 1, arpe=0.27)]
    name, _tol = select_parsimonious(fits, arpe_rel_margin=0.15)
    assert name == "Heston"                  # 0.062 <= 0.058*1.15 => within tol, fewer params
    # A tighter tolerance excludes Heston => the best (Bates) is selected.
    assert select_parsimonious(fits, arpe_rel_margin=0.02)[0] == "Bates"


# ── live-snapshot selection: ordering + Bates-vs-Heston ───────────────────────


def test_all_five_models_calibrated() -> None:
    names = {f.name for f in _SEL.fits}
    assert names == {"BS", "Heston", "Bates", "VG", "CGMY"}
    for f in _SEL.fits:
        assert f.arpe > 0.0 and f.rmse_iv > 0.0 and math.isfinite(f.aic) and math.isfinite(f.bic)


def test_selection_orders_models_by_fit() -> None:
    """SV models (Bates, Heston) reprice far better than the Levy/flat models (CGMY, VG, BS)."""
    by = {f.name: f for f in _SEL.fits}
    assert by["Bates"].arpe <= by["Heston"].arpe + 1e-9          # Bates >= Heston (warm-started superset)
    assert by["Heston"].arpe < by["CGMY"].arpe < by["VG"].arpe   # SV beats pure Levy on the term structure
    assert by["VG"].arpe < by["BS"].arpe                          # any smile beats flat BS
    # AIC and BIC select an SV model, not BS/VG/CGMY.
    assert _SEL.selected_by_aic in ("Bates", "Heston")
    assert _SEL.selected_by_bic in ("Bates", "Heston")


def test_bates_reprices_at_least_as_well_as_heston() -> None:
    """M3.3: Bates (Heston SV + jumps) reprices >= Heston; report the ARPE improvement."""
    by = {f.name: f for f in _SEL.fits}
    assert by["Bates"].arpe <= by["Heston"].arpe + 1e-9
    assert by["Bates"].rmse_iv <= by["Heston"].rmse_iv + 1e-6


# ── stability on a second, independent snapshot ───────────────────────────────


def test_selection_stable_on_second_snapshot() -> None:
    """The fit ordering (Bates <= Heston < BS) is stable on a second, independent live snapshot."""
    snap2_dir = _ROOT / "market_snapshots" / "2026-07-30T104316Z"
    snap2 = load_snapshot(snap2_dir)
    slices2 = ingest_chain_slices(snap2.instruments, snap2.book_summaries, _REF)
    specs = {s.name: s for s in build_specs(0.16)}
    bs = calibrate_spec(specs["BS"], slices2, N=96, n_starts=2, maxiter=800)
    heston = calibrate_spec(specs["Heston"], slices2, N=130, n_starts=2, maxiter=1800)
    hp = np.array(heston.params)
    warm = [np.concatenate([hp, [lam, mu, sj]]) for (lam, mu, sj)
            in ((0.5, -0.1, 0.15), (3.0, -0.15, 0.2), (8.0, -0.06, 0.03))]
    bates = calibrate_spec(replace(specs["Bates"], seeds=warm), slices2, N=130, n_starts=3, maxiter=1800)
    assert bates.arpe <= heston.arpe + 1e-9          # Bates still >= Heston
    assert heston.arpe < bs.arpe                      # SV still far better than flat BS
