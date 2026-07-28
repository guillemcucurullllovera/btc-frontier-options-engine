# Agent A4 — Execution, Impact & Tranching (MiniMax)
**Branch:** feat/execution · **Depends on:** contracts.md
## Task
(1) impact.py: I-Star equations (Kissell eq. 4.6 and 4.7 with explicit parameters), timing risk, benchmark selection, Block RFQ / Voice Broker execution-path assumption per Deribit institutional trading articles; parametric per-clip IV give-up (default 0.5-2.0 vol pts, configurable); net overlay yield after give-up. (2) tranches.py: scheduler across expiry ladder [30,37,44] DTE and clip sizes [250..1000] BTC over 4-8 weeks; machine-readable schedule + human table. (3) waterfall.py: add sensitivity mode (spot +-1..10%; fee-base variants: full notional vs executed volume).

**Important correction per contracts.md §17.3:** Specify the `KissellConfig` model per contracts.md §12.1 with all eight parameters: `a1`, `a2`, `a3`, `b1`, `a4`, `order_size_btc`, `adv_btc`, `volatility`, `pov`. Implement `estimate_impact(config: KissellConfig) -> ImpactEstimate` with the I-Star formula: `I*_bp = a1 * (Q/ADV)^a2 * σ^a3`, `MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*`.

## Definition of Done
- Schedule totals exactly 30,000 BTC; sensitivities tested; give-up feeds A3 cycle yields
- KissellConfig validated with provenance per component
- Waterfall sensitivity mode covers all spot_offset × fee_base combinations
