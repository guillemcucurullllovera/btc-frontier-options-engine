# C10 · N4.1 — MS-25 readiness dossier

**SIMULATED / diagnostic · MS-26-gated · deck & canonical `main` untouched.** This dossier assesses whether
the C9/C10 advanced-methods engine is a **candidate for MS-25 (decision-grade) elevation** against the three
conditions the C9 completion dossier (§4/§7) set. It is a **recommendation with evidence for the operator's
determination — NOT a self-elevation.** No best/optimal or ranking claim is made.

Sprint: `sprint/c9-advanced-methods`. Evidence base: the C9 phases (M0–M7) + C10 (N1 `d373f71`, N2 `eadf642`,
N3.0 `0eb2fe3`, N3 `77c9d0b`, N3.5 `70b7be4`, N3.6 `09e7894`). Whole-suite: **871 passed / 3 skipped**,
mypy/ruff/anon/git clean throughout; deck & `main` untouched.

## The three MS-25 conditions — status & evidence

### (a) Faithful downside tail — MET (decision-grade, with a stated caveat on μ_v magnitude)
The symmetric-normal jump block (which understated the η downside, Phase D/F) is replaced by the **SVJJ**
asymmetric price-vol co-jump model, now the **operational physical-risk model**:
- **Downside jump asymmetry is real, daily-scale, and ALL-REGIME** — daily η ≈ **1.42** (Phase B full
  history); confirmed across 8 years and every regime (N3.5.1, 787 730 five-minute bars): intraday η is
  mild 0.90–1.17 in every regime incl. the 2022 crash → the downside is a daily/multi-day feature, **not a
  recent-window artifact**.
- **The co-jump is OBSERVED, not assumed** (N3.6): on spot-jump days (2021–2026) the price-jump and DVOL
  move are strongly negatively correlated — **ρ_J = −0.738 (SE 0.107), decision-grade**, asymmetric
  (down-jumps spike DVOL +0.157, up +0.019). μ_v is **data-anchored to ≈0.12–0.39 (central ~0.17)** with an
  explicit implied-vs-instantaneous caveat.
- **SVJJ validated**: λ=0→Heston exact, μ_v=0→factorised (2.6e-18), **CF-vs-MC within 0.4 SE**; reproduces
  η≈1.5; seed-stable; 0 non-finite.
- **Honest-downside impact**: ES97.5 **≈+4.5% fatter (central), band [+3%, +10%]** vs the symmetric block;
  **defined-risk overlays (collar, call-spread) BOUNDED (0%)** across the whole μ_v range.
- **Caveat (stated):** ρ_J direction/strength is decision-grade; the μ_v *magnitude* is decision-grade **with**
  the implied→instantaneous mapping range (20-event sample). → **condition (a) MET; residual is the μ_v
  magnitude band, honestly carried.**

### (b) Cross-temporal Q-signal — MET at the ATM level (free), full-smile accruing
- **Free DVOL Q-history** (N3.1): 1 955 daily ATM-implied-vol obs 2021–2026; Q-ATM-vol **halved 0.92→0.46**
  (tracks the P decline); the **forward VRP is POSITIVE and stable (+0.096, positive 75% of days)** — a
  decision-grade cross-temporal Q-signal from free data.
- **Durable daily archiver** (N2 + N3.0): live, checksummed, worktree-independent — the full-smile history
  accrues from today.
- **Caveat:** the **full-smile** (skew/term-structure) cross-temporal Q is not yet available — Deribit's free
  API exposes no historical option trades (N3.5.2, 3 probes). → **condition (b) MET at ATM; full-smile is a
  documented residual (accrue or backfill).**

### (c) Decision-grade parameter uncertainty — MET (via the validated PF)
- The returns-only SVCJ MCMC does **not** converge, even on stationary windows (N3.2, κ R̂=2.2 on 2yr) —
  reported honestly, not forced.
- **The validated particle filter (ESS 915, healthy) is the operational source** (N3.3): block-bootstrap →
  PF P-vol + realized-jump distribution → the operational risk band **ES97.5 ±≈7%** (tail-exposed),
  **defined-risk bounded**, seed-stable. Re-banded from Phase D's ±15–18% (the wider band is the conservative
  cross-method superset). → **condition (c) MET via the PF alternative** (SVCJ non-convergence documented).

## The two residuals (honest)
| Residual | Status | Path to close |
|----------|--------|---------------|
| **Full-smile historical Q** (skew/term-structure over time) | ATM-level delivered free (DVOL); full-smile awaits data | **Accrue** (durable archiver, running) **or pay** (Tardis ~$300–700/mo / Laevitas). Not required for the ATM VRP signal. |
| **SVCJ convergence** (returns-only) | Non-convergent (weak identification); PF is the operational fallback | A **joint options+returns** SVCJ needs historical smiles (data-gated, same as above) **or** accept the validated-PF band as operational (recommended). |

## MS-25-readiness assessment (for the operator)
**All three conditions are MET** — (a) faithful, observed-co-jump downside; (b) free cross-temporal ATM
Q-signal + durable archiver; (c) decision-grade PF parameter uncertainty — **each with an explicit, honestly
carried caveat/residual** (μ_v magnitude band; full-smile Q accrual; SVCJ-via-PF). The engine reprices the
live surface to ARPE 5.55% (vs ~27% GBM), is validated against external oracles (QuantLib/Fang–Oosterlee/BS/
FFT), and carries EVT-backtested, uncertainty-banded, defined-risk-invariant risk numbers.

**Recommendation:** the C9/C10 engine is a **strong candidate for MS-25 (decision-grade) elevation** for its
core — CF-priced Bates/SVJJ pricing & risk, the observed-co-jump downside, the DVOL Q-signal, and the
PF-based parameter uncertainty — **subject to the operator's determination** and to carrying the two
documented residuals as bounded uncertainty (not as blockers). **This is a candidate assessment with
evidence, NOT a self-elevation;** the MS-25/MS-26 decision and any client-facing use remain the operator's.
No best/optimal claim; alternatives presented, not ranked.
