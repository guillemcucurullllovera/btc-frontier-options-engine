"""In-house inverse-payoff transform for the CF spine (C9 · M1.5).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. No library source exists for the
Deribit inverse-payoff transform, so it is derived in-house two independent ways and cross-checked:

DERIVATION (why inverse_BTC = USD_vanilla / S0). A Deribit inverse call pays (S_T - K)^+ / S_T BTC
at expiry and the premium is paid in BTC. The USD value at t0 of that BTC settlement is
    e^{-rT} E^Q[ ((S_T - K)^+ / S_T) * S_T ]  =  e^{-rT} E^Q[ (S_T - K)^+ ]  =  vanilla_USD_call,
because converting the BTC settlement back to USD at S_T cancels the 1/S_T. The BTC premium is that
USD value converted at the t0 spot S0, so

    inverse_call_BTC = cos_vanilla_USD(model, S0, K, T) / S0.

This generalises the M0 identity price_inverse_btc * S == BS_USD to ANY CF model. Two computations:
  1. ``inverse_option_price`` — the identity above (COS USD vanilla / S0), the primary path.
  2. ``inverse_option_price_stock_measure`` — direct COS of the BTC payoff (1 - K/S_T)^+ under the
     STOCK (share) numeraire, whose CF is the Esscher tilt phi^S(u)=phi_R(u-i)/phi_R(-i) and whose
     price carries the e^{-qT} stock-numeraire discount. An independent cross-check.

Validated vs the M0 closed form price_inverse_btc at q=0 AND q>0 (machine eps for GBM), vs
Carr-Madan/S0 (Heston), and by inverse put-call parity C_inv - P_inv = e^{-qT}(1 - K/F).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pricing.cf.characteristic_functions import CharModel, CumTuple, numerical_cumulants
from pricing.cf.cos import cos_price, cos_truncation

Complex = npt.NDArray[np.complex128]
FloatArr = npt.NDArray[np.float64]


# ── Primary: the price_BTC * S == USD-vanilla identity ───────────────────────


def inverse_option_price(model: CharModel, S0: float, K: float, T: float, kind: str = "call",
                         N: int = 1024, L: float = 14.0) -> float:
    """Inverse-BTC option price (BTC per 1 BTC contract) = COS USD vanilla / S0."""
    return cos_price(model, S0, K, T, kind, N=N, L=L) / S0


# ── Cross-check: direct COS under the stock (share) numeraire ────────────────


@dataclass(frozen=True)
class StockMeasureModel:
    """Esscher t=1 tilt of a base model: phi^S(u) = phi_R(u - i) / phi_R(-i) (share numeraire)."""

    base: CharModel

    @property
    def r(self) -> float:
        return self.base.r

    @property
    def q(self) -> float:
        return self.base.q

    def cf(self, u: complex | Complex, T: float) -> Complex:
        uu = np.asarray(u, dtype=np.complex128)
        num = self.base.cf(uu - 1j, T)
        den = self.base.cf(np.array([-1j], dtype=np.complex128), T)[0]
        return np.asarray(num / den, dtype=np.complex128)

    def cumulants(self, T: float) -> CumTuple:
        return numerical_cumulants(self, T)


def _chi_exp(k: FloatArr, a: float, b: float, c: float, d: float, alpha: float) -> FloatArr:
    """∫_c^d e^{alpha y} cos(k pi (y-a)/(b-a)) dy = [e^{alpha y}(alpha cos + w sin)]_c^d / (alpha^2+w^2)."""
    w = k * math.pi / (b - a)
    denom = alpha * alpha + w * w
    def term(y: float) -> FloatArr:
        return math.exp(alpha * y) * (alpha * np.cos(w * (y - a)) + w * np.sin(w * (y - a)))
    return (term(d) - term(c)) / denom


def _psi(k: FloatArr, a: float, b: float, c: float, d: float) -> FloatArr:
    w = k * math.pi / (b - a)
    out = np.empty_like(k)
    out[0] = d - c
    wk = w[1:]
    out[1:] = (np.sin(wk * (d - a)) - np.sin(wk * (c - a))) / wk
    return out


def inverse_option_price_stock_measure(model: CharModel, S0: float, K: float, T: float,
                                       kind: str = "call", N: int = 2048, L: float = 16.0) -> float:
    """Direct COS of the inverse BTC payoff (1 - K/S_T)^+ under the stock numeraire (cross-check).

    inverse_call_BTC = e^{-qT} E^{Q^S}[ (1 - e^{-y})^+ ],  y = ln(S_T/K), payoff on y in [0,b].
    Put via inverse parity. Uses the Esscher-tilted CF (share measure); no e^{-rT} discount here —
    the stock-numeraire discount is e^{-qT}.
    """
    sm = StockMeasureModel(model)
    a, b = cos_truncation(sm, S0, K, T, L)
    k = np.arange(N, dtype=np.float64)
    w = k * math.pi / (b - a)
    x = math.log(S0 / K)
    phi = sm.cf(w.astype(np.complex128), T)
    Fk = np.real(phi * np.exp(1j * w * (x - a)))
    wts = np.ones(N)
    wts[0] = 0.5
    # Call BTC payoff (1 - e^{-y})^+ on y in [max(0,a), b]; empty region => 0.
    lo = max(0.0, a)
    if lo >= b:
        call_btc = 0.0
    else:
        Uk_call = (2.0 / (b - a)) * (_psi(k, a, b, lo, b) - _chi_exp(k, a, b, lo, b, -1.0))
        call_btc = math.exp(-model.q * T) * float(np.sum(wts * Fk * Uk_call))
    if kind == "call":
        return call_btc
    # Inverse put-call parity in BTC: C_inv - P_inv = e^{-qT}(1 - K/F), F = S0 e^{(r-q)T}.
    F = S0 * math.exp((model.r - model.q) * T)
    return call_btc - math.exp(-model.q * T) * (1.0 - K / F)
