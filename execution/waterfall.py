"""Price/fee waterfall calculator (mandate Sec. 2.2). Reads config/params.yaml.

Run:  python3 -m execution.waterfall  (from btc_engine/)

Phase 0: typed, file-handle leak fixed.  Preserves exact numerical behaviour
and public compatibility with existing tests.

A4 extension: waterfall_sensitivity() produces labelled dicts for every
(spot_offset_pct, fee_base) combination.  fee_base variant preserves D-1
decision marker (both variants computed, not resolved).
"""

from __future__ import annotations

import pathlib
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

CFG: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "config" / "params.yaml"
)


def _default_spot_offsets() -> list[float]:
    return [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]


def _default_fee_bases() -> list[Literal["reference_notional", "executed_volume"]]:
    return ["reference_notional", "executed_volume"]


class WaterfallSensitivity(BaseModel):
    """Sensitivity parameters for waterfall — frozen per contracts.md §12.4."""

    spot_offsets_pct: list[float] = Field(default_factory=_default_spot_offsets)
    fee_bases: list[Literal["reference_notional", "executed_volume"]] = Field(
        default_factory=_default_fee_bases
    )


def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:
    """Load raw params.yaml.  File handle closed after read."""
    path = path or CFG
    with open(path, encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)
    if isinstance(raw, dict):
        return raw
    return {}


def _compute_waterfall(
    S: float,
    q: int,
    disc: float,
    fee_rate: float,
    ovl: float,
    fee_base: Literal["reference_notional", "executed_volume"] = "reference_notional",
) -> dict[str, Any]:
    """Core waterfall arithmetic — reused by waterfall() and waterfall_sensitivity()."""
    notional: float = S * q
    price_after_disc: float = S * (1.0 - disc)
    fee_notional = notional * (1.0 - disc) if fee_base == "executed_volume" else notional
    fee_usd: float = fee_notional * fee_rate
    client_cash_per_btc: float = price_after_disc + fee_usd / q
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


def waterfall(p: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute mandate-economic waterfall from params.

    Returns a dict of labelled float/int values.  Numerical behaviour is
    preserved byte-for-byte from the Sprint-0 scaffold (reference_notional base).
    """
    p = p or load_params()
    S: float = float(p["reference_spot_usd"])
    q: int = int(p["btc_quantity"])
    disc: float = float(p["seller_discount_pct"]) / 100.0
    fee: float = float(p["execution_fee_pct"]) / 100.0
    ovl: float = float(p["target_option_yield_pct"]) / 100.0
    return _compute_waterfall(S, q, disc, fee, ovl, "reference_notional")


def waterfall_sensitivity(
    p: dict[str, Any] | None = None,
    sensitivity: WaterfallSensitivity | None = None,
) -> list[dict[str, Any]]:
    """Produce waterfall for every (spot_offset_pct, fee_base) combination.

    Each result dict includes 'spot_offset_pct' and 'fee_base' keys
    identifying the variant.  fee_base=None (D-1 unresolved) is preserved
    by computing both variants but not silently choosing.
    """
    p = p or load_params()
    sens = sensitivity or WaterfallSensitivity()
    S: float = float(p["reference_spot_usd"])
    q: int = int(p["btc_quantity"])
    disc: float = float(p["seller_discount_pct"]) / 100.0
    fee: float = float(p["execution_fee_pct"]) / 100.0
    ovl: float = float(p["target_option_yield_pct"]) / 100.0

    results: list[dict[str, Any]] = []
    for offset in sens.spot_offsets_pct:
        S_adj = S * (1.0 + offset / 100.0)
        for fb in sens.fee_bases:
            row = _compute_waterfall(S_adj, q, disc, fee, ovl, fb)
            row["spot_offset_pct"] = offset
            row["spot"] = S_adj
            row["fee_base"] = fb
            results.append(row)
    return results


if __name__ == "__main__":
    for k, v in waterfall().items():
        if isinstance(v, float):
            print(f"{k:45s} {v:,.2f}")
        else:
            print(f"{k:45s} {v}")
