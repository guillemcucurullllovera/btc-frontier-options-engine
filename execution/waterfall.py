"""Price/fee waterfall calculator (mandate Sec. 2.2). Reads config/params.yaml.

Run:  python3 -m execution.waterfall  (from btc_engine/)

Phase 0: typed, file-handle leak fixed.  Preserves exact numerical behaviour
and public compatibility with existing tests.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

CFG: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "config" / "params.yaml"
)


def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:
    """Load raw params.yaml.  File handle closed after read."""
    path = path or CFG
    with open(path, encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)
    if isinstance(raw, dict):
        return raw
    return {}


def waterfall(p: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute mandate-economic waterfall from params.

    Returns a dict of labelled float/int values.  Numerical behaviour is
    preserved byte-for-byte from the Sprint-0 scaffold.
    """
    p = p or load_params()
    S: float = float(p["reference_spot_usd"])
    q: int = int(p["btc_quantity"])
    disc: float = float(p["seller_discount_pct"]) / 100.0
    fee: float = float(p["execution_fee_pct"]) / 100.0
    ovl: float = float(p["target_option_yield_pct"]) / 100.0

    notional: float = S * q
    price_after_disc: float = S * (1.0 - disc)
    fee_usd: float = notional * fee
    client_cash_per_btc: float = price_after_disc + S * fee
    overlay_usd: float = notional * ovl
    effective_per_btc: float = client_cash_per_btc - S * ovl

    return {
        "reference_spot_usd": S,
        "btc_quantity": q,
        "reference_notional_usd": notional,
        "seller_discount_usd": notional * disc,
        "price_after_discount_per_btc": price_after_disc,
        "asymmetrica_fee_usd": fee_usd,
        "asymmetrica_fee_btc_equiv": fee_usd / S,
        "client_cash_at_close_per_btc": client_cash_per_btc,
        "client_cash_at_close_total": client_cash_per_btc * q,
        "overlay_target_usd": overlay_usd,
        "client_effective_cost_per_btc_target_case": effective_per_btc,
        "client_effective_cost_total_target_case": effective_per_btc * q,
        "net_discount_vs_reference_pct": 100.0 * (1.0 - effective_per_btc / S),
    }


if __name__ == "__main__":
    for k, v in waterfall().items():
        if isinstance(v, float):
            print(f"{k:45s} {v:,.2f}")
        else:
            print(f"{k:45s} {v}")
