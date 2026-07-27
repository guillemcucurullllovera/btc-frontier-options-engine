# Agent A4 — Execution, Impact & Tranching (MiniMax)
**Branch:** feat/execution · **Depends on:** contracts.md
## Task
(1) impact.py: parametric per-clip IV give-up (default 0.5-2.0 vol pts, configurable; square-root impact form for the spot leg per Kissell/Almgren-Chriss); net overlay yield after give-up. (2) tranches.py: scheduler across expiry ladder [30,37,44] DTE and clip sizes [250..1000] BTC over 4-8 weeks; machine-readable schedule + human table. (3) waterfall.py: add sensitivity mode (spot +-1..10%; fee-base variants: full notional vs executed volume).
## Definition of Done
- Schedule totals exactly 30,000 BTC; sensitivities tested; give-up feeds A3 cycle yields
