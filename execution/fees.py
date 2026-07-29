"""Unified fee engine (WP-B7 / FRF-013 / AT-013).

One reconciled fee ledger per strategy. Keyed on venue/product via the
`SettlementSpec`:

  * Deribit BTC legs pay the documented Deribit trading fee
    MIN(0.0003 BTC, 0.125 x option_price_BTC) x contracts, and the delivery fee
    is handled by the settlement engine.
  * OTC legs pay NO Deribit venue fee.
  * The Asymmetrica 0.5% execution fee is modelled SEPARATELY and counted
    EXACTLY ONCE per strategy, on the D-1 base.

D-1 is NOT resolved and NOT defaulted: `asymmetrica_fee_both_variants` returns
BOTH variants. Reference cases (30,000 BTC @ $65,000 spot, 2.5% discount, 0.5%):
  * reference notional     → $9,750,000
  * executed/discounted    → $9,506,250
"""

from __future__ import annotations

from dataclasses import dataclass

from config.models import Provenance
from engine.settlement import SettlementCurrency, SettlementSpec, Venue

# Deribit option trading fee (spec lines 3572-3574): MIN(0.0003 BTC, 12.5% of
# the option price) per contract.
_DERIBIT_TRADING_FEE_FLAT_BTC = 0.0003
_DERIBIT_TRADING_FEE_PREMIUM_FRAC = 0.125


@dataclass(frozen=True)
class AsymmetricaFee:
    """The Asymmetrica execution fee under BOTH unresolved D-1 bases."""

    fee_pct: float                         # decimal, e.g. 0.005
    reference_notional_usd: float          # qty x reference spot
    executed_notional_usd: float           # qty x reference spot x (1 - discount)
    reference_notional_fee_usd: float      # D-1 variant A
    executed_notional_fee_usd: float       # D-1 variant B
    provenance: Provenance = Provenance.BUSINESS_REQUIREMENT
    pending_decision_refs: tuple[str, ...] = ("D-1",)

    def fee_for(self, fee_base: str) -> float:
        if fee_base == "reference_notional":
            return self.reference_notional_fee_usd
        if fee_base == "executed_volume":
            return self.executed_notional_fee_usd
        raise ValueError(
            f"fee_base must be 'reference_notional' or 'executed_volume' (D-1); "
            f"got {fee_base!r} — the engine must not silently default D-1."
        )


def asymmetrica_fee_both_variants(
    reference_btc: float,
    reference_spot_usd: float,
    fee_pct: float,
    seller_discount_pct: float,
) -> AsymmetricaFee:
    """Both D-1 fee-base variants for the Asymmetrica execution fee.

    `fee_pct` and `seller_discount_pct` are decimals (0.005, 0.025).
    """
    if reference_btc < 0 or reference_spot_usd < 0 or fee_pct < 0:
        raise ValueError("asymmetrica_fee_both_variants requires non-negative inputs")
    ref_notional = reference_btc * reference_spot_usd
    exec_notional = ref_notional * (1.0 - seller_discount_pct)
    return AsymmetricaFee(
        fee_pct=fee_pct,
        reference_notional_usd=ref_notional,
        executed_notional_usd=exec_notional,
        reference_notional_fee_usd=fee_pct * ref_notional,
        executed_notional_fee_usd=fee_pct * exec_notional,
    )


def deribit_trading_fee_btc(option_price_btc: float, contracts: float) -> float:
    """Deribit per-leg option trading fee in BTC (spec 3572-3574).

    Applies ONLY to Deribit BTC-settled legs. `option_price_btc` is the
    per-contract premium in BTC; `contracts` = quantity x contract_multiplier.
    """
    if option_price_btc <= 0.0 or contracts <= 0.0:
        return 0.0
    per_contract = min(_DERIBIT_TRADING_FEE_FLAT_BTC, _DERIBIT_TRADING_FEE_PREMIUM_FRAC * option_price_btc)
    return per_contract * contracts


def leg_trading_fee(
    spec: SettlementSpec,
    option_price_quote_ccy: float,
    contracts: float,
    spot_usd: float,
) -> tuple[float, float]:
    """Venue trading fee for one option leg → (fee_usd, fee_btc).

    Deribit BTC legs pay the Deribit formula (premium is quoted in BTC). Every
    other venue/product (OTC, CME, linear) pays NO Deribit venue fee here — a
    unit-mismatch on USD-quoted OTC premiums is thereby avoided (FRF-013).
    """
    if (spec.venue is Venue.DERIBIT
            and spec.settlement_currency is SettlementCurrency.BTC):
        fee_btc = deribit_trading_fee_btc(option_price_quote_ccy, contracts)
        return fee_btc * spot_usd, fee_btc
    return 0.0, 0.0
