"""Price/fee waterfall calculator (mandate Sec. 2.2). Reads config/params.yaml.
Run: python3 -m execution.waterfall  (from btc_engine/)"""
from __future__ import annotations
import pathlib
import yaml

CFG = pathlib.Path(__file__).resolve().parents[1] / "config" / "params.yaml"


def load_params(path=CFG) -> dict:
    return yaml.safe_load(open(path))


def waterfall(p: dict | None = None) -> dict:
    p = p or load_params()
    S, q = float(p["reference_spot_usd"]), int(p["btc_quantity"])
    disc, fee, ovl = (float(p[k]) / 100 for k in
                      ("seller_discount_pct", "execution_fee_pct", "target_option_yield_pct"))
    notional = S * q
    price_after_disc = S * (1 - disc)
    fee_usd = notional * fee
    client_cash_per_btc = price_after_disc + S * fee
    overlay_usd = notional * ovl
    effective_per_btc = client_cash_per_btc - S * ovl
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
        "net_discount_vs_reference_pct": 100 * (1 - effective_per_btc / S),
    }


if __name__ == "__main__":
    for k, v in waterfall().items():
        print(f"{k:45s} {v:,.2f}" if isinstance(v, float) else f"{k:45s} {v}")
