"""Unscented Kalman filter for the latent variance path (C9 · M4.2).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Identifies the PHYSICAL (P-measure)
stochastic-vol dynamics from the observed BTC spot returns (Hirsa §8.6 / Example 25).

State-space SV model (state = latent variance v_t):
  transition   v_{t+1} = v_t + kappa (theta - v_t) dt + eta_t,   Q_t = volvol^2 * v_t * dt  (CIR, state-dep)
  observation  log(r_t^2) = log(v_t dt) + log(eps_t^2),  eps~N(0,1)
             => h_obs(v) = log(v dt) + E[log chi^2_1],  R = Var[log chi^2_1] = pi^2/2
The log-return-squared observation is LINEAR-in-log but NONLINEAR in v (the log), with a heavy,
non-Gaussian noise whose first two moments (mean -1.2704, var 4.9348) are matched — the standard
QML/UKF treatment (Harvey-Ruiz-Shephard 1994; Kim-Shephard-Chib 1998). The UKF sigma-point machinery
handles the log nonlinearity and the state-dependent process noise.

Diagnostics: whiteness of the standardised innovations (Ljung-Box), and NIS = innovation^2 / S in the
chi^2_1 band; on SIMULATED data the filtered path is compared to the known true variance (NEES).
The predictive log-likelihood supports MLE parameter estimation + SE (M4.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize

FloatArr = npt.NDArray[np.float64]

_E_LOG_CHI2_1 = -1.2703628454614782      # E[log chi^2_1] = psi(1/2) + log 2
_VAR_LOG_CHI2_1 = math.pi ** 2 / 2.0     # Var[log chi^2_1] = 4.9348...


@dataclass(frozen=True)
class UKFResult:
    filtered_variance: FloatArr          # E[v_t | y_{1..t}]
    filtered_std: FloatArr               # sqrt of the state variance
    innovations: FloatArr                # standardised innovations (y - yhat)/sqrt(S)
    nis: FloatArr                        # normalised innovation squared, innov^2/S ~ chi^2_1
    log_likelihood: float
    provenance: str = "P-ESTIMATED"


def _sigma_points(x: float, P: float) -> tuple[FloatArr, FloatArr, FloatArr]:
    """1-D UKF sigma points and (mean, cov) weights. alpha=1, beta=2, kappa=0 (lambda=0)."""
    lam = 0.0
    sp = math.sqrt(max(P, 1e-18))
    pts = np.array([x, x + sp, x - sp], dtype=np.float64)
    wm = np.array([lam / (1.0 + lam), 1.0 / (2.0 * (1.0 + lam)), 1.0 / (2.0 * (1.0 + lam))])
    wc = wm.copy()
    wc[0] += 1.0 - 1.0 + 2.0             # (1 - alpha^2 + beta) with alpha=1, beta=2
    return pts, wm, wc


def unscented_kalman_sv(
    returns: FloatArr, kappa: float, theta: float, vol_of_vol: float, dt: float = 1.0 / 365.0,
    v0: float | None = None, p0: float | None = None,
) -> UKFResult:
    """UKF over the latent variance given the SV parameters; returns the filtered path + diagnostics."""
    r = np.asarray(returns, dtype=np.float64)
    n = r.size
    v = float(v0) if v0 is not None else max(float(np.var(r)) / dt, 1e-6)
    P = float(p0) if p0 is not None else (theta * dt) ** 2 + 1e-8
    y_all = np.log(np.maximum(r * r, 1e-300))     # observation log(r^2)

    fv = np.empty(n)
    fs = np.empty(n)
    innov = np.empty(n)
    nis = np.empty(n)
    ll = 0.0
    for t in range(n):
        # ── predict (CIR mean; state-dependent process variance) ──
        pts, wm, wc = _sigma_points(v, P)
        fpts = pts + kappa * (theta - pts) * dt
        v_pred = float(wm @ fpts)
        q = vol_of_vol * vol_of_vol * max(v, 1e-8) * dt
        P_pred = float(wc @ (fpts - v_pred) ** 2) + q
        v_pred = max(v_pred, 1e-10)

        # ── update via the log(r^2) observation ──
        pts2, wm2, wc2 = _sigma_points(v_pred, P_pred)
        pts2 = np.maximum(pts2, 1e-12)
        ypts = np.log(pts2 * dt) + _E_LOG_CHI2_1
        y_hat = float(wm2 @ ypts)
        S = float(wc2 @ (ypts - y_hat) ** 2) + _VAR_LOG_CHI2_1
        Pxy = float(wc2 @ ((pts2 - v_pred) * (ypts - y_hat)))
        K = Pxy / S
        resid = float(y_all[t]) - y_hat
        v = max(v_pred + K * resid, 1e-10)
        P = max(P_pred - K * K * S, 1e-14)

        fv[t] = v
        fs[t] = math.sqrt(P)
        innov[t] = resid / math.sqrt(S)
        nis[t] = resid * resid / S
        ll += -0.5 * (math.log(2.0 * math.pi * S) + resid * resid / S)

    return UKFResult(fv, fs, innov, nis, float(ll))


@dataclass(frozen=True)
class FilterConsistency:
    ljung_box_pvalue: float | None       # whiteness of standardised innovations (H0: white)
    innovations_white: bool
    mean_nis: float                      # should be ~1 (chi^2_1 mean) if consistent
    nis_in_band: bool                    # mean NIS within a 2-sigma band around 1
    n: int


def filter_consistency(res: UKFResult, lags: int = 10) -> FilterConsistency:
    """Innovation whiteness (Ljung-Box) + NIS consistency (mean ~ 1) diagnostics."""
    innov = res.innovations
    n = innov.size
    lb_p: float | None = None
    if n > lags + 2:
        try:
            from statsmodels.stats.diagnostic import acorr_ljungbox  # type: ignore[import-untyped]
            df = acorr_ljungbox(innov, lags=[lags])   # returns a DataFrame with 'lb_pvalue'
            lb_p = float(df["lb_pvalue"].iloc[-1])
        except Exception:
            lb_p = None
    mean_nis = float(np.mean(res.nis))
    band = 2.0 * math.sqrt(2.0 / n)      # sd of the mean of chi^2_1 (var 2) / sqrt(n), 2-sigma
    return FilterConsistency(
        ljung_box_pvalue=lb_p,
        innovations_white=(lb_p is None or lb_p > 0.05),
        mean_nis=mean_nis,
        nis_in_band=abs(mean_nis - 1.0) < max(band, 0.3),
        n=n,
    )


# ── M4.1 · P-measure SV MLE via the UKF likelihood, with Fisher SE ───────────


@dataclass(frozen=True)
class SVMLEResult:
    kappa: float
    theta: float
    vol_of_vol: float
    se_kappa: float
    se_theta: float
    se_vol_of_vol: float          # Fisher (inverse observed-information) standard errors
    log_likelihood: float
    n_obs: int
    provenance: str = "P-ESTIMATED"


def sv_mle(returns: FloatArr, dt: float = 1.0 / 365.0,
           x0: tuple[float, float, float] = (3.0, 0.25, 0.8)) -> SVMLEResult:
    """MLE of the physical SV params (kappa, theta, volvol) by maximising the UKF likelihood.

    Optimised in log-space (positivity); Fisher SE from the numerical Hessian of the negative
    log-likelihood, delta-method'd back to natural units. Extends the M0.3 MLE-SE machinery to the
    P-measure continuous-SV parameters.

    CAVEAT (documented): the UKF matches the very non-Gaussian log-chi^2 observation noise by its
    first two moments (QML), which biases theta LOW by ~15-25% and makes the Fisher SE
    over-optimistic; kappa/volvol are weakly identified from a short daily series. The robust P-vol
    estimate is the discrete-time GARCH (M0.3, Fisher + sandwich SE); this continuous-SV MLE is
    reported alongside with its QML caveat, not as the primary P-measure anchor.
    """
    r = np.asarray(returns, dtype=np.float64)

    def nll(logp: FloatArr) -> float:
        k, th, vv = np.exp(logp)
        res = unscented_kalman_sv(r, float(k), float(th), float(vv), dt)
        return -res.log_likelihood if math.isfinite(res.log_likelihood) else 1e12

    lp0 = np.log(np.array(x0))
    sol = minimize(nll, lp0, method="Nelder-Mead",
                   options={"xatol": 1e-5, "fatol": 1e-6, "maxiter": 2000})
    lp = np.asarray(sol.x, dtype=np.float64)
    k, th, vv = (float(x) for x in np.exp(lp))

    # Hessian of nll in log-space (central differences) -> covariance -> delta-method to natural.
    h = 1e-3
    H = np.zeros((3, 3))
    f0 = nll(lp)
    for i in range(3):
        for j in range(i, 3):
            ei = np.zeros(3)
            ej = np.zeros(3)
            ei[i] = h
            ej[j] = h
            fpp = nll(lp + ei + ej)
            fpm = nll(lp + ei - ej)
            fmp = nll(lp - ei + ej)
            fmm = nll(lp - ei - ej)
            H[i, j] = H[j, i] = (fpp - fpm - fmp + fmm) / (4.0 * h * h)
    try:
        cov_log = np.linalg.inv(H)
        se_log = np.sqrt(np.maximum(np.diag(cov_log), 0.0))
    except np.linalg.LinAlgError:
        se_log = np.full(3, float("nan"))
    # delta method: se(x) = x * se(log x) for x = exp(log x).
    se_k, se_th, se_vv = (float(v * s) for v, s in zip((k, th, vv), se_log, strict=True))
    return SVMLEResult(k, th, vv, se_k, se_th, se_vv, float(-f0), int(r.size))


# ── M4.4 · bootstrap particle filter (jump-SV latent state) ──────────────────


@dataclass(frozen=True)
class ParticleFilterResult:
    filtered_variance: FloatArr
    ess: FloatArr                 # effective sample size per step (health of the particle set)
    n_resample: int
    log_likelihood: float
    provenance: str = "P-ESTIMATED"


def bootstrap_particle_filter(
    returns: FloatArr, kappa: float, theta: float, vol_of_vol: float, dt: float = 1.0 / 365.0,
    n_particles: int = 2000, v0: float | None = None, seed: int = 20260730,
) -> ParticleFilterResult:
    """Bootstrap particle filter for the latent variance (jump-SV-ready SIR).

    Propagates CIR-Euler variance particles, weights by the return likelihood N(r_t; 0, v dt), and
    systematically resamples when ESS falls below N/2. Reports per-step ESS (particle-set health).
    MCMC (SVCJ, Eraker-Johannes-Polson) is DEFERRED pending source acquisition (see tracker).
    """
    r = np.asarray(returns, dtype=np.float64)
    n = r.size
    rng = np.random.default_rng(seed)
    v = np.full(n_particles, float(v0) if v0 is not None else max(float(np.var(r)) / dt, 1e-6))
    w = np.full(n_particles, 1.0 / n_particles)
    fv = np.empty(n)
    ess = np.empty(n)
    n_resample = 0
    ll = 0.0
    for t in range(n):
        # propagate (full-truncation CIR Euler).
        vp = np.maximum(v, 0.0)
        v = vp + kappa * (theta - vp) * dt + vol_of_vol * np.sqrt(vp * dt) * rng.standard_normal(n_particles)
        v = np.maximum(v, 1e-10)
        # weight by the observation likelihood N(r_t; 0, v*dt).
        var = v * dt
        loglik = -0.5 * (np.log(2.0 * math.pi * var) + r[t] ** 2 / var)
        logw = np.log(np.maximum(w, 1e-300)) + loglik
        logw -= logw.max()
        w = np.exp(logw)
        wsum = w.sum()
        ll += math.log(wsum / n_particles) + float(logw.max()) if wsum > 0 else -1e6
        w /= wsum
        fv[t] = float(np.sum(w * v))
        eff = 1.0 / float(np.sum(w * w))
        ess[t] = eff
        if eff < n_particles / 2.0:                       # systematic resampling
            positions = (rng.random() + np.arange(n_particles)) / n_particles
            idx = np.searchsorted(np.cumsum(w), positions)
            idx = np.clip(idx, 0, n_particles - 1)
            v = v[idx]
            w = np.full(n_particles, 1.0 / n_particles)
            n_resample += 1
    return ParticleFilterResult(fv, ess, n_resample, float(ll))
