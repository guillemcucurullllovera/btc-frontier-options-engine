# Sanitised BTC Acquisition Mandate

## Business objective

Evaluate structures for acquiring a reference quantity of 30,000 BTC at an
effective discount to spot.

All quantities and percentages must remain configurable.

## Reference economics

- Reference BTC quantity: 30,000 BTC
- Target effective discount: approximately 5.0% versus reference spot
- Potential direct seller discount: approximately 2.5%
- Potential additional options contribution: approximately 2.5%
- Asymmetrica execution and structuring fee: 0.5%

The seller discount, options contribution, execution costs and Asymmetrica fee
must be modelled separately.

## Structures requiring analysis

- Direct discounted BTC acquisition
- Covered call: long BTC plus short call
- Cash-secured put
- Long BTC plus short put
- Partial covered-call overlay
- Staggered strikes and expiries
- Call spreads
- Collars
- Rolling and closing rules
- Delta or futures hedging where relevant

## Source-diagram discrepancy

One supplied diagram is labelled:

"Covered Put Strategy (Long BTC + Short Put)"

The title must not be treated as authoritative.

The position shown consists of:

- Long BTC
- Short put

The engine must derive its canonical classification and payoff from the actual
position legs. It must compare the calculated result with the source labels,
breakeven and profit/loss annotations.

## Required analysis

- Expiry payoff
- Mark-to-market P&L
- Premium contribution
- Effective BTC acquisition cost
- Strike-breach and finish-ITM probability
- Physical assignment where applicable
- Cash and inverse-BTC settlement
- Rolling and early-close costs
- Hedge costs
- Bid/ask spread
- Market impact
- Tranching for institutional scale
- Historical backtesting
- Monte Carlo and stress testing
- Out-of-sample validation
- Regime analysis

## Data rules

- Massive is the primary long-history BTC spot source.
- Deribit supplies current native BTC-options information.
- Observed market data must remain separate from model-generated historical
  option prices.
- No simulated bid, ask, implied volatility, Greek or liquidity value may be
  represented as an observed market value.

## Confidentiality

Do not include counterparty identities, sovereign-fund identities, introducer
identities, wallet addresses, API keys or other deal-identifying information in
prompts, reports, fixtures, logs or commits.
