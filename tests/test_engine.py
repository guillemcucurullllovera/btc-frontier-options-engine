"""Golden-vector and mandate-economics tests. Run from btc_engine/: python3 -m pytest -q"""
from __future__ import annotations

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from execution.waterfall import load_params, waterfall
from pricing.black_scholes import (
    greeks,
    implied_vol,
    premium_pct_at_delta,
    price,
    strike_for_delta,
)

# ---------- Golden vectors (Hull/Haug standard case) ----------
S: float = 100.0
K: float = 100.0
r: float = 0.05
sig: float = 0.20
T: float = 1.0


def test_call_golden() -> None:
    assert abs(price(S, K, r, sig, T, "call") - 10.4506) < 1e-3


def test_put_golden() -> None:
    assert abs(price(S, K, r, sig, T, "put") - 5.5735) < 1e-3


def test_put_call_parity() -> None:
    c = price(S, K, r, sig, T, "call")
    p = price(S, K, r, sig, T, "put")
    assert abs((c - p) - (S - K * math.exp(-r * T))) < 1e-9


def test_delta_golden() -> None:
    assert abs(greeks(S, K, r, sig, T, "call").delta - 0.6368) < 1e-3


def test_implied_vol_roundtrip() -> None:
    c = price(S, K, r, sig, T, "call")
    assert abs(implied_vol(c, S, K, r, T, "call") - sig) < 1e-6


def test_strike_for_delta_roundtrip() -> None:
    Kx = strike_for_delta(65000, 0.125, 0.04, 0.45, 37 / 365, "call")
    assert abs(greeks(65000, Kx, 0.04, 0.45, 37 / 365, "call").delta - 0.125) < 1e-6


# ---------- Mandate-case checks (Sec. 3.2 of the plan) ----------
def test_mandate_125delta_premium_band() -> None:
    pct, Kx = premium_pct_at_delta(65000, 0.125, 0.04, 0.45, 37, "call")
    assert 0.7 < pct < 1.0  # ~0.82% of notional at DVOL 45
    assert 76000 < Kx < 80000  # strike ~+19-20% above spot
    assert 1.15 < Kx / 65000 < 1.23  # consistent with 15-20% mandate guidance


def test_target_yield_requires_higher_delta_or_iv() -> None:
    """3% of spot in one 37-DTE cycle: show it prices at ~30-35 delta at IV 45%."""
    from scipy.optimize import brentq

    def _diff(d: float) -> float:
        return premium_pct_at_delta(65000, d, 0.04, 0.45, 37, "call")[0] - 3.0

    d_star: float = float(brentq(_diff, 0.16, 0.60))
    assert 0.28 < d_star < 0.38


# ---------- Waterfall economics ----------
def test_waterfall_mandate_numbers() -> None:
    w = waterfall(load_params())
    assert abs(w["reference_notional_usd"] - 1_950_000_000) < 1
    assert abs(w["asymmetrica_fee_usd"] - 9_750_000) < 1
    assert abs(w["asymmetrica_fee_btc_equiv"] - 150.0) < 1e-9
    assert abs(w["client_cash_at_close_per_btc"] - 63_700) < 1e-6
    assert abs(w["client_effective_cost_per_btc_target_case"] - 62_075) < 1e-6
    assert abs(w["net_discount_vs_reference_pct"] - 4.5) < 1e-9
