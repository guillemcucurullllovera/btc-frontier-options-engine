# Agent A2 — Data & Volatility Layer (MiniMax via OpenCode, Hetzner — needs network)
**Branch:** feat/vol · **Parallel-safe:** yes
## Task
(1) Harden vol/dvol_feed.py: retries/backoff, parquet caching to data/raw/, fixture recorder for offline tests. (2) surface.py: fit smile per expiry from book_summary mark_iv (spline; SVI stretch goal); interpolate IV(delta,dte). (3) history.py: ingest CryptoDataDownload free CSVs (daily DVOL + option OHLCV by expiry) into data/hist/. (4) garch.py: GARCH(1,1) on daily log returns (arch pkg); realized-vol forecast vs DVOL comparison.
## Definition of Done
- `python -m vol.dvol_feed` prints live spot, DVOL, chain size from Hetzner
- Recorded fixtures enable full offline test run; surface round-trips mark_iv within 0.5 vol pts
- Data schema documented in data/README.md
