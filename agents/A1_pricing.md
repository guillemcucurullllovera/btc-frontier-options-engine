# Agent A1 — Pricing & Greeks (DeepSeek V4 via OpenCode)
**Branch:** feat/pricing · **Depends on:** contracts.md (frozen interfaces) · **Parallel-safe:** yes
## Task
Extend pricing/black_scholes.py: (1) Black-76 on futures; (2) inverse-BTC option pricing re-derived from Deribit official spec (`deribitfilesascopiedtxt.txt` §"Inverse Options" lines 1–199) — implement `price_inverse_btc`, `greeks_inverse_btc`, `settlement_inverse_call_holder`, `settlement_inverse_put_holder` per contracts.md §7.3 using the full settlement-holder formula with delivery price, contract multiplier, and holder/writer sign convention; (3) full put Greeks; (4) vectorized numpy pricing over strike/expiry grids.
## Important correction per contracts.md §17.3
Do NOT use the `price_in_BTC = USD_price / index` approximation. Re-derive the inverse-BTC payoff from `deribitfilesascopiedtxt.txt` §"Inverse Options". Implement `settlement_inverse_*_holder` functions per contracts.md §7.3 with explicit holder/writer documentation.
## Definition of Done
- Existing tests stay green; >=10 new golden vectors from Haug tables
- Inverse settlement golden vectors: `settlement_inverse_call_holder(125000, 100000) == 0.2` and `settlement_inverse_put_holder(80000, 100000) == 0.25`
- QuantLib parity: max abs diff < 1e-6 on 50 random (S,K,r,sigma,T) draws for BS; < 1e-4 for Black-76 (hypothesis)
- mypy --strict clean; ruff clean
