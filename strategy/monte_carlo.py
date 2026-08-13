"""Monte Carlo simulation for strategy analysis.

Supports:
  - GBM with deterministic seeding
  - Merton jump-diffusion with antithetic variates
  - VaR and ES defined explicitly in loss space (VaR_k >= 0 convention)
  - Separate P&L-quantile fields sorted ascending (lowest P&L tail)
  - ITM and touch probability for all option legs
  - Parameter validation rejecting impossible configurations
  - Research-quality path counts (>= 50,000 for reference runs)

No look-ahead bias. All paths deterministic given seed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from scipy.stats import norm

from config.models import Provenance
from engine.errors import ValidationError
from engine.strategy import Strategy
from strategy.payoffs import strategy_pnl


@dataclass(frozen=True)
class MonteCarloConfig:
    n_paths: int = 10_000
    horizon_years: float = 30.0 / 365.0
    initial_spot: float = 65_000.0
    drift: float = 0.10
    volatility: float = 0.45
    risk_free_rate: float = 0.04
    model: Literal["GBM", "Merton"] = "GBM"
    seed: int = 42
    use_antithetic: bool = True
    jump_intensity: float = 2.0
    jump_mean: float = -0.05
    jump_std: float = 0.10
    n_steps: int | None = None

    def __post_init__(self) -> None:
        if self.initial_spot <= 0:
            raise ValidationError(f"initial_spot must be positive, got {self.initial_spot}")
        if self.volatility < 0:
            raise ValidationError(f"volatility must be non-negative, got {self.volatility}")
        if self.horizon_years <= 0:
            raise ValidationError(f"horizon_years must be positive, got {self.horizon_years}")
        if self.n_paths <= 0:
            raise ValidationError(f"n_paths must be positive, got {self.n_paths}")
        steps = self.n_steps or max(int(self.horizon_years * 365), 1)
        if steps <= 0:
            raise ValidationError(f"n_steps must be positive, got {steps}")
        if self.jump_intensity < 0:
            raise ValidationError(f"jump_intensity must be non-negative, got {self.jump_intensity}")
        if self.jump_std < 0:
            raise ValidationError(f"jump_std must be non-negative, got {self.jump_std}")


@dataclass(frozen=True)
class MonteCarloResult:
    strategy_id: str
    n_paths: int
    model: str
    seed: int
    horizon_years: float
    initial_spot: float
    drift: float
    volatility: float
    jump_params: dict[str, Any] | None = None

    expected_pnl: float = 0.0
    median_pnl: float = 0.0
    std_pnl: float = 0.0
    percentile_5: float = 0.0
    percentile_1: float = 0.0

    var_95: float = 0.0
    var_99: float = 0.0
    es_975: float = 0.0
    es_99: float = 0.0

    var_95_pnl: float = 0.0
    var_99_pnl: float = 0.0
    es_975_pnl: float = 0.0
    es_99_pnl: float = 0.0

    itm_probability: float = 0.0
    touch_probability: float = 0.0
    probability_of_loss: float = 0.0
    expected_premium_pct: float = 0.0

    expected_btc_inventory: float = 0.0
    expected_cash_requirement: float = 0.0

    pnl_distribution: list[float] = field(default_factory=list)
    worst_paths: list[float] = field(default_factory=list)

    hedge_cost_mean_usd: float = 0.0
    hedge_cost_mean_btc: float = 0.0
    hedge_strategy: Literal["none", "static", "delta"] = "none"
    pending_decision_refs: list[str] = field(default_factory=list)
    provenance: Provenance = Provenance.SIMULATED

    # C9 · M0.3: control-variate variance reduction on E[P&L]. Pure post-processing on the
    # already-generated (seeded/antithetic) paths — does NOT touch the RNG stream, so the
    # reproducibility contract is preserved.
    expected_pnl_se: float = 0.0            # plain MC standard error of the mean
    cv_expected_pnl: float = 0.0           # control-variate-adjusted mean (unbiased)
    cv_expected_pnl_se: float = 0.0        # CV standard error of the mean
    cv_variance_reduction: float = 0.0     # 1 - Var_cv/Var_plain (in [0,1))
    cv_controls: list[str] = field(default_factory=list)


W_HEDGE_MODEL_UNSPECIFIED = "W-HEDGE-MODEL-UNSPECIFIED: delta-hedge path requested but D-9 unresolved"


def _simulate_gbm(config: MonteCarloConfig) -> tuple[np.ndarray, np.ndarray]:
    """Simulate GBM paths with antithetic variates. All n_paths populated."""
    rng = np.random.default_rng(config.seed)
    n_steps = config.n_steps or max(int(config.horizon_years * 365), 1)
    dt = config.horizon_years / n_steps
    n_paths = config.n_paths
    half = n_paths // 2 if config.use_antithetic else n_paths
    if config.use_antithetic and half * 2 < n_paths:
        half += 1

    paths = np.zeros((n_paths, n_steps + 1))
    paths[:, 0] = config.initial_spot
    S = config.initial_spot
    mu = config.drift
    sigma = config.volatility

    for i in range(half):
        z = rng.normal(size=n_steps)
        returns = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * z
        paths[i, 1:] = S * np.exp(np.cumsum(returns))
        if config.use_antithetic:
            anti_idx = i + half
            if anti_idx < n_paths:
                returns_anti = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * (-z)
                paths[anti_idx, 1:] = S * np.exp(np.cumsum(returns_anti))

    return paths, paths[:, -1]


def _simulate_merton(config: MonteCarloConfig) -> tuple[np.ndarray, np.ndarray]:
    """Simulate Merton jump-diffusion paths.

    All n_paths populated. Antithetic pairing provides variance reduction
    through negatively correlated normal shocks; jumps are independently
    resampled per path (not antithetic on jumps — documented behaviour).
    """
    rng = np.random.default_rng(config.seed)
    n_steps = config.n_steps or max(int(config.horizon_years * 365), 1)
    dt = config.horizon_years / n_steps
    n_paths = config.n_paths
    half = n_paths // 2 if config.use_antithetic else n_paths
    if config.use_antithetic and half * 2 < n_paths:
        half += 1

    paths = np.zeros((n_paths, n_steps + 1))
    paths[:, 0] = config.initial_spot
    S = config.initial_spot
    mu = config.drift
    sigma = config.volatility
    lam = config.jump_intensity
    mu_j = config.jump_mean
    sigma_j = config.jump_std
    jump_compensation = lam * (np.exp(mu_j + 0.5 * sigma_j ** 2) - 1)

    for i in range(half):
        z = rng.normal(size=n_steps)
        jump_counts = rng.poisson(lam * dt, size=n_steps)
        jumps = np.zeros(n_steps)
        for t in range(n_steps):
            if jump_counts[t] > 0:
                jumps[t] = np.sum(rng.normal(mu_j, sigma_j, size=jump_counts[t]))
        returns = (mu - 0.5 * sigma ** 2 - jump_compensation) * dt + sigma * np.sqrt(dt) * z + jumps
        paths[i, 1:] = S * np.exp(np.cumsum(returns))

        if config.use_antithetic:
            anti_idx = i + half
            if anti_idx < n_paths:
                anti_jumps = np.zeros(n_steps)
                for t in range(n_steps):
                    if jump_counts[t] > 0:
                        anti_jumps[t] = np.sum(rng.normal(mu_j, sigma_j, size=jump_counts[t]))
                returns_anti = (mu - 0.5 * sigma ** 2 - jump_compensation) * dt + sigma * np.sqrt(dt) * (-z) + anti_jumps
                paths[anti_idx, 1:] = S * np.exp(np.cumsum(returns_anti))

    return paths, paths[:, -1]


def sim_final_spot_only(
    initial_spot: float,
    drift: float,
    volatility: float,
    horizon_years: float,
    n_paths: int = 10_000,
    seed: int = 42,
    model: str = "GBM",
    use_antithetic: bool = True,
) -> np.ndarray:
    """Generate deterministic final spot prices only (no intermediate path)."""
    rng = np.random.default_rng(seed)
    half = n_paths // 2 if use_antithetic else n_paths
    if use_antithetic and half * 2 < n_paths:
        half += 1
    T = horizon_years
    sigma = volatility
    z = rng.normal(size=half)
    results = np.zeros(n_paths)
    for i in range(half):
        final = initial_spot * np.exp((drift - 0.5 * sigma ** 2) * T + sigma * np.sqrt(T) * z[i])
        results[i] = final
        if use_antithetic:
            anti_idx = i + half
            if anti_idx < n_paths:
                results[anti_idx] = initial_spot * np.exp((drift - 0.5 * sigma ** 2) * T + sigma * np.sqrt(T) * (-z[i]))
    return results


def _compute_var_es(losses: np.ndarray, n_paths: int) -> dict[str, float]:
    """Compute VaR and ES in loss space.

    VaR_k = loss quantile at confidence level k (k in [0,1]).
      - VaR_95 = 95th percentile of sorted losses.
    ES_k = mean loss beyond VaR_k.
      - ES_975 = mean of the top 2.5% of losses.

    Loss-space fields (var_95, es_975, etc.) are non-negative.
    P&L-space fields capture the same tail but in P&L units
    (ascending pnl, lowest P&L = worst tail).
    """
    sorted_losses = np.sort(losses)

    var_95_idx = min(int(n_paths * 0.95), n_paths - 1)
    var_99_idx = min(int(n_paths * 0.99), n_paths - 1)
    var_95 = float(sorted_losses[var_95_idx])
    var_99 = float(sorted_losses[var_99_idx])

    es_975_idx = max(int(n_paths * 0.975), 1)
    es_99_idx = max(int(n_paths * 0.99), 1)
    es_975 = float(np.mean(sorted_losses[es_975_idx:])) if es_975_idx < n_paths else var_95
    es_99 = float(np.mean(sorted_losses[es_99_idx:])) if es_99_idx < n_paths else var_99

    sorted_pnl = np.sort(-sorted_losses)
    n_975 = int(n_paths * (1.0 - 0.975))
    n_99 = int(n_paths * (1.0 - 0.99))
    n_975 = max(n_975, 1)
    n_99 = max(n_99, 1)

    var_95_pnl = float(sorted_pnl[max(n_paths - var_95_idx - 1, 0)])
    var_99_pnl = float(sorted_pnl[max(n_paths - var_99_idx - 1, 0)])
    es_975_pnl = float(np.mean(sorted_pnl[:n_975])) if n_975 > 0 else var_99_pnl
    es_99_pnl = float(np.mean(sorted_pnl[:n_99])) if n_99 > 0 else var_99_pnl

    return {
        "var_95": var_95,
        "var_99": var_99,
        "es_975": es_975,
        "es_99": es_99,
        "var_95_pnl": var_95_pnl,
        "var_99_pnl": var_99_pnl,
        "es_975_pnl": es_975_pnl,
        "es_99_pnl": es_99_pnl,
    }


@dataclass(frozen=True)
class ControlVariateEstimate:
    plain_mean: float
    plain_se: float
    cv_mean: float
    cv_se: float
    variance_reduction: float          # 1 - Var_cv/Var_plain
    controls: list[str]


def _gbm_payoff_mean(S0: float, K: float, mu: float, sigma: float, T: float, kind: str) -> float:
    """Undiscounted E[payoff(S_T)] under GBM(drift=mu): Black-Scholes with r->mu, no discount.

    E[S_T] = S0*exp(mu*T); d1 uses mu. This is the EXACT control-variate mean under the GBM
    simulation measure (drift mu, not r), so the CV estimator stays unbiased.
    """
    if sigma <= 0 or T <= 0:
        fwd = S0 * math.exp(mu * T)
        return max(fwd - K, 0.0) if kind == "call" else max(K - fwd, 0.0)
    fwd = S0 * math.exp(mu * T)
    d1 = (math.log(S0 / K) + (mu + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "call":
        return float(fwd * norm.cdf(d1) - K * norm.cdf(d2))
    return float(K * norm.cdf(-d2) - fwd * norm.cdf(-d1))


def control_variate_expected_pnl(
    pnl: np.ndarray, final_prices: np.ndarray, config: MonteCarloConfig, strategy: Strategy,
) -> ControlVariateEstimate:
    """Multivariate control-variate estimator of E[P&L] with exact analytic control means.

    Controls (all with KNOWN population means, so the estimator is unbiased regardless of fit):
      * terminal spot S_T           — mean S0*exp(drift*T) (exact for GBM and compensated Merton);
      * per-option-leg vanilla payoff max(S_T-K,0)/max(K-S_T,0) — analytic GBM mean (GBM only;
        omitted for Merton, whose payoff mean is a jump series, to keep the control mean exact).

    Optimal coefficients via OLS on the demeaned controls; the adjusted-mean variance is
    Var(P&L)*(1-R^2)/n. Deterministic given the (seeded) paths.
    """
    Y = np.asarray(pnl, dtype=np.float64)
    ST = np.asarray(final_prices, dtype=np.float64)
    n = Y.size
    S0, mu, sigma, T = config.initial_spot, config.drift, config.volatility, config.horizon_years

    cols: list[np.ndarray] = [ST]
    means: list[float] = [S0 * math.exp(mu * T)]
    names: list[str] = ["S_T"]
    if config.model == "GBM":
        seen: set[tuple[float, str]] = set()
        for leg in strategy.legs:
            if leg.option_type is None or leg.strike is None:
                continue
            key = (float(leg.strike), leg.option_type)
            if key in seen:
                continue
            seen.add(key)
            K = float(leg.strike)
            payoff = (np.maximum(ST - K, 0.0) if leg.option_type == "call"
                      else np.maximum(K - ST, 0.0))
            cols.append(payoff)
            means.append(_gbm_payoff_mean(S0, K, mu, sigma, T, leg.option_type))
            names.append(f"payoff_{leg.option_type}_{K:.0f}")

    C = np.column_stack(cols)
    mu_C = np.array(means, dtype=np.float64)
    plain_mean = float(np.mean(Y))
    plain_var = float(np.var(Y, ddof=1)) / n

    Cdm = C - C.mean(axis=0, keepdims=True)
    Ydm = Y - plain_mean
    # Guard against a degenerate (constant) control column.
    keep = np.std(Cdm, axis=0) > 1e-12
    if not np.any(keep):
        return ControlVariateEstimate(plain_mean, math.sqrt(plain_var), plain_mean,
                                      math.sqrt(plain_var), 0.0, [])
    Cdm_k = Cdm[:, keep]
    beta, *_ = np.linalg.lstsq(Cdm_k, Ydm, rcond=None)
    resid = Ydm - Cdm_k @ beta
    cv_mean = plain_mean - float(beta @ (C.mean(axis=0)[keep] - mu_C[keep]))
    cv_var = float(np.var(resid, ddof=1)) / n
    var_reduction = max(0.0, 1.0 - cv_var / plain_var) if plain_var > 0 else 0.0
    return ControlVariateEstimate(
        plain_mean=plain_mean, plain_se=math.sqrt(plain_var),
        cv_mean=cv_mean, cv_se=math.sqrt(cv_var), variance_reduction=var_reduction,
        controls=[nm for nm, k in zip(names, keep, strict=True) if k],
    )


def run_monte_carlo(
    strategy: Strategy,
    config: MonteCarloConfig,
) -> MonteCarloResult:
    """Run Monte Carlo simulation for a strategy.

    All paths populated. VaR/ES defined in loss space.
    ITM/touch probabilities computed for all option legs.
    """
    if config.model == "Merton":
        paths, final_prices = _simulate_merton(config)
    else:
        paths, final_prices = _simulate_gbm(config)

    n_paths = config.n_paths
    pnl_distribution = np.zeros(n_paths)
    for i in range(n_paths):
        pnl_distribution[i] = strategy_pnl(strategy, float(final_prices[i]))

    expected_pnl = float(np.mean(pnl_distribution))
    median_pnl = float(np.median(pnl_distribution))
    std_pnl = float(np.std(pnl_distribution))
    percentile_5 = float(np.percentile(pnl_distribution, 5))
    percentile_1 = float(np.percentile(pnl_distribution, 1))

    losses = -pnl_distribution
    var_es = _compute_var_es(losses, n_paths)

    prob_loss = float(np.mean(pnl_distribution < 0))

    itm_prob = 0.0
    touch_prob = 0.0
    option_legs = [leg for leg in strategy.legs if leg.option_type is not None]
    if option_legs:
        itm_counts = np.zeros(len(option_legs))
        touch_counts = np.zeros(len(option_legs))
        for idx_leg, leg in enumerate(option_legs):
            K = leg.strike or 0.0
            if leg.option_type == "call":
                itm_counts[idx_leg] = np.mean(final_prices > K)
                path_max = np.max(paths, axis=1)
                touch_counts[idx_leg] = np.mean(path_max > K)
            else:
                itm_counts[idx_leg] = np.mean(final_prices < K)
                path_min = np.min(paths, axis=1)
                touch_counts[idx_leg] = np.mean(path_min < K)
        itm_prob = float(np.max(itm_counts))
        touch_prob = float(np.max(touch_counts))

    sorted_pnl = np.sort(pnl_distribution)
    worst_paths = list(sorted_pnl[:10].astype(float))

    cv = control_variate_expected_pnl(pnl_distribution, final_prices, config, strategy)

    btc_held = sum(
        leg.quantity for leg in strategy.legs
        if leg.product == "spot" and leg.side == "LONG"
    )

    return MonteCarloResult(
        strategy_id=strategy.strategy_id,
        n_paths=n_paths,
        model=config.model,
        seed=config.seed,
        horizon_years=config.horizon_years,
        initial_spot=config.initial_spot,
        drift=config.drift,
        volatility=config.volatility,
        jump_params={"intensity": config.jump_intensity, "mean": config.jump_mean, "std": config.jump_std} if config.model == "Merton" else None,
        expected_pnl=expected_pnl,
        median_pnl=median_pnl,
        std_pnl=std_pnl,
        percentile_5=percentile_5,
        percentile_1=percentile_1,
        var_95=var_es["var_95"],
        var_99=var_es["var_99"],
        es_975=var_es["es_975"],
        es_99=var_es["es_99"],
        var_95_pnl=var_es["var_95_pnl"],
        var_99_pnl=var_es["var_99_pnl"],
        es_975_pnl=var_es["es_975_pnl"],
        es_99_pnl=var_es["es_99_pnl"],
        itm_probability=itm_prob,
        touch_probability=touch_prob,
        probability_of_loss=prob_loss,
        expected_premium_pct=0.0,
        expected_btc_inventory=btc_held,
        expected_cash_requirement=btc_held * config.initial_spot,
        pnl_distribution=pnl_distribution.tolist(),
        worst_paths=worst_paths,
        hedge_strategy="none",
        pending_decision_refs=["D-9"],
        provenance=Provenance.SIMULATED,
        expected_pnl_se=cv.plain_se,
        cv_expected_pnl=cv.cv_mean,
        cv_expected_pnl_se=cv.cv_se,
        cv_variance_reduction=cv.variance_reduction,
        cv_controls=cv.controls,
    )
