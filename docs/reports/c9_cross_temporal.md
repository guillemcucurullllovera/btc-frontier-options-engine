# C9 · Phase E — Cross-temporal robustness (regime stability of the physical dynamics)

**SIMULATED / diagnostic · MS-26-gated · P-ESTIMATED from OBSERVED Binance history · frozen Q anchor
untouched.** Deck & canonical `main` untouched. Run: `scripts/cross_temporal_stability.py`; evidence:
`c9_cross_temporal.json`.

## Data-gap (documented up front)
**The Q model (Heston/Bates smile) cannot be re-calibrated historically** — we hold a *single frozen option
chain*, not historical option surfaces. So Q is held at the frozen anchor (ATM implied ≈ 0.37 / calibrated
Q-vol 0.50) and **only the physical side is re-estimated per window**; the VRP-stability uses that frozen Q.
Acquiring a historical Deribit surface archive is the prerequisite for true Q-stability (flagged for M7).

## Stability table (6 contiguous regime windows, 2017–2026)

| Window | n | realized vol | GARCH persist | GARCH uncond | jump λ/yr | jump η | **roughness H** | VRP vs Q(0.37) |
|--------|---|-------------:|--------------:|-------------:|----------:|-------:|----------------:|---------------:|
| 2017–18 early/bear | 501 | **0.92** | 0.99 | 0.96 | 5.1 | 0.97 | n/a | −0.55 |
| 2019–20 pre/COVID | 547 | 0.80 | 0.92 | 1.01 | 8.7 | **1.56** | 0.101 | −0.43 |
| 2020–21 bull | 549 | 0.73 | 0.98 | 0.75 | 4.0 | 1.42 | 0.103 | −0.36 |
| 2022 LUNA/FTX | 365 | 0.64 | 0.64 | 0.68 | 8.0 | 1.05 | 0.077 | −0.27 |
| 2023–24 recovery | 547 | 0.47 | 0.82 | 0.48 | 7.3 | 0.97 | 0.022 | −0.10 |
| 2024–26 recent | 760 | **0.46** | 0.92 | 0.46 | 4.8 | 0.92 | 0.044 | −0.09 |
| **min/max (CoV)** | | 0.46/0.92 (0.25) | 0.64/0.99 (0.14) | 0.46/1.01 (0.29) | 4.0/8.7 (0.28) | 0.92/1.56 (0.22) | **0.02/0.10 (0.46)** | −0.55/−0.09 (0.56) |

## What is stable, what trends, what is regime-dependent

**STRUCTURALLY STABLE — volatility roughness.** H stays in **0.02–0.10 across every window** (always far
below 0.5) — **BTC volatility is rough in every regime**, a structural property independent of the market
state. This corroborates Phase A's Q-surface roughness (H≈0.20) from an *independent* data source (the
realized-variance time-series), and sits in the Gatheral–Jaisson–Rosenbaum "volatility is rough" range.
*(Caveat: RV measurement noise biases H downward, so the true H may be somewhat higher; the qualitative
"rough in all regimes" conclusion is robust.)*

**SECULARLY TRENDING — the vol level.** Realized vol **halves over the sample: 0.92 → 0.46** (2017-18 →
2024-26). BTC volatility is **not stationary** — it declines with market maturation. Consequence: a
full-history or early-history vol assumption **overstates** current vol; the **recent-regime ~0.46** is the
relevant forward level (consistent with the M5.4 forecast band and the Phase B current-conditional).

**REGIME-DEPENDENT — jump asymmetry and the VRP.**
- **Jump downside asymmetry η** is strongest in the crash-heavy windows (2019-20 η=1.56 incl. COVID; 2020-21
  η=1.42) and ~symmetric in calm windows (recent η=0.92). → the downside tail is a **crash-regime**
  phenomenon (as Phase B's long-vs-2yr split already showed), not a constant.
- **VRP (vs the frozen 0.37 implied) is negative in EVERY window but shrinks toward neutral**: −0.55 → −0.09.
  Realized vol has always exceeded the frozen implied historically, but the gap has closed as vol declined —
  in the recent regime the VRP is **near-neutral (−0.09)**. This is the cross-temporal resolution of the
  VRP-sign question: **structurally negative over the long fat-tailed history, near-neutral now** — fully
  consistent with M5.4 (regime-dependent) and Phase D (thin-to-negative under the richer estimate).

*(GARCH persistence is fairly stable ~0.9 except the 2022-collapse window, 0.64, where the crash dominates.
The SV-MLE θ is noisy across windows — CoV 0.54, degenerating to 0 in one window — reflecting its documented
QML weak-identification; it is not a stability anchor.)*

## Bottom line for the dossier
The physical dynamics are **not** a single stationary parameter set. **Roughness is structural (H≈0.02–0.10
always); the vol level trends down (0.9→0.46); jump-downside and the VRP are regime-dependent (VRP negative
long-run, near-neutral now).** Any forward risk statement should use the **recent-regime** vol (~0.46) with
the **structural rough + crash-downside** tail, not a full-history average — and must carry the
parameter-uncertainty band of Phase D. True Q-stability awaits a historical option-surface archive (M7 gap).
