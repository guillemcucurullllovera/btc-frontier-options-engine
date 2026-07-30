"""Calibrated-model risk integration: physical-simulate, Q-mark (C9 · M5.1).

SIMULATED / diagnostic; MS-26-gated; holder-basis (C8); frozen anchor. This is where the calibrated
model finally drives the client-facing risk numbers — with an explicit MEASURE ARCHITECTURE:

  * Scenario PATHS = PHYSICAL measure ("what could happen"): P-vol level (M4.6 GARCH ~46% / UKF ~43%),
    P-symmetric realized jumps (M4.6: lambda~4.5/yr, ~10% variance share, roughly symmetric), an
    ASSUMED drift band, and the SV structure (kappa, vol-of-vol, rho) from the Q-calibration as
    best-available (P-estimation of these is deferred to M4.4b-MCMC). Full-truncation is violated so
    the QE variance scheme is used.
  * Option repricing = the Q-calibrated Bates via the M1 COS pricer — so the variance risk premium
    (Q > P) is captured exactly as in R1 (simulate physical, sell/mark at the Q-implied premium).

Every parameter carries a provenance tag (P-ESTIMATED / Q-CALIBRATED / ASSUMED). Risk metrics
(VaR/ES/prob-loss + CVaR frontier + EVT tail) each carry SE/CI (M0.3). No best/optimal language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from pricing.cf.characteristic_functions import Bates
from pricing.cf.cos import cos_call, cos_put
from risk.cvar_frontier import CvarEstimate, ru_cvar_ci
from risk.tail import TailEstimate, with_bootstrap_ci
from strategy.multi_cycle_mc import MultiCycleMCConfig, _simulate_paths_full

Structure = Literal["unhedged", "covered_call", "long_btc_plus_short_put"]
ModelName = Literal["GBM", "Merton", "Bates"]

# ── Provenance-labelled parameter blocks (from M2/M3 Q-calibration + M4.6 P-estimation) ──

# Q-calibrated Bates (M3, frozen anchor) — used ONLY to mark the option premium (reprices the smile;
# the degenerate jumps do not impair the PRICE). Provenance: Q-CALIBRATED.
Q_BATES = Bates(r=0.0, q=0.0, v0=0.078, kappa=8.37, theta=0.209, sigma=5.50, rho=-0.403,
                lam=16.4, mu_j=-0.055, sigma_j=0.001)

# Physical scenario parameters (M4.6 refresh). Provenance tags in PARAM_PROVENANCE.
P_VOL = 0.45                 # P-ESTIMATED: GARCH uncond ~0.46 / UKF ~0.43
P_JUMP_LAM = 4.5             # P-ESTIMATED: realized-jump intensity (M4.6, 2yr)
P_JUMP_MEAN = 0.0            # P-ESTIMATED: ~symmetric (M4.6 mean +0.7% ~ 0)
P_JUMP_STD = 0.088           # P-ESTIMATED: realized-jump size std (M4.6)

PARAM_PROVENANCE: dict[str, str] = {
    "p_vol": "P-ESTIMATED (M4.6 GARCH/UKF)",
    "jump_lam/mean/std": "P-ESTIMATED (M4.6 realized jumps, ~symmetric)",
    "drift": "ASSUMED (drift band {-0.10, 0, +0.10}, MS-26)",
    "kappa/vol_of_vol/rho": "Q-CALIBRATED best-available (P-estimation deferred to M4.4b-MCMC)",
    "premium_mark": "Q-CALIBRATED Bates via COS (VRP Q>P)",
}


@dataclass(frozen=True)
class PhysicalRiskConfig:
    S0: float = 63_402.0
    T: float = 45.0 / 365.0
    n_paths: int = 200_000
    n_steps: int = 60
    drift: float = 0.0                    # ASSUMED (drift band); default centre
    p_vol: float = P_VOL                  # P long-run/spot vol level
    kappa: float = 8.37                   # Q best-available SV structure
    vol_of_vol: float = 5.50
    rho: float = -0.403
    jump_lam: float = P_JUMP_LAM
    jump_mean: float = P_JUMP_MEAN
    jump_std: float = P_JUMP_STD
    seed: int = 20260730


def simulate_terminal(cfg: PhysicalRiskConfig, model: ModelName) -> np.ndarray:
    """Physical terminal spot S_T under GBM / Merton / Bates (QE for Bates). Reproducible."""
    common: dict[str, Any] = {
        "n_paths": cfg.n_paths, "n_cycles": 1, "cycle_length_years": cfg.T,
        "n_steps_per_cycle": cfg.n_steps, "initial_spot": cfg.S0, "drift": cfg.drift,
        "risk_free_rate": cfg.drift, "seed": cfg.seed, "use_antithetic": True,
        "chunk_size": min(cfg.n_paths, 50_000),
    }
    if model == "GBM":
        mc = MultiCycleMCConfig(model="GBM", volatility=cfg.p_vol, **common)
    elif model == "Merton":
        mc = MultiCycleMCConfig(model="Merton", volatility=cfg.p_vol, jump_intensity=cfg.jump_lam,
                                jump_mean=cfg.jump_mean, jump_std=cfg.jump_std, **common)
    else:
        v = cfg.p_vol ** 2
        mc = MultiCycleMCConfig(model="Bates", variance_scheme="qe", heston_v0=v, heston_kappa=cfg.kappa,
                                heston_theta=v, heston_vol_of_vol=cfg.vol_of_vol, heston_rho=cfg.rho,
                                jump_intensity=cfg.jump_lam, jump_mean=cfg.jump_mean,
                                jump_std=cfg.jump_std, **common)
    return _simulate_paths_full(mc)[:, -1]


def q_bates_premium(S0: float, K: float, T: float, kind: str, q_bates: Bates = Q_BATES) -> float:
    """USD option premium marked at the Q-calibrated Bates (COS)."""
    if kind == "call":
        return cos_call(q_bates, S0, K, T, N=2048, L=16.0)
    return cos_put(q_bates, S0, K, T, N=2048, L=16.0)


def holder_basis_pnl(structure: Structure, S0: float, K: float, S_T: np.ndarray,
                     prem_usd: float, coverage: float = 1.0) -> np.ndarray:
    """Holder-basis USD P&L per BTC of the held block (holding on the full block, overlay on coverage)."""
    holding = S_T - S0
    if structure == "unhedged":
        return holding
    if structure == "covered_call":
        overlay = prem_usd - np.maximum(S_T - K, 0.0)
    elif structure == "long_btc_plus_short_put":
        overlay = prem_usd - np.maximum(K - S_T, 0.0)
    else:
        raise ValueError(f"unknown structure {structure!r}")
    return holding + coverage * overlay


@dataclass(frozen=True)
class RiskMetrics:
    model: str
    structure: str
    mean_pnl: float
    mean_pnl_se: float
    prob_loss: float
    var95: float                 # loss magnitude (>=0)
    es975: float
    cvar95: CvarEstimate         # RU CVaR with bootstrap SE/CI
    evt_tail: TailEstimate       # EVT/GPD VaR/ES with bootstrap SE/CI
    vrp_carry: float             # premium received - E^P[option payoff]; SIGN is snapshot-dependent
    #                              (this anchor: implied ~37% < P-realized ~45% => NEGATIVE VRP)
    n_paths: int
    provenance: str = "SIMULATED"


def _risk_metrics(model: str, structure: str, pnl: np.ndarray, prem_usd: float,
                  option_payoff: np.ndarray | None, n_boot: int) -> RiskMetrics:
    losses = -pnl
    var95 = float(np.percentile(losses, 95.0))
    es975 = float(np.mean(losses[losses >= float(np.percentile(losses, 97.5))]))
    vrp = float(prem_usd - np.mean(option_payoff)) if option_payoff is not None else 0.0
    return RiskMetrics(
        model=model, structure=structure,
        mean_pnl=float(np.mean(pnl)), mean_pnl_se=float(np.std(pnl) / np.sqrt(pnl.size)),
        prob_loss=float(np.mean(pnl < 0.0)), var95=var95, es975=es975,
        cvar95=ru_cvar_ci(pnl, beta=0.95, n_boot=n_boot),
        evt_tail=with_bootstrap_ci(pnl, method="evt_gpd", confidence=0.975, n_boot=n_boot),
        vrp_carry=vrp, n_paths=int(pnl.size),
    )


def bates_risk(structure: Structure, cfg: PhysicalRiskConfig, K: float,
               kind: str = "put", coverage: float = 1.0, n_boot: int = 200) -> dict[str, RiskMetrics]:
    """Physical-sim + Q-mark risk for a holder-basis structure under GBM / Merton / Bates."""
    prem = 0.0 if structure == "unhedged" else q_bates_premium(cfg.S0, K, cfg.T, kind)
    out: dict[str, RiskMetrics] = {}
    models: tuple[ModelName, ...] = ("GBM", "Merton", "Bates")
    for model in models:
        st = simulate_terminal(cfg, model)
        pnl = holder_basis_pnl(structure, cfg.S0, K, st, prem, coverage)
        payoff = None
        if structure == "covered_call":
            payoff = np.maximum(st - K, 0.0)
        elif structure == "long_btc_plus_short_put":
            payoff = np.maximum(K - st, 0.0)
        out[model] = _risk_metrics(model, structure, pnl, prem, payoff, n_boot)
    return out


@dataclass(frozen=True)
class CvarFrontierPoint:
    structure: str
    strike_pct: float
    mean_pnl: float
    cvar95: float
    cvar95_se: float
    provenance: str = "SIMULATED"


def cvar_frontier(cfg: PhysicalRiskConfig, structure: Structure, strike_pcts: tuple[float, ...],
                  kind: str = "put", coverage: float = 1.0, n_boot: int = 150) -> list[CvarFrontierPoint]:
    """Holder-basis CVaR loss-budget frontier under the Bates physical scenarios (per strike)."""
    st = simulate_terminal(cfg, "Bates")
    pts: list[CvarFrontierPoint] = []
    for pct in strike_pcts:
        K = cfg.S0 * (1.0 + pct / 100.0)
        prem = q_bates_premium(cfg.S0, K, cfg.T, kind)
        pnl = holder_basis_pnl(structure, cfg.S0, K, st, prem, coverage)
        est = ru_cvar_ci(pnl, beta=0.95, n_boot=n_boot)
        pts.append(CvarFrontierPoint(structure, pct, float(np.mean(pnl)), est.cvar, est.cvar_se))
    return pts
