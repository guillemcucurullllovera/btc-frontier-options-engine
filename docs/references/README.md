# BTC Engine Reference Library

This directory will contain concise, source-grounded implementation notes.

Original textbooks, papers and official documents will later be stored in a
private Git-ignored source directory. They have not yet been transferred.

## Planned topics

- Option pricing and Greeks
- Implied volatility and volatility surfaces
- Inverse BTC options
- Covered calls
- Cash-secured puts
- Long BTC plus short put
- Assignment, exercise and settlement
- Rolling and dynamic hedging
- Monte Carlo and stress testing
- Backtest validation
- Market microstructure and execution impact
- Counterparty, collateral and OTC documentation
- Bitcoin transaction and custody mechanics

## Source hierarchy

1. Venue and contract documentation
2. Official API documentation
3. Peer-reviewed and specialist financial literature
4. Textbooks
5. Internal business requirements

Venue documentation controls actual exercise, settlement, fees, margin and
contract behaviour.

Each implementation note must record:

- Exact source, edition and chapter or section
- Formula or operational rule
- Assumptions
- Software module affected
- Tests required
- Whether the content is theory, venue rules, observed data or a business
  requirement
