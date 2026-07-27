# Agent A3 — Scenarios, Backtest, Monte Carlo (DeepSeek V4)
**Branch:** feat/scenarios · **Depends on:** A1 interfaces, A2 fixtures
## Task
(1) montecarlo.py: GBM + Merton jump-diffusion + Kou double-exponential; antithetic variates; 100k paths < 5s. (2) backtest.py: cycle engine — each 30-45 DTE cycle sells calls at target delta band using IV from A2 history (DVOL proxy where chains missing, labeled "model-reconstructed"); paths: (i) spot now, (ii) OTC -2.5% alone, (iii) covered call 10-15d, (iv) covered call at the ~30-35d needed for 3%/cycle, (v) cash-secured-put entry; window Jan-2023..Jul-2026. (3) stress.py: replay 2023-24 surge, 2025 breakout to 126k ATH, 2026 retrace to ~65k; DVOL 35->65 shock.
Outputs: P&L distribution, per-cycle ITM frequency, cycles-to-2.5%-target distribution, effective acquisition cost per path — serialized to reports/data/*.json.
## Definition of Done
- Deterministic seeds; no parameter fitting inside the evaluation window (Lopez de Prado hygiene, documented)
