# BTC 30k Engine — build-first pipeline
Tests:        cd btc_engine && python3 -m pytest -q       (9 green at handover)
Waterfall:    python3 -m execution.waterfall
Live data:    python3 -m vol.dvol_feed                    (networked box; Deribit public API, no auth)
Agent briefs: agents/A1..A6 — paste-ready for OpenCode; A6 freezes contracts.md before parallel start
Params:       config/params.yaml — single source of truth; nothing hard-coded
