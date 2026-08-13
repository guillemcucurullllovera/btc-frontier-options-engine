"""C9 · M1.4 — Lugannani-Rice saddlepoint for the deep-OTM wings + COS breakdown boundary.

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. No calibration/live data.

Oracles: the GBM saddlepoint is validated against Black-Scholes across the whole moneyness range
(including the far tail where COS returns negative garbage); the Heston saddlepoint is an
asymptotic wing approximation validated to within a documented tolerance of COS; the COS
breakdown boundary is measured and shown to move outward with the truncation width L.
"""

from __future__ import annotations

import math

import pytest

from pricing.black_scholes import price as bs_price
from pricing.cf.characteristic_functions import GBM, Heston
from pricing.cf.cos import cos_call
from pricing.cf.saddlepoint import (
    _strip_edge,
    cos_breakdown_strike,
    saddlepoint_call,
    saddlepoint_price,
    wing_price,
)

_GBM = GBM(r=0.05, q=0.0, sigma=0.25)
_HESTON = Heston(r=0.0, q=0.0, v0=0.0175, kappa=1.5768, theta=0.0398, sigma=0.5751, rho=-0.5711)


def test_saddlepoint_gbm_matches_bs_across_moneyness() -> None:
    """GBM Lugannani-Rice call matches Black-Scholes from ATM into the deep tail (rel < 1e-4)."""
    max_rel = 0.0
    for K in (100.0, 130.0, 160.0, 200.0, 300.0, 400.0, 500.0):
        b = bs_price(100.0, K, 0.05, 0.25, 1.0, "call")
        sp = saddlepoint_call(_GBM, 100.0, K, 1.0)
        assert sp.valid
        max_rel = max(max_rel, abs(sp.price - b) / b)
    assert max_rel < 1e-4, f"max GBM saddlepoint rel-err = {max_rel:.2e}"


def test_saddlepoint_matches_bs_deep_where_price_is_resolvable() -> None:
    """GBM saddlepoint stays accurate down to a price ~1e-9 (K=500), an independent tail check."""
    sp = saddlepoint_call(_GBM, 100.0, 500.0, 1.0)
    bs = bs_price(100.0, 500.0, 0.05, 0.25, 1.0, "call")
    assert sp.valid and sp.price > 0.0
    assert sp.price == pytest.approx(bs, rel=1e-3)          # price ~1.8e-9, rel-err ~4e-6


def test_wing_router_recovers_positive_price_where_default_cos_breaks() -> None:
    """At the Heston COS(default) breakdown strike, the wing router recovers a correct positive price."""
    Kb = cos_breakdown_strike(_HESTON, 100.0, 1.0, "call", N=256, L=12.0)   # ~246
    assert cos_call(_HESTON, 100.0, Kb, 1.0, N=256, L=12.0) <= 0.0          # default COS broke here
    ref = cos_call(_HESTON, 100.0, Kb, 1.0, N=4096, L=24.0)                 # high-accuracy reference
    wp = wing_price(_HESTON, 100.0, Kb, 1.0, "call")
    assert wp.price > 0.0
    assert wp.price == pytest.approx(ref, rel=0.1)          # large-L COS / saddlepoint recovers it


def test_saddlepoint_heston_within_documented_tolerance() -> None:
    """Heston saddlepoint (first-order asymptotic) agrees with COS to within ~15% in the overlap."""
    max_rel = 0.0
    for K in (95.0, 100.0, 130.0, 160.0, 200.0):
        ref = cos_call(_HESTON, 100.0, K, 1.0, N=4096, L=20.0)
        sp = saddlepoint_call(_HESTON, 100.0, K, 1.0)
        assert sp.valid and sp.price > 0.0
        max_rel = max(max_rel, abs(sp.price - ref) / ref)
    assert max_rel < 0.15, f"Heston saddlepoint overlap rel-err = {max_rel:.2%}"


def test_analyticity_strip_bounded_for_heston_open_for_gbm() -> None:
    """Heston has a bounded MGF strip (moment explosion); GBM's is effectively unbounded."""
    h_lo, h_hi = _strip_edge(_HESTON, 1.0, -1.0), _strip_edge(_HESTON, 1.0, +1.0)
    assert -20.0 < h_lo < 0.0 < h_hi < 30.0                # finite, bracketing 0
    g_hi = _strip_edge(_GBM, 1.0, +1.0)
    assert g_hi > 30.0                                      # GBM CGF convex everywhere -> hits the cap


def test_cos_breakdown_boundary_moves_out_with_L() -> None:
    """The COS deep-OTM breakdown strike increases with the truncation width L (documented knob)."""
    k_heston_l12 = cos_breakdown_strike(_HESTON, 100.0, 1.0, "call", N=256, L=12.0)
    k_heston_l24 = cos_breakdown_strike(_HESTON, 100.0, 1.0, "call", N=4096, L=24.0)
    k_gbm_l10 = cos_breakdown_strike(_GBM, 100.0, 1.0, "call", N=256, L=10.0)
    assert math.isfinite(k_heston_l12) and math.isfinite(k_heston_l24)
    assert k_heston_l24 > k_heston_l12                      # larger L => COS valid further out
    # Heston's fat tail breaks COS far earlier than GBM's.
    assert k_heston_l12 < k_gbm_l10


def test_wing_router_positive_in_deep_wing() -> None:
    """wing_price returns positive prices through the deep wing, switching COS->saddlepoint."""
    methods = set()
    for K in (150.0, 300.0, 600.0, 1000.0):
        wp = wing_price(_HESTON, 100.0, K, 1.0, "call")
        assert wp.price >= 0.0 and math.isfinite(wp.price)
        methods.add(wp.method)
    assert "cos" in methods                                 # COS used where valid
    # The extreme wing where even L=24 COS fails routes to the saddlepoint.
    assert wing_price(_HESTON, 100.0, 1000.0, 1.0, "call").method == "saddlepoint"


def test_saddlepoint_put_call_parity() -> None:
    """Saddlepoint put (via parity) + parity identity is self-consistent for GBM."""
    S0, K, T = 100.0, 130.0, 1.0
    c = saddlepoint_price(_GBM, S0, K, T, "call")
    p = saddlepoint_price(_GBM, S0, K, T, "put")
    parity = S0 * math.exp(-_GBM.q * T) - K * math.exp(-_GBM.r * T)
    assert (c - p) == pytest.approx(parity, abs=1e-10)
