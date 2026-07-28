# CEO Strategy Research Mandate

This document defines the research objective. It contains no client,
counterparty, wallet or transaction-identifying information.

## Objective

Determine whether an options overlay can improve the effective economics of a
configurable 30,000 BTC acquisition where:

- the seller discount target case is approximately 2.5%;
- an additional approximately 2.5% is sought from an options overlay;
- the execution fee is 0.5%, modelled separately from the seller discount,
  option premium and market-impact costs.

These percentages are business targets, not forecasts.

## Strategies requiring analysis

At minimum:

1. Covered call: long BTC plus short call.
2. Cash-secured put: cash collateral plus short put.
3. Long BTC plus short put, represented explicitly by its actual legs.
4. Partial covered-call overlays.
5. Staggered strikes and expiries.
6. Rolling and early-close policies.
7. Call spreads and collars where they improve the risk profile.

Do not infer a canonical strategy classification from a source title or chart
label.

## Required quantitative analysis

For every strategy and variant, analyse:

- expiry payoff;
- mark-to-market P&L;
- premium contribution;
- effective BTC acquisition economics;
- probability of finishing in the money;
- probability of touching or breaching the strike;
- venue-specific exercise and settlement risk;
- rolling and early-close costs;
- hedge costs;
- missed-upside risk;
- downside exposure;
- bid/ask spread;
- market impact;
- execution tranching for institutional scale;
- historical backtesting;
- Monte Carlo simulation;
- stress testing;
- out-of-sample validation;
- regime sensitivity.

## Hypotheses that must be tested, not assumed

The following are candidate policies rather than approved conclusions:

- 10–15 delta calls;
- 30–45 days to expiry;
- strikes approximately 15–20% above spot;
- approximately 3% premium per cycle;
- option delta as a direct assignment-probability estimate;
- selling only when implied volatility is elevated;
- reducing or pausing the overlay during strong BTC breakouts;
- the covered call being the safest or optimal structure.

The research must report when these claims hold, when they fail and what
trade-offs create the result.

## Presentation timing

Do not prepare the final client presentation or video yet.

First:

1. complete the source-backed design;
2. implement and validate the required engine;
3. run the strategy comparisons, backtests and stress tests;
4. independently verify the conclusions.

Only after that should a simple non-technical presentation be created showing
the strategies that remain defensible after testing.
