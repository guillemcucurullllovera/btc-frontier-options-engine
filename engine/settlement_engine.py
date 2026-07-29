"""Settlement engine — one settlement pathway per leg, producing a
`SettlementResult` (contracts.md §10.3) with provenance.

FRF-004 / FRF-025 (AT-004, AT-025): exactly ONE pathway per leg keyed on the
`SettlementSpec`; `contract_multiplier` is consumed; delivery price is honoured;
a cash-settled option NEVER also credits physical BTC. Placed in its own module
(not `engine/settlement.py`) so it can import `Leg` without an import cycle
(`engine.strategy` imports `engine.settlement`, not this module).

D-12 policy: a cash-settled outcome produces cash settlement only. Any BTC
acquisition after a cash settlement is a SEPARATE, explicit spot purchase modelled
by the backtest ledger — never a physical credit from the option itself.

FRF-013 / AT-013: delivery fee is accounted exactly once (gross settlement +
separate fee deduction). net_to_account is the gross settlement amount — the
backtest handles the fee deduction separately.

Venue guard (FRF-005 / D-3): CASH+BTC settlement pathway applies ONLY to
Venue.DERIBIT inverse options. OTC or CME legs with CASH+BTC raise
SettlementError rather than silently inheriting Deribit delivery-fee assumptions.
"""

from __future__ import annotations

from pydantic import BaseModel

from config.models import Provenance
from engine.errors import SettlementError
from engine.settlement import SettlementCurrency, SettlementMechanism, SettlementSpec, Venue
from engine.strategy import Leg
from pricing.inverse import (
    settlement_inverse_call_holder,
    settlement_inverse_put_holder,
)

# Deribit venue delivery fee: 0.015% of the underlying value per contract.
# For Deribit inverse options the underlying per contract is 1 BTC, so the fee is
# 0.015% * 1 BTC = 0.00015 BTC per contract. Capped at 12.5% of the option's
# settlement value (Deribit spec line 3755).
# `contracts` already includes contract_multiplier, so the per-contract fee
# scales correctly for any contract size (e.g. CME mult=5 → 5* the rate).
_DERIBIT_DELIVERY_FEE_RATE_BTC_PER_CONTRACT = 0.00015  # 0.015% of 1 BTC
_DERIBIT_DELIVERY_FEE_CAP_FRAC = 0.125  # 12.5% of option value


class SettlementResult(BaseModel):
    """What actually happens at expiry under venue rules (contracts §10.3).

    `settlement_amount` and `net_to_account` are the LONG HOLDER's gross
    receipts in `settlement_currency` — net_to_account is the GROSS amount
    (NOT net of delivery fee; the backtest handles the fee separately to avoid
    double-counting). The SHORT writer's cash flow is the negation (the
    backtest applies the sign). Quantities already include `contract_multiplier`.
    """

    model_config = {"arbitrary_types_allowed": True}

    leg: Leg
    settlement: SettlementSpec
    delivery_price: float
    is_itm: bool
    settlement_amount: float          # in settlement currency (BTC or USD), holder gross
    settlement_currency: SettlementCurrency
    venue_delivery_fee: float         # in settlement currency (before contract scaling; may be zero)
    net_to_account: float             # gross settlement (same as settlement_amount) — fee deducted by backtest
    contracts: float                  # quantity x contract_multiplier
    provenance: Provenance = Provenance.CALCULATED


def _holder_is_itm(option_type: str, delivery_price: float, strike: float) -> bool:
    if option_type == "call":
        return delivery_price > strike
    return delivery_price < strike


def _deribit_delivery_fee(btc_per_contract: float, contracts: float) -> float:
    """Delivery fee per the Deribit spec (line 3755): 0.015% of underlying with
    12.5%-of-option-value cap.

    `btc_per_contract` is the gross settlement per 1-contract-unit (not
    yet multiplied by contracts). `contracts` already includes the multiplier.
    """
    fee_per = min(
        _DERIBIT_DELIVERY_FEE_RATE_BTC_PER_CONTRACT,
        _DERIBIT_DELIVERY_FEE_CAP_FRAC * btc_per_contract,
    )
    return fee_per * contracts


def settle_leg(
    leg: Leg,
    delivery_price: float,
    provenance: Provenance = Provenance.CALCULATED,
) -> SettlementResult:
    """Settle one option leg at `delivery_price` via its single venue pathway.

    Returns the LONG HOLDER's gross/net settlement. Raises `SettlementError`
    for an unsupported / undocumented venue-mechanism combination rather than
    inheriting another venue's assumptions (D-3 policy).

    Venue-guard (FRF-005 / D-3): CASH + BTC settlement only applies to
    Deribit inverse options. Other venue * mechanism * currency combos must
    be explicitly enumerated or raise SettlementError.
    """
    spec = leg.settlement
    if spec is None or leg.option_type is None or leg.strike is None:
        raise SettlementError(f"settle_leg requires an option leg with a settlement spec: {leg.instrument}")
    if delivery_price <= 0.0:
        raise SettlementError(f"delivery_price must be positive, got {delivery_price}")

    strike = leg.strike
    mult = spec.contract_multiplier
    contracts = leg.quantity * mult
    itm = _holder_is_itm(leg.option_type, delivery_price, strike)
    mech = spec.settlement_mechanism
    ccy = spec.settlement_currency
    venue = spec.venue

    # Venue-guard: CASH + BTC is ONLY for Deribit inverse options.
    # OTC / CME with CASH+BTC is unsupported — must be explicitly configured.
    if mech is SettlementMechanism.CASH and ccy is SettlementCurrency.BTC:
        if venue is not Venue.DERIBIT:
            raise SettlementError(
                f"CASH + BTC settlement is only supported for Venue.DERIBIT. "
                f"Got venue={venue}, product={spec.product}. "
                f"Configure an explicit pathway for this combination rather than "
                f"inheriting Deribit assumptions."
            )
        # Deribit inverse: cash-settled in BTC. Holder BTC per contract.
        if leg.option_type == "call":
            btc_per = settlement_inverse_call_holder(delivery_price, strike)
        else:
            btc_per = settlement_inverse_put_holder(delivery_price, strike)
        amount = contracts * btc_per
        # Delivery fee: computed here, deducted ONCE by the backtest ledger.
        fee = _deribit_delivery_fee(btc_per, contracts) if itm else 0.0
        return SettlementResult(
            leg=leg, settlement=spec, delivery_price=delivery_price, is_itm=itm,
            settlement_amount=amount, settlement_currency=ccy,
            venue_delivery_fee=fee,
            net_to_account=amount,  # gross — fee deducted separately by backtest
            contracts=contracts, provenance=provenance,
        )

    if mech in (SettlementMechanism.CASH, SettlementMechanism.FUTURES_DELIVERY_THEN_CASH) \
            and ccy in (SettlementCurrency.USD, SettlementCurrency.USDC):
        usd_per = max(delivery_price - strike, 0.0) if leg.option_type == "call" else max(strike - delivery_price, 0.0)
        amount = contracts * usd_per
        return SettlementResult(
            leg=leg, settlement=spec, delivery_price=delivery_price, is_itm=itm,
            settlement_amount=amount, settlement_currency=ccy,
            venue_delivery_fee=0.0,
            net_to_account=amount,  # gross — no venue delivery fee for USD/C-settled
            contracts=contracts, provenance=provenance,
        )

    if mech is SettlementMechanism.PHYSICAL_UNDERLYING:
        usd_per = max(delivery_price - strike, 0.0) if leg.option_type == "call" else max(strike - delivery_price, 0.0)
        amount = contracts * usd_per
        return SettlementResult(
            leg=leg, settlement=spec, delivery_price=delivery_price, is_itm=itm,
            settlement_amount=amount, settlement_currency=ccy,
            venue_delivery_fee=0.0,
            net_to_account=amount,  # gross
            contracts=contracts, provenance=provenance,
        )

    raise SettlementError(
        f"Unsupported settlement combination: mechanism={mech.value}, currency={ccy.value}, "
        f"venue={venue.value}, product={spec.product}. "
        f"Configure it explicitly rather than inheriting assumptions."
    )
