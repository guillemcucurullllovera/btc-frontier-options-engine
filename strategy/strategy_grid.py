"""C8 deterministic strategy grid (single-cycle, live-IV).

Computes the quantitative comparison grid the CEO drew by hand - correctly and
off a frozen live snapshot.  Modeling frame (locked): the client already HOLDS
the 30,000-BTC block (spot acquired at t0); this module analyses the option
overlay on that position.  Every scenario/P&L cell decomposes into:

  * holding (BTC) leg  - MTM from the t0 spot; the client's inherent exposure
                         (present wherever a long-BTC leg exists);
  * cash/collateral leg - where relevant (cash-secured put);
  * option leg(s)      - premium +/- payoff; the advised component;

and the total, reported separately at three granularities (per-BTC of the block
/ per CME 5-BTC contract / per 30,000-BTC portfolio).  Structures with no
long-BTC leg (cash-secured put, call spread) are framed on their own terms.

Grid axes: {8-structure toolkit + 2 heroes} x strike% x the two real listed
expiries x coverage {25,50,75,100}%.  Each row prices at its own listed
`mark_iv`.  sigma-normalised scenarios use each expiry's OWN ATM IV
(sigma_h(T)=ATM_IV(T)*sqrt(T/365)); DVOL is headline only.

Pricing bridge (documented, brief sec 2.7): USD P&L uses linear-USD Black-Scholes
(`pricing.black_scholes`) with Deribit `mark_iv` as the vol input and a USD
risk-free rate `r`; Deribit options are inverse/BTC-settled, CME linear/USD.

No best/optimal/preferred/safest language.  "attractive when..." tags state a
market condition, not a recommendation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from engine.data_models import BookSummary, OptionInstrument
from pricing.black_scholes import greeks as bs_greeks
from pricing.black_scholes import price as bs_price
from vol.chain import iv_for, snap_to_listed_strike

# ── Locked grid dimensions ─────────────────────────────────────────────────

PORTFOLIO_BTC: int = 30_000
CME_CONTRACT_BTC: int = 5
CALL_OTM_PCT: tuple[float, ...] = (1.5, 3.0, 5.0, 10.0, 15.0)
PUT_OTM_PCT: tuple[float, ...] = (3.0, 5.0, 10.0)
COVERAGE_PCT: tuple[float, ...] = (25.0, 50.0, 75.0, 100.0)
SIGMA_STEPS: tuple[float, ...] = (-2.0, -1.0, 0.0, 1.0, 2.0)

# Multi-leg framing conventions (documented; grid-construction detail, not a
# business decision - surfaced in the gate report for confirmation):
COLLAR_FLOOR_PCTS: tuple[float, ...] = (10.0, 5.0)  # protective-put floors; 10% primary (deck Slide-4)
CALL_SPREAD_PAIRS: tuple[tuple[float, float], ...] = (
    (1.5, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 15.0),
)  # CREDIT call spread: SHORT lower strike / LONG higher strike (premium-generating)
LADDER_PCTS: tuple[float, ...] = (5.0, 10.0, 15.0)  # short-call rungs, equal-weighted

CEO_REFERENCE_PREMIUM_PCT: float = 2.0   # labelled reference marker only
DECK_REFERENCE_PREMIUM_PCT: float = 2.5  # labelled reference marker only

MANDATE_REFERENCE_SPOT: float = 65_000.0  # stated mandate reference (not a pricing input)
STRUCTURING_FEE_PCT: float = 0.5          # Asymmetrica execution fee (config execution_fee_pct)

# Pending decisions attached to every grid row + the grid (never resolved here).
PENDING_DECISION_REFS: tuple[str, ...] = ("D-1", "D-4", "D-7", "D-9", "D-10", "MS-25", "MS-26")

# T0-5 / MS-11: BTC carry (convenience yield) q is ASSUMED 0. USD premiums are EXACT at q=0
# (linear-USD Black-Scholes); a non-zero q shifts the USD-equivalent inverse price
# (q=2/5/10% -> approx -1.4/-3.4/-6.7%). Surfaced as a provenance-tagged assumption, not silent.
CARRY_Q_ASSUMPTION: dict[str, object] = {
    "carry_q": 0.0,
    "provenance": "ASSUMED (MS-11)",
    "rationale": "no observed BTC convenience-yield source; USD premium is exact at q=0",
    "sensitivity_usd_equiv_pct": {"q_2pct": -1.4, "q_5pct": -3.4, "q_10pct": -6.7},
    "audit_path": "pricing.inverse.price_inverse_btc(q=...) for the exact inverse identity",
}

HERO_STRUCTURES: frozenset[str] = frozenset({"covered_call", "long_btc_plus_short_put"})

ATTRACTIVE_WHEN: dict[str, str] = {
    "unhedged_baseline": "Reference: full upside and full downside on the held BTC; no overlay.",
    "covered_call": (
        "When the view is neutral-to-mildly-bullish and generating premium on the held BTC "
        "is prioritised over retaining uncapped upside."
    ),
    "long_btc_plus_short_put": (
        "When willing to acquire more BTC on a decline (accepting amplified downside below the "
        "strike) in exchange for premium; a neutral-to-mildly-bullish view with conviction to hold."
    ),
    "cash_secured_put": (
        "When seeking to acquire BTC at a net price below spot, funded by premium, with cash "
        "collateral set aside."
    ),
    "collar": (
        "When downside protection is prioritised and some upside/premium is given up to fund the floor."
    ),
    "call_spread": (
        "When a defined-risk, option-only bullish payoff is wanted without holding spot."
    ),
    "strike_ladder": (
        "When graduated upside participation across multiple strikes is preferred to a single cap."
    ),
}

DISCLAIMER: str = (
    "Full risk analysis of alternative option overlays on the client's existing 30,000-BTC "
    "holding. Each outcome is decomposed into the client's inherent BTC holding and the advised "
    "option overlay: for the covered call the overlay is a non-negative premium cushion and the "
    "downside is inherent to holding BTC; for Long BTC + short put the overlay adds incremental "
    "downside below the strike. Capped upside is opportunity cost (foregone gain), not a loss. "
    "Investment decisions and their outcomes rest with the client."
)

PENDING_GATES: tuple[str, ...] = (
    "D-1 fee base", "D-4/D-7 put-sleeve scope", "D-9 hedge model", "D-10 loss budget",
    "MS-25 objective function", "MS-26 sim methodology", "CSCV/PBO/DSR PENDING_METHOD",
)


# ── Granularity ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Granular:
    """One USD quantity at three granularities."""

    per_btc: float          # per BTC of the 30,000-BTC block
    per_contract: float     # per CME 5-BTC contract
    per_portfolio: float    # full 30,000-BTC block


def _granular(per_portfolio: float, block: int = PORTFOLIO_BTC) -> Granular:
    per_btc = per_portfolio / block
    return Granular(
        per_btc=per_btc,
        per_contract=per_btc * CME_CONTRACT_BTC,
        per_portfolio=per_portfolio,
    )


# ── Leg / structure specification ──────────────────────────────────────────


@dataclass(frozen=True)
class OptionLegSpec:
    kind: str               # "call" | "put"
    side: str               # "LONG" | "SHORT"
    requested_pct: float    # signed %OTM off t0 spot (+ above, - below); for labels
    listed_strike: float
    iv: float               # decimal, annualised - this leg's own listed mark_iv
    iv_provenance: str
    instrument: str
    premium_per_btc: float  # bs_price(S0, K, r, iv, T, kind) - t0 premium, USD/BTC
    r: float                # risk-free rate used to price this leg
    r_provenance: str       # "observed (deribit interest_rate)" | "assumed (config 4%)"
    notional_weight: float = 1.0  # fraction of coveragexblock this leg covers

    @property
    def side_sign(self) -> float:
        """P&L sign on (premium - value): SHORT receives premium (+), LONG pays (-)."""
        return 1.0 if self.side == "SHORT" else -1.0

    @property
    def position_sign(self) -> float:
        """Greek/position-value sign: LONG position holds +value, SHORT holds -value."""
        return -1.0 if self.side == "SHORT" else 1.0


@dataclass(frozen=True)
class StructureSpec:
    structure_id: str
    canonical_kind: str
    has_holding: bool
    has_cash: bool
    option_legs: list[OptionLegSpec]
    primary_strike_pct: float | None
    primary_leg_index: int | None   # index into option_legs for prob-win / breakeven framing


# ── Metric blocks ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PremiumBlock:
    net_per_btc: float          # per BTC of option notional (net structure credit +, debit -)
    pct_of_spot: float
    per_contract: float
    per_portfolio: float
    ceo_reference_pct: float = CEO_REFERENCE_PREMIUM_PCT
    deck_reference_pct: float = DECK_REFERENCE_PREMIUM_PCT


@dataclass(frozen=True)
class ProbWin:
    measure: str
    value: float                # short option NOT exercised, risk-neutral
    delta_proxy: float          # 1 - |delta_short| ~ P(not ITM)
    note: str


@dataclass(frozen=True)
class MaxLossBlock:
    worst_case_spot: float
    holding: Granular
    option: Granular
    cash: Granular
    total: Granular
    total_pct_of_notional: float
    total_pct_of_capital: float
    capital_usd: float
    unbounded: bool
    notional_basis: str = "portfolio_notional = 30,000 * S0"
    capital_basis: str = ""  # set per structure (BTC value / cash collateral / defined risk)


@dataclass(frozen=True)
class BreakevenBlock:
    strike_pct_otm: float | None
    true_breakevens: list[float]
    note: str


@dataclass(frozen=True)
class GreeksBlock:
    option_delta_per_btc: float     # overlay, per BTC of option notional
    option_gamma_per_btc: float
    option_vega_per_btc: float
    option_theta_per_year_per_btc: float
    theta_per_day_per_btc: float
    total_position_delta_per_block_btc: float  # holding + coveragexoverlay, per block BTC


@dataclass(frozen=True)
class RiskRewardBlock:
    premium_to_max_loss: float | None
    upside_downside_2sigma: float | None
    definition: str


@dataclass(frozen=True)
class FeeBlock:
    """Structuring fee (Asymmetrica 0.5%) — SEPARATE from scenario P&L (pre-fee grid).

    D-1 (fee base) is unresolved: both variants are emitted, never baked in.
    """

    fee_pct: float
    on_reference_notional_usd: float   # D-1 variant A: 0.5% * 30,000 * mandate reference spot
    on_executed_volume_usd: float      # D-1 variant B: 0.5% * coverage * 30,000 * S0 (traded overlay)
    decision_ref: str = "D-1"
    note: str = "Structuring fee is a separate line; NOT included in scenario P&L (pre-fee grid)."


@dataclass(frozen=True)
class OpportunityCostCell:
    """Upside foregone vs unhedged long BTC in a +sigma scenario (foregone gain, not a loss)."""

    k_sigma: float
    scenario_spot: float
    foregone: Granular  # max(0, unhedged_total - structure_total_portfolio_view)


@dataclass(frozen=True)
class ScenarioCell:
    k_sigma: float
    sigma_horizon: float
    pct_move: float
    scenario_spot: float
    mode: str                   # "instantaneous" | "terminal"
    holding: Granular
    option: Granular
    cash: Granular
    total: Granular
    pct_of_portfolio: float


@dataclass(frozen=True)
class DecayPoint:
    dte_days: float
    option_value_per_btc: float   # net structure option value at t0 spot, remaining time
    theta_per_day_per_btc: float


@dataclass(frozen=True)
class GridRow:
    structure_id: str
    canonical_kind: str
    is_hero: bool
    benchmark_only: bool     # unhedged_baseline: internal benchmark, never featured/recommended
    has_holding: bool
    has_cash: bool
    business_label: str
    expiry_label: str
    expiry_utc: str
    dte_days: float
    t_years: float
    coverage_pct: float
    strike_pct: float | None
    atm_iv: float
    sigma_horizon: float
    option_legs: list[OptionLegSpec]
    premium: PremiumBlock
    prob_win: ProbWin | None
    max_loss: MaxLossBlock
    breakeven: BreakevenBlock
    greeks: GreeksBlock
    risk_reward: RiskRewardBlock
    structuring_fee: FeeBlock
    # Standalone view: the structure as defined (no-holding structures show no BTC leg).
    scenarios_instantaneous: list[ScenarioCell]
    scenarios_terminal: list[ScenarioCell]
    # Total-portfolio view: existing 30,000-BTC holding + the structure (comparability basis
    # so no-holding structures are comparable to holding-inclusive ones).
    scenarios_instantaneous_portfolio: list[ScenarioCell]
    scenarios_terminal_portfolio: list[ScenarioCell]
    scenario_view_note: str
    opportunity_cost: list[OpportunityCostCell]
    theta_decay: list[DecayPoint]
    effective_net_price: float | None   # cash-secured put only
    attractive_when: str
    pending_decision_refs: tuple[str, ...] = PENDING_DECISION_REFS


@dataclass(frozen=True)
class GridExpiry:
    label: str
    expiry_utc: str
    dte_days: float
    t_years: float
    atm_iv: float
    sigma_horizon: float


@dataclass(frozen=True)
class StrategyGrid:
    as_of_utc: str
    snapshot_dir: str
    s0: float
    r_fallback: float               # config ASSUMED rate; per-leg r is OBSERVED where available
    r_provenance: str
    mandate_reference_spot: float
    block_btc: int
    cme_contract_btc: int
    expiries: list[GridExpiry]
    rows: list[GridRow]
    framing_notes: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    pending_gates: tuple[str, ...] = PENDING_GATES
    pending_decision_refs: tuple[str, ...] = PENDING_DECISION_REFS
    carry_assumption: dict[str, object] = field(default_factory=lambda: dict(CARRY_Q_ASSUMPTION))


# ── Pricing primitives (linear-USD BS bridge) ──────────────────────────────


def _intrinsic(s: float, k: float, kind: str) -> float:
    return max(s - k, 0.0) if kind == "call" else max(k - s, 0.0)


def _option_value(s: float, k: float, r: float, sigma: float, t: float, kind: str, mode: str) -> float:
    """Option value per BTC: BS reprice (instantaneous, time/IV held) or intrinsic (terminal)."""
    if mode == "terminal":
        return _intrinsic(s, k, kind)
    return bs_price(s, k, r, sigma, t, kind)


def _d2(s: float, k: float, r: float, sigma: float, t: float) -> float:
    return (math.log(s / k) + (r - 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


# ── Per-leg / per-structure economics (closed form, per option-notional BTC) ─


def _leg_pnl_per_btc(leg: OptionLegSpec, s: float, t: float, mode: str) -> float:
    """Option-leg P&L per BTC of that leg's notional at spot *s* (uses the leg's own r).

    SHORT: premium received - current value.  LONG: -premium paid + current value.
    """
    value = _option_value(s, leg.listed_strike, leg.r, leg.iv, t, leg.kind, mode)
    return leg.side_sign * (leg.premium_per_btc - value)


def _option_pnl_per_notional_btc(spec: StructureSpec, s: float, t: float, mode: str) -> float:
    return sum(
        leg.notional_weight * _leg_pnl_per_btc(leg, s, t, mode) for leg in spec.option_legs
    )


def _net_premium_per_btc(spec: StructureSpec) -> float:
    # Credit (+) for short legs, debit (-) for long legs, weighted by notional.
    return sum(
        leg.notional_weight * leg.side_sign * leg.premium_per_btc for leg in spec.option_legs
    )


def _holding_pnl_per_block_btc(s: float, s0: float) -> float:
    return s - s0


def _cell(
    spec: StructureSpec,
    s: float,
    s0: float,
    t: float,
    coverage: float,
    block: int,
    mode: str,
    k_sigma: float,
    sigma_h: float,
    holding_always: bool = False,
) -> ScenarioCell:
    include_holding = spec.has_holding or holding_always
    holding_pp = (block * _holding_pnl_per_block_btc(s, s0)) if include_holding else 0.0
    option_pp = coverage * block * _option_pnl_per_notional_btc(spec, s, t, mode)
    cash_pp = 0.0
    total_pp = holding_pp + option_pp + cash_pp
    notional = block * s0
    return ScenarioCell(
        k_sigma=k_sigma,
        sigma_horizon=sigma_h,
        pct_move=k_sigma * sigma_h,
        scenario_spot=s,
        mode=mode,
        holding=_granular(holding_pp, block),
        option=_granular(option_pp, block),
        cash=_granular(cash_pp, block),
        total=_granular(total_pp, block),
        pct_of_portfolio=total_pp / notional if notional > 0 else 0.0,
    )


def _scenarios(
    spec: StructureSpec, s0: float, t: float, coverage: float, block: int,
    sigma_h: float, mode: str, holding_always: bool = False,
) -> list[ScenarioCell]:
    cells: list[ScenarioCell] = []
    for k in SIGMA_STEPS:
        s = max(s0 * (1.0 + k * sigma_h), 1e-6)
        cells.append(_cell(spec, s, s0, t, coverage, block, mode, k, sigma_h, holding_always))
    return cells


def _kinks(spec: StructureSpec, s0: float) -> list[float]:
    strikes = sorted({leg.listed_strike for leg in spec.option_legs})
    hi = max([s0 * 3.0, *strikes]) + 1.0
    return [0.0, *strikes, hi]


def _terminal_total_per_portfolio(
    spec: StructureSpec, s: float, s0: float, coverage: float, block: int
) -> float:
    holding = (block * _holding_pnl_per_block_btc(s, s0)) if spec.has_holding else 0.0
    option = coverage * block * _option_pnl_per_notional_btc(spec, s, 0.0, "terminal")
    return holding + option


def _max_loss(spec: StructureSpec, s0: float, coverage: float, block: int) -> MaxLossBlock:
    kinks = _kinks(spec, s0)
    # Piecewise-linear terminal P&L: global min over S in [0,inf) is at a kink unless
    # the slope stays negative past the last kink (uncapped short-call exposure).
    hi = kinks[-1]
    slope = (
        _terminal_total_per_portfolio(spec, hi + 1.0, s0, coverage, block)
        - _terminal_total_per_portfolio(spec, hi, s0, coverage, block)
    )
    unbounded = slope < -1e-6
    worst = min(kinks, key=lambda s: _terminal_total_per_portfolio(spec, s, s0, coverage, block))
    holding_pp = (block * _holding_pnl_per_block_btc(worst, s0)) if spec.has_holding else 0.0
    option_pp = coverage * block * _option_pnl_per_notional_btc(spec, worst, 0.0, "terminal")
    total_pp = holding_pp + option_pp
    capital = _capital_usd(spec, s0, coverage, block)
    notional = block * s0
    if spec.has_cash:
        capital_basis = "cash collateral = coverage * 30,000 * put strike"
    elif spec.has_holding:
        capital_basis = "value of held BTC = 30,000 * S0"
    else:
        capital_basis = "structural max loss (defined-risk, option-only)"
    return MaxLossBlock(
        worst_case_spot=worst,
        holding=_granular(holding_pp, block),
        option=_granular(option_pp, block),
        cash=_granular(0.0, block),
        total=_granular(total_pp, block),
        total_pct_of_notional=(total_pp / notional) if notional > 0 else 0.0,
        total_pct_of_capital=(total_pp / capital) if capital > 0 else 0.0,
        capital_usd=capital,
        unbounded=unbounded,
        capital_basis=capital_basis,
    )


def _capital_usd(spec: StructureSpec, s0: float, coverage: float, block: int) -> float:
    if spec.has_cash:  # cash-secured put: collateral = coveragexblockxstrike
        k = spec.option_legs[spec.primary_leg_index or 0].listed_strike
        return coverage * block * k
    if spec.has_holding:  # BTC value held
        return block * s0
    # option-only defined-risk (call spread): capital = structural max loss magnitude
    ml = -min(
        _terminal_total_per_portfolio(spec, s, s0, coverage, block) for s in _kinks(spec, s0)
    )
    return max(ml, 0.0)


def _breakevens(spec: StructureSpec, s0: float, coverage: float, block: int) -> list[float]:
    """True P&L breakevens (terminal) - exact roots of the piecewise-linear total."""
    kinks = _kinks(spec, s0)
    xs = sorted(set(kinks))
    ys = [_terminal_total_per_portfolio(spec, x, s0, coverage, block) for x in xs]
    roots: list[float] = []
    for i in range(len(xs) - 1):
        a, b = xs[i], xs[i + 1]
        fa, fb = ys[i], ys[i + 1]
        if fa == 0.0:
            roots.append(a)
        if (fa < 0.0 < fb) or (fa > 0.0 > fb):
            roots.append(a - fa * (b - a) / (fb - fa))
    if ys and ys[-1] == 0.0:
        roots.append(xs[-1])
    deduped: list[float] = []
    for be in sorted(roots):
        if be > 0.0 and (not deduped or abs(be - deduped[-1]) > 1e-4):
            deduped.append(be)
    return deduped


def _prob_win(spec: StructureSpec, s0: float, t: float) -> ProbWin | None:
    if spec.primary_leg_index is None:
        return None
    leg = spec.option_legs[spec.primary_leg_index]
    if leg.side != "SHORT":
        return None
    d2 = _d2(s0, leg.listed_strike, leg.r, leg.iv, t)
    if leg.kind == "call":
        value = _norm_cdf(-d2)
        measure = "risk_neutral P(S_T<K_call)=N(-d2)"
    else:
        value = _norm_cdf(d2)
        measure = "risk_neutral P(S_T>K_put)=N(d2)"
    g = bs_greeks(s0, leg.listed_strike, leg.r, leg.iv, t, leg.kind)
    return ProbWin(
        measure=measure,
        value=value,
        delta_proxy=1.0 - abs(g.delta),
        note="Risk-neutral (drift = r); short option not exercised. Not a real-world probability.",
    )


def _greeks(spec: StructureSpec, s0: float, t: float, coverage: float) -> GreeksBlock:
    delta = gamma = vega = theta = 0.0
    for leg in spec.option_legs:
        g = bs_greeks(s0, leg.listed_strike, leg.r, leg.iv, t, leg.kind)
        w = leg.notional_weight * leg.position_sign
        delta += w * g.delta
        gamma += w * g.gamma
        vega += w * g.vega
        theta += w * g.theta
    holding_delta = 1.0 if spec.has_holding else 0.0
    return GreeksBlock(
        option_delta_per_btc=delta,
        option_gamma_per_btc=gamma,
        option_vega_per_btc=vega,
        option_theta_per_year_per_btc=theta,
        theta_per_day_per_btc=theta / 365.0,
        total_position_delta_per_block_btc=holding_delta + coverage * delta,
    )


def _theta_decay(spec: StructureSpec, s0: float, t: float) -> list[DecayPoint]:
    """Net structure option value at t0 spot as remaining time decays (5 points)."""
    points: list[DecayPoint] = []
    for frac in (1.0, 0.75, 0.5, 0.25, 0.0):
        t_rem = max(t * frac, 1e-6)
        value = sum(
            leg.notional_weight * leg.side_sign
            * (leg.premium_per_btc
               - _option_value(s0, leg.listed_strike, leg.r, leg.iv, t_rem, leg.kind, "instantaneous"))
            for leg in spec.option_legs
        )
        theta = 0.0
        for leg in spec.option_legs:
            g = bs_greeks(s0, leg.listed_strike, leg.r, leg.iv, t_rem, leg.kind)
            theta += leg.notional_weight * leg.position_sign * g.theta
        points.append(DecayPoint(
            dte_days=t_rem * 365.0,
            option_value_per_btc=value,
            theta_per_day_per_btc=theta / 365.0,
        ))
    return points


def _risk_reward(
    net_premium_portfolio: float,
    max_loss: MaxLossBlock,
    terminal: list[ScenarioCell],
) -> RiskRewardBlock:
    p_to_ml: float | None = None
    if max_loss.total.per_portfolio < 0.0 and not max_loss.unbounded:
        p_to_ml = net_premium_portfolio / abs(max_loss.total.per_portfolio)
    up = next((c.total.per_portfolio for c in terminal if c.k_sigma == 2.0), None)
    down = next((c.total.per_portfolio for c in terminal if c.k_sigma == -2.0), None)
    ud: float | None = None
    if up is not None and down is not None and down < 0.0:
        ud = up / abs(down)
    return RiskRewardBlock(
        premium_to_max_loss=p_to_ml,
        upside_downside_2sigma=ud,
        definition=(
            "premium_to_max_loss = net premium received / |structural max loss|; "
            "upside_downside_2sigma = terminal P&L at +2sigma / |terminal P&L at -2sigma| "
            "(numerator is the finite +2sigma scenario, so uncapped upside is bounded to the band)."
        ),
    )


# ── Row assembly ───────────────────────────────────────────────────────────


def _premium_block(spec: StructureSpec, s0: float, coverage: float, block: int) -> PremiumBlock:
    net = _net_premium_per_btc(spec)
    return PremiumBlock(
        net_per_btc=net,
        pct_of_spot=100.0 * net / s0,
        per_contract=net * CME_CONTRACT_BTC,
        per_portfolio=net * coverage * block,
    )


def _fee_block(coverage: float, block: int, mandate_ref: float, s0: float) -> FeeBlock:
    fee = STRUCTURING_FEE_PCT / 100.0
    return FeeBlock(
        fee_pct=STRUCTURING_FEE_PCT,
        on_reference_notional_usd=fee * block * mandate_ref,
        on_executed_volume_usd=fee * coverage * block * s0,
    )


def _opportunity_cost(
    portfolio_terminal: list[ScenarioCell], block: int, s0: float,
) -> list[OpportunityCostCell]:
    """Upside foregone vs unhedged long BTC in the +sigma scenarios (total-portfolio view)."""
    cells: list[OpportunityCostCell] = []
    for c in portfolio_terminal:
        if c.k_sigma <= 0.0:
            continue
        unhedged_pp = block * (c.scenario_spot - s0)
        foregone_pp = max(0.0, unhedged_pp - c.total.per_portfolio)
        cells.append(OpportunityCostCell(
            k_sigma=c.k_sigma, scenario_spot=c.scenario_spot,
            foregone=_granular(foregone_pp, block),
        ))
    return cells


def _compute_row(
    spec: StructureSpec,
    business_label: str,
    exp: GridExpiry,
    coverage_pct: float,
    s0: float,
    block: int,
    mandate_ref: float,
) -> GridRow:
    coverage = coverage_pct / 100.0
    t = exp.t_years
    sh = exp.sigma_horizon
    premium = _premium_block(spec, s0, coverage, block)
    inst = _scenarios(spec, s0, t, coverage, block, sh, "instantaneous")
    term = _scenarios(spec, s0, t, coverage, block, sh, "terminal")
    inst_pf = _scenarios(spec, s0, t, coverage, block, sh, "instantaneous", holding_always=True)
    term_pf = _scenarios(spec, s0, t, coverage, block, sh, "terminal", holding_always=True)
    max_loss = _max_loss(spec, s0, coverage, block)
    breakevens = _breakevens(spec, s0, coverage, block)
    greeks = _greeks(spec, s0, t, coverage)
    prob_win = _prob_win(spec, s0, t)
    risk_reward = _risk_reward(premium.per_portfolio, max_loss, term)

    effective_net_price: float | None = None
    if spec.has_cash and spec.primary_leg_index is not None:
        leg = spec.option_legs[spec.primary_leg_index]
        effective_net_price = leg.listed_strike - leg.premium_per_btc

    same = spec.has_holding
    view_note = (
        "Standalone == total-portfolio (this structure already includes the 30,000-BTC holding)."
        if same else
        "Standalone excludes the BTC holding; total-portfolio view = 30,000-BTC holding + structure."
    )

    return GridRow(
        structure_id=spec.structure_id,
        canonical_kind=spec.canonical_kind,
        is_hero=spec.structure_id in HERO_STRUCTURES,
        benchmark_only=(spec.structure_id == "unhedged_baseline"),
        has_holding=spec.has_holding,
        has_cash=spec.has_cash,
        business_label=business_label,
        expiry_label=exp.label,
        expiry_utc=exp.expiry_utc,
        dte_days=exp.dte_days,
        t_years=t,
        coverage_pct=coverage_pct,
        strike_pct=spec.primary_strike_pct,
        atm_iv=exp.atm_iv,
        sigma_horizon=sh,
        option_legs=list(spec.option_legs),
        premium=premium,
        prob_win=prob_win,
        max_loss=max_loss,
        breakeven=BreakevenBlock(
            strike_pct_otm=spec.primary_strike_pct,
            true_breakevens=breakevens,
            note="(a) strike distance %OTM; (b) true terminal P&L breakeven spot(s).",
        ),
        greeks=greeks,
        risk_reward=risk_reward,
        structuring_fee=_fee_block(coverage, block, mandate_ref, s0),
        scenarios_instantaneous=inst,
        scenarios_terminal=term,
        scenarios_instantaneous_portfolio=inst_pf,
        scenarios_terminal_portfolio=term_pf,
        scenario_view_note=view_note,
        opportunity_cost=_opportunity_cost(term_pf, block, s0),
        theta_decay=_theta_decay(spec, s0, t),
        effective_net_price=effective_net_price,
        attractive_when=ATTRACTIVE_WHEN.get(spec.structure_id, ""),
    )


# ── Structure-spec builders ────────────────────────────────────────────────


def _resolve_leg_r(
    name: str, books: Sequence[BookSummary], fallback_r: float,
) -> tuple[float, str]:
    """Per-instrument r: OBSERVED Deribit interest_rate if the book exists, else ASSUMED config."""
    for b in books:
        if b.instrument_name == name:
            return b.interest_rate, "observed (deribit interest_rate)"
    return fallback_r, f"assumed (config {fallback_r * 100:g}%)"


def _leg(
    kind: str, side: str, pct_signed: float, s0: float, fallback_r: float, t: float,
    expiry_utc: str, instruments: Sequence[OptionInstrument], books: Sequence[BookSummary],
    notional_weight: float = 1.0,
) -> OptionLegSpec:
    expiry = datetime.fromisoformat(expiry_utc)
    requested = s0 * (1.0 + pct_signed / 100.0)
    listed, name = snap_to_listed_strike(instruments, expiry, kind, requested)
    lk = iv_for(listed, expiry, kind, instruments, books)
    r, r_prov = _resolve_leg_r(name, books, fallback_r)
    prem = bs_price(s0, listed, r, lk.iv, t, kind)
    return OptionLegSpec(
        kind=kind, side=side, requested_pct=pct_signed, listed_strike=listed,
        iv=lk.iv, iv_provenance=lk.provenance.value, instrument=name,
        premium_per_btc=prem, r=r, r_provenance=r_prov, notional_weight=notional_weight,
    )


def _specs_for_expiry(
    exp: GridExpiry, s0: float, fallback_r: float,
    instruments: Sequence[OptionInstrument], books: Sequence[BookSummary],
) -> list[tuple[StructureSpec, str]]:
    """All (StructureSpec, business_label) for one expiry, sweeping strike%."""
    t = exp.t_years
    e = exp.expiry_utc
    out: list[tuple[StructureSpec, str]] = []

    def opt(kind: str, side: str, pct: float, w: float = 1.0) -> OptionLegSpec:
        return _leg(kind, side, pct, s0, fallback_r, t, e, instruments, books, w)

    # Unhedged baseline (holding only) - one reference row per expiry.
    out.append((StructureSpec(
        structure_id="unhedged_baseline", canonical_kind="unhedged", has_holding=True,
        has_cash=False, option_legs=[], primary_strike_pct=None, primary_leg_index=None,
    ), "Unhedged BTC Holding"))

    # Covered call (HERO) / partial overlay - holding + short call at +pct.
    for pct in CALL_OTM_PCT:
        out.append((StructureSpec(
            structure_id="covered_call",
            canonical_kind="covered_call",
            has_holding=True, has_cash=False,
            option_legs=[opt("call", "SHORT", pct)],
            primary_strike_pct=pct, primary_leg_index=0,
        ), "Covered Call (Long BTC + Short Call)"))

    # Long BTC + short put (HERO) - holding + short put at -pct.
    for pct in PUT_OTM_PCT:
        out.append((StructureSpec(
            structure_id="long_btc_plus_short_put",
            canonical_kind="long_btc_plus_short_put",
            has_holding=True, has_cash=False,
            option_legs=[opt("put", "SHORT", -pct)],
            primary_strike_pct=-pct, primary_leg_index=0,
        ), "Long BTC + Short Put"))

    # Cash-secured put - cash + short put at -pct (no holding).
    for pct in PUT_OTM_PCT:
        out.append((StructureSpec(
            structure_id="cash_secured_put", canonical_kind="cash_secured_put",
            has_holding=False, has_cash=True,
            option_legs=[opt("put", "SHORT", -pct)],
            primary_strike_pct=-pct, primary_leg_index=0,
        ), "Cash-Secured Put"))

    # Collar - holding + short call at +pct + long protective put at a floor.
    # Primary floor 10% OTM (deck Slide-4 ~ -10%); a labelled 5% floor variant is also emitted.
    for floor in COLLAR_FLOOR_PCTS:
        for pct in CALL_OTM_PCT:
            out.append((StructureSpec(
                structure_id="collar", canonical_kind="collar",
                has_holding=True, has_cash=False,
                option_legs=[opt("call", "SHORT", pct), opt("put", "LONG", -floor)],
                primary_strike_pct=pct, primary_leg_index=0,
            ), f"Collar (Long BTC + Short Call + Long Put, {floor:g}% floor)"))

    # Call spread - short call + long call, adjacent widths (no holding).
    for short_pct, long_pct in CALL_SPREAD_PAIRS:
        out.append((StructureSpec(
            structure_id="call_spread", canonical_kind="call_spread",
            has_holding=False, has_cash=False,
            option_legs=[opt("call", "SHORT", short_pct), opt("call", "LONG", long_pct)],
            primary_strike_pct=short_pct, primary_leg_index=0,
        ), f"Call Spread ({short_pct:g}%/{long_pct:g}%)"))

    # Strike ladder - holding + equal-weighted short calls across rungs (single expiry).
    ladder_legs = [opt("call", "SHORT", p, 1.0 / len(LADDER_PCTS)) for p in LADDER_PCTS]
    out.append((StructureSpec(
        structure_id="strike_ladder", canonical_kind="partial_overlay",
        has_holding=True, has_cash=False, option_legs=ladder_legs,
        primary_strike_pct=LADDER_PCTS[0], primary_leg_index=0,
    ), "Strike Ladder (Long BTC + laddered Short Calls)"))

    return out


# ── Grid build ─────────────────────────────────────────────────────────────


def atm_iv_for_expiry(
    expiry_utc: str, s0: float,
    instruments: Sequence[OptionInstrument], books: Sequence[BookSummary],
) -> float:
    expiry = datetime.fromisoformat(expiry_utc)
    listed, _ = snap_to_listed_strike(instruments, expiry, "call", s0)
    return iv_for(listed, expiry, "call", instruments, books).iv


def build_grid(
    as_of_utc: str,
    snapshot_dir: str,
    s0: float,
    r_fallback: float,
    expiries: list[GridExpiry],
    instruments: Sequence[OptionInstrument],
    books: Sequence[BookSummary],
    block: int = PORTFOLIO_BTC,
    mandate_reference_spot: float = MANDATE_REFERENCE_SPOT,
) -> StrategyGrid:
    """Build the full deterministic strategy grid off a frozen snapshot.

    Each option leg prices with its own OBSERVED Deribit interest_rate where the
    book summary exists, else *r_fallback* (ASSUMED, labelled per leg).
    """
    rows: list[GridRow] = []
    r_provs: set[str] = set()
    for exp in expiries:
        for spec, label in _specs_for_expiry(exp, s0, r_fallback, instruments, books):
            if not spec.has_holding and not spec.option_legs:
                continue
            r_provs.update(leg.r_provenance for leg in spec.option_legs)
            coverages = COVERAGE_PCT if spec.option_legs else (100.0,)
            for coverage_pct in coverages:
                rows.append(_compute_row(
                    spec, label, exp, coverage_pct, s0, block, mandate_reference_spot,
                ))
    r_provenance = "; ".join(sorted(r_provs)) if r_provs else "n/a"

    framing_notes = [
        f"t0 = snapshot as-of {as_of_utc}; DTE and greeks computed from t0.",
        "Holding leg = full 30,000-BTC block (client's inherent exposure), MTM from t0 spot.",
        "Option leg notional = coverage x 30,000 BTC (the advised overlay).",
        "partial_overlay = covered_call family at coverage<100% (canonical kind reflects it).",
        f"collar: short call over strike%, protective long put floors {COLLAR_FLOOR_PCTS} %OTM "
        f"(10% primary per deck Slide-4; 5% variant also emitted).",
        "call_spread: CREDIT spread - SHORT lower strike / LONG higher strike (premium-generating).",
        f"strike_ladder: equal-weighted short calls at {LADDER_PCTS} %OTM, single expiry "
        f"(multi-DTE ladder is Phase 3).",
        "Scenario sigma per tenor: sigma_h(T)=ATM_IV(T)*sqrt(T/365); each expiry uses its own ATM IV.",
        f"Pricing bridge: linear-USD Black-Scholes with Deribit mark_iv and r [{r_provenance}]; "
        "Deribit is inverse/BTC-settled, CME is linear/USD-settled.",
        "Two scenario views per row: standalone + total-portfolio (30,000-BTC holding + structure).",
        "Denominators labelled: scenario % over portfolio notional (30,000*S0); max-loss %capital "
        "over the structure's own committed capital (see max_loss.capital_basis).",
        "Structuring fee (0.5%) is a SEPARATE line, pre-fee grid; both D-1 bases emitted.",
        "Grid is unhedged (D-9): greeks shown, no delta-hedge P&L applied.",
        "BTC carry q ASSUMED 0 (MS-11); USD premiums exact at q=0; see grid.carry_assumption "
        "for the q-sensitivity and the exact inverse-identity audit path.",
        "opportunity_cost = max(0, unhedged_total - structure_total) on the total-portfolio view "
        "(net of premium; the brief's gross max(0,S_T-K)*q differs by the premium received).",
        "unhedged_baseline is an internal benchmark only - never a featured/recommended row.",
        "CEO 2% / deck 2.5% premium and 36%/45% vol are labelled reference markers only.",
    ]
    return StrategyGrid(
        as_of_utc=as_of_utc, snapshot_dir=snapshot_dir, s0=s0,
        r_fallback=r_fallback, r_provenance=r_provenance,
        mandate_reference_spot=mandate_reference_spot,
        block_btc=block, cme_contract_btc=CME_CONTRACT_BTC,
        expiries=expiries, rows=rows, framing_notes=framing_notes,
    )
