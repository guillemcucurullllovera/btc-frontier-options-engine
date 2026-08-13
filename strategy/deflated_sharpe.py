"""Canonical anti-overfitting statistics — PSR, DSR, and CSCV-PBO with purged &
embargoed walk-forward, per Bailey & Lopez de Prado.

This REPLACES the mislabeled home-grown "DSR"/"CSCV" in strategy/regimes.py.

Authority (repo reference library at /home/francisco/btc/reference_library_incoming/):
  - Advances in Financial Machine Learning, Marcos Lopez de Prado (2018):
      ch.7  = purging & embargo (fix information leakage in CV),
      ch.12 = Combinatorial Purged Cross-Validation,
      ch.14.7.1/2/3 = Sharpe / Probabilistic Sharpe / Deflated Sharpe ratios.
  - Bailey & Lopez de Prado (2012) "The Sharpe Ratio Efficient Frontier" (PSR).
  - Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio" (DSR).
  - Bailey, Borwein, Lopez de Prado, Zhu (2017) "The Probability of Backtest
      Overfitting" (CSCV / PBO).

FREQUENCY CONVENTION (critical): every Sharpe ratio in this module is
PER-PERIOD (non-annualized): SR_hat = mean(r)/std(r) at the native sampling
frequency of the return series, and T = number of such observations. PSR/DSR are
DEFINED in this frequency. Do NOT pass an annualized Sharpe. Annualization
(x*sqrt(a)) is only for human-facing reporting, never inside PSR/DSR.

DSR and PSR are PROBABILITIES in [0, 1]. The 5% significance gate is > 0.95.
"""
from __future__ import annotations

from itertools import combinations
from math import erf, exp, log, sqrt

import numpy as np

_EULER_MASCHERONI = 0.5772156649015329
_E = exp(1.0)
_SQRT2 = sqrt(2.0)


# ---------------------------------------------------------------------------
# Standard-normal CDF / inverse-CDF (dependency-free; scipy used if available)
# ---------------------------------------------------------------------------
def _phi(x: float) -> float:
    """Standard-normal CDF via erf (no scipy dependency)."""
    return 0.5 * (1.0 + erf(x / _SQRT2))


try:  # prefer scipy's inverse-normal when present; fall back to Acklam otherwise
    from scipy.special import ndtri as _ppf  # type: ignore
except Exception:  # pragma: no cover - environment-dependent

    def _ppf(p: float) -> float:
        """Acklam rational approximation of the inverse standard-normal CDF."""
        if p <= 0.0:
            return -np.inf
        if p >= 1.0:
            return np.inf
        a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
             1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
        b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
             6.680131188771972e01, -1.328068155288572e01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
             -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
             3.754408661907416e00]
        plow, phigh = 0.02425, 1.0 - 0.02425
        if p < plow:
            q = sqrt(-2.0 * log(p))
            return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                   ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        if p <= phigh:
            q = p - 0.5
            r = q * q
            return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
                   (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        q = sqrt(-2.0 * log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


# ---------------------------------------------------------------------------
# Sharpe ratio (per-period) with sample moments
# ---------------------------------------------------------------------------
def sharpe_ratio(returns, rf_per_period: float = 0.0) -> float:
    """Per-period Sharpe = mean(excess)/std(excess). NOT annualized."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return float("nan")
    sd = r.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float((r.mean() - rf_per_period) / sd)


def _skew_kurt(returns) -> tuple[float, float]:
    """Population skewness (g1) and NON-excess kurtosis (g2, Gaussian == 3)."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    rc = r - r.mean()
    s = r.std(ddof=0)
    if s == 0 or r.size < 2:
        return 0.0, 3.0
    g1 = float((rc ** 3).mean() / s ** 3)
    g2 = float((rc ** 4).mean() / s ** 4)
    return g1, g2


# ---------------------------------------------------------------------------
# Probabilistic Sharpe Ratio  (AFML 14.7.2 ; Bailey & LdP 2012)
# ---------------------------------------------------------------------------
def probabilistic_sharpe_ratio(returns, sr_benchmark: float = 0.0) -> dict:
    """PSR(SR*) = Z[ (SR_hat - SR*) * sqrt(T-1) /
                     sqrt(1 - g1*SR_hat + ((g2-1)/4)*SR_hat^2) ].

    A probability in [0,1] that the true (per-period) Sharpe exceeds SR*,
    correcting for track-record length T, skewness g1, and kurtosis g2.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    T = r.size
    if T < 3 or r.std(ddof=1) == 0:
        return {"psr": None, "sr_hat": None, "skew": None, "kurt": None,
                "T": int(T), "insufficient": True}
    sr = sharpe_ratio(r)
    g1, g2 = _skew_kurt(r)
    denom = 1.0 - g1 * sr + (g2 - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return {"psr": None, "sr_hat": sr, "skew": g1, "kurt": g2,
                "T": int(T), "insufficient": True,
                "reason": "non-positive PSR variance term (extreme non-normality)"}
    z = (sr - sr_benchmark) * sqrt(T - 1) / sqrt(denom)
    return {"psr": float(_phi(z)), "z_stat": float(z), "sr_hat": float(sr),
            "sr_benchmark": float(sr_benchmark), "skew": g1, "kurt": g2,
            "T": int(T), "insufficient": False}


# ---------------------------------------------------------------------------
# Deflated benchmark SR*  and  Deflated Sharpe Ratio  (AFML 14.7.3 ; B&LdP 2014)
# ---------------------------------------------------------------------------
def expected_max_sharpe(variance_of_trial_sr: float, n_trials: int) -> float:
    """Deflated benchmark SR* = expected maximum Sharpe under H0 (true SR = 0):

        SR* = sqrt(V) * [ (1-gamma)*Z^-1(1 - 1/N) + gamma*Z^-1(1 - 1/(N*e)) ]

    where V = variance ACROSS the N trials' estimated (per-period) Sharpes,
    N = number of independent trials, gamma = Euler-Mascheroni, e = Euler's number.
    """
    N = max(int(n_trials), 1)
    if N == 1 or variance_of_trial_sr <= 0:
        return 0.0
    z1 = _ppf(1.0 - 1.0 / N)
    z2 = _ppf(1.0 - 1.0 / (N * _E))
    return float(sqrt(variance_of_trial_sr) *
                 ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2))


def deflated_sharpe_ratio(selected_returns, trial_sharpes=None,
                          n_trials: int | None = None,
                          variance_of_trial_sr: float | None = None) -> dict:
    """Deflated Sharpe Ratio = PSR evaluated at the deflated benchmark SR*.

    Preferred call (canonical): pass `trial_sharpes` = the per-period Sharpe of
    EVERY configuration tried (the full grid of N trials). V and N are taken
    from that vector -> SR* reflects the ACTUAL selection multiplicity and the
    ACTUAL dispersion of the strategies searched.

    Fallback: pass n_trials (+ optionally variance_of_trial_sr). If variance is
    omitted, the H0 estimator-variance proxy Var(SR_hat) ~ 1/T is used; this is
    weaker (it ignores how similar/dissimilar the searched strategies are) and
    should be labelled as such in any report.

    DSR is a probability; the 5% skill gate is DSR > 0.95.
    """
    r = np.asarray(selected_returns, dtype=float)
    r = r[np.isfinite(r)]
    T = r.size
    if T < 10:
        return {"dsr": None, "insufficient": True,
                "reason": f"need >=10 obs, have {T}", "T": int(T)}

    if trial_sharpes is not None:
        ts = np.asarray(trial_sharpes, dtype=float)
        ts = ts[np.isfinite(ts)]
        N = ts.size
        V = float(np.var(ts, ddof=1)) if N > 1 else 0.0
        var_source = "grid"
    else:
        if n_trials is None:
            raise ValueError("pass trial_sharpes, or n_trials for the fallback")
        N = int(n_trials)
        V = float(variance_of_trial_sr) if variance_of_trial_sr is not None else 1.0 / T
        var_source = "supplied" if variance_of_trial_sr is not None else "H0_proxy_1/T"

    sr_star = expected_max_sharpe(V, N)
    psr = probabilistic_sharpe_ratio(r, sr_benchmark=sr_star)
    return {
        "dsr": psr.get("psr"),
        "sr_hat": psr.get("sr_hat"),
        "sr_star": float(sr_star),
        "n_trials": int(N),
        "variance_of_trial_sr": float(V),
        "variance_source": var_source,
        "skew": psr.get("skew"),
        "kurt": psr.get("kurt"),
        "T": int(T),
        "z_stat": psr.get("z_stat"),
        "insufficient": bool(psr.get("insufficient", False)),
        "reason": psr.get("reason"),
    }


# ---------------------------------------------------------------------------
# Purge & embargo helpers (AFML ch.7)
# ---------------------------------------------------------------------------
def purge_embargo_train_mask(n_obs: int, test_lo: int, test_hi: int,
                             purge: int, embargo: int) -> np.ndarray:
    """Boolean TRAIN mask over [0, n_obs) that excludes the test block
    [test_lo, test_hi] plus a `purge` window on BOTH sides (labels of adjacent
    train obs overlap the test labels) and an `embargo` window AFTER the test
    block (serial-correlation buffer). AFML ch.7.4.
    """
    mask = np.ones(n_obs, dtype=bool)
    lo = max(0, test_lo - purge)
    hi = min(n_obs - 1, test_hi + purge + embargo)
    mask[lo:hi + 1] = False
    return mask


# ---------------------------------------------------------------------------
# CSCV / PBO  (AFML ch.12 ; Bailey et al. 2017)
# ---------------------------------------------------------------------------
def cscv_pbo(perf_matrix: np.ndarray, S: int = 16,
             purge: int = 0, embargo: int = 0) -> dict:
    """Combinatorially-Symmetric Cross-Validation Probability of Backtest
    Overfitting.

    perf_matrix: shape (T_obs, N_configs) of per-observation performance
        contributions (e.g. per-period or per-cycle returns), one COLUMN per
        configuration searched. N_configs >= 2 is REQUIRED — PBO measures
        selection bias ACROSS the config grid; it is undefined for one config.

    Method (canonical): partition the T rows into S disjoint contiguous blocks;
    for EVERY combination of S/2 blocks as train (complement = test), pick the
    in-sample-best config n*, then measure its relative rank omega in (0,1) among
    the OOS Sharpes. logit = ln(omega/(1-omega)). PBO = P(logit <= 0) = the
    frequency with which the in-sample winner lands below the OOS median.

    purge/embargo (>0): drop the `purge` rows adjacent to each train/test block
    boundary and `embargo` rows after each test block from the TRAIN side, to
    kill leakage from overlapping labels (needed when rows are overlapping daily
    marks of multi-day option cycles; set purge = tenor_in_rows). Not needed when
    rows are already non-overlapping per-cycle P&L.
    """
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2:
        return {"pbo": None, "reason": "perf_matrix must be 2-D (T x N)", "n_splits": 0}
    T, N = M.shape
    if N < 2:
        return {"pbo": None, "n_splits": 0,
                "reason": "PBO requires >= 2 configurations (a search grid)"}
    if S % 2 != 0:
        S -= 1
    if S < 2 or T < 2 * S:
        return {"pbo": None, "n_splits": 0,
                "reason": f"need even S>=2 and T>=2S; have T={T}, S={S}"}

    blocks = np.array_split(np.arange(T), S)

    def _sharpe_cols(rows: np.ndarray) -> np.ndarray:
        sub = M[rows]
        mu = sub.mean(axis=0)
        sd = sub.std(axis=0, ddof=1)
        return np.where(sd > 0, mu / sd, 0.0)

    logits = []
    is_best_oos_rank = []
    for train_blocks in combinations(range(S), S // 2):
        test_blocks = [b for b in range(S) if b not in train_blocks]
        tr = np.concatenate([blocks[b] for b in train_blocks])
        te = np.concatenate([blocks[b] for b in test_blocks])
        if purge > 0 or embargo > 0:
            keep = np.ones(T, dtype=bool)
            for b in test_blocks:
                keep &= purge_embargo_train_mask(T, blocks[b][0], blocks[b][-1],
                                                 purge, embargo)
            tr = tr[keep[tr]]
            if tr.size < N + 1:
                continue
        s_tr = _sharpe_cols(tr)
        s_te = _sharpe_cols(te)
        n_star = int(np.argmax(s_tr))
        # relative OOS rank of the in-sample-best config, in (0,1)
        order = np.argsort(s_te)  # ascending
        rank = int(np.where(order == n_star)[0][0])  # 0..N-1
        omega = (rank + 1.0) / (N + 1.0)
        omega = min(max(omega, 1e-9), 1.0 - 1e-9)
        logits.append(log(omega / (1.0 - omega)))
        is_best_oos_rank.append(rank / (N - 1.0))

    if not logits:
        return {"pbo": None, "n_splits": 0, "reason": "no valid CSCV splits"}
    logits = np.asarray(logits)
    return {
        "pbo": float(np.mean(logits <= 0.0)),
        "n_splits": int(logits.size),
        "median_logit": float(np.median(logits)),
        "mean_oos_relrank_of_is_best": float(np.mean(is_best_oos_rank)),
        "S": int(S),
        "n_configs": int(N),
    }


# ---------------------------------------------------------------------------
# Purged + embargoed walk-forward over a config grid (AFML ch.7 + ch.12)
# ---------------------------------------------------------------------------
def purged_embargoed_walk_forward(returns_matrix: np.ndarray,
                                  boundaries: list[int],
                                  purge: int,
                                  embargo: int,
                                  tune_cols: list[int] | None = None) -> dict:
    """Expanding-window walk-forward with purge & embargo.

    returns_matrix: (T, N) per-period returns, one column per config.
    boundaries: sorted row indices splitting the sample into OOS folds.
    purge/embargo: rows (e.g. purge = option tenor in rows; embargo ~ 1% of T).
    tune_cols: subset of columns eligible for selection (defaults to all).

    For each fold, select the config with the best per-period Sharpe on the
    PURGED training rows (strictly before the fold, minus a purge gap), then
    record that config's returns on the fold (starting embargo rows after the
    boundary). Returns the stitched OOS return series and the per-fold picks.
    """
    M = np.asarray(returns_matrix, dtype=float)
    T, N = M.shape
    cols = list(range(N)) if tune_cols is None else list(tune_cols)
    bnds = sorted(b for b in boundaries if 0 < b < T)
    picks: list[dict] = []
    oos_chunks: list[np.ndarray] = []
    for k, b in enumerate(bnds):
        train_hi = b - purge
        test_lo = b + embargo
        test_hi = bnds[k + 1] if k + 1 < len(bnds) else T
        if train_hi < 30 or test_lo >= test_hi:
            continue
        tr = M[:train_hi][:, cols]
        tr_sr = np.array([sharpe_ratio(tr[:, j]) for j in range(tr.shape[1])])
        if not np.any(np.isfinite(tr_sr)):
            continue
        best_local = int(np.nanargmax(tr_sr))
        best_col = cols[best_local]
        oos_chunks.append(M[test_lo:test_hi, best_col])
        picks.append({"boundary_idx": int(b), "picked_col": int(best_col),
                      "train_sharpe": float(tr_sr[best_local]),
                      "test_rows": int(test_hi - test_lo)})
    if not oos_chunks:
        return {"oos_returns": np.array([]), "picks": picks, "insufficient": True}
    oos = np.concatenate(oos_chunks)
    return {"oos_returns": oos, "oos_sharpe": sharpe_ratio(oos),
            "picks": picks, "purge": purge, "embargo": embargo,
            "insufficient": False}
