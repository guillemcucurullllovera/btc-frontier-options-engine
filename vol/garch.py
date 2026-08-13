"""GARCH(1,1) realised-volatility model with diagnostics.

Uses the `arch` package for model estimation.
Provides:
  - GarchEstimator: fit GARCH(1,1) to daily log returns.
  - GarchDiagnostics: Ljung-Box, ARCH-LM, parameter stability checks.
  - Realised-vol forecast vs DVOL comparison.
  - Strict separation of model_reconstructed vs observed volatility.

Per AGENTS.md and authoritative_corrections.md §5:
  - DVOL is an observed index (30-day constant-maturity implied vol).
  - GARCH forecasts are model_reconstructed and labelled as such.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import numpy.typing as npt

from config.models import Provenance

# Optional diagnostics (statsmodels)
try:
    from statsmodels.stats.diagnostic import (  # type: ignore[import-untyped]
        acorr_ljungbox,
        het_arch,
    )
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False


class GarchError(Exception):
    """GARCH model estimation or diagnostic failure."""


@dataclass(frozen=True)
class GarchParams:
    omega: float
    alpha: float
    beta: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def unconditional_variance(self) -> float:
        if self.persistence >= 1.0:
            return float("inf")
        return self.omega / (1.0 - self.persistence)

    @property
    def unconditional_vol(self) -> float:
        uv = self.unconditional_variance
        if uv == float("inf"):
            return float("inf")
        return float(np.sqrt(uv))


@dataclass(frozen=True)
class GarchResult:
    """Complete GARCH(1,1) estimation result."""

    params: GarchParams
    conditional_variances: list[float]
    residuals: list[float]  # Standardised residuals
    log_likelihood: float
    aic: float
    bic: float
    n_obs: int
    convergence: bool
    fit_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    provenance: Provenance = Provenance.MODEL_RECONSTRUCTED
    origin: str = "garch_model"

    # Annualised forecast (decimal, e.g. 0.45 = 45%)
    forecast_vol: float = 0.0

    # C9 · M0.3: MLE standard errors on {omega, alpha, beta} (returns-scale units, unscaled
    # back to decimal-variance). Two covariance estimators (SR 11-7 parameter uncertainty):
    #   * sandwich  — robust (Bollerslev-Wooldridge) H^-1 J H^-1, valid under misspecification;
    #   * fisher    — classical inverse observed-information (H^-1), tighter if correctly specified.
    param_std_errors: dict[str, float] = field(default_factory=dict)         # sandwich/robust
    param_std_errors_fisher: dict[str, float] = field(default_factory=dict)  # classical


@dataclass(frozen=True)
class GarchDiagnostics:
    """Diagnostic tests for a fitted GARCH model."""

    ljung_box_stat: float | None  # Test statistic
    ljung_box_pvalue: float | None  # p-value (H0: no autocorrelation)
    ljung_box_lags: int
    arch_lm_stat: float | None
    arch_lm_pvalue: float | None
    arch_lm_lags: int
    parameter_stable: bool | None  # None = not checked
    warnings: list[str] = field(default_factory=list)

    @property
    def passes_ljung_box(self, alpha: float = 0.05) -> bool:
        if self.ljung_box_pvalue is None:
            return True
        return self.ljung_box_pvalue > alpha

    @property
    def passes_arch_lm(self, alpha: float = 0.05) -> bool:
        if self.arch_lm_pvalue is None:
            return True
        return self.arch_lm_pvalue > alpha


@dataclass(frozen=True)
class VolForecast:
    """Volatility forecast comparison between model and market."""

    garch_forecast: float  # Annualised GARCH forecast (decimal)
    dvol_latest: float | None  # Latest DVOL index (decimal)
    forecast_timestamp: datetime
    provenance: Provenance = Provenance.MODEL_RECONSTRUCTED
    origin: str = "garch_model"
    spread: float | None = None  # garch - dvol (decimal)
    spread_bp: float | None = None  # spread in vol points (garch - dvol) * 100


class GarchEstimator:
    """GARCH(1,1) estimator for daily log returns.

    Args:
        returns: Daily log returns as a numpy array.
        dist: Error distribution ('normal' or 't').
    """

    def __init__(
        self,
        returns: npt.NDArray[np.float64] | list[float],
        dist: str = "normal",
    ) -> None:
        self._returns = np.asarray(returns, dtype=np.float64)
        self._dist = dist

    def fit(self) -> GarchResult:
        """Estimate GARCH(1,1) parameters via MLE.

        Returns:
            GarchResult with parameters, conditional variances, diagnostics.
        """
        from arch import arch_model
        n = len(self._returns)
        if n < 10:
            raise GarchError(f"Need at least 10 observations; got {n}")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _dist: str = self._dist
            am = arch_model(self._returns * 100.0, vol="GARCH", p=1, q=1, dist=_dist)  # type: ignore[arg-type]
            res = am.fit(disp="off", show_warning=False)
            # Second fit only re-estimates the covariance (params identical) for the
            # classical Fisher SE alongside the default robust sandwich SE.
            res_fisher = am.fit(disp="off", show_warning=False, cov_type="classic")

        omega = float(res.params["omega"]) / 10000.0
        alpha = float(res.params.get("alpha[1]", 0.0))
        beta = float(res.params.get("beta[1]", 0.0))
        se_sandwich = _unscale_std_errors(res.std_err)
        se_fisher = _unscale_std_errors(res_fisher.std_err)

        cond_var = (np.asarray(res.conditional_volatility, dtype=np.float64) / 100.0) ** 2
        std_resid = list(np.asarray(res.resid, dtype=np.float64) / (np.asarray(res.conditional_volatility, dtype=np.float64) + 1e-12))

        # T0-1: annualise with sqrt(365) for the 24/7 BTC market, consistent with
        # vol/realised.py and the engine 365-day convention (Sinclair Ch.2). The
        # earlier sqrt(252) introduced a ~20% GARCH-vs-DVOL/realised inconsistency.
        forecast_vol_annualised = float(np.sqrt(np.mean(cond_var)) * np.sqrt(365))

        log_likelihood_val = getattr(res, "log_likelihood", getattr(res, "loglikelihood", 0.0))
        return GarchResult(
            params=GarchParams(omega=omega, alpha=alpha, beta=beta),
            conditional_variances=list(cond_var),
            residuals=std_resid,
            log_likelihood=float(log_likelihood_val),
            aic=float(res.aic),
            bic=float(res.bic),
            n_obs=n,
            convergence=bool(res.convergence_flag == 0),
            forecast_vol=forecast_vol_annualised,
            param_std_errors=se_sandwich,
            param_std_errors_fisher=se_fisher,
        )


def _unscale_std_errors(std_err: object) -> dict[str, float]:
    """Map arch (x100-returns-scale) SEs back to decimal-variance units for {omega,alpha,beta}.

    Returns scaled by 100 => variance scaled by 1e4 (omega SE /1e4). alpha/beta are
    scale-invariant. Missing params are omitted. ``std_err`` is a pandas Series.
    """
    def _get(name: str) -> float | None:
        try:
            val = std_err[name]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return None
        return float(val) if val is not None else None

    out: dict[str, float] = {}
    om = _get("omega")
    if om is not None:
        out["omega"] = om / 10000.0
    for scaled_name, key in (("alpha[1]", "alpha"), ("beta[1]", "beta")):
        v = _get(scaled_name)
        if v is not None:
            out[key] = v
    return out


def compute_diagnostics(
    result: GarchResult,
    lags: int = 10,
) -> GarchDiagnostics:
    """Run standard diagnostic tests on a fitted GARCH model.

    Args:
        result: Fitted GARCH result.
        lags: Number of lags for Ljung-Box and ARCH-LM tests.

    Returns:
        GarchDiagnostics with test statistics and p-values.
    """
    warnings_list: list[str] = []
    alpha = result.params.alpha
    beta = result.params.beta

    if alpha + beta >= 0.999:
        warnings_list.append(f"Near-unit-root: alpha+beta={alpha + beta:.4f} >= 0.999")

    resid = np.asarray(result.residuals, dtype=np.float64)

    lb_stat: float | None = None
    lb_pval: float | None = None
    arch_stat: float | None = None
    arch_pval: float | None = None

    if HAS_STATSMODELS and len(resid) > lags + 5:
        try:
            lb_result = acorr_ljungbox(resid, lags=[lags], return_df=False)
            if lb_result and len(lb_result) > 0:
                lb_stat = float(lb_result[0].get("lb_stat", lb_result[0].get("stat", None)))
                lb_pval = float(lb_result[0].get("lb_pvalue", lb_result[0].get("pvalue", None)))
        except Exception:
            pass

        try:
            arch_result = het_arch(resid, nlags=lags)
            arch_stat = float(arch_result[0])
            arch_pval = float(arch_result[1])
        except Exception:
            pass

    if lb_pval is not None and lb_pval < 0.05:
        warnings_list.append(
            f"Ljung-Box p={lb_pval:.4f} < 0.05 at lag {lags}: residual autocorrelation detected"
        )
    if arch_pval is not None and arch_pval < 0.05:
        warnings_list.append(
            f"ARCH-LM p={arch_pval:.4f} < 0.05 at lag {lags}: remaining ARCH effects"
        )

    return GarchDiagnostics(
        ljung_box_stat=lb_stat,
        ljung_box_pvalue=lb_pval,
        ljung_box_lags=lags,
        arch_lm_stat=arch_stat,
        arch_lm_pvalue=arch_pval,
        arch_lm_lags=lags,
        parameter_stable=alpha + beta < 0.999,
        warnings=warnings_list,
    )


def forward_forecast_vol(
    result: GarchResult, last_return: float, horizon_days: int, annualise: bool = True,
) -> float:
    """GARCH(1,1) conditional FORWARD-forecast vol averaged over the option horizon (C9 · M5.4).

    Unlike ``GarchResult.forecast_vol`` (the in-sample average conditional vol, ~unconditional), this
    is a genuine forward forecast that mean-reverts from the CURRENT conditional variance toward the
    unconditional level over the horizon:
        E[sig^2_{t+h}] = uncond + persistence^{h-1} (sig^2_{t+1} - uncond),
    averaged over h = 1..H. This is the CENTRAL scenario vol for M5.4 (replacing the 2-year
    unconditional). Returns annualised (sqrt(365)) vol by default.
    """
    p = result.params
    uncond = p.unconditional_variance
    last_cv = result.conditional_variances[-1] if result.conditional_variances else uncond
    sig2_next = p.omega + p.alpha * last_return * last_return + p.beta * last_cv
    persist = p.persistence
    avg_var = float(np.mean([
        uncond + persist ** (h - 1) * (sig2_next - uncond) for h in range(1, max(horizon_days, 1) + 1)
    ]))
    avg_var = max(avg_var, 1e-12)
    return float(np.sqrt(avg_var) * np.sqrt(365.0)) if annualise else float(np.sqrt(avg_var))


def compute_forecast(
    result: GarchResult,
    dvol: float | None = None,
) -> VolForecast:
    """Create a VolForecast comparing GARCH forecast with DVOL.

    Args:
        result: Fitted GARCH result.
        dvol: Latest DVOL index value (decimal, e.g. 0.45 = 45%).

    Returns:
        VolForecast with GARCH forecast, DVOL (if provided), and spread.
    """
    fv = result.forecast_vol
    spread = (fv - dvol) if dvol is not None else None
    spread_bp = spread * 100.0 if spread is not None else None
    return VolForecast(
        garch_forecast=fv,
        dvol_latest=dvol,
        forecast_timestamp=result.fit_timestamp,
        spread=spread,
        spread_bp=spread_bp,
    )
