# 30,000 BTC Programme — Build-First Delivery Plan (Parallel Agents)
**Fable pass, 27.07.2026. Mode: pipeline construction & validation — we are building and testing the full workflow that demonstrates the winning idea, not executing the live transaction. Production gates are parked at the end, non-blocking.**
**Companion artifact: `btc_engine_scaffold.zip` — a working Sprint-0 starter (9 tests green, waterfall verified) so the build starts from running code, not a blank repo.**

---

## 1. What "success" means in this mode

Three demo artifacts prove the idea is executable and sellable:

1. **The live waterfall** — one command shows the full economics at any spot: $1.95bn notional, $9.75M / 150 BTC Asymmetrica fee, $62,075 effective client cost (4.5% net) at the $65,000 reference. *(Already runs in the scaffold.)*
2. **The cycle simulator** — for any delta/DTE/IV combination, the engine shows premium per cycle, ITM frequency, and cycles-to-target; the mandate structure (10–15Δ, 30–45 DTE) reaches the 2.5% overlay target in ~2–4 cycles at current DVOL, faster on vol spikes. This is the table that survives scrutiny from any advisor or client-side trader.
3. **The corrected chart pack** — the six-step payoff sequence (spot → option leg → combined, for both structures) generated at live spot, replacing the mislabeled chart in circulation.

Everything below exists to produce these three artifacts at institutional quality, fast.

---

## 2. Parallel-agent architecture

**Orchestration model:** one repo, one frozen interface contract, six agents on independent branches. Fable (this pass) is architect + validator; DeepSeek V4 and MiniMax via OpenCode on the Hetzner box are the implementation workforce. Claude Code slots back in as the implementation layer whenever it's working again — the briefs are tool-agnostic.

```
                    ┌─ A1 Pricing & Greeks (DeepSeek) ──────┐
Sprint 0            ├─ A2 Data & Vol layer (MiniMax, net) ──┤
A6 freezes          ├─ A3 Scenarios/Backtest/MC (DeepSeek) ─┼─→ A6 merges → Fable
contracts.md   ──→  ├─ A4 Execution/Impact (MiniMax) ───────┤   cross-validates →
+ stubs             └─ A5 Reports/Charts/Demo (DeepSeek) ───┘   demo pack ships
```

**Why this parallelizes cleanly:** the only true dependency is the interface contract (function signatures + pydantic models), which A6 freezes on day 0. A1–A5 then work against stubs and recorded fixtures simultaneously. Merge order A1→A2→A4→A3→A5 resolves the soft dependencies (A3 consumes A1's pricers and A2's IV history; A5 consumes everyone's outputs).

**Non-negotiable rules baked into every brief:**
- Anonymization: DeepSeek/MiniMax receive only generic, parameter-driven tasks — no counterparty names, wallets, or deal-identifying details in any prompt, commit, or fixture. (Confidential synthesis stays in Fable.)
- Cross-validation: no single model's arithmetic ships. Every human-facing number is independently re-derived in the Fable pass before it leaves the repo. (The scaffold's test suite is the first layer of this: Haug golden vectors, put-call parity, delta-inversion roundtrips, and the mandate-economics assertions are already enforced in CI.)
- `config/params.yaml` is the single source of truth; nothing hard-coded, so alternative structures are testable without rewrites.

**The six agent briefs are in the scaffold** (`agents/A1..A6_*.md`), each with branch, dependencies, definition of done, and a paste-ready OpenCode prompt.

---

## 3. Sprint plan (working days, aggressive but realistic)

### Sprint 0 — Day 0–1: Foundation *(delivered with this document)*
Scaffold running: BS pricer with Greeks + delta↔strike inversion + implied vol; waterfall calculator reproducing the mandate economics; Deribit public-API feed module (spot index, DVOL, option chain, book summaries — no auth needed, ready to run from Hetzner); 9-test suite green. **A6's day-1 job:** freeze `contracts.md` + pydantic models, stand up the repo on the Hetzner box with CI (pytest+mypy+ruff), record the first live fixtures from Deribit. Gate: contracts frozen, CI green, live fixtures captured.

### Sprint 1 — Days 1–4: Parallel core build (A1 ∥ A2 ∥ A4)
- **A1:** Black-76, inverse-option adjustment (BTC-settled convention documented against Deribit's spec), vectorized grid pricing, QuantLib parity suite.
- **A2:** hardened live feed with caching + fixture recorder; smile fit per expiry from `book_summary` mark IVs; CryptoDataDownload historical ingest (daily DVOL + option OHLCV — the free tier that makes v1 possible without vendor spend); GARCH realized-vol forecast.
- **A4:** IV give-up model per RFQ clip; tranche scheduler across the [30/37/44] DTE ladder summing to exactly 30,000 BTC; waterfall sensitivity mode (spot ±10%, fee-base variants — this directly feeds open decision "fee on full notional vs executed volume", a $9.75M swing).
Gate: parity suite green; live surface round-trips mark IV within 0.5 vol pts; schedules reconcile.

### Sprint 2 — Days 4–7: Scenarios & stress (A3, consuming A1+A2)
Monte Carlo (GBM + Merton + Kou jumps, 100k paths <5s); the five-path backtest over Jan-2023→Jul-2026 (immediate spot / OTC −2.5% alone / covered call at mandate delta / covered call at the ~30–35Δ that yields 3%/cycle / cash-secured-put entry); stress replays of the 2023–24 surge, the 2025 breakout to the $126k ATH, the 2026 retrace to ~$65k, and the recent DVOL 35→65 shock. Where historical chains are missing, premiums are DVOL-reconstructed and labeled as such — honest v1, upgradeable to vendor data later. Gate: deterministic, serialized results; cycles-to-target distribution produced.

### Sprint 3 — Days 7–10: Demo assembly (A5 + Fable)
Corrected six-chart payoff pack at live spot; cycle-tracker report (realized premium vs 2.5% cumulative target); `python -m reports.demo` → complete demo pack offline in <60s; Fable cross-validation of every table; internal dry-run of the demo script (Sec. 5). Gate: demo pack reproducible from a clean clone.

### Sprint 4 — Days 10–14: Hardening & optional upgrades
Live RFQ-quote capture hooks (so the impact model calibrates on real quotes the day sourcing starts); Docker + one-command Hetzner deploy; optional vendor-data slot (Amberdata/Tardis/Kaiko, $5–30k) wired but not required; parameter presets for alternative structures (collar; put-sleeve percentages) so client-conversation variants render live.

**Total: ~2 weeks to a demo that sells the idea, with the heavy lifting parallelized across days 1–7.**

---

## 4. Data plan (all free-tier for v1; verified sources)

| Need | Source | Access | Notes |
|---|---|---|---|
| Live spot index | Deribit `/public/get_index_price` | No auth | Module ready in scaffold |
| Live DVOL | Deribit `/public/get_volatility_index_data` | No auth | Current band ~40–45 (27.07) |
| Live option chain + mark IVs | Deribit `/public/get_instruments`, `/public/get_book_summary_by_currency` | No auth | Surface calibration input |
| Historical DVOL + option OHLCV | CryptoDataDownload free CSVs | Free | Powers the v1 backtest |
| Spot history | Any major venue API / CSV | Free | Cross-checked vs 27.07 cluster $64.5–65.4k |
| Full historical bid/ask chains | Amberdata / Tardis / Kaiko / Coin Metrics | Paid ($5–30k) | Optional production upgrade; slot wired in Sprint 4 |
| Venue rulebooks (Deribit specs/Block RFQ, CME specs/Rule 526-538/BRR/BVX, Binance VIP-OTC, ISDA DA definitions summaries, FINMA guidance) | Official sites | Free | Fetched, dated, versioned into `docs/` during Sprint 1 by A2 as a side task — venue rules override textbook theory wherever they conflict |

---

## 5. The demo script (15 minutes — what actually sells it)

1. **Open with the waterfall, live.** Fetch spot, run one command, show the full economics at today's price including Asymmetrica's 150 BTC / $9.75M fee line. Message: *the economics are engineered, not asserted.*
2. **The cycle simulator.** Slide delta from 10 to 35 on screen: premium/cycle, ITM frequency, and cycles-to-2.5% update live. Show the mandate structure reaching the target in ~2–4 cycles, and exactly what an acceleration costs. Message: *we quantify the trade-off curve the client will be choosing on — nobody in the room can hand-wave past our own table.*
3. **The chart pack.** The six-step payoff sequence, correctly labeled, generated at the live price. Message: *client education materials come from the engine, so they're always current and always right.*
4. **The stress reel.** The 2025-breakout replay showing what happens to each structure in the exact scenario the client fears. Message: *we've already lived the bad path in simulation.*
5. **Close with the tranche schedule** — 30,000 BTC laddered across expiries and clips with modeled impact. Message: *size has been engineered, not ignored.*

The client presentation itself (deck/video) remains its own later workstream — but every asset in it is generated by this engine, which is precisely the capability story Francisco wants to tell.

---

## 6. Production gates (parked — explicitly non-blocking for the build)

Nothing in Sprints 0–4 requires KYC, counsel, or counterparty verification: the pipeline builds and demos entirely on public market data and configurable parameters. The production track (counterparty verification per the existing NDA→satoshi-test procedure, counsel on Asymmetrica's role classification, mandate letters, venue accounts, term-sheet adaptation to the live structure) activates only when a real counterparty enters the process — it runs in parallel to Sprint 4 at the earliest, and none of it touches the engine's critical path. The one thing worth doing early because it's free and instant: Francisco's written answers to the four parameter decisions (fee base, reference price source, venue selection, put-sleeve consent), since they're config values the engine will otherwise carry as variants.

---

## 7. Extras identified during this pass (things the second prompt implies but doesn't spell out)

- **Fixture-recording discipline** (A2): every live API response cached and replayable → the whole pipeline tests offline, CI never depends on exchange uptime, and demos never fail on stage.
- **Fee-base sensitivity as a first-class output** (A4): the "full notional vs executed volume" question is a $9.75M swing — rendering it as a live toggle turns an awkward open item into a deliberate client choice.
- **The correction note as an asset:** regenerating the mislabeled chart *correctly labeled* (leveraged-bullish, slope +1/+2, no profit cap) documents the team's rigor — quietly valuable when an advisor reviews the materials.
- **DVOL-triggered execution rule as code, not prose** (A3/A4): `sell_when_dvol_above: 55, stand_down_on_breakout: true` in params — the vol-opportunistic policy becomes testable and demo-able.
- **QuantLib as the independent referee** (A1/A6): parity in CI means every number the team shows has been agreed by two implementations.
- **Tool-agnostic briefs:** written so Claude Code, DeepSeek, or MiniMax can each execute them — the workforce is swappable, the architecture isn't.

---
*Companion artifacts delivered with this plan: `btc_engine_scaffold.zip` (running code, 9 tests green, agent briefs A1–A6, README). Prior strategy/compliance analysis: `Asymmetrica_BTC_30k_Mandate_Plan_v2.md` — remains the reference for the economics and structures; this document supersedes its phasing for build purposes.*
