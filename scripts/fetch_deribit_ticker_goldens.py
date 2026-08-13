"""Capture a frozen snapshot of live Deribit ``public/ticker`` marks for inverse-pricer
certification (A2 Track 3). Provenance: OBSERVED (timestamped). Free public REST, no API key.

Deribit marks BTC inverse options with Black-76 on the per-expiry forward F, r = q = 0
(Lucic-Sepp fn 3/8; ACI §3.1). Each ``public/ticker`` returns, per instrument:
    index_price      -> S   (Deribit BTC index, USD/BTC)
    underlying_price -> F   (per-expiry forward, USD/BTC)
    mark_price       -> V_BTC (coin-settled mark, BTC)
    mark_iv          -> Black vol (percent)
    greeks{delta,gamma,vega,theta,rho}  (delta = premium-adjusted exchange Delta_BTC)

Selection: >=12 instruments spanning {OTM, ATM, ITM} x {call, put} across the 3 nearest
"round" expiries (~weekly / ~monthly / ~quarterly). Writes tests/fixtures/deribit_ticker_goldens.json.

Run (engine venv):  PYTHONPATH=. python scripts/fetch_deribit_ticker_goldens.py
"""

from __future__ import annotations

import json
import pathlib
import time
import urllib.request
from datetime import UTC, datetime

API = "https://www.deribit.com/api/v2/"
FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "deribit_ticker_goldens.json"


def _get(method: str, **params: object) -> dict:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API}{method}?{q}" if q else f"{API}{method}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        payload = json.load(resp)
    if "result" not in payload:
        raise RuntimeError(f"{method} returned no result: {payload}")
    return payload["result"]


def _expiry_ms(instrument_name: str, instruments: list[dict]) -> int:
    for inst in instruments:
        if inst["instrument_name"] == instrument_name:
            return int(inst["expiration_timestamp"])
    raise KeyError(instrument_name)


def select_instruments(instruments: list[dict], index: float) -> list[str]:
    """Pick OTM/ATM/ITM x call/put across the 3 nearest expiries (>=12 instruments)."""
    now_ms = time.time() * 1000.0
    by_exp: dict[int, list[dict]] = {}
    for inst in instruments:
        if inst.get("option_type") not in ("call", "put"):
            continue
        exp = int(inst["expiration_timestamp"])
        if exp <= now_ms:
            continue
        by_exp.setdefault(exp, []).append(inst)
    # 3 expiries: nearest, ~monthly (>=21d), ~quarterly (>=75d) where available.
    exps = sorted(by_exp)
    chosen_exps: list[int] = []
    targets_d = (0.0, 21.0, 75.0)
    for td in targets_d:
        cand = [e for e in exps if (e - now_ms) / 86400_000.0 >= td and e not in chosen_exps]
        if cand:
            chosen_exps.append(min(cand, key=lambda e: abs((e - now_ms) / 86400_000.0 - td)))
    picked: list[str] = []
    for exp in chosen_exps:
        strikes = sorted({float(i["strike"]) for i in by_exp[exp]})
        if not strikes:
            continue
        atm = min(strikes, key=lambda k: abs(k - index))
        itm_c = max((k for k in strikes if k < index * 0.92), default=atm)   # ITM call / OTM put
        otm_c = min((k for k in strikes if k > index * 1.08), default=atm)   # OTM call / ITM put
        for strike, kinds in ((atm, ("call", "put")), (otm_c, ("call",)), (itm_c, ("put",))):
            for kind in kinds:
                name = next((i["instrument_name"] for i in by_exp[exp]
                             if float(i["strike"]) == strike and i["option_type"] == kind), None)
                if name and name not in picked:
                    picked.append(name)
    return picked


def capture() -> dict:
    captured_at = datetime.now(UTC).isoformat()
    instruments = _get("public/get_instruments", currency="BTC", kind="option", expired="false")
    index = float(_get("public/get_index_price", index_name="btc_usd")["index_price"])
    names = select_instruments(instruments, index)
    goldens: list[dict] = []
    for name in names:
        try:
            t = _get("public/ticker", instrument_name=name)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {name}: {exc}")
            continue
        exp_ms = _expiry_ms(name, instruments)
        S = float(t["index_price"])
        F = float(t.get("underlying_price") or S)
        K = float(t["instrument_name"].split("-")[2])
        kind = "call" if t["instrument_name"].endswith("-C") else "put"
        T = max((exp_ms - t["timestamp"]) / (365.0 * 86400_000.0), 0.0)
        g = t.get("greeks", {}) or {}
        goldens.append({
            "instrument_name": name,
            "timestamp_ms": int(t["timestamp"]),
            "expiration_timestamp_ms": int(exp_ms),
            "S_index": S,
            "F_underlying": F,
            "K_strike": K,
            "T_years": T,
            "kind": kind,
            "mark_price_btc": float(t["mark_price"]),
            "mark_iv_pct": float(t["mark_iv"]),
            "interest_rate": float(t.get("interest_rate", 0.0)),
            "greeks": {k: (float(v) if v is not None else None)
                       for k, v in g.items() if k in ("delta", "gamma", "vega", "theta", "rho")},
        })
        print(f"  captured {name}: S={S:.1f} F={F:.1f} K={K:.0f} mark={t['mark_price']} "
              f"iv={t['mark_iv']:.2f} delta={g.get('delta')}")
    return {
        "provenance": "OBSERVED",
        "source": "Deribit public/ticker (free REST, no key)",
        "marking_convention": "Black-76 on F, r=q=0 (Lucic-Sepp fn 3/8; ACI 3.1)",
        "captured_at_utc": captured_at,
        "n": len(goldens),
        "goldens": goldens,
    }


def main() -> None:
    print("Capturing Deribit ticker goldens (OBSERVED, free public REST) ...")
    snap = capture()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(snap, indent=2) + "\n")
    print(f"Wrote {snap['n']} goldens -> {FIXTURE}")


if __name__ == "__main__":
    main()
