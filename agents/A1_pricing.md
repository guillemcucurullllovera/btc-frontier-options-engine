# Agent A1 — Pricing & Greeks (DeepSeek V4 via OpenCode)
**Branch:** feat/pricing · **Depends on:** contracts.md (frozen interfaces) · **Parallel-safe:** yes
## Task
Extend pricing/black_scholes.py: (1) Black-76 on futures; (2) inverse-option adjustment (BTC-settled payoff: price in BTC = USD price / index; document convention vs Deribit spec); (3) full put Greeks; (4) vectorized numpy pricing over strike/expiry grids.
## Definition of Done
- Existing tests stay green; >=10 new golden vectors from Haug tables
- QuantLib parity: max abs diff < 1e-6 on 50 random (S,K,r,sigma,T) draws (hypothesis)
- mypy --strict clean; ruff clean
## Paste-ready prompt
"You are implementing module pricing/ in a Python 3.12 quant repo. Interfaces are frozen in contracts.md. Do not modify other modules. Extend black_scholes.py with Black-76, an inverse BTC option adjustment (document the convention), put Greeks, and vectorized grid pricing. Add Haug golden-vector tests and a QuantLib parity test using hypothesis. All numbers decimals, T in years. Run pytest and paste output."
