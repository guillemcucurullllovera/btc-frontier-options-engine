"""Multi-cycle Monte Carlo simulation for strategy analysis (C7 / WP-C7 / FRF-021).

Implements the Stage-3 C7 requirement: a multi-cycle MC consistent with the
repaired lifecycle (re-strike at every cycle), GBM and Merton (jump-diffusion)
kept completely separate, deterministic seeds persisted, all assumptions
persisted. All outputs are labelled SIMULATED — no observed evidence is claimed.

Design (see /home/francisco/btc/c7_state_audit.md):

- **Vectorised over paths**, small explicit loop over cycles. Because every cycle
  re-strikes at ``entry_spot * (1 ± strike_target_pct)`` and Black-Scholes ``price``
  is homogeneous degree 1 in (spot, strike), the per-unit premium each cycle equals
  ``entry_spot * price(1.0, 1 ± p, r, sigma, T)`` — a single scalar computed once.
  No per-path option pricing; no per-path Python loop.
- **Bounded memory**: paths are generated in fixed-size chunks; only per-path
  *scalar* outputs (pnl, final value, btc, premium, fees, eac) are retained, never
  the full ``(n_paths, n_steps+1)`` matrix.
- **Deterministic, chunk-independent, resumable RNG**: each chunk draws from an
  independent substream ``SeedSequence([seed, chunk_index]).spawn(...)``. Same
  (seed, config) → identical results; a resumed run recomputes from the last
  completed chunk → identical; chunked vs unchunked agree within MC tolerance
  (chunk_size participates in the substream derivation — documented).
- **Correct settlement**: options settle in **cash** (the OTC-USD venue the mandate
  strategy builders use); no fictitious physical BTC delivery (authoritative_
  corrections.md §1), so BTC inventory persists across cycles. The D-12
  ``post_purchase`` interpretation funds a discretionary BTC buy with separately-
  tracked ``extra_capital`` (no double-debit, no hidden leverage).
- **Independent scalar reference** (``_run_multi_cycle_path``) mirrors the vectorised
  economics for one path and is used as the test oracle.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from config.models import Provenance
from engine.errors import ValidationError
from engine.strategy import Strategy
from pricing.black_scholes import price as bs_price

ROUND = 8

_pending_d1 = "D-1"
_pending_d9 = "D-9"
_pending_d12 = "D-12"

# Default chunk size: bounds peak memory of the transient path matrix
# (chunk x (n_steps+1) floats) and defines the RNG substream partition.
DEFAULT_CHUNK_SIZE = 50_000

FeeBase = Literal["reference_notional", "executed_volume"]
D12Interp = Literal["cash_settled", "post_purchase"]
ModelName = Literal["GBM", "Merton"]


@dataclass(frozen=True)
class MultiCycleMCConfig:
    n_paths: int = 10_000
    n_cycles: int = 12
    cycle_length_years: float = 30.0 / 365.0
    initial_spot: float = 65_000.0
    drift: float = 0.10
    volatility: float = 0.45
    risk_free_rate: float = 0.04
    model: ModelName = "GBM"
    seed: int = 42
    use_antithetic: bool = True
    jump_intensity: float = 2.0
    jump_mean: float = -0.05
    jump_std: float = 0.10
    n_steps_per_cycle: int = 30

    strike_target_pct: float = 0.15
    btc_quantity: float = 30_000.0
    d1_fee_base: FeeBase = "reference_notional"
    execution_fee_pct: float = 0.005
    seller_discount_pct: float = 0.025
    d12_interpretation: D12Interp = "cash_settled"

    capital_base: float = 1_950_000_000.0

    # Processing / memory controls (do NOT change the economic model).
    chunk_size: int = DEFAULT_CHUNK_SIZE
    # Retain full per-path distributions in the result (needed for exact
    # percentiles on small runs / tests). Large campaign runs set this False;
    # percentiles are still computed from the retained scalar arrays during the
    # run, only the *result object* omits the multi-million-element lists.
    store_paths: bool = True

    def __post_init__(self) -> None:
        if self.initial_spot <= 0:
            raise ValidationError(f"initial_spot must be positive, got {self.initial_spot}")
        if self.volatility < 0:
            raise ValidationError(f"volatility must be non-negative, got {self.volatility}")
        if self.n_paths <= 0:
            raise ValidationError(f"n_paths must be positive, got {self.n_paths}")
        if self.n_cycles <= 0:
            raise ValidationError(f"n_cycles must be positive, got {self.n_cycles}")
        if self.n_steps_per_cycle <= 0:
            raise ValidationError(
                f"n_steps_per_cycle must be positive, got {self.n_steps_per_cycle}"
            )
        if self.cycle_length_years <= 0:
            raise ValidationError(
                f"cycle_length_years must be positive, got {self.cycle_length_years}"
            )
        if self.drift < -1.0 or self.drift > 5.0:
            raise ValidationError(f"drift {self.drift} outside plausible range")
        if not 0.0 < self.strike_target_pct < 1.0:
            raise ValidationError(
                f"strike_target_pct must be in (0, 1), got {self.strike_target_pct}"
            )
        if self.btc_quantity <= 0:
            raise ValidationError(f"btc_quantity must be positive, got {self.btc_quantity}")
        if self.capital_base <= 0:
            raise ValidationError(f"capital_base must be positive, got {self.capital_base}")
        if self.execution_fee_pct < 0:
            raise ValidationError(
                f"execution_fee_pct must be non-negative, got {self.execution_fee_pct}"
            )
        if not 0.0 <= self.seller_discount_pct < 1.0:
            raise ValidationError(
                f"seller_discount_pct must be in [0, 1), got {self.seller_discount_pct}"
            )
        if self.jump_intensity < 0:
            raise ValidationError(
                f"jump_intensity must be non-negative, got {self.jump_intensity}"
            )
        if self.jump_std < 0:
            raise ValidationError(f"jump_std must be non-negative, got {self.jump_std}")
        if self.chunk_size <= 0:
            raise ValidationError(f"chunk_size must be positive, got {self.chunk_size}")
        if self.model not in ("GBM", "Merton"):
            raise ValidationError(f"model must be 'GBM' or 'Merton', got {self.model!r}")

    @property
    def total_horizon_years(self) -> float:
        return self.n_cycles * self.cycle_length_years

    @property
    def total_steps(self) -> int:
        return self.n_cycles * self.n_steps_per_cycle

    @property
    def reference_notional(self) -> float:
        return self.btc_quantity * self.initial_spot

    @property
    def executed_notional(self) -> float:
        return self.reference_notional * (1.0 - self.seller_discount_pct)

    @property
    def asym_fee_usd(self) -> float:
        if self.d1_fee_base == "reference_notional":
            return self.execution_fee_pct * self.reference_notional
        return self.execution_fee_pct * self.executed_notional

    def assumptions_dict(self) -> dict[str, Any]:
        return {
            "drift": self.drift,
            "volatility": self.volatility,
            "risk_free_rate": self.risk_free_rate,
            "model": self.model,
            "jump_intensity": self.jump_intensity,
            "jump_mean": self.jump_mean,
            "jump_std": self.jump_std,
            "cycle_length_years": self.cycle_length_years,
            "n_steps_per_cycle": self.n_steps_per_cycle,
            "n_cycles": self.n_cycles,
            "n_paths": self.n_paths,
            "seed": self.seed,
            "use_antithetic": self.use_antithetic,
            "chunk_size": self.chunk_size,
            "strike_target_pct": self.strike_target_pct,
            "btc_quantity": self.btc_quantity,
            "initial_spot": self.initial_spot,
            "capital_base": self.capital_base,
            "d1_fee_base": self.d1_fee_base,
            "execution_fee_pct": self.execution_fee_pct,
            "seller_discount_pct": self.seller_discount_pct,
            "d12_interpretation": self.d12_interpretation,
            "convenience_yield_q": 0.0,  # ASSUMED (MS-11): BS with q=0.
            "provenance": "SIMULATED",
        }

    def fingerprint(self) -> str:
        """Stable hash of the economically-relevant configuration (for checkpoints)."""
        payload = json.dumps(self.assumptions_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class MultiCycleMCResult:
    strategy_id: str
    strategy_kind: str
    business_label: str
    n_paths: int
    n_cycles: int
    model: str
    seed: int
    total_horizon_years: float
    initial_spot: float
    drift: float
    volatility: float
    risk_free_rate: float
    jump_params: dict[str, float] | None = None
    d1_fee_base: str = "reference_notional"
    d12_interpretation: str = "cash_settled"

    mean_outcome_usd: float = 0.0
    median_outcome_usd: float = 0.0
    std_outcome_usd: float = 0.0
    percentile_5_usd: float = 0.0
    percentile_1_usd: float = 0.0

    mean_outcome_pct_capital: float = 0.0
    median_outcome_pct_capital: float = 0.0
    std_outcome_pct_capital: float = 0.0
    percentile_5_pct_capital: float = 0.0
    percentile_1_pct_capital: float = 0.0

    expected_shortfall_95: float = 0.0
    expected_shortfall_99: float = 0.0

    probability_of_loss: float = 0.0
    probability_of_exceeding_seller_discount: float = 0.0

    mean_eac_usd_per_btc: float = 0.0
    eac_distribution_5: float = 0.0
    eac_distribution_95: float = 0.0

    max_loss_usd: float = 0.0
    max_loss_pct_capital: float = 0.0

    ci_95_mean_lower: float = 0.0
    ci_95_mean_upper: float = 0.0
    mc_standard_error: float = 0.0

    mean_final_btc: float = 0.0
    mean_total_premium_pct: float = 0.0
    mean_total_fees_usd: float = 0.0

    total_asym_fee_usd: float = 0.0

    # D-12 post-purchase discretionary acquisition (separately accounted; 0 for
    # cash_settled and for non-put strategies).
    mean_post_purchase_usd_deployed: float = 0.0
    mean_post_purchase_btc_acquired: float = 0.0

    pnl_distribution: list[float] = field(default_factory=list)
    eac_distribution: list[float] = field(default_factory=list)

    provenance: Provenance = Provenance.SIMULATED
    pending_decision_refs: list[str] = field(default_factory=list)

    assumptions: dict[str, Any] = field(default_factory=dict)


# ── unit premiums (computed once; homogeneity of Black-Scholes) ────────────────


def _unit_premiums(config: MultiCycleMCConfig) -> tuple[float, float]:
    """Per-unit (spot-normalised) call and put premia for a strike ``1 ± p``.

    ``bs_price(S, S*(1±p), r, sigma, T) == S * bs_price(1.0, 1±p, r, sigma, T)``
    by degree-1 homogeneity, so the per-cycle premium is ``entry_spot * unit``.
    """
    T = config.cycle_length_years
    r = config.risk_free_rate
    s = config.volatility
    p = config.strike_target_pct
    call_u = bs_price(1.0, 1.0 + p, r, s, T, "call")
    put_u = bs_price(1.0, 1.0 - p, r, s, T, "put")
    return call_u, put_u


# ── path generation (chunked, vectorised, deterministic per chunk) ─────────────


def _chunk_children(seed: int, chunk_index: int, model: ModelName) -> dict[str, np.random.Generator]:
    """Independent RNG substreams for one chunk, keyed by (seed, chunk_index).

    Same seed+chunk_index → identical streams (reproducible + resumable). GBM and
    Merton share the diffusion stream (common random numbers); Merton adds two jump
    streams. Streams are drawn as whole-chunk blocks so a chunk is self-contained.
    """
    ss = np.random.SeedSequence([int(seed), int(chunk_index)])
    if model == "Merton":
        diff, jc, jz = ss.spawn(3)
        return {
            "diff": np.random.default_rng(diff),
            "jcount": np.random.default_rng(jc),
            "jsize": np.random.default_rng(jz),
        }
    (diff,) = ss.spawn(1)
    return {"diff": np.random.default_rng(diff)}


def _diffusion_normals(gen: np.random.Generator, m: int, n_steps: int, antithetic: bool) -> np.ndarray:
    """(m, n_steps) standard normals; even rows primary, odd rows their negation."""
    if not antithetic:
        return gen.standard_normal((m, n_steps))
    n_prim = (m + 1) // 2
    zp = gen.standard_normal((n_prim, n_steps))
    z = np.empty((m, n_steps), dtype=np.float64)
    z[0::2] = zp
    n_partner = m // 2
    if n_partner:
        z[1::2] = -zp[:n_partner]
    return z


def _generate_chunk_paths(
    config: MultiCycleMCConfig, chunk_index: int, m: int
) -> np.ndarray:
    """Fine-grained spot paths for ``m`` paths of one chunk: shape (m, total_steps+1)."""
    n_steps = config.total_steps
    dt = config.cycle_length_years / config.n_steps_per_cycle
    sqdt = math.sqrt(dt)
    mu = config.drift
    sigma = config.volatility
    S0 = config.initial_spot
    children = _chunk_children(config.seed, chunk_index, config.model)

    z = _diffusion_normals(children["diff"], m, n_steps, config.use_antithetic)
    rets = (mu - 0.5 * sigma * sigma) * dt + sigma * sqdt * z

    if config.model == "Merton":
        lam = config.jump_intensity
        mu_j = config.jump_mean
        sigma_j = config.jump_std
        jc = lam * (math.exp(mu_j + 0.5 * sigma_j * sigma_j) - 1.0)
        # Jumps are per-path i.i.d. (not antithetic). Compound Poisson normal:
        # total step jump = mu_j*N + sigma_j*sqrt(N)*Z2, N ~ Poisson(lam*dt).
        n_jumps = children["jcount"].poisson(lam * dt, size=(m, n_steps))
        z2 = children["jsize"].standard_normal((m, n_steps))
        jumps = mu_j * n_jumps + sigma_j * np.sqrt(n_jumps) * z2
        rets = rets - jc * dt + jumps

    paths = np.empty((m, n_steps + 1), dtype=np.float64)
    paths[:, 0] = S0
    paths[:, 1:] = S0 * np.exp(np.cumsum(rets, axis=1))
    return paths


def _iter_chunks(n_paths: int, chunk_size: int, antithetic: bool) -> list[tuple[int, int, int]]:
    """Chunk plan: list of (chunk_index, start, count). Chunk size is forced even
    when antithetic so no pair straddles a chunk boundary (last chunk may be odd)."""
    step = chunk_size
    if antithetic and step % 2 == 1:
        step += 1
    plan: list[tuple[int, int, int]] = []
    idx = 0
    start = 0
    while start < n_paths:
        count = min(step, n_paths - start)
        plan.append((idx, start, count))
        start += count
        idx += 1
    return plan


def _simulate_paths_full(config: MultiCycleMCConfig) -> np.ndarray:
    """Assemble all chunks into one (n_paths, total_steps+1) array.

    Back-compatible helper used by tests / smoke checks. Uses the *same* chunk plan
    and per-chunk RNG as the production driver, so driver results reproduce this."""
    plan = _iter_chunks(config.n_paths, config.chunk_size, config.use_antithetic)
    out = np.empty((config.n_paths, config.total_steps + 1), dtype=np.float64)
    for chunk_index, start, count in plan:
        out[start : start + count] = _generate_chunk_paths(config, chunk_index, count)
    return out


def _simulate_gbm_paths(config: MultiCycleMCConfig) -> np.ndarray:
    if config.model != "GBM":
        # Force GBM generation regardless of config.model for this explicit helper.
        config = _with(config, model="GBM")
    return _simulate_paths_full(config)


def _simulate_merton_paths(config: MultiCycleMCConfig) -> np.ndarray:
    if config.model != "Merton":
        config = _with(config, model="Merton")
    return _simulate_paths_full(config)


def _with(config: MultiCycleMCConfig, **changes: Any) -> MultiCycleMCConfig:
    from dataclasses import replace

    return replace(config, **changes)


# ── economics: vectorised (production) and scalar (independent oracle) ─────────


@dataclass(frozen=True)
class _CycleOutputs:
    pnl: np.ndarray
    final_value: np.ndarray
    final_btc: np.ndarray
    premium_pct: np.ndarray
    fees: np.ndarray
    eac: np.ndarray
    post_purchase_usd: np.ndarray
    post_purchase_btc: np.ndarray


def _run_cycles_vectorized(
    strategy: Strategy, paths: np.ndarray, config: MultiCycleMCConfig
) -> _CycleOutputs:
    """Vectorised multi-cycle economics over a (m, total_steps+1) path block.

    Options are CASH-settled (writer/holder exchange intrinsic; BTC inventory is
    retained — no fictitious physical delivery). The asym fee is charged once at
    inception. D-12 ``post_purchase`` funds a discretionary BTC buy with separately
    tracked ``extra_capital`` (added to the P&L base; no double-debit, no leverage).
    """
    m = paths.shape[0]
    steps_per = config.n_steps_per_cycle
    total_steps = config.total_steps
    qty = config.btc_quantity
    p = config.strike_target_pct
    kind = strategy.canonical.value
    call_u, put_u = _unit_premiums(config)

    if kind == "cash_secured_put":
        btc = np.zeros(m)
        cash = np.full(m, qty * config.initial_spot)  # cash collateral
    else:
        btc = np.full(m, qty)
        cash = np.zeros(m)
    initial_capital = btc * config.initial_spot + cash
    asym = config.asym_fee_usd
    fees = np.full(m, asym)
    cash = cash - asym
    extra_capital = np.zeros(m)
    pp_btc = np.zeros(m)
    premium_pct = np.zeros(m)

    for c in range(config.n_cycles):
        entry = paths[:, c * steps_per]
        exit_ = paths[:, min((c + 1) * steps_per, total_steps)]

        if kind == "unhedged_baseline":
            continue
        if kind in ("covered_call", "partial_overlay"):
            overlay = btc if kind == "covered_call" else btc * 0.5
            strike = entry * (1.0 + p)
            cash = cash + entry * call_u * overlay
            premium_pct = premium_pct + call_u * (overlay / qty)
            cash = cash - np.maximum(exit_ - strike, 0.0) * overlay  # short call cash-settle
        elif kind == "long_btc_plus_short_put":
            strike = entry * (1.0 - p)
            cash = cash + entry * put_u * btc
            premium_pct = premium_pct + put_u
            payout = np.maximum(strike - exit_, 0.0) * btc  # short put cash-settle
            cash = cash - payout
            if config.d12_interpretation == "post_purchase":
                add = np.where(exit_ > 0.0, payout / np.where(exit_ > 0.0, exit_, 1.0), 0.0)
                btc = btc + add
                pp_btc = pp_btc + add
                extra_capital = extra_capital + payout
        elif kind == "collar":
            strike_c = entry * (1.0 + p)
            strike_p = entry * (1.0 - p)
            cash = cash + (entry * call_u - entry * put_u) * btc
            premium_pct = premium_pct + (call_u - put_u)
            cash = cash - np.maximum(exit_ - strike_c, 0.0) * btc  # short call
            cash = cash + np.maximum(strike_p - exit_, 0.0) * btc  # long put
        elif kind == "cash_secured_put":
            strike = entry * (1.0 - p)
            cash = cash + entry * put_u * qty
            premium_pct = premium_pct + put_u
            payout = np.maximum(strike - exit_, 0.0) * qty
            cash = cash - payout
            if config.d12_interpretation == "post_purchase":
                add = np.where(exit_ > 0.0, payout / np.where(exit_ > 0.0, exit_, 1.0), 0.0)
                btc = btc + add
                pp_btc = pp_btc + add
                extra_capital = extra_capital + payout
        # bespoke / protective_put etc: hold-only (no overlay modelled here).

    final_spot = paths[:, -1]
    final_value = cash + btc * final_spot
    pnl = final_value - initial_capital - extra_capital
    safe_btc = np.where(btc > 1e-9, btc, 1.0)
    eac = np.where(btc > 1e-9, (initial_capital + extra_capital - cash) / safe_btc, np.nan)

    return _CycleOutputs(
        pnl=pnl,
        final_value=final_value,
        final_btc=btc,
        premium_pct=premium_pct,
        fees=fees,
        eac=eac,
        post_purchase_usd=extra_capital,
        post_purchase_btc=pp_btc,
    )


def _run_multi_cycle_path(
    strategy: Strategy,
    path: np.ndarray,
    config: MultiCycleMCConfig,
) -> tuple[float, float, float, float, float, float]:
    """Independent scalar reference for ONE path.

    Mirrors :func:`_run_cycles_vectorized` for a single 1-D path and is used as the
    test oracle (scalar-vs-vectorised equivalence). Kept deliberately independent of
    the vectorised code path.

    Returns ``(final_pnl, final_value, final_btc, total_premium_pct, total_fees, eac)``.
    """
    steps_per = config.n_steps_per_cycle
    total_steps = config.total_steps
    qty = config.btc_quantity
    p = config.strike_target_pct
    kind = strategy.canonical.value
    call_u, put_u = _unit_premiums(config)

    if kind == "cash_secured_put":
        btc = 0.0
        cash = qty * config.initial_spot
    else:
        btc = qty
        cash = 0.0
    initial_capital = btc * config.initial_spot + cash
    total_fees = config.asym_fee_usd
    cash -= total_fees
    extra_capital = 0.0
    total_premium_pct = 0.0

    for c in range(config.n_cycles):
        entry = float(path[c * steps_per])
        exit_ = float(path[min((c + 1) * steps_per, total_steps)])

        if kind == "unhedged_baseline":
            continue
        if kind in ("covered_call", "partial_overlay"):
            overlay = btc if kind == "covered_call" else btc * 0.5
            strike = entry * (1.0 + p)
            cash += entry * call_u * overlay
            total_premium_pct += call_u * (overlay / qty)
            cash -= max(exit_ - strike, 0.0) * overlay
        elif kind == "long_btc_plus_short_put":
            strike = entry * (1.0 - p)
            cash += entry * put_u * btc
            total_premium_pct += put_u
            payout = max(strike - exit_, 0.0) * btc
            cash -= payout
            if config.d12_interpretation == "post_purchase" and exit_ > 0.0:
                add = payout / exit_
                btc += add
                extra_capital += payout
        elif kind == "collar":
            strike_c = entry * (1.0 + p)
            strike_p = entry * (1.0 - p)
            cash += (entry * call_u - entry * put_u) * btc
            total_premium_pct += call_u - put_u
            cash -= max(exit_ - strike_c, 0.0) * btc
            cash += max(strike_p - exit_, 0.0) * btc
        elif kind == "cash_secured_put":
            strike = entry * (1.0 - p)
            cash += entry * put_u * qty
            total_premium_pct += put_u
            payout = max(strike - exit_, 0.0) * qty
            cash -= payout
            if config.d12_interpretation == "post_purchase" and exit_ > 0.0:
                add = payout / exit_
                btc += add
                extra_capital += payout

    final_spot = float(path[-1])
    final_value = cash + btc * final_spot
    final_pnl = final_value - initial_capital - extra_capital
    eac = (initial_capital + extra_capital - cash) / btc if btc > 1e-9 else float("nan")
    return final_pnl, final_value, btc, total_premium_pct, total_fees, eac


def _seller_discount_threshold(config: MultiCycleMCConfig) -> float:
    return config.seller_discount_pct * config.btc_quantity * config.initial_spot


# ── metric finalisation ────────────────────────────────────────────────────────


def _finalize(
    strategy: Strategy,
    config: MultiCycleMCConfig,
    pnl: np.ndarray,
    final_btc: np.ndarray,
    premium_pct: np.ndarray,
    fees: np.ndarray,
    eac: np.ndarray,
    pp_usd: np.ndarray,
    pp_btc: np.ndarray,
) -> MultiCycleMCResult:
    n = pnl.shape[0]
    capital = config.capital_base

    mean_pnl = float(np.mean(pnl))
    median_pnl = float(np.median(pnl))
    std_pnl = float(np.std(pnl))
    p5 = float(np.percentile(pnl, 5))
    p1 = float(np.percentile(pnl, 1))

    # Expected shortfall: mean loss in the worst (1-alpha) tail. Losses = -pnl.
    losses = -pnl
    es95 = float(np.mean(losses[losses >= np.percentile(losses, 95)])) if n else 0.0
    es99 = float(np.mean(losses[losses >= np.percentile(losses, 99)])) if n else 0.0
    max_loss = float(np.max(losses)) if n else 0.0

    prob_loss = float(np.mean(pnl < 0))
    prob_exceed = float(np.mean(pnl > _seller_discount_threshold(config)))

    valid_eac = eac[~np.isnan(eac)]
    mean_eac = float(np.mean(valid_eac)) if valid_eac.size else float("nan")
    eac_5 = float(np.percentile(valid_eac, 5)) if valid_eac.size else float("nan")
    eac_95 = float(np.percentile(valid_eac, 95)) if valid_eac.size else float("nan")

    mc_se = std_pnl / math.sqrt(n) if n else 0.0
    ci_half = 1.96 * mc_se

    jump_params = None
    if config.model == "Merton":
        jump_params = {
            "intensity": config.jump_intensity,
            "mean": config.jump_mean,
            "std": config.jump_std,
        }

    return MultiCycleMCResult(
        strategy_id=strategy.strategy_id,
        strategy_kind=strategy.canonical.value,
        business_label=strategy.business_label,
        n_paths=n,
        n_cycles=config.n_cycles,
        model=config.model,
        seed=config.seed,
        total_horizon_years=config.total_horizon_years,
        initial_spot=config.initial_spot,
        drift=config.drift,
        volatility=config.volatility,
        risk_free_rate=config.risk_free_rate,
        jump_params=jump_params,
        d1_fee_base=config.d1_fee_base,
        d12_interpretation=config.d12_interpretation,
        mean_outcome_usd=mean_pnl,
        median_outcome_usd=median_pnl,
        std_outcome_usd=std_pnl,
        percentile_5_usd=p5,
        percentile_1_usd=p1,
        mean_outcome_pct_capital=100.0 * mean_pnl / capital,
        median_outcome_pct_capital=100.0 * median_pnl / capital,
        std_outcome_pct_capital=100.0 * std_pnl / capital,
        percentile_5_pct_capital=100.0 * p5 / capital,
        percentile_1_pct_capital=100.0 * p1 / capital,
        expected_shortfall_95=es95,
        expected_shortfall_99=es99,
        probability_of_loss=prob_loss,
        probability_of_exceeding_seller_discount=prob_exceed,
        mean_eac_usd_per_btc=mean_eac,
        eac_distribution_5=eac_5,
        eac_distribution_95=eac_95,
        max_loss_usd=max_loss,
        max_loss_pct_capital=100.0 * max_loss / capital,
        ci_95_mean_lower=mean_pnl - ci_half,
        ci_95_mean_upper=mean_pnl + ci_half,
        mc_standard_error=mc_se,
        mean_final_btc=float(np.mean(final_btc)),
        mean_total_premium_pct=float(np.mean(premium_pct)),
        mean_total_fees_usd=float(np.mean(fees)),
        total_asym_fee_usd=config.asym_fee_usd,
        mean_post_purchase_usd_deployed=float(np.mean(pp_usd)),
        mean_post_purchase_btc_acquired=float(np.mean(pp_btc)),
        pnl_distribution=pnl.tolist() if config.store_paths else [],
        eac_distribution=eac.tolist() if config.store_paths else [],
        provenance=Provenance.SIMULATED,
        pending_decision_refs=[_pending_d1, _pending_d9, _pending_d12],
        assumptions=config.assumptions_dict(),
    )


# ── checkpointing ──────────────────────────────────────────────────────────────


_CKPT_FIELDS = ("pnl", "fv", "btc", "prem", "fees", "eac", "pp_usd", "pp_btc")


def _checkpoint_paths(checkpoint: str | Path) -> tuple[Path, Path]:
    base = Path(checkpoint)
    return base.with_suffix(".json"), base.with_suffix(".npy")


def _save_checkpoint(
    checkpoint: str | Path,
    config: MultiCycleMCConfig,
    strategy_id: str,
    done: int,
    acc: dict[str, np.ndarray],
) -> None:
    meta_path, npy_path = _checkpoint_paths(checkpoint)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    # Stack the equal-length per-path fields into one (n_fields, done) array.
    stacked = np.vstack([np.asarray(acc[f], dtype=np.float64) for f in _CKPT_FIELDS])
    np.save(npy_path, stacked)
    meta = {
        "fingerprint": config.fingerprint(),
        "strategy_id": strategy_id,
        "n_paths": config.n_paths,
        "done": done,
        "fields": list(_CKPT_FIELDS),
        "array": npy_path.name,
    }
    meta_path.write_text(json.dumps(meta, indent=2))


def _load_checkpoint(
    checkpoint: str | Path, config: MultiCycleMCConfig, strategy_id: str
) -> tuple[int, dict[str, np.ndarray]] | None:
    meta_path, npy_path = _checkpoint_paths(checkpoint)
    if not meta_path.exists() or not npy_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("fingerprint") != config.fingerprint() or meta.get("strategy_id") != strategy_id:
        # Config changed since checkpoint: ignore stale checkpoint (do not silently reuse).
        return None
    if int(meta.get("n_paths", -1)) != config.n_paths:
        return None
    if list(meta.get("fields", [])) != list(_CKPT_FIELDS):
        return None
    stacked = np.load(npy_path)
    acc = {f: stacked[i] for i, f in enumerate(_CKPT_FIELDS)}
    return int(meta["done"]), acc


# ── driver ─────────────────────────────────────────────────────────────────────


def run_multi_cycle_monte_carlo(
    strategy: Strategy,
    config: MultiCycleMCConfig,
    *,
    checkpoint: str | Path | None = None,
    checkpoint_every_chunks: int = 5,
    progress_cb: Any = None,
) -> MultiCycleMCResult:
    """Run the multi-cycle Monte Carlo, vectorised over paths and chunked over the
    path dimension for bounded memory.

    Deterministic given (seed, config). If ``checkpoint`` is given, per-path scalar
    outputs are persisted every ``checkpoint_every_chunks`` chunks and a matching
    prior checkpoint is resumed (recomputing only the remaining chunks)."""
    plan = _iter_chunks(config.n_paths, config.chunk_size, config.use_antithetic)

    fields = ("pnl", "fv", "btc", "prem", "fees", "eac", "pp_usd", "pp_btc")
    acc: dict[str, list[np.ndarray]] = {f: [] for f in fields}
    done = 0

    if checkpoint is not None:
        loaded = _load_checkpoint(checkpoint, config, strategy.strategy_id)
        if loaded is not None:
            done, saved = loaded
            for f in fields:
                if saved.get(f) is not None and saved[f].size:
                    acc[f].append(saved[f])

    chunks_since_ckpt = 0
    for chunk_index, start, count in plan:
        if start + count <= done:
            continue  # already covered by a resumed checkpoint
        paths = _generate_chunk_paths(config, chunk_index, count)
        out = _run_cycles_vectorized(strategy, paths, config)
        acc["pnl"].append(out.pnl)
        acc["fv"].append(out.final_value)
        acc["btc"].append(out.final_btc)
        acc["prem"].append(out.premium_pct)
        acc["fees"].append(out.fees)
        acc["eac"].append(out.eac)
        acc["pp_usd"].append(out.post_purchase_usd)
        acc["pp_btc"].append(out.post_purchase_btc)
        done = start + count
        chunks_since_ckpt += 1
        if progress_cb is not None:
            progress_cb(done, config.n_paths)
        if checkpoint is not None and chunks_since_ckpt >= checkpoint_every_chunks:
            merged = {f: np.concatenate(acc[f]) for f in fields if acc[f]}
            _save_checkpoint(checkpoint, config, strategy.strategy_id, done, merged)
            chunks_since_ckpt = 0

    merged = {f: (np.concatenate(acc[f]) if acc[f] else np.zeros(0)) for f in fields}
    if checkpoint is not None:
        _save_checkpoint(checkpoint, config, strategy.strategy_id, done, merged)

    return _finalize(
        strategy,
        config,
        merged["pnl"],
        merged["btc"],
        merged["prem"],
        merged["fees"],
        merged["eac"],
        merged["pp_usd"],
        merged["pp_btc"],
    )


def run_c7_fasttrack_suite(
    strategies: list[Strategy],
    strategy_labels: list[str],
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, MultiCycleMCResult]:
    """Run the C7 fast-track MC suite for a compact strategy universe.

    Emits separate rows for GBM/Merton x D-1 (reference/executed) x D-12
    (cash_settled/post_purchase). ``config_overrides`` is applied to the base config
    (e.g. ``{"n_paths": 10}`` for fast tests) — validated against known fields.
    """
    overrides = dict(config_overrides or {})
    allowed = set(MultiCycleMCConfig.__dataclass_fields__)
    unknown = set(overrides) - allowed
    if unknown:
        raise ValidationError(f"Unknown config_overrides keys: {sorted(unknown)}")
    # Fields fixed by the suite's own sweep (must not be overridden).
    for reserved in ("model", "d1_fee_base", "d12_interpretation"):
        overrides.pop(reserved, None)

    base_kwargs: dict[str, Any] = {"n_paths": 10_000, "n_cycles": 12}
    base_kwargs.update(overrides)

    results: dict[str, MultiCycleMCResult] = {}
    fee_bases: list[FeeBase] = ["reference_notional", "executed_volume"]
    d12_opt: list[D12Interp] = ["cash_settled", "post_purchase"]
    models: list[ModelName] = ["GBM", "Merton"]

    for s, lbl in zip(strategies, strategy_labels, strict=True):
        for model in models:
            for fb in fee_bases:
                for d12 in d12_opt:
                    cfg = MultiCycleMCConfig(
                        model=model, d1_fee_base=fb, d12_interpretation=d12, **base_kwargs
                    )
                    key = f"{lbl}_{model}_D1-{fb}_D12-{d12}"
                    results[key] = run_multi_cycle_monte_carlo(s, cfg)
    return results


def benchmark_mc(config: MultiCycleMCConfig | None = None) -> dict[str, Any]:
    """Run a timing benchmark to calibrate runtime before a production run."""
    if config is None:
        config = MultiCycleMCConfig(n_paths=10_000, n_cycles=12)
    from strategy.definitions import build_covered_call

    strat = build_covered_call(
        quantity=config.btc_quantity,
        entry_spot=config.initial_spot,
        strike=config.initial_spot * (1.0 + config.strike_target_pct),
        premium_received=1500.0,
    )
    t0 = time.perf_counter()
    run_multi_cycle_monte_carlo(strat, config)
    elapsed = time.perf_counter() - t0
    pps = config.n_paths / elapsed if elapsed > 0 else float("inf")
    return {
        "n_paths": config.n_paths,
        "n_cycles": config.n_cycles,
        "model": config.model,
        "elapsed_seconds": round(elapsed, 3),
        "paths_per_second": round(pps, 1),
        "projected_100k_minutes": round((100_000 / pps) / 60.0, 3) if pps else float("inf"),
        "projected_50k_seconds": round(50_000 / pps, 2) if pps else float("inf"),
        "projected_25k_seconds": round(25_000 / pps, 2) if pps else float("inf"),
    }
