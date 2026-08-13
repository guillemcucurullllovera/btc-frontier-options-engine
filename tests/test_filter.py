"""C9 · M4.2 — UKF latent-variance filter (physical SV dynamics).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched.

Oracles: on SIMULATED Heston data the true latent-variance path is known, so the filter is checked
for skill (correlation), statistical consistency (NEES ~ 1, NIS ~ 1), and white innovations; a
misspecified (near-constant-vol) filter is shown to have no skill. The real 64-bar BTC series is a
small-sample diagnostic (white innovations, plausible filtered vol).
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np

from vol.filter import (
    bootstrap_particle_filter,
    filter_consistency,
    sv_mle,
    unscented_kalman_sv,
)
from vol.jumps import log_returns


def _sim_heston(n: int, kappa: float, theta: float, volvol: float, rho: float, v0: float,
                dt: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Full-truncation Euler Heston returns + the KNOWN true variance path (ground truth)."""
    rng = np.random.default_rng(seed)
    v = v0
    rs = np.empty(n)
    vs = np.empty(n)
    for t in range(n):
        z1 = rng.standard_normal()
        z2 = rho * z1 + math.sqrt(1.0 - rho * rho) * rng.standard_normal()
        vp = max(v, 0.0)
        rs[t] = -0.5 * vp * dt + math.sqrt(vp * dt) * z1
        vs[t] = vp
        v = v + kappa * (theta - vp) * dt + volvol * math.sqrt(vp * dt) * z2
    return rs, vs


_DT = 1.0 / 365.0
_R, _VTRUE = _sim_heston(2000, kappa=3.0, theta=0.25, volvol=0.8, rho=-0.4, v0=0.25, dt=_DT, seed=42)
_RES = unscented_kalman_sv(_R, kappa=3.0, theta=0.25, vol_of_vol=0.8, dt=_DT, v0=0.25)


def test_ukf_recovers_latent_variance() -> None:
    """The filtered variance tracks the known true path with real skill."""
    corr = float(np.corrcoef(_RES.filtered_variance, _VTRUE)[0, 1])
    assert corr > 0.45                                     # daily SV filtering: log(r^2) obs is very noisy
    rel_rmse = float(np.sqrt(np.mean((_RES.filtered_variance - _VTRUE) ** 2)) / np.mean(_VTRUE))
    assert rel_rmse < 0.6


def test_ukf_statistically_consistent() -> None:
    """NEES ~ 1 (errors match the reported covariance) and NIS ~ 1 (innovation covariance right)."""
    nees = float(np.mean((_RES.filtered_variance - _VTRUE) ** 2 / _RES.filtered_std ** 2))
    assert 0.5 < nees < 2.0                                # well-calibrated filter uncertainty
    fc = filter_consistency(_RES)
    assert fc.nis_in_band                                  # mean NIS within band of 1
    assert fc.innovations_white                            # Ljung-Box does not reject whiteness


def test_ukf_beats_misspecified_constant_vol_filter() -> None:
    """The SV filter has skill; a near-constant-vol (misspecified) filter does not."""
    corr_sv = float(np.corrcoef(_RES.filtered_variance, _VTRUE)[0, 1])
    res_const = unscented_kalman_sv(_R, kappa=0.01, theta=0.25, vol_of_vol=0.01, dt=_DT, v0=0.25)
    corr_const = float(np.corrcoef(res_const.filtered_variance, _VTRUE)[0, 1])
    assert corr_sv > corr_const + 0.3


def test_ukf_log_likelihood_finite() -> None:
    """The predictive log-likelihood is finite (basis for the M4.1 MLE + SE)."""
    assert math.isfinite(_RES.log_likelihood)
    # A wildly wrong theta gives a lower likelihood (the surface is informative).
    worse = unscented_kalman_sv(_R, kappa=3.0, theta=2.0, vol_of_vol=0.8, dt=_DT, v0=0.25)
    assert worse.log_likelihood < _RES.log_likelihood


def test_ukf_real_btc_white_and_plausible() -> None:
    """Real 64-bar BTC: innovations white, NIS consistent, filtered vol in a plausible range."""
    path = pathlib.Path(__file__).resolve().parents[1] / "market_snapshots" / "2026-07-30T104316Z" / "spot_history.json"
    rows = json.loads(path.read_text())
    if isinstance(rows, dict):
        rows = rows.get("result", rows)
    r = log_returns(np.array([x["close"] for x in rows], dtype=np.float64))
    res = unscented_kalman_sv(r, kappa=9.0, theta=0.25, vol_of_vol=1.0, dt=_DT,
                              v0=float(np.var(r) / _DT))
    fc = filter_consistency(res, lags=5)
    ann_vol = np.sqrt(res.filtered_variance)
    assert 0.15 < float(ann_vol.mean()) < 1.5              # plausible BTC vol band
    assert fc.innovations_white and fc.nis_in_band


# ── M4.1 · P-measure SV MLE + SE (UKF likelihood) ─────────────────────────────


def test_sv_mle_finite_params_and_se_shrinks_with_n() -> None:
    """MLE runs, gives finite params/SE, theta in a plausible (QML-biased) band, SE shrinks with n."""
    r_small, _ = _sim_heston(800, 3.0, 0.25, 0.8, -0.4, 0.25, _DT, 1)
    r_big, _ = _sim_heston(2500, 3.0, 0.25, 0.8, -0.4, 0.25, _DT, 1)
    m_s = sv_mle(r_small, _DT)
    m_b = sv_mle(r_big, _DT)
    for m in (m_s, m_b):
        assert all(math.isfinite(x) and x > 0 for x in (m.theta, m.kappa, m.vol_of_vol))
        assert all(math.isfinite(x) and x >= 0 for x in (m.se_theta, m.se_kappa, m.se_vol_of_vol))
        assert 0.12 < m.theta < 0.35                       # QML biases theta low (~0.19 vs 0.25)
    assert m_b.se_theta <= m_s.se_theta                    # SE shrinks with sample size


# ── M4.4 · bootstrap particle filter (jump-SV) ────────────────────────────────

_PF = bootstrap_particle_filter(_R, kappa=3.0, theta=0.25, vol_of_vol=0.8, dt=_DT,
                                n_particles=3000, v0=0.25, seed=7)


def test_particle_filter_tracks_and_healthy_ess() -> None:
    """The PF tracks the latent variance with a healthy (non-degenerate) particle set."""
    corr = float(np.corrcoef(_PF.filtered_variance, _VTRUE)[0, 1])
    assert corr > 0.5
    assert float(_PF.ess.mean()) > 3000 / 3.0             # ESS stays healthy on average
    assert _PF.n_resample > 0                              # adaptive resampling kicks in
    assert float(_PF.ess.min()) > 50                       # never collapses to a few particles


def test_particle_filter_beats_ukf_likelihood() -> None:
    """The (exact) PF attains a higher predictive likelihood than the Gaussian-approx UKF."""
    assert _PF.log_likelihood > _RES.log_likelihood
    corr_pf = float(np.corrcoef(_PF.filtered_variance, _VTRUE)[0, 1])
    corr_ukf = float(np.corrcoef(_RES.filtered_variance, _VTRUE)[0, 1])
    assert corr_pf >= corr_ukf - 0.02                      # PF at least as good at tracking


def test_particle_filter_reproducible() -> None:
    a = bootstrap_particle_filter(_R, 3.0, 0.25, 0.8, _DT, n_particles=1500, v0=0.25, seed=7)
    b = bootstrap_particle_filter(_R, 3.0, 0.25, 0.8, _DT, n_particles=1500, v0=0.25, seed=7)
    assert np.array_equal(a.filtered_variance, b.filtered_variance)
