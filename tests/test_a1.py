"""A1 pricing tests — Black-76, inverse-BTC, grid pricing, Greeks.

Covers contracts.md §§7, 13.1, 13.5, 13.8.
Existing 9 tests in test_engine.py and all Phase-0 tests in test_phase0.py
must continue to pass unchanged.
"""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pricing.black76 import greeks_black76, price_black76
from pricing.black_scholes import (
    OptionQuote,
    greeks,
    implied_vol,
    premium_pct_at_delta,
    price,
    strike_for_delta,
)
from pricing.grid import price_grid
from pricing.inverse import (
    greeks_inverse_btc,
    price_inverse_btc,
    settlement_inverse_call_holder,
    settlement_inverse_put_holder,
)
from pricing.payoff import payoff_bs_call, payoff_bs_put

# ═══════════════════════════════════════════════════════════════════════════════
# §13.1 — Golden vectors: Black-Scholes (preserved, re-asserted)
# ═══════════════════════════════════════════════════════════════════════════════

_S_ATM = 100.0
_K_ATM = 100.0
_r_ATM = 0.05
_sig_ATM = 0.20
_T_ATM = 1.0


def test_call_golden() -> None:
    assert abs(price(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "call") - 10.4506) < 1e-3


def test_put_golden() -> None:
    assert abs(price(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "put") - 5.5735) < 1e-3


def test_put_call_parity() -> None:
    c = price(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "call")
    p = price(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "put")
    assert abs((c - p) - (_S_ATM - _K_ATM * math.exp(-_r_ATM * _T_ATM))) < 1e-9


def test_delta_golden() -> None:
    assert abs(greeks(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "call").delta - 0.6368) < 1e-3


def test_implied_vol_roundtrip() -> None:
    c = price(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "call")
    assert abs(implied_vol(c, _S_ATM, _K_ATM, _r_ATM, _T_ATM, "call") - _sig_ATM) < 1e-6


def test_strike_for_delta_roundtrip() -> None:
    Kx = strike_for_delta(65000, 0.125, 0.04, 0.45, 37 / 365, "call")
    assert abs(greeks(65000, Kx, 0.04, 0.45, 37 / 365, "call").delta - 0.125) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# §13.1 — Golden vectors: Black-76 (Haug §1.1.3, p.6)
# ═══════════════════════════════════════════════════════════════════════════════


def test_black76_call_golden() -> None:
    """Haug §1.1.3: F=X=19, o=0.28, T=0.75, r=0.10 -> call ≈ 1.7011."""
    F, X = 19.0, 19.0
    c = price_black76(F, X, 0.10, 0.28, 0.75, "call")
    assert abs(c - 1.7011) < 1e-3


def test_black76_put_golden() -> None:
    """Haug: at-the-money forward, call = put (parity)."""
    F, X = 19.0, 19.0
    c = price_black76(F, X, 0.10, 0.28, 0.75, "call")
    p = price_black76(F, X, 0.10, 0.28, 0.75, "put")
    assert abs(c - p) < 1e-9


def test_black76_put_call_parity() -> None:
    """Black-76 put-call parity: C - P = exp(-rT)·(F - X)."""
    F, X, r, sig, T = 20.0, 19.0, 0.05, 0.25, 0.5
    c = price_black76(F, X, r, sig, T, "call")
    p = price_black76(F, X, r, sig, T, "put")
    assert abs((c - p) - math.exp(-r * T) * (F - X)) < 1e-9


def test_black76_otm_call_near_zero() -> None:
    """Deep OTM call ≈ 0."""
    p = price_black76(100.0, 200.0, 0.05, 0.20, 0.5, "call")
    assert p < 1e-4


def test_black76_itm_call() -> None:
    """Deep ITM call ≈ exp(-rT)·(F - X)."""
    F, X, r, sig, T = 100.0, 50.0, 0.05, 0.20, 0.25
    c = price_black76(F, X, r, sig, T, "call")
    intrinsic = math.exp(-r * T) * (F - X)
    assert abs(c - intrinsic) < 2e-4


def test_black76_greeks_extreme_cases() -> None:
    """Greeks don't produce NaN for extreme ITM/OTM."""
    for kind in ("call", "put"):
        q = greeks_black76(100.0, 200.0, 0.05, 0.20, 0.25, kind)
        assert not math.isnan(q.delta)
        assert not math.isnan(q.gamma)

        q = greeks_black76(100.0, 0.01, 0.05, 0.20, 0.25, kind)
        assert not math.isnan(q.delta)


# ═══════════════════════════════════════════════════════════════════════════════
# §13.1 — Golden vectors: Put Greeks (Hull/Haug)
# ═══════════════════════════════════════════════════════════════════════════════


def test_put_delta_golden() -> None:
    """ATM put delta ≈ -0.3632 = N(d1)-1 = 0.6368-1."""
    q = greeks(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "put")
    assert abs(q.delta - (-0.3632)) < 1e-3


def test_put_gamma_same_as_call() -> None:
    """Gamma is identical for calls and puts at same strike."""
    call_q = greeks(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "call")
    put_q = greeks(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "put")
    assert abs(call_q.gamma - put_q.gamma) < 1e-10


def test_put_vega_same_as_call() -> None:
    """Vega is identical for calls and puts at same strike."""
    call_q = greeks(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "call")
    put_q = greeks(_S_ATM, _K_ATM, _r_ATM, _sig_ATM, _T_ATM, "put")
    assert abs(call_q.vega - put_q.vega) < 1e-10


def test_put_theta_sign() -> None:
    """OTM put theta should be negative (time decay hurts long holder)."""
    q = greeks(100.0, 95.0, 0.05, 0.20, 0.5, "put")
    assert q.theta < 0.0

    # Deep ITM put (S=100,K=120) can have positive theta (behaves like a loan)
    q_itm = greeks(100.0, 120.0, 0.05, 0.20, 0.5, "put")
    assert not math.isnan(q_itm.theta)


# ═══════════════════════════════════════════════════════════════════════════════
# §13.8 — Inverse settlement golden vectors (Deribit spec lines 16-56)
# ═══════════════════════════════════════════════════════════════════════════════


def test_inverse_call_holder_settlement() -> None:
    """From Deribit spec line 22: S_T=125k, K=100k -> 0.2 BTC."""
    s = settlement_inverse_call_holder(125000.0, 100000.0)
    assert s == pytest.approx(0.2, abs=1e-9)


def test_inverse_put_holder_settlement() -> None:
    """S_T=80k, K=100k -> max(100k-80k,0)/80k = 0.25 BTC."""
    s = settlement_inverse_put_holder(80000.0, 100000.0)
    assert s == pytest.approx(0.25, abs=1e-9)


def test_inverse_call_writer_sign() -> None:
    """Short call writer cash flow = -0.2 BTC x 1 contract."""
    holder = settlement_inverse_call_holder(125000.0, 100000.0)
    writer = -holder
    assert writer == pytest.approx(-0.2, abs=1e-9)


def test_inverse_call_otm_settlement() -> None:
    """OTM call: delivery <= strike -> 0."""
    assert settlement_inverse_call_holder(95000.0, 100000.0) == 0.0


def test_inverse_put_otm_settlement() -> None:
    """OTM put: delivery >= strike -> 0."""
    assert settlement_inverse_put_holder(105000.0, 100000.0) == 0.0


def test_inverse_call_atm_settlement() -> None:
    """At the money: max(0,0)/S = 0."""
    assert settlement_inverse_call_holder(100000.0, 100000.0) == 0.0


def test_inverse_put_atm_settlement() -> None:
    assert settlement_inverse_put_holder(100000.0, 100000.0) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Inverse BTC pricing cross-checks
# ═══════════════════════════════════════════════════════════════════════════════


def test_inverse_call_price_atm() -> None:
    """ATM inverse call: price > 0 for o>0, T>0."""
    p = price_inverse_btc(100000.0, 100000.0, 0.04, 0.45, 30.0 / 365.0, "call")
    assert p > 0.0
    assert p < 0.1


def test_inverse_call_price_deep_otm() -> None:
    """Deep OTM inverse call -> ≈ 0."""
    p = price_inverse_btc(100000.0, 200000.0, 0.04, 0.45, 30.0 / 365.0, "call")
    assert p < 0.01


def test_inverse_call_price_deep_itm() -> None:
    """Deep ITM inverse call limit: as K->0, price -> exp(-rT)."""
    p = price_inverse_btc(100000.0, 100.0, 0.04, 0.45, 30.0 / 365.0, "call")
    expected_limit = math.exp(-0.04 * 30.0 / 365.0)
    assert 0.98 < p / expected_limit < 1.00


def test_inverse_put_price_atm() -> None:
    """ATM inverse put/call both nonzero and obey put-call parity."""
    S, K, r, sig, T = 100000.0, 100000.0, 0.04, 0.45, 30.0 / 365.0
    c = price_inverse_btc(S, K, r, sig, T, "call")
    p = price_inverse_btc(S, K, r, sig, T, "put")
    assert c > 0.0
    assert p > 0.0

    F = S * math.exp(r * T)
    parity = c - p
    expected_parity = math.exp(-r * T) * (1.0 - K / F)
    assert abs(parity - expected_parity) < 1e-9


def test_inverse_put_parity_general() -> None:
    """Inverse put-call parity: C - P = exp(-rT)·(1 - K/F)."""
    S, K, r, sig, T = 95000.0, 100000.0, 0.04, 0.50, 0.1
    F = S * math.exp(r * T)  # q = 0
    c = price_inverse_btc(S, K, r, sig, T, "call")
    p = price_inverse_btc(S, K, r, sig, T, "put")
    expected = math.exp(-r * T) * (1.0 - K / F)
    assert abs(c - p - expected) < 1e-9


def test_inverse_call_settlement_consistency() -> None:
    """At T≈0 the inverse price should approach the settlement value."""
    S, K = 125000.0, 100000.0
    p = price_inverse_btc(S, K, 0.04, 0.45, 1e-8, "call")
    expected = settlement_inverse_call_holder(S, K)
    assert abs(p - expected) < 1e-4


def test_inverse_put_settlement_consistency() -> None:
    S, K = 80000.0, 100000.0
    p = price_inverse_btc(S, K, 0.04, 0.45, 1e-8, "put")
    expected = settlement_inverse_put_holder(S, K)
    assert abs(p - expected) < 1e-4


def test_inverse_call_price_non_negative() -> None:
    """Inverse call price >= 0 for all valid inputs."""
    for kind in ("call", "put"):
        p = price_inverse_btc(50000.0, 100000.0, 0.05, 0.80, 1.0, kind)
        assert p >= 0.0


def test_inverse_call_price_zero_vol() -> None:
    """At zero vol, inverse call = max(0, exp(-rT)·(1 - K/F))."""
    S, K, r, T = 100000.0, 95000.0, 0.04, 0.5
    F = S * math.exp(r * T)
    c = price_inverse_btc(S, K, r, 1e-12, T, "call")
    expected = max(0.0, math.exp(-r * T) * (1.0 - K / F))
    assert abs(c - expected) < 1e-4


# ═══════════════════════════════════════════════════════════════════════════════
# Finite-difference Greek cross-checks
# ═══════════════════════════════════════════════════════════════════════════════


def test_bs_greeks_by_fd() -> None:
    """Black-Scholes analytical Greeks match central finite differences."""
    S, K, r, sig, T = 100.0, 100.0, 0.05, 0.20, 1.0
    q = greeks(S, K, r, sig, T, "call")

    h_s = 1e-4
    fd_delta = (price(S + h_s, K, r, sig, T) - price(S - h_s, K, r, sig, T)) / (2 * h_s)
    assert abs(q.delta - fd_delta) < 1e-4

    fd_gamma = (price(S + h_s, K, r, sig, T) - 2 * price(S, K, r, sig, T) + price(S - h_s, K, r, sig, T)) / (h_s * h_s)
    assert abs(q.gamma - fd_gamma) < 1e-6

    h_v = 1e-4
    fd_vega = (price(S, K, r, sig + h_v, T) - price(S, K, r, sig - h_v, T)) / (2 * h_v)
    assert abs(q.vega - fd_vega) < 1e-4

    h_t = 1e-6
    fd_theta = -(price(S, K, r, sig, T + h_t) - price(S, K, r, sig, T - h_t)) / (2 * h_t)
    assert abs(q.theta - fd_theta) < 1e-4


def test_black76_greeks_by_fd() -> None:
    """Black-76 analytical Greeks match central finite differences."""
    F, X, r, sig, T = 20.0, 19.0, 0.05, 0.25, 0.5
    q = greeks_black76(F, X, r, sig, T, "call")

    h_f = 1e-3
    fd_delta = (price_black76(F + h_f, X, r, sig, T) - price_black76(F - h_f, X, r, sig, T)) / (2 * h_f)
    assert abs(q.delta - fd_delta) < 1e-4

    fd_gamma = (price_black76(F + h_f, X, r, sig, T) - 2 * price_black76(F, X, r, sig, T) + price_black76(F - h_f, X, r, sig, T)) / (h_f * h_f)
    assert abs(q.gamma - fd_gamma) < 1e-6

    h_v = 1e-4
    fd_vega = (price_black76(F, X, r, sig + h_v, T) - price_black76(F, X, r, sig - h_v, T)) / (2 * h_v)
    assert abs(q.vega - fd_vega) < 1e-4

    h_t = 1e-6
    fd_theta = -(price_black76(F, X, r, sig, T + h_t) - price_black76(F, X, r, sig, T - h_t)) / (2 * h_t)
    assert abs(q.theta - fd_theta) < 1e-4


def test_black76_put_greeks_by_fd() -> None:
    """Black-76 put analytical Greeks match finite differences."""
    F, X, r, sig, T = 20.0, 21.0, 0.05, 0.25, 0.5
    q = greeks_black76(F, X, r, sig, T, "put")

    h_f = 1e-3
    fd_delta = (price_black76(F + h_f, X, r, sig, T, "put") - price_black76(F - h_f, X, r, sig, T, "put")) / (2 * h_f)
    assert abs(q.delta - fd_delta) < 1e-4


def test_inverse_greeks_by_fd() -> None:
    """Inverse BTC finite-difference Greeks are internally consistent
    (the greeks_inverse_btc function itself uses FD, so cross-validate
    with coarser step sizes to ensure no coding errors)."""
    S, K, r, sig, T = 100000.0, 95000.0, 0.04, 0.50, 0.25
    q = greeks_inverse_btc(S, K, r, sig, T, "call")

    h_s = 10.0
    fd_delta = (price_inverse_btc(S + h_s, K, r, sig, T) - price_inverse_btc(S - h_s, K, r, sig, T)) / (2 * h_s)
    assert abs(q.delta - fd_delta) < 1e-6

    fd_gamma = (price_inverse_btc(S + h_s, K, r, sig, T) - 2 * price_inverse_btc(S, K, r, sig, T) + price_inverse_btc(S - h_s, K, r, sig, T)) / (h_s * h_s)
    assert abs(q.gamma - fd_gamma) < 1e-6

    h_v = 5e-4
    fd_vega = (price_inverse_btc(S, K, r, sig + h_v, T) - price_inverse_btc(S, K, r, sig - h_v, T)) / (2 * h_v)
    assert abs(q.vega - fd_vega) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# Delta inversion tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_strike_for_delta_call_range() -> None:
    """Call delta ∈ [0,1] should produce valid strikes."""
    for d in (0.05, 0.25, 0.50, 0.75, 0.95):
        K = strike_for_delta(50000.0, d, 0.04, 0.45, 0.1, "call")
        assert K > 0.0
        q = greeks(50000.0, K, 0.04, 0.45, 0.1, "call")
        assert abs(q.delta - d) < 1e-6


def test_strike_for_delta_put_range() -> None:
    """Put delta ∈ [-1,0] should produce valid strikes."""
    for d in (-0.05, -0.25, -0.50, -0.75, -0.95):
        K = strike_for_delta(50000.0, d, 0.04, 0.45, 0.1, "put")
        assert K > 0.0
        q = greeks(50000.0, K, 0.04, 0.45, 0.1, "put")
        assert abs(q.delta - d) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# Implied-volatility edge-case validation
# ═══════════════════════════════════════════════════════════════════════════════


def test_implied_vol_edge_cases() -> None:
    """IV converges for ITM, OTM, ATM."""
    for S_K in ((120.0, 100.0), (100.0, 120.0), (100.0, 100.0)):
        Sx, Kx = S_K
        c = price(Sx, Kx, 0.05, 0.30, 0.5, "call")
        iv = implied_vol(c, Sx, Kx, 0.05, 0.5, "call")
        assert abs(iv - 0.30) < 1e-5


def test_implied_vol_atm() -> None:
    """ATM IV recovery is tight."""
    c = price(100.0, 100.0, 0.05, 0.20, 0.25, "call")
    iv = implied_vol(c, 100.0, 100.0, 0.05, 0.25, "call")
    assert abs(iv - 0.20) < 1e-5


def test_implied_vol_deep_otm() -> None:
    """Deep OTM call still recovers IV within tolerance."""
    c = price(100.0, 150.0, 0.05, 0.30, 0.25, "call")
    assert c > 0.0
    iv = implied_vol(c, 100.0, 150.0, 0.05, 0.25, "call")
    assert abs(iv - 0.30) < 1e-5


def test_implied_vol_deep_itm() -> None:
    """Deep ITM call recovers IV."""
    c = price(100.0, 50.0, 0.05, 0.30, 0.25, "call")
    iv = implied_vol(c, 100.0, 50.0, 0.05, 0.25, "call")
    assert abs(iv - 0.30) < 1e-5


def test_premium_pct_at_delta_edge() -> None:
    """premium_pct_at_delta returns reasonable values at edge deltas."""
    for d in (0.05, 0.95):
        pct, K = premium_pct_at_delta(65000.0, d, 0.04, 0.45, 30.0, "call")
        assert 0.0 < pct < 100.0
        assert K > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Vectorised grid pricing tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_price_grid_shape() -> None:
    """Grid output has correct shape (M strikes x N expiries)."""
    Ks = np.array([90000.0, 100000.0, 110000.0])
    Ts = np.array([0.08, 0.16, 0.25, 0.50])
    result = price_grid(100000.0, Ks, 0.04, 0.45, Ts, "call")
    assert result.shape == (3, 4)


def test_price_grid_matches_scalar() -> None:
    """Grid prices match scalar BS prices at each point."""
    Ks = np.array([80000.0, 100000.0, 120000.0])
    Ts = np.array([0.05, 0.25, 0.75])
    S = 100000.0
    r, sig = 0.04, 0.45

    grid = price_grid(S, Ks, r, sig, Ts, "call")
    for i, K in enumerate(Ks):
        for j, T in enumerate(Ts):
            expected = price(S, K, r, sig, T, "call")
            assert abs(grid[i, j] - expected) < 1e-9


def test_price_grid_put() -> None:
    """Grid with put kind matches scalar put prices."""
    Ks = np.array([95000.0, 100000.0, 105000.0])
    Ts = np.array([0.05, 0.10])
    S, r, sig = 100000.0, 0.04, 0.45
    grid = price_grid(S, Ks, r, sig, Ts, "put")
    for i, K in enumerate(Ks):
        for j, T in enumerate(Ts):
            expected = price(S, K, r, sig, T, "put")
            assert abs(grid[i, j] - expected) < 1e-9


def test_price_grid_no_nan() -> None:
    """Grid output has no NaN or inf."""
    Ks = np.linspace(50000.0, 200000.0, 10)
    Ts = np.array([0.01, 0.1, 0.5, 1.0])
    result = price_grid(100000.0, Ks, 0.04, 0.45, Ts, "call")
    assert np.all(np.isfinite(result))


def test_price_grid_zero_vol() -> None:
    """Grid with zero vol handles edge case."""
    Ks = np.array([90000.0, 100000.0])
    Ts = np.array([0.25])
    result = price_grid(100000.0, Ks, 0.04, 0.0, Ts, "call")
    assert np.all(np.isfinite(result))


# ═══════════════════════════════════════════════════════════════════════════════
# Payoff functions
# ═══════════════════════════════════════════════════════════════════════════════


def test_payoff_bs_call() -> None:
    assert payoff_bs_call(120.0, 100.0) == 20.0
    assert payoff_bs_call(80.0, 100.0) == 0.0


def test_payoff_bs_put() -> None:
    assert payoff_bs_put(80.0, 100.0) == 20.0
    assert payoff_bs_put(120.0, 100.0) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# OptionQuote preservation test (re-asserted for A1 scope)
# ═══════════════════════════════════════════════════════════════════════════════


def test_optionquote_preserved_a1() -> None:
    """OptionQuote fields are exactly (price, delta, gamma, vega, theta, strike)."""
    fields = {f.name for f in OptionQuote.__dataclass_fields__.values()}
    assert fields == {"price", "delta", "gamma", "vega", "theta", "strike"}


# ═══════════════════════════════════════════════════════════════════════════════
# Pure-function test (no config/params.yaml read)
# ═══════════════════════════════════════════════════════════════════════════════


def test_a1_pricing_no_yaml_read() -> None:
    """New A1 pricing modules do not import or read config/params.yaml."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for mod_name in ("pricing.black76", "pricing.inverse", "pricing.grid", "pricing.payoff"):
        mod_path = root / (mod_name.replace(".", "/") + ".py")
        content = mod_path.read_text()
        assert "import yaml" not in content, f"{mod_name} imports yaml"
        assert "from yaml" not in content, f"{mod_name} imports yaml"
        assert "params.yaml" not in content, f"{mod_name} references params.yaml"


# ═══════════════════════════════════════════════════════════════════════════════
# QuantLib parity tests (A1, A6 — §7.5, §13.5)
# ═══════════════════════════════════════════════════════════════════════════════


try:
    import QuantLib as ql
    _QL_AVAILABLE = True
except ImportError:
    _QL_AVAILABLE = False


@pytest.mark.skipif(not _QL_AVAILABLE, reason="QuantLib not installed")
def test_quantlib_bs_parity() -> None:
    """Black-Scholes vs QuantLib: max abs diff < 1e-6."""
    today = ql.Date(15, 7, 2026)
    ql.Settings.instance().evaluationDate = today
    day_counter = ql.Actual365Fixed()
    calendar = ql.UnitedStates(ql.UnitedStates.Settlement)

    test_cases = [
        (100.0, 100.0, 0.05, 0.20, 1.0, ql.Option.Call),
        (100.0, 100.0, 0.05, 0.20, 1.0, ql.Option.Put),
        (100.0, 120.0, 0.03, 0.30, 0.5, ql.Option.Call),
        (100.0, 80.0, 0.08, 0.15, 0.25, ql.Option.Call),
        (100.0, 80.0, 0.08, 0.15, 0.25, ql.Option.Put),
        (50000.0, 65000.0, 0.04, 0.65, 0.1, ql.Option.Call),
        (50000.0, 50000.0, 0.04, 0.10, 2.0, ql.Option.Call),
        (50000.0, 50000.0, 0.04, 0.10, 2.0, ql.Option.Put),
        (100.0, 100.0, 0.10, 0.50, 0.08, ql.Option.Call),
        (100.0, 50.0, 0.05, 0.25, 0.75, ql.Option.Call),
    ]

    max_err = 0.0
    for S, K, r, sig, T_approx, ql_kind in test_cases:
        days = int(T_approx * 365)
        expiry = today + days
        T = day_counter.yearFraction(today, expiry)  # exact QL year fraction

        payoff = ql.PlainVanillaPayoff(ql_kind, K)
        exercise = ql.EuropeanExercise(expiry)

        spot_handle = ql.QuoteHandle(ql.SimpleQuote(S))
        rf_ts = ql.YieldTermStructureHandle(ql.FlatForward(today, r, day_counter))
        div_ts = ql.YieldTermStructureHandle(ql.FlatForward(today, 0.0, day_counter))
        flat_vol_ts = ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(today, calendar, sig, day_counter)
        )

        process = ql.BlackScholesMertonProcess(spot_handle, div_ts, rf_ts, flat_vol_ts)
        option = ql.VanillaOption(payoff, exercise)
        engine = ql.AnalyticEuropeanEngine(process)
        option.setPricingEngine(engine)

        ql_price = option.NPV()

        kind_str = "call" if ql_kind == ql.Option.Call else "put"
        our_price = price(S, K, r, sig, T, kind_str)

        err = abs(ql_price - our_price)
        max_err = max(max_err, err)

    assert max_err < 1e-6, f"Max QuantLib BS diff: {max_err:.2e}"


@pytest.mark.skipif(not _QL_AVAILABLE, reason="QuantLib not installed")
def test_quantlib_black76_parity() -> None:
    """Black-76 vs QuantLib: max abs diff < 1e-4 (per contracts.md §7.5)."""
    today = ql.Date(15, 7, 2026)
    ql.Settings.instance().evaluationDate = today
    day_counter = ql.Actual365Fixed()
    calendar = ql.UnitedStates(ql.UnitedStates.Settlement)

    test_cases = [
        (19.0, 19.0, 0.10, 0.28, 0.75, ql.Option.Call),
        (19.0, 19.0, 0.10, 0.28, 0.75, ql.Option.Put),
        (20.0, 19.0, 0.05, 0.25, 0.5, ql.Option.Call),
        (20.0, 21.0, 0.05, 0.25, 0.5, ql.Option.Put),
        (100.0, 200.0, 0.05, 0.20, 0.25, ql.Option.Call),
        (100.0, 50.0, 0.05, 0.50, 0.75, ql.Option.Put),
        (100.0, 100.0, 0.10, 0.80, 0.08, ql.Option.Call),
        (100.0, 100.0, 0.02, 0.05, 2.0, ql.Option.Call),
    ]

    max_err = 0.0
    for F, X, r, sig, T_approx, ql_kind in test_cases:
        days = int(T_approx * 365)
        expiry = today + days
        T = day_counter.yearFraction(today, expiry)  # exact QL year fraction

        payoff = ql.PlainVanillaPayoff(ql_kind, X)
        exercise = ql.EuropeanExercise(expiry)

        spot_handle = ql.QuoteHandle(ql.SimpleQuote(F))
        rf_ts = ql.YieldTermStructureHandle(ql.FlatForward(today, r, day_counter))
        vol_ts = ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(today, calendar, sig, day_counter)
        )

        # Black-76 via BSM: set dividend yield = r, so drift = r-r = 0.
        process = ql.BlackScholesMertonProcess(spot_handle, rf_ts, rf_ts, vol_ts)
        option = ql.VanillaOption(payoff, exercise)
        engine = ql.AnalyticEuropeanEngine(process)
        option.setPricingEngine(engine)

        ql_price = option.NPV()

        kind_str = "call" if ql_kind == ql.Option.Call else "put"
        our_price = price_black76(F, X, r, sig, T, kind_str)

        err = abs(ql_price - our_price)
        max_err = max(max_err, err)

    assert max_err < 1e-4, f"Max QuantLib Black-76 diff: {max_err:.2e}"
