"""Scenario definitions for stress testing and regime analysis.

Defines specific market scenarios with deterministic path generation.

Stage 3 (C9): shock_type labels must reflect actual data provenance:
  - OBSERVED_REPLAY: observed historical windows consumed as-is
  - SIMULATED: synthetic/bridge scenarios generated from parameters
  - Do not call synthetic scenarios historical replays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from config.models import Provenance
from engine.errors import ValidationError


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    shock_type: Literal["instantaneous", "replay", "regime_shift", "synthetic"]
    start_spot: float
    end_spot: float
    start_vol: float
    end_vol: float
    path: list[float] | None = None
    provenance: Provenance = Provenance.SIMULATED


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    strategy_pnl_usd: float
    strategy_pnl_pct: float
    premium_contribution_pct: float
    itm_on_scenario: bool
    max_adverse_excursion_pct: float
    venue_settlement_applied: bool
    provenance: Provenance = Provenance.CALCULATED


def generate_scenario_path(
    start_spot: float,
    end_spot: float,
    n_steps: int,
    annual_vol: float,
    seed: int = 42,
) -> list[float]:
    """Generate a deterministic path from start_spot to end_spot.

    Uses standard GBM with deterministic perturbation then constrains
    the endpoint. Validates inputs.
    """
    if n_steps <= 0:
        raise ValidationError(f"n_steps must be positive, got {n_steps}")
    if start_spot <= 0:
        raise ValidationError(f"start_spot must be positive, got {start_spot}")
    if end_spot <= 0:
        raise ValidationError(f"end_spot must be positive, got {end_spot}")
    if annual_vol < 0:
        raise ValidationError(f"annual_vol must be non-negative, got {annual_vol}")

    rng = np.random.default_rng(seed)
    dt = 1.0 / 365.0
    sigma = annual_vol
    total_T = n_steps * dt

    log_path = np.zeros(n_steps + 1)
    log_path[0] = np.log(start_spot)

    for i in range(n_steps):
        t = i * dt
        remaining = max(total_T - t, 1e-10)
        current = log_path[i]

        bridge_drift = (np.log(end_spot) - current) / remaining if remaining > 0 else 0.0
        noise = sigma * np.sqrt(dt) * rng.normal()
        log_path[i + 1] = current + bridge_drift * dt + noise

    log_path[-1] = np.log(end_spot)
    path = [max(float(np.exp(s)), 0.01) for s in log_path]
    path[-1] = end_spot
    return path


def build_all_scenarios(start_spot: float = 65_000.0) -> list[Scenario]:
    scenarios: list[Scenario] = []

    scenarios.append(Scenario(
        name="2025_breakout_to_126k",
        description="BTC surges to 126k (2025 ATH scenario)",
        shock_type="synthetic",
        start_spot=start_spot, end_spot=126_000.0,
        start_vol=0.45, end_vol=0.55,
        path=generate_scenario_path(start_spot, 126_000.0, 90, 0.45, seed=123),
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="2026_retrace_to_65k",
        description="BTC retraces from 126k to 65k",
        shock_type="synthetic",
        start_spot=126_000.0, end_spot=65_000.0,
        start_vol=0.55, end_vol=0.50,
        path=generate_scenario_path(126_000.0, 65_000.0, 90, 0.55, seed=456),
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="flash_crash_to_30k",
        description="Instantaneous 54% crash to 30k",
        shock_type="instantaneous",
        start_spot=start_spot, end_spot=30_000.0,
        start_vol=0.45, end_vol=0.80,
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="dvol_35_to_65_shock",
        description="Volatility spike from 35% to 65% DVOL with spot dropping 10%",
        shock_type="synthetic",
        start_spot=start_spot, end_spot=start_spot * 0.90,
        start_vol=0.35, end_vol=0.65,
        path=generate_scenario_path(start_spot, start_spot * 0.90, 30, 0.35, seed=789),
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="dvol_65_to_35_normalize",
        description="Volatility collapse from 65% to 35% with 15% spot rally",
        shock_type="synthetic",
        start_spot=start_spot * 0.90, end_spot=start_spot * 1.035,
        start_vol=0.65, end_vol=0.35,
        path=generate_scenario_path(start_spot * 0.90, start_spot * 1.035, 30, 0.65, seed=101),
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="liquidity_shock",
        description="Spot drops 25% with vol spike to 100% over 5 days",
        shock_type="synthetic",
        start_spot=start_spot, end_spot=start_spot * 0.75,
        start_vol=0.45, end_vol=1.00,
        path=generate_scenario_path(start_spot, start_spot * 0.75, 5, 0.45, seed=112),
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="settlement_price_shock",
        description="Delivery/settlement price 5% below VWAP at expiry",
        shock_type="instantaneous",
        start_spot=start_spot, end_spot=start_spot * 0.95,
        start_vol=0.45, end_vol=0.50,
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="combined_severe",
        description="40% spot drop + vol spike to 120% combined",
        shock_type="synthetic",
        start_spot=start_spot, end_spot=start_spot * 0.60,
        start_vol=0.45, end_vol=1.20,
        path=generate_scenario_path(start_spot, start_spot * 0.60, 20, 0.45, seed=345),
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="bull_rally_100k",
        description="BTC rallies 54% to 100k",
        shock_type="synthetic",
        start_spot=start_spot, end_spot=100_000.0,
        start_vol=0.45, end_vol=0.40,
        path=generate_scenario_path(start_spot, 100_000.0, 60, 0.45, seed=678),
        provenance=Provenance.SIMULATED,
    ))

    scenarios.append(Scenario(
        name="sideways_chop",
        description="BTC oscillates within +/-5% band for 90 days",
        shock_type="synthetic",
        start_spot=start_spot, end_spot=start_spot * 1.02,
        start_vol=0.30, end_vol=0.30,
        path=generate_scenario_path(start_spot, start_spot * 1.02, 90, 0.30, seed=901),
        provenance=Provenance.SIMULATED,
    ))

    return scenarios
