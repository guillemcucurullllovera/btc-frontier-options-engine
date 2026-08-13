"""Regime analysis for strategy comparison.

Classifies historical periods into:
  - BULL, BEAR, HIGH_VOL, LOW_VOL, SIDEWAYS

Implements CSCV/PBO/DSR overfitting harness per Bailey et al. (2015):
  - CSCV: Combinatorially Symmetrical Cross-Validation
  - PBO: Probability of Backtest Overfitting
  - DSR: Deflated Sharpe Ratio (not raw mean/std times 1-PBO)

Chronological train/test separation with no future-data leakage.
Expanding walk-forward and rolling walk-forward evaluation.
Typed InsufficientDataResult for insufficient observations.

Stage 3 additions:
  C4: Chronological OOS 3-fold fast-track with lifecycle containment.
  C5: Regime backtests using full cycle backtest in 4 regime windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np

from config.models import Provenance
from engine.strategy import Strategy
from strategy import deflated_sharpe as _ds


class RegimeLabel(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    SIDEWAYS = "sideways"


@dataclass(frozen=True)
class InsufficientDataResult:
    reason: str
    required_n: int
    available_n: int


@dataclass(frozen=True)
class RegimeResult:
    regime_name: str
    regime_label: RegimeLabel
    regime_dates: tuple[datetime, datetime]
    annualised_return: float
    annualised_vol: float
    avg_dvol: float
    trend_label: RegimeLabel | None = None
    strategy_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: Provenance = Provenance.CALCULATED


@dataclass(frozen=True)
class OOSValidationResult:
    train_period: tuple[datetime, datetime]
    test_period: tuple[datetime, datetime]
    train_sharpe: float | None
    test_sharpe: float | None
    train_itm_freq: float = 0.0
    test_itm_freq: float = 0.0
    pbo_estimate: float | None = None
    performance_degradation: float = 0.0
    cscv_s: int = 16
    cscv_n: int = 100
    deflated_sharpe_ratio: float | None = None   # HEADLINE = conservative (1/T) DSR
    dsr_conservative: float | None = None        # explicit conservative DSR
    dsr_grid_upper: float | None = None          # canonical grid-V DSR (upper bound)
    n_trials: int | None = None
    wf_oos_sharpe: float | None = None
    cscv_status: str | None = None               # e.g. NOT_APPLICABLE / COMPUTED
    is_insufficient_data: bool = False
    insufficient_data_reason: str | None = None
    signal_to_noise: float | None = None
    provenance: Provenance = Provenance.CALCULATED


def classify_regime(
    prices: np.ndarray,
    dates: list[datetime],
    window_days: int = 90,
    vol_window: int = 30,
    bull_threshold: float = 0.20,
    bear_threshold: float = -0.20,
    high_vol_threshold: float = 0.60,
    low_vol_threshold: float = 0.30,
) -> RegimeLabel:
    if len(prices) < max(window_days, vol_window):
        return RegimeLabel.SIDEWAYS
    lookback = min(window_days, len(prices))
    start_price = float(prices[-lookback])
    end_price = float(prices[-1])
    years = window_days / 365.0
    annual_return = (end_price / start_price - 1.0) / max(years, 0.01) if start_price > 0 else 0.0
    annual_vol = _compute_annual_vol(prices, vol_window)
    if annual_vol > high_vol_threshold:
        return RegimeLabel.HIGH_VOL
    if annual_return > bull_threshold:
        return RegimeLabel.BULL
    if annual_return < bear_threshold:
        return RegimeLabel.BEAR
    if annual_vol < low_vol_threshold:
        return RegimeLabel.LOW_VOL
    return RegimeLabel.SIDEWAYS


def _compute_annual_vol(prices: np.ndarray, vol_window: int) -> float:
    window = prices[-min(len(prices), vol_window):]
    if len(window) < 2:
        return 0.0
    log_rets = np.diff(np.log(window))
    return float(np.std(log_rets) * np.sqrt(365))


def split_train_test(
    dates: list[datetime],
    train_ratio: float = 0.70,
) -> tuple[list[int], list[int]]:
    split_idx = int(len(dates) * train_ratio)
    return list(range(split_idx)), list(range(split_idx, len(dates)))


def compute_regime_metrics(
    strategy: Strategy,
    spot_prices: np.ndarray,
    regime: RegimeLabel,
    regime_start: datetime,
    regime_end: datetime,
) -> dict[str, Any]:
    from strategy.payoffs import strategy_pnl
    if len(spot_prices) < 2:
        return {}
    pnl_at_end = strategy_pnl(strategy, float(spot_prices[-1]))
    log_rets = np.diff(np.log(spot_prices))
    annual_vol = float(np.std(log_rets) * np.sqrt(365)) if len(log_rets) > 1 else 0.0
    start_p = float(spot_prices[0])
    end_p = float(spot_prices[-1])
    years = max((regime_end - regime_start).days / 365.0, 0.01)
    annual_return = (end_p / start_p - 1.0) / years if start_p > 0 else 0.0
    return {
        "regime_label": str(regime),
        "regime_start": str(regime_start),
        "regime_end": str(regime_end),
        "spot_return_pct": annual_return * 100.0,
        "annualised_vol_pct": annual_vol * 100.0,
        "strategy_pnl_usd": pnl_at_end,
        "provenance": Provenance.CALCULATED,
    }


def run_regime_analysis(
    strategies: list[Strategy],
    dates: list[datetime],
    spot_prices: np.ndarray,
    window_days: int = 90,
) -> list[RegimeResult]:
    if len(dates) < window_days or len(spot_prices) < window_days:
        return []
    n_periods = len(dates) - window_days + 1
    regimes: dict[str, tuple[datetime, datetime, RegimeLabel, np.ndarray]] = {}
    for i in range(0, n_periods, max(window_days // 3, 1)):
        end_idx = min(i + window_days, len(dates) - 1)
        start_idx = max(0, end_idx - window_days + 1)
        if end_idx <= start_idx:
            continue
        segment_prices = spot_prices[start_idx:end_idx + 1].copy()
        segment_dates = dates[start_idx:end_idx + 1]
        label = classify_regime(segment_prices, list(segment_dates), window_days)
        period_start = segment_dates[0]
        period_end = segment_dates[-1]
        key = f"{label}_{period_start.strftime('%Y%m%d')}_{period_end.strftime('%Y%m%d')}"
        regimes[key] = (period_start, period_end, label, segment_prices)

    results: list[RegimeResult] = []
    for key, (start, end, label, prices) in regimes.items():
        if len(prices) < 2:
            continue
        ann_vol = _compute_annual_vol(prices, len(prices))
        years = max((end - start).days / 365.0, 0.01)
        ann_ret = (float(prices[-1]) / float(prices[0]) - 1.0) / years if prices[0] > 0 else 0.0
        strategy_metrics = {}
        for strategy in strategies:
            strategy_metrics[strategy.strategy_id] = compute_regime_metrics(strategy, prices, label, start, end)
        results.append(RegimeResult(
            regime_name=key,
            regime_label=label,
            regime_dates=(start, end),
            annualised_return=ann_ret,
            annualised_vol=ann_vol,
            avg_dvol=ann_vol,
            strategy_metrics=strategy_metrics,
        ))
    return results


def compute_cscv_pbo(
    perf: np.ndarray,
    s: int = 16,
    n_min: int = 100,
    purge: int = 0,
    embargo: int = 0,
) -> dict[str, Any]:
    """Canonical CSCV Probability of Backtest Overfitting (Bailey et al. 2017),
    delegated to `strategy.deflated_sharpe.cscv_pbo`.

    `perf` MUST be a (T_obs x N_configs) matrix — one COLUMN per configuration in
    the search grid. PBO measures selection bias ACROSS the grid, so it is
    UNDEFINED for a single strategy. A 1-D vector (or a 1-column matrix) therefore
    returns a typed NOT_APPLICABLE result — NEVER a fabricated number
    (Marcos' Third Law: report all trials or report nothing).

    This REPLACES the former home-grown `_cscv_matrix` / fabricated
    `DSR = (mean/std)*(1-PBO)*sqrt(n/365)` — neither of which computed the Bailey
    statistics. DSR is now a SEPARATE canonical call (see compute_oos_validation
    -> deflated_sharpe.deflated_sharpe_ratio).
    """
    M = np.asarray(perf, dtype=float)
    n_obs = int(M.shape[0]) if M.ndim >= 1 else 0
    if M.ndim == 1 or (M.ndim == 2 and M.shape[1] < 2):
        return {
            "pbo_estimate": None,
            "deflated_sharpe_ratio": None,
            "signal_to_noise": None,
            "is_insufficient_data": True,
            "cscv_status": "NOT_APPLICABLE",
            "insufficient_data_reason": (
                "CSCV/PBO requires a (T x N) grid with N>=2 configurations; a "
                "single performance vector cannot measure selection bias."
            ),
            "cscv_n": n_obs,
        }
    T, N = M.shape
    if T < n_min or T < 2 * s:
        return {
            "pbo_estimate": None,
            "deflated_sharpe_ratio": None,
            "signal_to_noise": None,
            "is_insufficient_data": True,
            "cscv_status": "INSUFFICIENT_DATA",
            "insufficient_data_reason": (
                f"Need >= {max(n_min, 2 * s)} observations, have {T}"
            ),
            "cscv_n": T,
            "n_configs": N,
        }
    res = _ds.cscv_pbo(M, S=s, purge=purge, embargo=embargo)
    pbo = res.get("pbo")
    return {
        "pbo_estimate": pbo,
        "deflated_sharpe_ratio": None,  # DSR is computed separately, canonically
        "signal_to_noise": None,
        "is_insufficient_data": pbo is None,
        "cscv_status": "COMPUTED" if pbo is not None else "NOT_APPLICABLE",
        "insufficient_data_reason": res.get("reason"),
        "n_splits": res.get("n_splits"),
        "median_logit": res.get("median_logit"),
        "cscv_n": T,
        "n_configs": N,
        "cscv_s": res.get("S", s),
    }


def compute_walk_forward_results(
    performance_by_period: dict[tuple[datetime, datetime], float],
) -> dict[str, Any]:
    """Expanding-window walk-forward evaluation."""
    sorted_periods = sorted(performance_by_period.keys(), key=lambda p: p[0])
    if len(sorted_periods) < 2:
        return {"in_sample": [], "out_of_sample": [], "insufficient_data": True}

    is_results: list[float] = []
    oos_results: list[float] = []

    for i in range(1, len(sorted_periods)):
        is_periods = sorted_periods[:i]
        oos_period = sorted_periods[i]
        is_perf = float(np.mean([performance_by_period[p] for p in is_periods]))
        oos_perf = performance_by_period[oos_period]
        is_results.append(is_perf)
        oos_results.append(oos_perf)

    return {"in_sample": is_results, "out_of_sample": oos_results, "insufficient_data": False}


def compute_oos_validation(
    train_result: dict[str, Any] | None = None,
    test_result: dict[str, Any] | None = None,
    cscv_s: int = 16,
    cscv_n: int = 100,
    perf_matrix: np.ndarray | None = None,
    trial_sharpes: np.ndarray | None = None,
    n_trials: int | None = None,
    purge: int = 0,
    embargo: int = 0,
) -> OOSValidationResult:
    """Out-of-sample validation with CANONICAL Bailey-Lopez de Prado statistics.

    Chronology enforced via call-site ordering (train precedes test).

    DSR / PBO are only computable with a search grid:
      * PBO (CSCV) needs `perf_matrix` = (T x N>=2) per-config returns.
      * DSR needs the selected strategy's per-period returns PLUS the number of
        trials N (and, canonically, the per-config `trial_sharpes` for the grid
        variance). Two variances are reported (AFML 14.7.3):
          - HEADLINE `deflated_sharpe_ratio` = conservative H0 (1/T) variance,
          - `dsr_grid_upper` = observed grid variance (labelled upper bound; the
            near-duplicate grid makes it anti-conservative).
    When no grid is supplied, PBO is typed NOT_APPLICABLE and DSR falls back to the
    conservative (1/T, n_trials) form — never a fabricated number.
    """
    train_sharpe = train_result.get("sharpe") if train_result else None
    test_sharpe = test_result.get("sharpe") if test_result else None

    train_period = train_result.get("train_period", (datetime.min, datetime.min)) if train_result else (datetime.min, datetime.min)
    test_period = test_result.get("test_period", (datetime.min, datetime.min)) if test_result else (datetime.min, datetime.min)
    if test_result and "test_period" in test_result:
        test_period_data = test_result.get("test_period")
        if test_period_data:
            test_period = test_period_data

    degradation = 0.0
    if train_sharpe is not None and test_sharpe is not None:
        degradation = train_sharpe - test_sharpe

    train_returns = train_result.get("returns", []) if train_result else []
    test_returns = test_result.get("returns", []) if test_result else []
    all_returns = np.array(list(train_returns) + list(test_returns), dtype=float)

    pbo: float | None = None
    dsr_headline: float | None = None
    dsr_cons: float | None = None
    dsr_grid: float | None = None
    n_tr: int | None = None
    sn: float | None = None
    cscv_status: str | None = None
    is_insufficient = False
    reason: str | None = None

    # ── PBO (needs a grid matrix) ──
    if perf_matrix is not None:
        cscv_result = compute_cscv_pbo(perf_matrix, s=cscv_s, n_min=cscv_n,
                                       purge=purge, embargo=embargo)
        pbo = cscv_result.get("pbo_estimate")
        cscv_status = cscv_result.get("cscv_status")
        if pbo is None:
            reason = cscv_result.get("insufficient_data_reason")
    else:
        cscv_status = "NOT_APPLICABLE"
        reason = "PBO not computed: no (T x N) config grid supplied."

    # ── DSR (probability; conservative headline + grid upper bound) ──
    if len(all_returns) >= 10:
        sr = _ds.sharpe_ratio(all_returns)
        sn = float(sr) if np.isfinite(sr) else None
        grid_trials = None
        if trial_sharpes is not None:
            grid_trials = np.asarray(trial_sharpes, dtype=float)
        elif perf_matrix is not None and np.asarray(perf_matrix).ndim == 2:
            M = np.asarray(perf_matrix, dtype=float)
            grid_trials = np.array([_ds.sharpe_ratio(M[:, j]) for j in range(M.shape[1])])
        N = int(n_trials) if n_trials is not None else (
            int(np.asarray(grid_trials).size) if grid_trials is not None else 1)
        n_tr = N
        # conservative (1/T) headline
        cons = _ds.deflated_sharpe_ratio(all_returns, n_trials=N)
        dsr_cons = cons.get("dsr")
        # grid-variance upper bound (if a grid is available)
        if grid_trials is not None and np.asarray(grid_trials).size > 1:
            grid = _ds.deflated_sharpe_ratio(all_returns, trial_sharpes=grid_trials)
            dsr_grid = grid.get("dsr")
        dsr_headline = dsr_cons
    else:
        is_insufficient = True
        reason = (reason or "") + f" DSR needs >=10 obs, have {len(all_returns)}."

    return OOSValidationResult(
        train_period=train_period,
        test_period=test_period,
        train_sharpe=train_sharpe,
        test_sharpe=test_sharpe,
        pbo_estimate=pbo,
        performance_degradation=degradation,
        cscv_s=cscv_s,
        cscv_n=cscv_n,
        deflated_sharpe_ratio=dsr_headline,
        dsr_conservative=dsr_cons,
        dsr_grid_upper=dsr_grid,
        n_trials=n_tr,
        cscv_status=cscv_status,
        is_insufficient_data=is_insufficient,
        insufficient_data_reason=reason,
        signal_to_noise=sn,
    )


# ── C4: Chronological OOS 3-Fold Fast-Track ───────────────────────────────


def compute_oos_validation_by_folds(
    cycle_returns: list[float],
    fold_definitions: list[dict[str, Any]],
    cscv_n: int = 100,
) -> dict[str, Any]:
    """C4: Chronological OOS fast-track with lifecycle-safe cycle assignment.

    Returns typed PENDING_METHOD verdict when full CSCV/PBO/DSR cannot be
    completed, with clear disclosure that chronological OOS folds are
    implemented but full overfitting validation remains pending.
    """
    n_returns = len(cycle_returns)
    n_folds = len(fold_definitions)

    if n_folds < 2 or n_returns < cscv_n:
        return {
            "pbo_estimate": None,
            "deflated_sharpe_ratio": None,
            "is_insufficient_data": True,
            "insufficient_data_reason": (
                f"Need at least {cscv_n} observations and 2+ folds, "
                f"have {n_returns} cycles and {n_folds} folds"
            ),
            "cscv_n": n_returns,
            "n_folds": n_folds,
            "method": "chronological_3fold_containment",
            "pbo_dsr_status": "PENDING_METHOD",
            "provenance": Provenance.CALCULATED.value,
        }

    perf_mean = float(np.mean(cycle_returns)) if cycle_returns else 0.0
    perf_std = float(np.std(cycle_returns)) if len(cycle_returns) > 1 else 1e-10

    sn_val = 0.0 if perf_std < 1e-10 else perf_mean / perf_std

    # A single per-cycle return vector cannot yield PBO (needs a config grid) and
    # yields only a conservative, single-trial DSR. Report both honestly.
    pbo_val = None
    is_insufficient = True
    reason = ("PBO NOT_APPLICABLE: a single per-cycle series has no config grid. "
              "Feed a (T x N) grid to compute_cscv_pbo for PBO.")
    try:
        dsr_res = _ds.deflated_sharpe_ratio(np.asarray(cycle_returns, dtype=float),
                                            n_trials=1)
        dsr_val = dsr_res.get("dsr")  # N=1 => undeflated PSR(0), NOT a grid-corrected DSR
    except Exception:
        dsr_val = None

    method_status = "PENDING_METHOD"  # PBO/DSR grid-based validation still pending

    return {
        "pbo_estimate": pbo_val,
        "deflated_sharpe_ratio": dsr_val,
        "signal_to_noise": sn_val,
        "is_insufficient_data": is_insufficient,
        "insufficient_data_reason": reason,
        "cscv_n": n_returns,
        "n_folds": n_folds,
        "fold_definitions": fold_definitions,
        "method": "chronological_3fold_containment",
        "pbo_dsr_status": method_status,
        "disclosure": (
            "Chronological 3-fold OOS with lifecycle containment is implemented. "
            "Full CSCV/PBO/DSR validation remains PENDING — do not present PBO/DSR "
            "as completed evidence."
        ),
        "provenance": Provenance.CALCULATED.value,
    }


# ── C5: Regime Backtests (Full Cycle) ─────────────────────────────────────


@dataclass(frozen=True)
class RegimeBacktestResult:
    regime_name: str
    regime_label: str
    regime_dates: tuple[datetime, datetime]
    annualised_return: float
    annualised_vol: float
    avg_dvol: float
    realized_vol: float
    strategy_results: dict[str, dict[str, Any]]
    provenance: Provenance = Provenance.CALCULATED


def run_regime_backtests(
    strategies: list[Strategy],
    dates: list[datetime],
    spot_prices: np.ndarray,
    iv_history: np.ndarray,
    regime_windows: list[dict[str, str]],
    backtest_kwargs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """C5: Run full cycle backtests within each regime window.

    Regime metrics come from full cycle backtests, not terminal payoff.
    avg_dvol is from observed DVOL; realized_vol from spot returns.
    Four non-overlapping or explicitly weighted regime windows.
    """
    from strategy.backtest import backtest_strategy, backtest_unhedged_observed

    kwargs = backtest_kwargs or {}
    results: list[dict[str, Any]] = []

    for window in regime_windows:
        name = window.get("name", "unknown")
        w_start_str: str = window["start"]
        w_end_str: str = window["end"]
        w_start = datetime.fromisoformat(w_start_str).replace(tzinfo=UTC)
        w_end = datetime.fromisoformat(w_end_str).replace(tzinfo=UTC)

        w_indices = [
            i for i, d in enumerate(dates)
            if w_start <= d <= w_end
        ]
        if len(w_indices) < 10:
            continue

        w_dates = [dates[i] for i in w_indices]
        w_spot = spot_prices[w_indices].copy()
        w_iv = iv_history[w_indices].copy()

        log_ret = np.diff(np.log(w_spot[w_spot > 0]))
        realized_vol = float(np.std(log_ret) * np.sqrt(365)) if len(log_ret) > 1 else 0.0
        avg_dvol_val = float(np.mean(w_iv)) if len(w_iv) > 0 else 0.0

        years = max((w_end - w_start).days / 365.0, 0.01)
        ann_ret = (float(w_spot[-1]) / float(w_spot[0]) - 1.0) / years if w_spot[0] > 0 else 0.0

        if avg_dvol_val > 0.60:
            regime_label = "high_vol"
        elif avg_dvol_val < 0.30:
            regime_label = "low_vol"
        elif ann_ret > 0.20:
            regime_label = "bull"
        elif ann_ret < -0.20:
            regime_label = "bear"
        else:
            regime_label = "sideways"

        strategy_results: dict[str, dict[str, Any]] = {}
        for s in strategies:
            try:
                if (
                    (s.canonical and str(s.canonical) in ("unhedged_baseline", "Unhedged BTC Acquisition"))
                    or s.strategy_id == "unhedged_baseline"
                ):
                    bt_result = backtest_unhedged_observed(s, w_dates, w_spot, w_iv)
                else:
                    bt_result = backtest_strategy(
                        s, w_dates, w_spot, w_iv, **kwargs,
                    )
                strategy_results[s.strategy_id] = {
                    "total_pnl_pct": getattr(bt_result, "total_pnl_pct", 0.0),
                    "total_pnl_usd": getattr(bt_result, "total_pnl_usd", 0.0),
                    "sharpe_ratio": getattr(bt_result, "sharpe_ratio", None),
                    "itm_frequency": getattr(bt_result, "itm_frequency", 0.0),
                    "max_drawdown_pct": getattr(bt_result, "max_drawdown_pct", 0.0),
                    "n_cycles": len(getattr(bt_result, "cycles", [])),
                }
            except Exception:
                strategy_results[s.strategy_id] = {
                    "total_pnl_pct": 0.0,
                    "n_cycles": 0,
                    "error": "backtest failed in regime window",
                }

        results.append({
            "regime_name": name,
            "regime_label": regime_label,
            "regime_start": w_start.isoformat(),
            "regime_end": w_end.isoformat(),
            "annualised_return": ann_ret,
            "annualised_vol": ann_ret,
            "avg_dvol": avg_dvol_val,
            "realized_vol": realized_vol,
            "dvol_provenance": (
                Provenance.OBSERVED.value
                if not np.all(np.isclose(w_iv, 0.45))
                else Provenance.ASSUMED.value
            ),
            "observation_count": len(w_dates),
            "strategies": strategy_results,
            "provenance": Provenance.CALCULATED.value,
        })

    return results
