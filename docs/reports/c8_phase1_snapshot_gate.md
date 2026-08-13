# C8 Phase 1 — Live Market Snapshot Gate Report

**Status:** Phase 1 complete; gated for orchestrator review before Phase 2.
**Discipline:** test-first; `pytest` / `mypy .` / `ruff check .` / anonymisation all green;
every emitted number provenance-labelled and snapshot-cited; no best/optimal/preferred
language; open decisions surfaced, not resolved.

---

## 1. Frozen snapshot (the deck's "as of" anchor)

Everything downstream reconciles to this single atomic pull of the Deribit public API.

| Field | Value |
|---|---|
| **As of (UTC)** | `2026-07-30T09:57:32.720182+00:00` |
| **git SHA** | `c9d0d9ae78fa9f6cb4e4b373eed4086d6ee0200c` (frozen C7 HEAD) |
| **Branch** | `sprint/c8-strategy-grid` |
| **Snapshot dir** | `market_snapshots/2026-07-30T095732Z/` |
| **Live BTC spot (USD)** | **64,496.28** (OBSERVED, deribit index) |
| **Mandate reference spot** | 65,000 (stated reference only; not used for pricing) |
| **DVOL (30-day BTC IV index)** | **0.3596 (35.96%)** (OBSERVED, deribit) |
| **Option instruments** | 934 (OBSERVED) |
| **Book summaries** | 934 (OBSERVED, per-instrument `mark_iv`) |

**SHA-256 checksums (frozen raw payloads):**

| File | sha256 |
|---|---|
| `index_price.json` | `0691a2df1fda48042a7692df3dabb52fed16eebb8af5065d0c6922ca4b89cde7` |
| `dvol.json` | `b8ac0f4d702520eecabb24ca5b74943a5817fb7eb9002907f3b95a87f2326f17` |
| `instruments.json` | `6c9f4cfa307f35fb34922ee1cd8a1d2ed9993aed973a22e0821f025bd55a80de` |
| `book_summary.json` | `b2cd9dba3017c312073c9d70f62add0a13e9d42b793e6fcd81a06a6437691ee8` |

Snapshot layout is byte-compatible with `tests/fixtures/`, so it replays offline via
`DeribitClient(fixture_dir=...)`. `snapshot_market.py` default replays the frozen snapshot
(stable numbers); `--refresh` re-anchors. Provenance for spot / DVOL / chain / IV flips to
**OBSERVED (deribit, 2026-07-30T09:57:32Z)** for this snapshot — resolving MS-1/MS-2/MS-3/D-2
**for the snapshot scope only** (the ASSUMED constant path is retained for offline/CI).

> **Reproducibility note:** the raw snapshot payload (~1.2 MB) is currently git-ignored under
> `market_snapshots/` (per orchestration §10 — bulk results not committed without approval).
> It persists on disk and is fully identified by the checksums above. **Decision surfaced
> (§7): commit the raw snapshot to the repo so the deck reconciles against version control, or
> keep it disk-only + checksum-referenced?**

---

## 2. Chosen expiries — exact calendar + days-left + liquidity evidence

"Liquid" = populated book summary (mark_iv > 0, both bid and ask present, non-zero OI).
Reference instant = the snapshot's own `as of` (2026-07-30T09:57:32Z).

| Target | Selected expiry | Calendar (UTC) | Days left | Liquid strikes | Total OI |
|---|---|---|---|---|---|
| ~30d | **28AUG26** | 2026-08-28T08:00:00Z | **28.92** | 92 / 98 | 48,361.2 |
| ~45d | **25SEP26** | 2026-09-25T08:00:00Z | **56.92** | 98 / 120 | 88,113.5 |
| ~60d | **25SEP26** | 2026-09-25T08:00:00Z | **56.92** | 98 / 120 | 88,113.5 |

### Material finding — tenor collapse (orchestrator-resolved)

The live Deribit ladder lists liquid monthlies at **~29d (28AUG26)** and **~57d (25SEP26)**,
then jumps to **~148d (25DEC26)**. **There is no listed ~45d or ~60d expiry**, so the nominal
30/45/60d targets resolve to only **two distinct liquid listed expiries** — 45d and 60d both
snap to 25SEP26. This was surfaced to the orchestrator before coding; the resolution chosen was
**"report the two genuine liquid monthlies and document the gap"** (not force a spurious third
tenor, not silently dedupe). The selector records the collapse explicitly:

> *"Targets 45d and 60d both resolve to 25SEP26 (56.9d): no distinct liquid listed expiry near
> the collapsed target(s)."*

Selection is general (nearest-liquid per target, future-only, tie-break toward higher OI then
sooner expiry) — if a genuine ~45d listing appears on a future snapshot, three distinct tenors
would emerge automatically.

---

## 3. Per-(strike,expiry) IV lookup

**Mechanism (orchestrator-resolved):** each grid cell uses the **exact listed instrument's
OBSERVED `mark_iv`**; a strike not listed falls back to **MODEL_RECONSTRUCTED** interpolation
across that expiry's listed smile in **strike space** (flat extrapolation beyond the listed
range). Note `vol/surface.py::iv_at` is delta-parameterised (and derives delta from a
strike-guess heuristic that ignores the true listed strike); since grid strikes are snapped to
listed strikes, strike-space smile interpolation is the faithful, directly-usable fallback. The
delta-parameterised surface is still fit for **diagnostics** (see §4).

**Preview over the swept OTM grid** (calls {1.5,3,5,10,15}%, puts {3,5,10}%, off live spot,
snapped to listed strikes) — all 16 cells resolved OBSERVED (direct listed mark_iv):

| Expiry | Kind | %OTM | Requested K | Listed K | IV | Provenance |
|---|---|---|---|---|---|---|
| 28AUG26 | call | +1.5 | 65,464 | 65,000 | 0.3403 | observed |
| 28AUG26 | call | +3.0 | 66,431 | 66,000 | 0.3363 | observed |
| 28AUG26 | call | +5.0 | 67,721 | 68,000 | 0.3262 | observed |
| 28AUG26 | call | +10.0 | 70,946 | 71,000 | 0.3207 | observed |
| 28AUG26 | call | +15.0 | 74,171 | 74,000 | 0.3298 | observed |
| 28AUG26 | put | −3.0 | 62,561 | 63,000 | 0.3548 | observed |
| 28AUG26 | put | −5.0 | 61,271 | 61,000 | 0.3695 | observed |
| 28AUG26 | put | −10.0 | 58,047 | 58,000 | 0.4023 | observed |

Smile is coherent (call skew declining then rising; put skew rising into OTM). The full preview
(16 rows, both expiries) is in `phase1_summary.json`. **Both requested-% and actual-listed
strike are reported**, per locked decision #1.

---

## 4. IV-surface fit diagnostics

`vol/surface.py::fit_surface` over 934 book summaries → **934 points**, method `spline`,
fit RMSE ≈ 9.3e-16. Used for diagnostics only; grid IV is sourced as in §3.

---

## 5. Realised vol — comparison only (365-day annualised)

Estimator: close-to-close log-return sample standard deviation (ddof=1), annualised ×√365.
Source: **Massive** (primary historical spot; 64 daily bars frozen into the snapshot as
`spot_history.json`). Realised vol is a **labelled comparison marker only — never a pricing
input**.

| Window | Realised σ (annual) | # returns | Provenance |
|---|---|---|---|
| 29d | **0.2897 (28.97%)** | 27 | OBSERVED (massive) |
| 30d | **0.2968 (29.68%)** | 28 | OBSERVED (massive) |
| 57d | **0.3420 (34.20%)** | 55 | OBSERVED (massive) |

**DVOL vs realised (30d):** implied **0.3596** − realised **0.2968** = **+0.0628** (implied
richer than realised by ~6.3 vol points; comparison marker only). The CEO's 36% and the engine
constant 45% are retained **only as labelled comparison markers**, not pricing inputs.

### Needed-fix applied (test-first) — Massive `DELAYED` status

Massive initially returned `status: "DELAYED"` (delayed-feed tier) with fully-populated, final
daily bars; the provider hard-rejected any non-`"OK"` status, blocking realised vol. Fixed
`vol/history.py` to accept `{"OK","DELAYED"}` (daily historical closes are final and observed;
latency is immaterial for prior-day closes) while still rejecting `"ERROR"`/empty. Covered by
`tests/test_vol.py::test_massive_accepts_delayed_status`; the existing malformed-response test
(status `"ERROR"` still raises) continues to pass. This is a §6 "C7 follow-up touched by this
work," not a business/methodology gate.

---

## 6. Gate checklist

| Gate | Result |
|---|---|
| `pytest` | **567 passed, 3 skipped** (network-marked), 2 pre-existing warnings; **+15 new tests** |
| `mypy .` | clean (57 source files, strict) |
| `ruff check .` | clean |
| `scripts/anonymisation_scan.py` | clean |
| Snapshot manifest w/ provenance | ✅ checksums + git SHA + UTC + OBSERVED labels |
| Surface fits | ✅ 934 points |
| Expiries chosen w/ liquidity evidence | ✅ §2 |
| Unit tests on selection + IV lookup (offline via fixtures) | ✅ `tests/test_c8_snapshot.py` (14) |

**New Phase-1 code:** `vol/snapshot.py`, `vol/chain.py`, `vol/realised.py`,
`scripts/snapshot_market.py`, `tests/test_c8_snapshot.py`; edits to `vol/history.py`
(DELAYED) + `tests/test_vol.py`; `.gitignore` (market_snapshots/). No production module rewritten;
C7's suite not regressed.

**Locked decisions consumed (this cycle, orchestrator-confirmed before coding):**
(1) tenor axis = two genuine liquid expiries + documented gap; (2) IV source = direct listed
mark_iv, strike-space smile fallback; (3) freeze the official snapshot now.

---

## 7. Surfaced for orchestrator — decisions NOT taken by the builder

1. **Commit the raw snapshot?** Currently git-ignored (bulk, per §10) but persisted on disk +
   checksum-identified. Commit for version-controlled deck reconciliation, or keep disk-only?
2. **Realised-vol source lineage.** Massive works but on a **DELAYED** feed. Confirm delayed
   Massive daily closes are acceptable as OBSERVED for the realised-vol comparison (recommended,
   since closes are final), or prefer another observed source.
3. **`vol/surface.py` annualisation.** `_expiry_from_name` uses **365.25**-day annualisation for
   its internal T, while the C8 mandate (§6) / orchestration §5.1 specify **365** everywhere.
   Phase-1 code uses days/365 consistently; the surface constant is untouched (frozen-behavior /
   test-first change deferred pending your nod — it affects only the diagnostic delta axis).

**Pending gates deliberately NOT resolved here** (require a firm decision): D-1 fee base,
D-4/D-7 put-sleeve scope, D-9 hedge model, D-10 loss budget, MS-25 objective function,
MS-26 sim methodology, CSCV/PBO/DSR (`PENDING_METHOD`).

---

## 8. What Phase 2 will consume

The frozen snapshot + `vol/chain` (selection, strike-snap, `iv_for`) + `vol/realised` +
`vol/surface` diagnostics feed `strategy/strategy_grid.py`: the full grid (8 toolkit + 2 heroes
× strike% × the two distinct expiries × coverage {25/50/75/100}%), each row priced at its own
live IV, with σ-normalised scenarios per real listed expiry (σ(T) = each expiry's ATM IV), three
granularities (per-BTC / per-CME-contract / per-portfolio), against an independent oracle.

---

## 9. Post-approval addendum — three decisions applied (orchestrator-directed)

Phase 1 was approved (gates verified independently). The three surfaced decisions were resolved
and applied; the body above is preserved as the approved record. Net effect on numbers is
immaterial (spot/DVOL moved a few points on the re-anchor; expiries and realised vol unchanged).

1. **Snapshot committed as the tracked working anchor.** A promoted anchor is now force-added to
   git; the `market_snapshots/` glob stays ignored so ad-hoc `--refresh` runs remain untracked.
   Only promoted anchors are committed. The committed anchor supersedes §1's snapshot:

   | Field | Committed anchor |
   |---|---|
   | Dir | `market_snapshots/2026-07-30T104316Z/` (pointer: `market_snapshots/ANCHOR`) |
   | As of (UTC) | `2026-07-30T10:43:16.778096+00:00` |
   | git SHA | `f7ebc49` (Phase-1 commit) |
   | Live spot | 64,509.34 USD |
   | DVOL | 0.3589 (35.89%) |
   | index_price.json | `93e324f689d4d5cf55ba8ca26ba926ac5a48bc4545b47889de6b4fab5ade44bc` |
   | dvol.json | `88928f551a547c0f5cb18c8cb8a8a86161c7661bdc0681451d2e83526d339919` |
   | instruments.json | `e63c593dd62274512b65890145c9851e3b9b2c5f66815a53aae2198e398f7d61` |
   | book_summary.json | `838e48e84294bcff9d2d6b317ac181a653d1d8a8d4652630de5ac5da313102d5` |

   Replay precedence: promoted anchor → latest ad-hoc → fixtures. `snapshot_market.py --refresh
   --promote` freezes and promotes in one step.

2. **DELAYED Massive closes accepted as OBSERVED.** The incomplete current-day bar is excluded
   (any bar dated on/after the reference date); the feed status is recorded in
   `spot_history_meta.json` (`status: "DELAYED"`, `provenance: "observed"`, `n_bars: 64`,
   `n_excluded_incomplete_current_day: 0` — the delayed feed already ends at the prior day,
   2026-07-29). Realised-vol windows match each real tenor (~29d, ~57d) plus the 30d DVOL window.

3. **`vol/surface.py` aligned to 365-day annualisation.** `_expiry_from_name` now uses 365 (was
   365.25), consistent with pricing `T = days/365`. Test-first: added
   `test_surface_expiry_uses_365_day_annualisation`. **No frozen test asserted 365.25** (only the
   code line itself), so nothing was flipped silently; the existing surface tests assert ranges
   and remain green.

Gates after decisions: **pytest 568 passed / 3 skipped**, mypy strict clean (57 files), ruff
clean. **Phase 2 proceeds per the locked modeling frame (leg decomposition; per-tenor σ).**
