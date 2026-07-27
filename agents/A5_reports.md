# Agent A5 — Reports, Charts & Demo Artifacts (DeepSeek V4)
**Branch:** feat/reports
## Task
(1) charts.py (matplotlib): six-chart corrected payoff sequence — A1 long spot, A2 short OTM call, A3 combined covered call; B1 reserved cash, B2 short OTM put, B3 combined cash-secured put — at live spot, premium-inclusive breakevens. Also regenerate the circulating long-BTC+short-put chart CORRECTLY labeled (leveraged-bullish; slope +1 above strike, +2 below; no max-profit cap) for the internal correction note. (2) cycle_report.py: per-cycle premium vs 2.5% cumulative target tracker. (3) demo.py: one command -> full demo pack (charts + waterfall + backtest summary md) into reports/out/.
## Definition of Done
- `python -m reports.demo` produces the complete pack from fixtures, offline, < 60s
