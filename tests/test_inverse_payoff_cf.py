"""C9 · M1.5 — in-house inverse-payoff transform for the CF spine.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. No calibration/live data.

Oracles: the M0 closed-form ``price_inverse_btc`` (GBM, q=0 and q>0); two independent in-house
derivations (USD-vanilla/S0 identity vs direct COS of (1-K/S_T)^+ under the stock numeraire);
Carr-Madan/S0 (independent numerical method); the inverse BTC put-call parity identity.
"""

from __future__ import annotations

import math

import pytest

from pricing.cf.carr_madan import carr_madan_call
from pricing.cf.characteristic_functions import GBM, Heston
from pricing.cf.inverse_payoff import (
    inverse_option_price,
    inverse_option_price_stock_measure,
)
from pricing.inverse import price_inverse_btc

_S0 = 60_000.0
_T = 45.0 / 365.0
_HESTON = Heston(r=0.0, q=0.0, v0=0.30, kappa=1.5, theta=0.30, sigma=0.6, rho=-0.4)


@pytest.mark.parametrize("r,q,sigma", [(0.0, 0.0, 0.55), (0.04, 0.0, 0.60), (0.04, 0.05, 0.50)])
def test_inverse_identity_matches_m0_closed_form(r: float, q: float, sigma: float) -> None:
    """inverse_BTC = COS_USD/S0 matches the M0 closed form price_inverse_btc (machine eps, any q)."""
    m = GBM(r=r, q=q, sigma=sigma)
    for K in (48_000.0, 60_000.0, 72_000.0):
        for kind in ("call", "put"):
            cf_px = inverse_option_price(m, _S0, K, _T, kind, N=1024, L=14.0)
            m0_px = price_inverse_btc(_S0, K, r, sigma, _T, kind, q)
            assert cf_px == pytest.approx(m0_px, abs=1e-12)


def test_inverse_stock_measure_matches_m0_closed_form() -> None:
    """The direct stock-numeraire COS of (1-K/S_T)^+ also matches the M0 closed form."""
    m = GBM(r=0.04, q=0.02, sigma=0.55)
    for K in (48_000.0, 60_000.0, 72_000.0):
        for kind in ("call", "put"):
            sm_px = inverse_option_price_stock_measure(m, _S0, K, _T, kind, N=2048, L=16.0)
            m0_px = price_inverse_btc(_S0, K, 0.04, 0.55, _T, kind, 0.02)
            assert sm_px == pytest.approx(m0_px, abs=1e-10)


def test_inverse_two_derivations_agree_under_heston() -> None:
    """USD-vanilla/S0 identity == direct stock-numeraire COS for Heston (independent derivations)."""
    for K in (48_000.0, 60_000.0, 75_000.0):
        for kind in ("call", "put"):
            a = inverse_option_price(_HESTON, _S0, K, _T, kind, N=2048, L=16.0)
            c = inverse_option_price_stock_measure(_HESTON, _S0, K, _T, kind, N=2048, L=16.0)
            assert a == pytest.approx(c, abs=1e-10)


def test_inverse_put_call_parity_btc() -> None:
    """C_inv - P_inv = e^{-qT}(1 - K/F),  F = S0 e^{(r-q)T}  (inverse BTC parity)."""
    m = Heston(r=0.03, q=0.01, v0=0.25, kappa=1.2, theta=0.25, sigma=0.5, rho=-0.5)
    F = _S0 * math.exp((m.r - m.q) * _T)
    for K in (55_000.0, 65_000.0):
        ci = inverse_option_price(m, _S0, K, _T, "call", N=2048, L=16.0)
        pi = inverse_option_price(m, _S0, K, _T, "put", N=2048, L=16.0)
        expected = math.exp(-m.q * _T) * (1.0 - K / F)
        assert (ci - pi) == pytest.approx(expected, abs=1e-10)


def test_inverse_via_carr_madan_cross_check() -> None:
    """Inverse Heston via an INDEPENDENT method (Carr-Madan/S0) matches the COS identity."""
    for K in (50_000.0, 60_000.0, 70_000.0):
        cos_inv = inverse_option_price(_HESTON, _S0, K, _T, "call", N=2048, L=16.0)
        cm_inv = carr_madan_call(_HESTON, _S0, K, _T, alpha=1.5, v_max=800.0, n=16384) / _S0
        assert cos_inv == pytest.approx(cm_inv, abs=1e-6)


def test_inverse_deep_itm_limit() -> None:
    """Deep-ITM inverse call (K -> 0): price -> e^{-qT} BTC (M0 anchor), for a CF model too."""
    m = Heston(r=0.02, q=0.03, v0=0.2, kappa=1.5, theta=0.2, sigma=0.5, rho=-0.4)
    px = inverse_option_price(m, _S0, 1.0, _T, "call", N=4096, L=18.0)
    assert px == pytest.approx(math.exp(-m.q * _T), abs=1e-4)
