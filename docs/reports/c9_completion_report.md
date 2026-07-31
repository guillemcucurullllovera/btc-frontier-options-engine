# C9 Advanced-Methods Upgrade — Completion Report & Model-Risk Dossier (SR-11-7)

**Program:** replace the GBM/Merton + `mark_iv` stack with a calibrated, characteristic-function-priced,
filter-estimated advanced-model engine. **Branch:** `sprint/c9-advanced-methods` (off C8 HEAD `286b69f`).
**Status of everything below:** **SIMULATED / diagnostic, MS-26-gated** — a methodology-and-fidelity upgrade,
**not** a decision-grade (MS-25) or best/optimal claim. **Deck & canonical `main` untouched.**
Date: 2026-07-31.

This dossier follows the Derman/SR-11-7 model-risk frame: purpose & scope → inventory → validation evidence
→ limitations (7 types) → decision-grade vs diagnostic tiering → **MS-26 sign-off recommendation for the
operator** (not a self-sign-off).

---

## 1. Purpose & scope
Price and risk-manage European, cash-settled BTC (Deribit) options with a model that **reprices the actual
BTC volatility surface** and drives **physical-measure scenario risk**, replacing the assumed-GBM/Merton +
per-tenor-ATM stack. In scope: SV + jumps (Bates), CF pricing (COS/Carr-Madan/saddlepoint), calibration &
model selection, filtering/estimation, EVT-hardened risk, rough-vol R&D. Out of scope (unchanged): rates,
credit, American/barrier/PDE — Deribit options are European & cash-settled.

## 2. Model inventory & the fidelity upgrade
| Layer | Old (C8) | New (C9) | Evidence |
|-------|----------|----------|----------|
| Pricing | Black-76 / GBM | **COS CF pricer** (+ Carr-Madan FFT oracle + saddlepoint wings) | COS-GBM vs BS **3.9e-14**; COS-Heston vs QuantLib **<1e-5**; Fang-Oosterlee goldens exact |
| Model | GBM + Merton jumps (assumed) | **Bates** (Heston SV + jumps), calibrated | Bates ARPE **5.55%** vs Heston 8.08% vs BS 26.9%; AIC/BIC/parsimony → Bates |
| Surface | per-tenor ATM IV | **whole-chain SVI/SSVI**, arb-free | SVI RMSE ≈1.0 vol pt; butterfly/calendar arb-free |
| Estimation | GARCH only | **UKF + particle filter + realized-jump detection + SVCJ MCMC** | UKF white-innovation; PF loglik −74 vs UKF −140; SVCJ recovery vol-corr 0.85 |
| Risk | GBM/Merton scenarios | **Bates physical-sim / Q-mark, EVT-hardened, uncertainty-banded** | ES97.5 ×1.67 vs GBM; Kupiec/Christoffersen backtests pass; ±15-18% param band |
| Inverse layer | wrong delta / marking | premium-adjusted Δ_BTC, r=q=0 off the observed future | Δ_BTC vs QuantLib **4.4e-16** |

**Headline fidelity gain:** the engine reprices the live BTC surface to **ARPE 5.55%** (toward the ~4-6% of
the BTC option-calibration literature) vs ~27% for the assumed-GBM baseline — the single largest fidelity
jump in the program.

## 3. Validation evidence (external / independent oracles)
- **Pricing:** BS closed form (machine-ε), **QuantLib** (Heston <1e-5, un-skipped + pinned), **Fang-Oosterlee**
  published goldens, Carr-Madan FFT cross-check, saddlepoint far-wing, CF-vs-MC within k·SE.
- **Calibration:** synthetic-parameter recovery exact; multi-start same optimum (obj spread 1e-10); residual
  quartet (RMSE/APE/ARPE/RMSE_IV) reported; penalized (AIC/BIC) selection stable on a 2nd snapshot.
- **Simulation:** martingale E[e^{−rT}S_T]=S0 to 4.5e-4; Feller-violation-safe (QE/full-truncation);
  reproducible substreams; vol-clustering + leverage reproduced.
- **Filtering/estimation:** UKF white innovations (NIS/NEES ≈1), PF healthy ESS, realized-jump detector
  14/15 recall on simulated ground truth; **SVCJ MCMC recovers simulated parameters** (all 90% CIs cover,
  vol-corr 0.85) — the recovery gate **caught a real determinant bug** before any BTC estimate was reported.
- **Risk:** VaR/ES **backtested** (Kupiec POF + Christoffersen independence pass a correct VaR, reject a
  too-tight one); every metric carries **SE/CI**; the campaign is **seed-stable, 0 non-finite (6M paths)**.

## 4. Model limitations (the honest register — carried, not hidden)
1. **Q-calibrated Bates jumps are DEGENERATE / unidentified** (λ pinned, σ_j≈0). Used **only to mark the
   price** (which they fit); **not** used as jump risk. The tail-jump source is the **physical** realized
   jumps (M4/Phase B), not the Q-calibration.
2. **Rough volatility is REAL but not the dominant fit lever.** BTC vol is rough from both the Q-surface
   (H≈0.20, M6.0/Phase A) and the realized-variance series (H≈0.02-0.10, Phase E) — yet a rough-Heston fit
   (7.4% at H≈0.20) **does not beat Bates (5.55%)**; jumps dominate. → heavy rough integration (M6.1-6.3)
   **not justified by fit** and skipped.
3. **SVCJ MCMC does NOT converge on the real 8.5-yr series** (κ R̂=9.4) — weak SV identification (returns-only)
   + constant-parameter misspecification across regimes. **The particle filter remains the operational
   latent-vol tool.** The one robust SVCJ signal is ρ_J≪0 (leveraged co-jumps). Point estimates are **not
   decision-grade**.
4. **The symmetric-normal jump block cannot represent the η≈1.4-1.5 downside SIZE asymmetry** (Phase B/E) →
   the modeled downside tail is **if anything understated**; the Phase C ρ_J<0 co-jump leverage points the
   same way. A faithful downside needs an asymmetric/co-jump block (**future work**).
5. **SV-MLE θ is QML-biased low and weakly identified** (documented; not a stability anchor).
6. **No historical Q-stability** — only a single frozen option chain exists (no historical Deribit surfaces),
   so the Q calibration is a **point-in-time** diagnostic and Q cannot be re-calibrated across regimes
   (Phase E data gap). Acquiring a historical surface archive is the prerequisite.
7. **Basis:** the physical estimation uses Binance BTCUSDT (USDT-quoted); log-returns are an excellent
   BTC/USD proxy, but price *levels* differ from the Deribit USD index by the (small, stationary) basis.
8. **Vol is non-stationary** (secular decline 0.92→0.46) — a constant/full-history vol overstates the
   forward level; the recent-regime ~0.46 is the relevant central, with the structural-rough + crash-downside
   tail and the Phase D ±15-18% parameter band.

## 5. Decision-grade vs diagnostic tiering
| Tier | Components |
|------|-----------|
| **Validated, high-confidence (diagnostic)** | CF pricing spine (COS/Carr-Madan/saddlepoint); Heston/Bates calibration & penalized selection; SVI/SSVI arb-free surface; inverse-Greek/marking fixes; UKF/PF filtering; realized-jump detection; EVT-hardened + backtested + uncertainty-banded risk |
| **Diagnostic with strong caveats** | Bates *jump* parameters (Q-degenerate → use P-jumps); P-vol level (regime/estimator spread 0.42-0.77); VRP sign (regime-dependent) |
| **Research / not decision-grade** | SVCJ MCMC point estimates (non-convergent on real data); rough-vol integration (real but fit-dominated by jumps); any single-snapshot Q value as a stable quantity |
| **Blocked on data** | Historical Q-surface stability (no historical chains) |

## 6. MS-26 sign-off RECOMMENDATION (for the operator — not a self-sign-off)
**Evidence FOR sign-off (MS-26, diagnostic methodology):**
- The engine is validated against **independent external oracles** (QuantLib, Fang-Oosterlee, BS, FFT) to
  machine-ε / <1e-5, and **reprices the live BTC surface materially better** than the GBM/Merton stack
  (ARPE 5.55% vs ~27%).
- Risk numbers are **model-calibrated, EVT-backtested, SE/CI'd, and parameter-uncertainty-banded**, with
  **reproducible, seed-stable** campaigns and **0 non-finite**.
- The estimation stack is **validated on simulated ground truth** (incl. the SVCJ recovery gate that caught
  a bug), and every parameter carries a **provenance label** (OBSERVED/CALCULATED/CALIBRATED/P-ESTIMATED/
  ASSUMED).
- Every limitation in §4 is **documented and carried**, not hidden; the honest findings (rough⊀jumps, SVCJ
  non-convergence, downside-understatement, VRP regime-dependence) are reported with their evidence.

**Evidence AGAINST / conditions:**
- Several components are **research-tier** (§5) and must **not** be used as decision-grade (MS-25) without the
  further work in §4 (asymmetric/co-jump downside block; historical Q archive; convergent SVCJ or an
  alternative for parameter distributions).
- The calibration is a **single-snapshot** diagnostic; the VRP is **thin-to-negative and regime-dependent**,
  not a stable structural premium — any "sell-vol" framing must carry that.

**Recommendation:** *Recommend the operator sign off **MS-26** for the **validated core** (CF pricing spine;
Heston/Bates calibration & selection; SVI/SSVI surface; inverse-layer fixes; UKF/PF filtering & realized-jump
estimation; EVT-hardened, backtested, uncertainty-banded risk) as the **diagnostic replacement** for the
GBM/Merton + mark_iv stack, with the §4 limitations carried as documented future work.* Hold the research-tier
items (SVCJ point estimates, rough integration, single-snapshot Q as a stable quantity) as **diagnostic-only**.
**Any MS-25 (decision-grade / client-facing) elevation is a separate determination by the operator** and is
gated on: (a) an asymmetric/co-jump downside representation, (b) a historical Q-surface archive for
cross-temporal Q-stability, and (c) resolution or replacement of the SVCJ convergence. **This is a
recommendation with evidence for the operator's sign-off decision — not a self-sign-off.**

## 7. Residual gates / next steps
- Acquire a **historical Deribit option-surface archive** → true Q-stability + historical calibration-residual
  tracking.
- Implement an **asymmetric / price-vol co-jump** jump block (SVCJ-style, ρ_J<0) to faithfully carry the
  downside tail into the risk numbers.
- Revisit the **SVCJ sampler** with tempering / longer runs / a stationary sub-window, or adopt the PF-based
  parameter distribution as the operational uncertainty source.
- If ever fit-justified on new data, the **rough-vol integration** (M6.1-6.3) can be reopened — the CF and
  the H-estimation are already in place.
