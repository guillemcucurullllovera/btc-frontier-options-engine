"""C8 R3 — property-based pricing tests (Tier-1 U14, Hypothesis).

Fuzzes Black-Scholes over (S, K, r, sigma, T) to catch edge cases no fixed vector
hits: non-negativity and intrinsic lower bounds, price bounds, monotonicity in
spot, put-call parity, delta bounds, and the implied-vol round-trip.
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pricing.black_scholes import greeks, implied_vol
from pricing.black_scholes import price as bs_price

_S = st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)
_K = st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)
_R = st.floats(min_value=-0.05, max_value=0.20, allow_nan=False, allow_infinity=False)
_SIG = st.floats(min_value=0.05, max_value=3.0, allow_nan=False, allow_infinity=False)
_T = st.floats(min_value=1.0 / 365.0, max_value=5.0, allow_nan=False, allow_infinity=False)


@given(_S, _K, _R, _SIG, _T, st.sampled_from(["call", "put"]))
@settings(max_examples=250, deadline=None)
def test_price_nonnegative_and_bounded(s: float, k: float, r: float, sig: float, t: float, kind: str) -> None:
    p = bs_price(s, k, r, sig, t, kind)
    assert p >= -1e-6
    df = math.exp(-r * t)
    if kind == "call":
        assert p <= s + 1e-6                       # call <= spot
        assert p >= max(s - k * df, 0.0) - 1e-4    # >= discounted intrinsic
    else:
        assert p <= k * df + 1e-6                   # put <= discounted strike
        assert p >= max(k * df - s, 0.0) - 1e-4


@given(_S, _K, _R, _SIG, _T)
@settings(max_examples=250, deadline=None)
def test_put_call_parity(s: float, k: float, r: float, sig: float, t: float) -> None:
    c = bs_price(s, k, r, sig, t, "call")
    p = bs_price(s, k, r, sig, t, "put")
    assert (c - p) == pytest.approx(s - k * math.exp(-r * t), rel=1e-6, abs=1e-4)


@given(_S, _K, _R, _SIG, _T)
@settings(max_examples=200, deadline=None)
def test_call_monotonic_in_spot(s: float, k: float, r: float, sig: float, t: float) -> None:
    bump = max(s * 0.01, 1.0)
    assert bs_price(s + bump, k, r, sig, t, "call") >= bs_price(s, k, r, sig, t, "call") - 1e-6
    assert bs_price(s + bump, k, r, sig, t, "put") <= bs_price(s, k, r, sig, t, "put") + 1e-6


@given(_S, _K, _R, _SIG, _T, st.sampled_from(["call", "put"]))
@settings(max_examples=200, deadline=None)
def test_delta_bounds(s: float, k: float, r: float, sig: float, t: float, kind: str) -> None:
    d = greeks(s, k, r, sig, t, kind).delta
    if kind == "call":
        assert -1e-9 <= d <= 1.0 + 1e-9
    else:
        assert -1.0 - 1e-9 <= d <= 1e-9


@given(
    st.floats(min_value=50.0, max_value=200.0),
    st.floats(min_value=50.0, max_value=200.0),
    st.floats(min_value=0.0, max_value=0.1),
    st.floats(min_value=0.10, max_value=2.0),
    st.floats(min_value=0.05, max_value=2.0),
    st.sampled_from(["call", "put"]),
)
@settings(max_examples=200, deadline=None)
def test_implied_vol_roundtrip(s: float, k: float, r: float, sig: float, t: float, kind: str) -> None:
    target = bs_price(s, k, r, sig, t, kind)
    assume(target > 1e-3)
    assume(greeks(s, k, r, sig, t, kind).vega > 1e-2)  # IV well-conditioned only where vega > 0
    iv = implied_vol(target, s, k, r, t, kind)
    # Defining property of IV: repricing at iv reproduces the target price.
    assert bs_price(s, k, r, iv, t, kind) == pytest.approx(target, rel=1e-6, abs=1e-6)
