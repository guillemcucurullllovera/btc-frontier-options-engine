"""Prototype builders for the TRUE multi-leg / asymmetric structures the D3
hedging study needs. Each returns a Strategy whose option legs carry their OWN
strikes (call above / put below, per leg) so that
`backtest_multileg.backtest_strategy_multileg` re-strikes each leg independently.

40% coverage convention: hold ALL 30,000 BTC (spot leg), sell short calls on
12,000 (the covered sleeve, split into 4 equal 3,000-BTC tranches for ladders);
the other 18,000 stay uncapped. Hedge legs (long puts) are sized to the covered
12,000 unless noted. Premiums here are placeholders — the backtest re-prices
every leg per cycle from the live IV, so build-time premiums are ignored.

PROTOTYPE — does not modify production `strategy/definitions.py`.
"""
from __future__ import annotations

from engine.strategy import Leg, Strategy, StrategyKind, classify
from strategy.definitions import _make_spot_leg, _make_usd_option_leg

# ── MANDATE LADDER (locked Aug-2026): the "+6% floor" ladder ─────────────────
# 'Safer' = +6% floor ladder, strikes 6/10/14/18%, quarterly, IV-timed entry.
# (Supersedes the earlier +4/6.67/9.33/12% RECONCILED_SPEC ladder; that set is
# retained below as LEGACY_LADDER_PCTS for reproducing prior runs / grid trials.)
SPEC_LADDER_PCTS = [0.06, 0.10, 0.14, 0.18]        # +6 / +10 / +14 / +18 %
LEGACY_LADDER_PCTS = [0.04, 0.0667, 0.0933, 0.12]  # prior locked ladder (grid trial only)
# Quarterly cadence, ~30-day tenor entered in IV-timed windows. The DTE spread
# across tranches keeps them structurally distinct (near/far) while all four are
# re-struck independently per cycle by backtest_multileg (per-leg strike ratios).
DTE_LADDER = [31, 38, 45, 52]


def _safe_classify(legs: list[Leg]) -> StrategyKind:
    try:
        return classify(legs)
    except Exception:
        return StrategyKind.BESPOKE


def build_laddered_cc(
    block: float = 30_000.0,
    entry_spot: float = 63_401.86,
    coverage: float = 0.40,
    ladder_pcts: list[float] | None = None,
    dte_ladder: list[int] | None = None,
    strategy_id: str = "laddered_cc_40",
) -> Strategy:
    """40%-coverage laddered covered call, ASYMMETRIC strikes (the deck spec)."""
    ladder_pcts = ladder_pcts or SPEC_LADDER_PCTS
    dte_ladder = dte_ladder or DTE_LADDER
    covered = block * coverage
    tranche = covered / len(ladder_pcts)
    legs = [_make_spot_leg(block, entry_spot)]
    for pct, dte in zip(ladder_pcts, dte_ladder):
        legs.append(_make_usd_option_leg("call", "SHORT", tranche,
                                         entry_spot * (1.0 + pct), entry_spot * 0.014, dte))
    return Strategy(strategy_id=strategy_id, business_label="Laddered Covered Call (40%)",
                    canonical=_safe_classify(legs), legs=legs,
                    structural_max_loss=block * entry_spot)


def build_financed_collar(
    block: float = 30_000.0,
    entry_spot: float = 63_401.86,
    coverage: float = 0.40,
    call_pct: float = 0.05,
    put_pct: float = 0.10,
    put_coverage: float | None = None,
    dte_days: int = 31,
    strategy_id: str = "financed_collar_40",
) -> Strategy:
    """Long block + short call (+call_pct) on covered sleeve + long put (-put_pct)
    on `put_coverage` of the block (default = call coverage). Setting put_coverage
    higher than coverage hedges a larger share of the block (partly out-of-pocket)."""
    covered = block * coverage
    put_qty = block * (put_coverage if put_coverage is not None else coverage)
    legs = [
        _make_spot_leg(block, entry_spot),
        _make_usd_option_leg("call", "SHORT", covered, entry_spot * (1.0 + call_pct), entry_spot * 0.012, dte_days),
        _make_usd_option_leg("put", "LONG", put_qty, entry_spot * (1.0 - put_pct), entry_spot * 0.006, dte_days),
    ]
    return Strategy(strategy_id=strategy_id, business_label="Financed Collar (40%)",
                    canonical=_safe_classify(legs), legs=legs,
                    structural_max_loss=block * entry_spot)


def build_symmetric_collar(
    block: float = 30_000.0,
    entry_spot: float = 63_401.86,
    coverage: float = 1.00,
    call_pct: float = 0.10,
    put_pct: float = 0.10,
    dte_days: int = 31,
    strategy_id: str = "symmetric_collar_100",
) -> Strategy:
    """Reproduces the multigran collar_symm10 (call +10% / put -10% on 100%)."""
    q = block * coverage
    legs = [
        _make_spot_leg(block, entry_spot),
        _make_usd_option_leg("call", "SHORT", q, entry_spot * (1.0 + call_pct), entry_spot * 0.012, dte_days),
        _make_usd_option_leg("put", "LONG", q, entry_spot * (1.0 - put_pct), entry_spot * 0.006, dte_days),
    ]
    return Strategy(strategy_id=strategy_id, business_label="Symmetric Collar (100%)",
                    canonical=_safe_classify(legs), legs=legs,
                    structural_max_loss=block * entry_spot)


def build_put_spread_collar(
    block: float = 30_000.0,
    entry_spot: float = 63_401.86,
    coverage: float = 0.40,
    call_pct: float = 0.05,
    put_long_pct: float = 0.10,
    put_short_pct: float = 0.20,
    dte_days: int = 31,
    strategy_id: str = "put_spread_collar_40",
) -> Strategy:
    """Collar whose floor is a PUT SPREAD (long -10% put / short -20% put): a
    cheaper partial floor covering the -10%..-20% band, financed by the call."""
    covered = block * coverage
    legs = [
        _make_spot_leg(block, entry_spot),
        _make_usd_option_leg("call", "SHORT", covered, entry_spot * (1.0 + call_pct), entry_spot * 0.012, dte_days),
        _make_usd_option_leg("put", "LONG", covered, entry_spot * (1.0 - put_long_pct), entry_spot * 0.006, dte_days),
        _make_usd_option_leg("put", "SHORT", covered, entry_spot * (1.0 - put_short_pct), entry_spot * 0.003, dte_days),
    ]
    return Strategy(strategy_id=strategy_id, business_label="Put-Spread Collar (40%)",
                    canonical=_safe_classify(legs), legs=legs,
                    structural_max_loss=block * entry_spot)


def build_protective_ladder(
    block: float = 30_000.0,
    entry_spot: float = 63_401.86,
    coverage: float = 0.40,
    ladder_pcts: list[float] | None = None,
    dte_ladder: list[int] | None = None,
    put_pct: float = 0.10,
    put_coverage: float | None = None,
    strategy_id: str = "protective_ladder_40",
) -> Strategy:
    """The asymmetric laddered CC PLUS a long -put_pct put floor on `put_coverage`
    of the block (default = call coverage), financed out of the ladder premium.
    Combines income ladder + tail floor."""
    ladder_pcts = ladder_pcts or SPEC_LADDER_PCTS
    dte_ladder = dte_ladder or DTE_LADDER
    covered = block * coverage
    put_qty = block * (put_coverage if put_coverage is not None else coverage)
    tranche = covered / len(ladder_pcts)
    legs = [_make_spot_leg(block, entry_spot)]
    for pct, dte in zip(ladder_pcts, dte_ladder):
        legs.append(_make_usd_option_leg("call", "SHORT", tranche,
                                         entry_spot * (1.0 + pct), entry_spot * 0.014, dte))
    legs.append(_make_usd_option_leg("put", "LONG", put_qty,
                                     entry_spot * (1.0 - put_pct), entry_spot * 0.006, dte_ladder[0]))
    return Strategy(strategy_id=strategy_id, business_label="Protective Laddered CC (40%)",
                    canonical=_safe_classify(legs), legs=legs,
                    structural_max_loss=block * entry_spot)


def build_tier_b_collar(
    block: float = 30_000.0,
    entry_spot: float = 63_401.86,
    coverage: float = 0.40,
    ladder_pcts: list[float] | None = None,
    dte_ladder: list[int] | None = None,
    put_pct: float = 0.10,
    put_coverage: float | None = None,
    strategy_id: str = "tier_b_collar_40",
) -> Strategy:
    """CANONICAL Tier-B (mandate): the +6% laddered covered call (income sleeve,
    `coverage` of the block, split into 4 independent-strike tranches) PLUS a long
    OTM put floor at -`put_pct` on `put_coverage` of the BLOCK.

    Independent per-leg strikes: each short-call tranche re-strikes at its own
    (1+pct) ratio; the put re-strikes at its own (1-put_pct) ratio; the engine
    (backtest_multileg.leg_strike_ratios) honours all five independently.

    Two documented floor variants: put_pct in {0.05 (CLL-aligned), 0.10 (cheaper)}.
    Sizing note (A3 D3): the put floors the *block* fraction it covers, NOT the
    call sleeve — so `put_coverage` is a SEPARATE, block-level parameter. To floor
    the whole 30k block set put_coverage=1.0; to floor the uncapped 18k set ~0.60.
    Financing (A3 D3): keep the package NET-SHORT-VOL — call-ladder premium must
    finance the put (see `financing_net_premium`). Default put_coverage = coverage
    (the covered sleeve only) — deliberately a PARTIAL floor unless raised.

    This is the same structure as build_protective_ladder, exposed under the
    mandate name and defaulting to the +6% SPEC ladder.
    """
    return build_protective_ladder(
        block=block, entry_spot=entry_spot, coverage=coverage,
        ladder_pcts=ladder_pcts or SPEC_LADDER_PCTS,
        dte_ladder=dte_ladder or DTE_LADDER,
        put_pct=put_pct, put_coverage=put_coverage,
        strategy_id=strategy_id,
    )


def financing_net_premium(call_premium_usd: float, put_premium_usd: float) -> dict[str, object]:
    """A3 D3 financing constraint: a Tier-B collar is DEFENSIBLE only if it stays
    net-short-vol, i.e. the short-call ladder premium finances the long put:
        net = call_premium - put_premium  >=  0 .
    A net-LONG-vol collar (put costs more than the call earns) "pays the VRP twice"
    (Israelov-Klein 2016) and is the construction to avoid.

    Returns the net premium, a bool `financed`, and the financing ratio. Evaluate
    per-cycle on the PRICED premiums from the backtest, not on build placeholders.
    """
    net = float(call_premium_usd) - float(put_premium_usd)
    ratio = (call_premium_usd / put_premium_usd) if put_premium_usd > 0 else float("inf")
    return {"net_premium_usd": net, "financed": bool(net >= 0.0),
            "call_premium_usd": float(call_premium_usd),
            "put_premium_usd": float(put_premium_usd),
            "financing_ratio": ratio}


def build_cc_spread(
    block: float = 30_000.0,
    entry_spot: float = 63_401.86,
    coverage: float = 0.40,
    short_pct: float = 0.04,
    long_pct: float = 0.09,
    dte_days: int = 31,
    strategy_id: str = "cc_spread_40",
) -> Strategy:
    """Covered-call SPREAD: short +short_pct call, long +long_pct call. Caps the
    upside give-back to the short..long band and RE-OPENS participation above
    +long_pct (the client keeps rallies past the long strike)."""
    covered = block * coverage
    legs = [
        _make_spot_leg(block, entry_spot),
        _make_usd_option_leg("call", "SHORT", covered, entry_spot * (1.0 + short_pct), entry_spot * 0.014, dte_days),
        _make_usd_option_leg("call", "LONG", covered, entry_spot * (1.0 + long_pct), entry_spot * 0.006, dte_days),
    ]
    return Strategy(strategy_id=strategy_id, business_label="Covered-Call Spread (40%)",
                    canonical=_safe_classify(legs), legs=legs,
                    structural_max_loss=block * entry_spot)
