"""Standard Black-Scholes payoff functions per contracts.md §7.3.

These are settlement amounts, not strategy P&L. Sign is positive for
the LONG HOLDER. For the SHORT WRITER, the cash flow is the negation.
"""

from __future__ import annotations


def payoff_bs_call(S_T: float, K: float) -> float:
    """max(S_T - K, 0) — gross settlement to the long call holder in USD."""

    return float(max(S_T - K, 0.0))


def payoff_bs_put(S_T: float, K: float) -> float:
    """max(K - S_T, 0) — gross settlement to the long put holder in USD."""

    return float(max(K - S_T, 0.0))
