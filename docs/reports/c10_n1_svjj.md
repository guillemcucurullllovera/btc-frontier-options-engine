# C10 · N1 — Asymmetric / price-vol co-jump downside block (SVJJ)

**SIMULATED / diagnostic · MS-26-gated · P-ESTIMATED jumps · holder-basis · frozen Q anchor untouched.**
Deck & canonical `main` untouched. **Modeling APPROVED; μ_v sensitivity-band amendment applied.** Code:
`pricing/cf/svjj.py`, `strategy/svjj_sim.py`; risk `scripts/svjj_risk_campaign.py`; tests `tests/test_svjj.py`;
evidence `c9_svjj_risk.json`. Addresses the Phase D/F future-work item (the symmetric-normal block understated
the η downside).

> **ELEVATION:** the SVJJ physical tail is now the **operational physical-risk model**, superseding the
> symmetric-normal block, and is reported as a **μ_v sensitivity band** — **central = μ_v=0** (the
> well-identified price-jump asymmetry, ~+0.8% fatter ES) with the **co-jump widening as a labelled uncertain
> band up to ~+3% (μ_v estimated → stress; direction ρ_J<0 robust, magnitude NOT decision-grade)**. Kou is
> retained as a labelled heavier-tail stress alternative; the recent-2yr backtest is the validation (the
> full-history rejection is a documented regime-mismatch, Phase E).

## N1.1 — Chosen jump spec (+ justification)
**Price jump: separate up/down lognormal (double-normal on the log-jump).** Fitted BOTH candidates to the
full-history realized jumps (Lee–Mykland α=0.05, n=40) by MLE:

| spec | params | LL | AIC | sampled std | sampled q0.1% | η |
|------|--------|----|-----|-------------|---------------|---|
| **Double-normal** ✅ | p_up=0.45, up N(+0.097, 0.035), down N(−0.083, 0.136) | **30.7** | **−51.3** | 0.137 | **−0.48** | 1.5 |
| Kou double-exp | p=0.58, η_up=10.2, η_dn=7.2 | 19.7 | −33.5 | 0.165 | −0.84 | 1.4 |

**Justification:** the double-normal wins on AIC (−51 vs −33) and on tail fidelity — it matches the
empirical jump std (0.137) AND the extreme quantile (q0.1% ≈ −0.48 vs the observed worst jump −0.50),
whereas **Kou over-extrapolates the crash tail** (q0.1% = −84%, never observed) because its exponential
mode-at-0 can't fit the empirical up-jumps clustering at +10%. The double-normal captures the downside as a
**wider, heavier down-component** (σ_dn 0.136 ≫ σ_up 0.035) → mean|down| > mean|up| (η≈1.5) even with a
less-negative down-*mean*. *(Kou remains available as a heavier-tail stress alternative if the operator
wants more conservative extreme-crash weight — a review lever.)*

**Vol co-jump:** a contemporaneous exponential variance jump ξ^v ~ Exp(μ_v) co-arriving with the SAME
Poisson(λ) as the price jump → volatility spikes coincide with the (down-skewed) price jumps = the ρ_J<0
leverage effect (Phase C's one robust signal). λ = 4.47/yr (Phase B).

## N1.1 — Model + validation (CF via the M1 spine → COS; MC reuses QE + reproducibility)
The SVJJ characteristic function is affine (Duffie–Pan–Singleton): `φ = exp(iu μ T + C_H + D_H v0 + A_J)`,
with the jump term `A_J = λ∫₀ᵀ[φ_price(u)·φ_volj(D_H(τ)) − 1]dτ` (φ_volj(D)=1/(1−μ_v D)) integrated by
128-pt Gauss–Legendre quadrature (D_H closed-form). Validated (7 tests):
- **λ=0 → Heston exactly** (diff 0.0); **μ_v=0 → factorised asymmetric-Bates** (diff 2.6e-18).
- CF valid: φ(0)=1, |φ|≤1 (real u), conjugate symmetry.
- **CF-vs-MC within 0.1–0.4 SE** (analytical CF vs the QE+jump MC empirical CF) — the key gate.
- Double-normal reproduces η≈1.5; MC reproducible (seed-stable); 0 non-finite.

## N1.2 — P-measure anchoring
Jump asymmetry from the P-realized jumps (η≈1.4, Phase B full-history); co-jump leverage direction from
Phase C (ρ_J≪0). **Provenance P-ESTIMATED.** The Q-degenerate jumps are NOT reintroduced as risk (option
marks stay the frozen Q_BATES; the physical tail is the SVJJ). ⚠️ **μ_v (co-jump size) is P-anchored in
DIRECTION only** — its magnitude is the least-identified parameter (Phase C did not converge); set to 0.10
(variance units) with a sensitivity flag.

## N1.3 — Operational SVJJ risk, μ_v sensitivity-banded (campaign 4.3M paths; seed-stable; 0 non-finite)
The operational physical tail is the SVJJ, reported as a band vs the **superseded** symmetric-normal block
(matched jump variance, zero skew, no co-jump):

| Structure | ES97.5 (prior symmetric) | **central μ_v=0** | **stress μ_v=est** | band widening |
|-----------|-------------------------:|------------------:|-------------------:|:-------------:|
| long_btc + short put | 59 138 | 59 678 (**+0.9%**) | 61 112 (**+3.3%**) | +0.9% … +3.3% |
| unhedged (hold) | 32 148 | 32 418 (+0.8%) | 33 136 (+3.1%) | +0.8% … +3.1% |
| cash-secured put | 26 990 | ~27 260 (+1.0%) | 27 977 (+3.7%) | +1.0% … +3.7% |
| covered_call / ladder | ~31k | +0.9% | +3.2% | +0.9% … +3.2% |
| **collar** | **5 734** | **5 734 (+0.0%)** | **5 734 (+0.0%)** | **bounded** |
| **call_spread** | **776** | **776 (+0.0%)** | **776 (+0.0%)** | **bounded** |

- **Central case (μ_v=0, well-identified): ~+0.8–1.0% fatter ES97.5** from the price-jump asymmetry alone
  (η≈1.4, anchored to the Phase B realized jumps). This is the decision-grade downside correction.
- **Stress case (μ_v estimated): up to ~+3.1–3.7%** — the additional widening from the vol co-jump.
  **This band is LABELLED UNCERTAIN**: the co-jump *direction* (ρ_J<0, vol-spikes-with-price-drops) is
  robust (Phase C), but its *magnitude* (μ_v) is not decision-grade (Phase C did not converge). The band
  spans μ_v=0 → μ_v=0.10.
- **Defined-risk overlays stay BOUNDED across the whole band**: collar ES97.5 = 5 734 and call_spread = 776
  **invariant to μ_v and across all 9 regime cells** (capped by construction) — the robust choice.
- Decomposition of the ES97.5 widening (unhedged, +987 at stress): price-jump asymmetry **+270** (central,
  anchored) + vol co-jump **+717** (the μ_v-banded, uncertain piece).

**Corrected VRP (SVJJ, faithful tail):** negative for every short-premium overlay and more negative than
the symmetric estimate — LBSP VRP −261 / −944 / −2 022 across current/forecast/stress vol (drift 0);
covered_call −895, ladder −809 at forecast. The faithful downside raises E^P[short-put payoff] → the VRP
**falls further into negative**, compounding Phase D/E (selling downside vol is less attractive still).

**Tail backtest (Kupiec/Christoffersen, 1-day VaR vs realized):**
- SVJJ and symmetric are **indistinguishable at the 1-day horizon** — λ·dt≈0.012, so jumps are too rare to
  differentiate a 1-day tail; the asymmetry's effect is a **multi-day / option-horizon** phenomenon (the
  ΔES above at 45 days), not a 1-day one.
- **Recent-2yr (matched vol 0.46): 99% VaR passes Kupiec (p=0.18)**; 95% is mildly conservative (obs 0.032).
  **Full-history: both reject** (obs 0.072@95% — the recent-regime vol is too tight for the high-vol early
  history) — a **regime-mismatch, consistent with Phase E** (vol non-stationary), not a tail-shape defect.

## Decisions (per operator review) & residual caveats
1. **μ_v presented as a sensitivity band** (APPLIED): central μ_v=0 (~+0.8%, decision-grade) → stress μ_v=est
   (~+3%, labelled uncertain; direction ρ_J<0 robust, magnitude not decision-grade).
2. **SVJJ elevated to the operational physical-risk model** (APPLIED), superseding the symmetric block, with
   the μ_v band. Validated (CF-vs-MC 0.4 SE) and bounded on the defined-risk overlays.
3. **Double-normal is the chosen price-jump spec** (by fit); **Kou retained as a labelled heavier-tail stress
   alternative** for extreme-crash sensitivity.
4. **Backtest:** the recent-2yr (matched-vol) coverage is the validation (99% VaR passes Kupiec p=0.18); the
   full-history rejection is a **documented regime-mismatch** (vol non-stationary, Phase E), not a tail-shape
   defect. The asymmetry is a multi-day/option-horizon effect (invisible at 1-day, where λ·dt≈0.012).
5. **Residual caveat (carried):** the μ_v magnitude (co-jump size) awaits a convergent SVCJ or an alternative
   estimator; until then the stress band is the honest expression of that uncertainty. The CF is a
   physical-process CF (vol co-jump convexity uncompensated), not a Q-pricer — option marks stay frozen Q_BATES.
