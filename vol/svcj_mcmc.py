"""SVCJ (stochastic-vol, contemporaneous co-jumps) Bayesian MCMC — Eraker-Johannes-Polson 2003.

C9 · overnight Phase C (M4.4b). SIMULATED / diagnostic; MS-26-gated; P-ESTIMATED from OBSERVED returns;
canonical main untouched. Implements the EJP (2003, "The Impact of Jumps in Volatility and Returns")
time-discretised SVCJ model and its Gibbs/Metropolis sampler with data augmentation of the latent
variance, jump times and jump sizes. Source: private_reference_library/new_phase/ejp_2003.

Discretised model (unit step; returns in PERCENT, y = 100*log-return, so the EJP prior scales apply):
    y_{t+1} - y_t = mu + sqrt(V_t) eps^y_{t+1} + xi^y_{t+1} J_{t+1}
    V_{t+1} - V_t = kappa(theta - V_t) + sigma_v sqrt(V_t) eps^v_{t+1} + xi^v_{t+1} J_{t+1}
    corr(eps^y, eps^v) = rho ; J ~ Bernoulli(lambda) contemporaneous
    xi^v ~ Exp(mu_v) ;  xi^y | xi^v ~ N(mu_y + rho_J xi^v, sigma_y^2)

Latent V is updated by an even/odd (checkerboard) vectorised random-walk Metropolis — V_t's full
conditional depends only on V_{t-1}, V_{t+1}, so alternating half-sweeps are conditionally independent
and vectorise. Parameters use conjugate normal/IG/Beta draws under the conditional-normal (rho-coupled)
decomposition; rho by independence Metropolis. Convergence by Gelman-Rubin R-hat + effective sample size.

Priors (weakly informative, EJP-structured; documented deviations where the OCR parametrisation is
ambiguous) are in ``SVCJPriors``. Validation: ``simulate_svcj`` + parameter recovery (tests).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

FloatArr = npt.NDArray[np.float64]
_PARAM_NAMES = ("mu", "kappa", "theta", "sigma_v", "rho", "lambda", "mu_y", "sigma_y", "mu_v", "rho_j")


@dataclass(frozen=True)
class SVCJParams:
    mu: float
    kappa: float
    theta: float
    sigma_v: float
    rho: float
    lam: float
    mu_y: float
    sigma_y: float
    mu_v: float
    rho_j: float

    def as_tuple(self) -> tuple[float, ...]:
        return (self.mu, self.kappa, self.theta, self.sigma_v, self.rho, self.lam,
                self.mu_y, self.sigma_y, self.mu_v, self.rho_j)


@dataclass(frozen=True)
class SVCJPriors:
    """Weakly-informative, EJP-structured priors (percent-return scale)."""
    mu_var: float = 100.0                 # mu ~ N(0, mu_var)
    b0_var: float = 100.0                 # kappa*theta ~ N(0, b0_var)
    b1_var: float = 1.0                   # kappa ~ N(0, b1_var), truncated > 0
    sigv2_a: float = 2.0                  # sigma_v^2 ~ IG(sigv2_a, sigv2_b)
    sigv2_b: float = 0.5
    lam_a: float = 2.0                    # lambda ~ Beta(lam_a, lam_b)  (EJP Beta(2,40))
    lam_b: float = 40.0
    muy_var: float = 100.0                # mu_y ~ N(0, muy_var)
    sigy2_a: float = 5.0                  # sigma_y^2 ~ IG(5, 20) (EJP; keeps jumps "large")
    sigy2_b: float = 20.0
    muv_a: float = 2.5                    # mu_v ~ IG(muv_a, muv_b) (conjugate for Exp mean; EJP used G(20,10))
    muv_b: float = 10.0
    rhoj_var: float = 4.0                 # rho_j ~ N(0, rhoj_var)


@dataclass
class SVCJPosterior:
    chains: FloatArr                      # (n_chains, n_keep, n_params)
    param_names: tuple[str, ...]
    rhat: dict[str, float]
    ess: dict[str, float]
    post_mean: dict[str, float]
    post_sd: dict[str, float]
    post_q05: dict[str, float]
    post_q95: dict[str, float]
    v_filtered: FloatArr                  # posterior-mean latent vol path (annualised) from chain 0
    jump_prob: FloatArr                   # posterior P(J_t=1) from chain 0
    accept_v: float
    accept_rho: float
    converged: bool
    n_iter: int
    n_burn: int
    provenance: str = "P-ESTIMATED"
    diagnostics: dict[str, float] = field(default_factory=dict)


# ── simulation (independent oracle for the recovery test) ────────────────────


def simulate_svcj(p: SVCJParams, n: int, seed: int, v0: float | None = None) -> tuple[FloatArr, FloatArr, FloatArr]:
    """Simulate the discretised SVCJ (percent returns). Returns (y_levels, V_true, J_true)."""
    rng = np.random.default_rng(seed)
    v = np.empty(n + 1)
    v[0] = v0 if v0 is not None else p.theta
    y = np.zeros(n + 1)
    jumps = np.zeros(n, dtype=np.float64)
    chol = np.array([[1.0, 0.0], [p.rho, np.sqrt(max(1.0 - p.rho ** 2, 0.0))]])
    for t in range(n):
        z = chol @ rng.standard_normal(2)
        j = 1.0 if rng.random() < p.lam else 0.0
        xiv = rng.exponential(p.mu_v) if j else 0.0
        xiy = (p.mu_y + p.rho_j * xiv + p.sigma_y * rng.standard_normal()) if j else 0.0
        sv = np.sqrt(max(v[t], 1e-8))
        y[t + 1] = y[t] + p.mu + sv * z[0] + xiy * j
        v[t + 1] = max(v[t] + p.kappa * (p.theta - v[t]) + p.sigma_v * sv * z[1] + xiv * j, 1e-6)
        jumps[t] = j
    return y, v, jumps


# ── diagnostics ──────────────────────────────────────────────────────────────


def gelman_rubin(chains: FloatArr) -> float:
    """R-hat for one parameter; chains shape (n_chains, n_draws)."""
    m, n = chains.shape
    if m < 2 or n < 2:
        return float("nan")
    means = chains.mean(axis=1)
    b = n * means.var(ddof=1)
    w = chains.var(axis=1, ddof=1).mean()
    if w <= 0:
        return float("nan")
    var_hat = (n - 1) / n * w + b / n
    return float(np.sqrt(var_hat / w))


def _ess(chain: FloatArr) -> float:
    """Effective sample size for one chain via the initial-positive-sequence autocorrelation sum."""
    n = chain.size
    x = chain - chain.mean()
    v = float(np.dot(x, x) / n)
    if v <= 0:
        return float(n)
    acf_sum = 0.0
    for lag in range(1, min(n - 1, 1000)):
        rho = float(np.dot(x[:-lag], x[lag:]) / (n * v))
        if rho < 0.05:
            break
        acf_sum += rho
    return float(n / (1.0 + 2.0 * acf_sum))


# ── sampler internals ────────────────────────────────────────────────────────


def _rtruncnorm_pos(mean: FloatArr, sd: FloatArr, rng: np.random.Generator) -> FloatArr:
    """Vectorised truncated-normal on (0, inf) via the inverse-CDF method (scipy ndtr/ndtri)."""
    from scipy.special import ndtr, ndtri
    sd = np.maximum(sd, 1e-9)
    alpha = (0.0 - mean) / sd
    phi_a = ndtr(alpha)                                    # P(Z < alpha)
    u = rng.random(mean.shape)
    p = phi_a + u * (1.0 - phi_a)
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    return np.asarray(mean + sd * ndtri(p), dtype=np.float64)


def _bivar_ld(dy: FloatArr, dV: FloatArr, Vp: FloatArr, mu: float, kappa: float, theta: float,
              sigma_v: float, rho: float, xiy: FloatArr, xiv: FloatArr, J: FloatArr) -> FloatArr:
    """Per-increment bivariate-normal log density of (dy, dV) given the previous variance Vp."""
    om = max(1.0 - rho * rho, 1e-8)
    sVp = np.sqrt(np.maximum(Vp, 1e-10))
    u = (dy - mu - xiy * J) / sVp
    w = (dV - kappa * (theta - Vp) - xiv * J) / (sigma_v * sVp)
    quad = (u * u - 2.0 * rho * u * w + w * w) / om
    # cov = Vp * [[1, rho*sigma_v],[rho*sigma_v, sigma_v^2]]  ->  det = Vp^2 * sigma_v^2 * (1-rho^2)
    logdet = 2.0 * np.log(np.maximum(Vp, 1e-10)) + 2.0 * math.log(sigma_v) + math.log(om)
    return np.asarray(-0.5 * logdet - 0.5 * quad, dtype=np.float64)


def _draw_ig(a: float, b: float, rng: np.random.Generator) -> float:
    """Inverse-Gamma(a, b) draw (shape a, scale b): 1 / Gamma(a, rate=b)."""
    g = rng.gamma(shape=max(a, 1e-6), scale=1.0 / max(b, 1e-12))
    return float(1.0 / max(g, 1e-12))


def _one_chain(y: FloatArr, pr: SVCJPriors, n_iter: int, n_burn: int, seed: int,
               ) -> tuple[FloatArr, FloatArr, FloatArr, float, float]:
    rng = np.random.default_rng(seed)
    T = y.size - 1
    dy = np.diff(y)
    # init latent variance at a rolling realised variance; jumps off; params at moment estimates
    v_scale = float(np.var(dy)) if T > 1 else 1.0
    V = np.full(T + 1, v_scale)
    J = np.zeros(T, dtype=np.float64)
    xiy = np.zeros(T)
    xiv = np.zeros(T)
    mu = float(np.mean(dy))
    kappa, theta, sigma_v, rho = 0.05, v_scale, 0.5 * math.sqrt(v_scale), -0.3
    lam, mu_y, sigma_y, mu_v, rho_j = 0.03, 0.0, 2.0 * math.sqrt(v_scale), v_scale, -0.5
    s_v = 0.15 * math.sqrt(v_scale)                        # V random-walk step (additive, reflect at 0)
    even = np.arange(0, T + 1, 2)
    odd = np.arange(1, T + 1, 2)

    keep = []
    acc_v = acc_rho = 0.0
    v_sum = np.zeros(T + 1)
    j_sum = np.zeros(T)
    n_keep_states = 0

    for it in range(n_iter):
        Vp = V[:-1]
        dV = np.diff(V)
        sVp = np.sqrt(np.maximum(Vp, 1e-10))
        om = max(1.0 - rho * rho, 1e-8)

        # --- jump sizes xiv (truncated-normal | J=1, else Exp prior), then xiy | xiv --------------
        epsY = (dy - mu - xiy) / sVp
        lam_j = 1.0 / (om * sigma_v * sigma_v * Vp)
        b_j = (dV - kappa * (theta - Vp)) / (om * sigma_v * sigma_v * Vp) - rho * epsY / (om * sigma_v * sVp)
        lam_p = (rho_j * rho_j) / (sigma_y * sigma_y)
        b_p = rho_j * (xiy - mu_y) / (sigma_y * sigma_y)
        prec_v = lam_j + lam_p
        o_v = 1.0 / prec_v
        a_v = (b_j + b_p - 1.0 / mu_v) * o_v
        xiv_new = _rtruncnorm_pos(a_v, np.sqrt(o_v), rng)
        xiv_prior = rng.exponential(mu_v, size=T)
        xiv = np.where(J > 0.5, xiv_new, xiv_prior)

        epsV = (dV - kappa * (theta - Vp) - xiv) / (sigma_v * sVp)
        lam_jy = 1.0 / (om * Vp)
        b_jy = (dy - mu) / (om * Vp) - rho * epsV / (om * sVp)
        lam_py = 1.0 / (sigma_y * sigma_y)
        b_py = (mu_y + rho_j * xiv) / (sigma_y * sigma_y)
        o_y = 1.0 / (lam_jy + lam_py)
        a_y = (b_jy + b_py) * o_y
        xiy_new = a_y + np.sqrt(o_y) * rng.standard_normal(T)
        xiy_prior = (mu_y + rho_j * xiv) + sigma_y * rng.standard_normal(T)
        xiy = np.where(J > 0.5, xiy_new, xiy_prior)

        # --- jump times J (Bernoulli via bivariate density ratio) --------------------------------
        u0 = (dy - mu) / sVp
        w0 = (dV - kappa * (theta - Vp)) / (sigma_v * sVp)
        m_no = (u0 * u0 - 2.0 * rho * u0 * w0 + w0 * w0) / om
        u1 = (dy - mu - xiy) / sVp
        w1 = (dV - kappa * (theta - Vp) - xiv) / (sigma_v * sVp)
        m_j = (u1 * u1 - 2.0 * rho * u1 * w1 + w1 * w1) / om
        logit = (math.log(lam) - 0.5 * m_j) - (math.log(1.0 - lam) - 0.5 * m_no)
        p1 = 1.0 / (1.0 + np.exp(-np.clip(logit, -700, 700)))
        J = (rng.random(T) < p1).astype(np.float64)

        # --- latent variance V: even/odd vectorised random-walk Metropolis (log-scale) -----------
        for idx in (even, odd):
            ld_cur = _bivar_ld(dy, np.diff(V), V[:-1], mu, kappa, theta, sigma_v, rho, xiy, xiv, J)
            Vprop = V.copy()
            step = np.exp(s_v / math.sqrt(max(v_scale, 1e-8)) * rng.standard_normal(idx.size))
            Vprop[idx] = V[idx] * step
            ld_prop = _bivar_ld(dy, np.diff(Vprop), Vprop[:-1], mu, kappa, theta, sigma_v, rho, xiy, xiv, J)
            dld = ld_prop - ld_cur
            delta = np.zeros(T + 1)
            delta[1:] += dld                               # increment i affects candidate i+1 (its dV target)
            delta[:-1] += dld                              # increment i affects candidate i   (its Vp)
            delta_idx = delta[idx] + (np.log(Vprop[idx]) - np.log(V[idx]))   # + log-scale Jacobian
            accept = np.log(rng.random(idx.size)) < delta_idx
            V[idx] = np.where(accept, Vprop[idx], V[idx])
            acc_v += float(np.mean(accept)) / 2.0

        # --- parameters --------------------------------------------------------------------------
        Vp = V[:-1]
        dV = np.diff(V)
        sVp = np.sqrt(np.maximum(Vp, 1e-10))
        # rho: independence Metropolis centered at the sample correlation of standardised innovations
        eY = (dy - mu - xiy * J) / sVp
        eV = (dV - kappa * (theta - Vp) - xiv * J) / (sigma_v * sVp)
        r_hat = float(np.clip(np.corrcoef(eY, eV)[0, 1], -0.98, 0.98)) if T > 2 else rho
        s_yy = float(np.sum(eY * eY))
        s_yv = float(np.sum(eY * eV))
        s_vv = float(np.sum(eV * eV))

        def _rho_ll(rr: float, syy: float = s_yy, syv: float = s_yv, svv: float = s_vv) -> float:
            o = max(1.0 - rr * rr, 1e-8)
            return -0.5 * T * math.log(o) - 0.5 / o * (syy - 2.0 * rr * syv + svv)
        prop_sd = 0.05
        rho_prop = float(np.clip(r_hat + prop_sd * rng.standard_normal(), -0.98, 0.98))
        # independence proposal N(r_hat, prop_sd) -> include the q-ratio in the MH acceptance
        q_corr = (0.5 * ((rho_prop - r_hat) / prop_sd) ** 2) - (0.5 * ((rho - r_hat) / prop_sd) ** 2)
        if math.log(rng.random()) < (_rho_ll(rho_prop) - _rho_ll(rho) + q_corr):
            rho = rho_prop
            acc_rho += 1.0
        om = max(1.0 - rho * rho, 1e-8)

        # mu | rest (conditional-normal, coupled through rho)
        eV = (dV - kappa * (theta - Vp) - xiv * J) / (sigma_v * sVp)
        wgt = 1.0 / (Vp * om)
        resp = dy - xiy * J - sVp * rho * eV
        prec = float(np.sum(wgt)) + 1.0 / pr.mu_var
        mean = float(np.sum(wgt * resp)) / prec
        mu = mean + rng.standard_normal() / math.sqrt(prec)

        # (kappa*theta=b0, kappa=b1) | rest, weighted regression of the vol increment
        eY = (dy - mu - xiy * J) / sVp
        wv = 1.0 / (sigma_v * sigma_v * Vp * om)
        zresp = dV - xiv * J - sigma_v * sVp * rho * eY
        X = np.column_stack([np.ones(T), -Vp])
        XtW = X.T * wv
        Lam = XtW @ X + np.diag([1.0 / pr.b0_var, 1.0 / pr.b1_var])
        rhs = XtW @ zresp
        cov = np.linalg.inv(Lam)
        m = cov @ rhs
        b = rng.multivariate_normal(m, cov)
        b0, b1 = float(b[0]), float(b[1])
        if b1 > 1e-4 and b0 > 0.0:                          # keep kappa>0 and theta=b0/b1>0
            kappa, theta = b1, b0 / b1

        # sigma_v^2 | rest (IG on the standardised vol residual; partially marginalised over rho)
        resid = (dV - xiv * J - (kappa * (theta - Vp))) / sVp
        ssr = float(np.sum(resid * resid))
        sigma_v = math.sqrt(_draw_ig(pr.sigv2_a + 0.5 * T, pr.sigv2_b + 0.5 * ssr, rng))

        # lambda | J
        nJ = float(np.sum(J))
        lam = float(rng.beta(pr.lam_a + nJ, pr.lam_b + T - nJ))
        lam = min(max(lam, 1e-5), 0.5)

        # jump-return params (mu_y, rho_j, sigma_y^2) from J=1 sizes
        mask = J > 0.5
        nj = int(np.sum(mask))
        if nj >= 2:
            xy = xiy[mask]
            xv = xiv[mask]
            Xj = np.column_stack([np.ones(nj), xv])
            Lj = Xj.T @ Xj / (sigma_y * sigma_y) + np.diag([1.0 / pr.muy_var, 1.0 / pr.rhoj_var])
            covj = np.linalg.inv(Lj)
            mj = covj @ (Xj.T @ xy / (sigma_y * sigma_y))
            coef = rng.multivariate_normal(mj, covj)
            mu_y, rho_j = float(coef[0]), float(coef[1])
            ssy = float(np.sum((xy - mu_y - rho_j * xv) ** 2))
            sigma_y = math.sqrt(_draw_ig(pr.sigy2_a + 0.5 * nj, pr.sigy2_b + 0.5 * ssy, rng))
            mu_v = _draw_ig(pr.muv_a + nj, pr.muv_b + float(np.sum(xv)), rng)
        else:
            mu_y = math.sqrt(pr.muy_var) * rng.standard_normal()
            rho_j = math.sqrt(pr.rhoj_var) * rng.standard_normal()
            sigma_y = math.sqrt(_draw_ig(pr.sigy2_a, pr.sigy2_b, rng))
            mu_v = _draw_ig(pr.muv_a, pr.muv_b, rng)

        if it >= n_burn:
            keep.append([mu, kappa, theta, sigma_v, rho, lam, mu_y, sigma_y, mu_v, rho_j])
            v_sum += V
            j_sum += J
            n_keep_states += 1

    v_mean = v_sum / max(n_keep_states, 1)
    j_mean = j_sum / max(n_keep_states, 1)
    return (np.asarray(keep, dtype=np.float64), v_mean, j_mean,
            acc_v / n_iter, acc_rho / n_iter)


def svcj_mcmc(y_pct: FloatArr, n_iter: int = 4000, n_chains: int = 3, n_burn: int = 1500,
              seed: int = 20260731, priors: SVCJPriors | None = None,
              bars_per_year: float = 365.0) -> SVCJPosterior:
    """Run the SVCJ Gibbs/Metropolis sampler over ``n_chains`` and summarise the posterior.

    ``y_pct`` is the level series of PERCENT log-returns (100*log-price) so the EJP prior scales apply.
    Returns posterior means/quantiles, Gelman-Rubin R-hat and ESS per parameter, the posterior-mean
    latent-vol path (annualised) and jump probabilities, and a converged flag (all R-hat < 1.1).
    """
    pr = priors or SVCJPriors()
    chains = []
    v_paths = []
    j_paths = []
    acc_v_list = []
    acc_rho_list = []
    for c in range(n_chains):
        draws, vmean, jmean, av, ar = _one_chain(y_pct, pr, n_iter, n_burn, seed + 101 * c)
        chains.append(draws)
        v_paths.append(vmean)
        j_paths.append(jmean)
        acc_v_list.append(av)
        acc_rho_list.append(ar)
    arr = np.stack(chains, axis=0)                         # (n_chains, n_keep, n_params)

    rhat, ess, pm, psd, q05, q95 = {}, {}, {}, {}, {}, {}
    for k, name in enumerate(_PARAM_NAMES):
        per_chain = arr[:, :, k]
        rhat[name] = gelman_rubin(per_chain)
        ess[name] = float(sum(_ess(per_chain[c]) for c in range(n_chains)))
        flat = per_chain.reshape(-1)
        pm[name] = float(np.mean(flat))
        psd[name] = float(np.std(flat))
        q05[name] = float(np.quantile(flat, 0.05))
        q95[name] = float(np.quantile(flat, 0.95))

    # annualise the posterior-mean latent vol path: V is percent^2 daily -> sqrt(V)/100 * sqrt(bars/yr)
    v_ann = np.sqrt(np.maximum(v_paths[0], 0.0)) / 100.0 * math.sqrt(bars_per_year)
    converged = all(np.isfinite(r) and r < 1.1 for r in rhat.values())
    return SVCJPosterior(
        chains=arr, param_names=_PARAM_NAMES, rhat=rhat, ess=ess, post_mean=pm, post_sd=psd,
        post_q05=q05, post_q95=q95, v_filtered=v_ann, jump_prob=j_paths[0],
        accept_v=float(np.mean(acc_v_list)), accept_rho=float(np.mean(acc_rho_list)),
        converged=converged, n_iter=n_iter, n_burn=n_burn,
        diagnostics={"mean_jump_prob": float(np.mean(j_paths[0]))},
    )
