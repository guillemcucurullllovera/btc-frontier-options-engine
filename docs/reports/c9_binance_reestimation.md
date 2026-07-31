# C9 · Phase B — Binance history + physical re-estimation (multi-frequency jump revisit)

**SIMULATED / diagnostic · MS-26-gated · P-ESTIMATED from OBSERVED Binance BTCUSDT returns.**
Deck & canonical `main` untouched; frozen Q option/DVOL anchor untouched. Evidence: `c9_binance_reestimation.json`;
data: `market_snapshots/binance_history/{1d,1h,1m}/`. Provider `vol/binance.py`; fetch `scripts/fetch_binance_history.py`.

## Data upgrade
Public Binance archive (`data.binance.vision`, no auth) + REST tail (`api.binance.com`, no key), BTCUSDT:

| Interval | Bars | Range | Committed? |
|----------|------|-------|-----------|
| **1d** | **3 270** | 2017-08-17 → 2026-07-30 | full (808 KB) |
| **1h** | **66 378** | 2019-01-01 → 2026-07-31 | meta+sha only (16 MB gitignored) |
| **1m** | **129 599** | last ~90 days | meta+sha only (31 MB gitignored) |

vs M4.6's **728** daily bars (2yr). **BASIS CAVEAT:** BTCUSDT is a USDT-quoted Binance spot price; the option
chain's Deribit index is a multi-exchange USD index. Price *levels* differ by the small/stationary USDT basis +
exchange composition; **log-returns — the input to all physical-dynamics estimation — are an excellent BTC/USD
proxy.** Timestamps normalised across the Binance ms→µs switch (2025). Checksummed (sha256 in each `meta.json`).

## THE headline: the downside jump asymmetry is a LONG-HISTORY effect, not a high-frequency one

The M4.6 finding was "over 2 years the jumps are roughly symmetric (η≈1.04)". The question posed for Phase B was
whether the **down-skew reappears at high frequency**. It does **not** — it reappears at **low frequency over a
long sample**:

| Frequency | n obs | λ (Lee–Mykland, /yr) | frac down | **η = mean\|down\|/mean\|up\|** | jump-var share |
|-----------|-------|----------------------|-----------|-------------------------------|----------------|
| **1d** (2017–2026) | 3 269 | 3.2 | 0.52 | **1.53** | 0.167 |
| **1h** | 66 377 | 61 | 0.55 | 1.09 | 0.154 |
| **1m** | 129 598 | 1 618 *(microstructure)* | 0.42 | **0.98** | 0.066 |

**M4.6-comparability check — identical detector (α=0.05, window=20), full history vs last 2 years:**

| Sample | jumps | λ/yr | frac down | **η** |
|--------|-------|------|-----------|-------|
| **Full 2017–2026** | 40 | 4.47 | 0.43 | **1.42** |
| **Last 2 yr (≈M4.6)** | 10 | 5.0 | 0.40 | **1.09** |

**Interpretation.** With the *same* detector, the full 8.5-yr history shows a clear downside **size** asymmetry
(η≈1.4–1.5: down-moves ~40–50% larger than up-moves), while the last-2yr window reproduces the near-symmetric
M4.6 picture (η≈1.09). At 1-minute the "jumps" are symmetric microstructure noise (η≈0.98, more up than down).
→ **The M4.6 "symmetric daily" result was a 2-year-window artifact** — the calm 2024–26 uptrend missed the crash
episodes (2018 bear, Mar-2020 COVID, May-2021, 2022 LUNA/FTX). The economically-meaningful downside jump tail is
**real** over the long sample and lives at the **daily/multi-day** scale, not intraday. (Note the asymmetry is in
jump *size*, not count — fewer but larger down-moves.)

## Vol level & filtering (full daily history)
Annualised P-vol estimates cluster **higher** than the 2yr numbers (which spanned only calm regime):

| Estimator | Annualised vol |
|-----------|----------------|
| Realized (√365 · std) | 0.68 |
| GARCH unconditional | **0.77** (α=0.10±0.014, β=0.87±0.016, persistence 0.974, converged, finite Fisher SE) |
| UKF filtered mean | 0.52 |
| Particle filter (ESS≈1124/1500) | 0.61 |
| SV-MLE θ (QML, biased low — documented) | 0.49 |

## Q-vs-P (full history)
Q=0.50 (M2/M3 frozen anchor) vs full-history P GARCH-unconditional **0.77** → ratio **0.65 < 1**: over the long
fat-tailed history realized vol **exceeds** the Q-implied → **negative VRP over the full sample**, vs the
current-regime *positive* VRP (implied 37% > current-conditional 31%). **Reinforces M5.4: the VRP sign is a
regime/sample-window artifact**, not a stable structural premium.

## Honesty flags
- **1m λ (1618/yr) is meaningless** — inflated by the test's false-positive rate × 130k obs (microstructure). The
  reported *asymmetry* (η), not the raw λ, is the economically meaningful intraday signal.
- **Hourly GARCH unconditional (168%) is unreliable** — hourly persistence is near-integrated (0.997), so the
  unconditional variance is unstable/inflated. The **daily** GARCH (persistence 0.974, unconditional 77%) is the
  meaningful vol anchor; hourly GARCH is reported for completeness only.
- Estimation is **P-ESTIMATED / diagnostic**; the frozen Q calibration anchor is untouched.

## Implication for the risk model (Phase D)
The P-jump inputs should carry the **long-history downside asymmetry** (η≈1.4–1.5, frac-down in size), not the
symmetric 2yr estimate — the tail is fatter and more downward than the M4.6 anchor implied. Vol regime band should
acknowledge the 0.5–0.77 long-run range alongside the ~0.43 current-conditional.
