# C9 · Phase D — Risk re-derivation with parameter uncertainty + campaign MC

**SIMULATED / diagnostic · MS-26-gated · holder-basis · frozen Q anchor untouched.**
Deck & canonical `main` untouched. Code: `strategy/bates_risk.py::parameter_uncertainty_band`; run:
`scripts/risk_uncertainty_campaign.py`; evidence: `c9_risk_uncertainty.json`. Campaign: **6 000 000 paths**
(30 parameter draws × 200 000), **seed-stable ✅**, **0 non-finite ✅**.

## Method
Re-derives the full-structure risk (all 7 C8 structures, holder-basis) with **enriched jumps** from Phase B
(full-history realized jumps: λ≈4.47/yr, std 0.137 — **larger** than M4.6's 0.088; η=1.42 downside size
asymmetry) and **propagates parameter uncertainty**: each of 30 draws **bootstraps the realized jumps** and
**draws the P-vol** from the estimator spread `N(0.52, 0.10)` (realized 0.68 / GARCH 0.77 / UKF 0.52 / PF
0.61 / SVCJ-θ 0.42). The SVCJ posterior did not converge, so it is used **qualitatively** (ρ_J<0 co-jump
leverage), not sampled. Every metric therefore carries a **[q05, q95] parameter-uncertainty band ON TOP of
the within-draw Monte-Carlo SE/CI**.

## Findings

### 1. Parameter uncertainty is MATERIAL for tail-exposed structures
| Structure | ES97.5 central | [q05, q95] band | band width |
|-----------|---------------:|:---------------:|-----------:|
| long_btc_plus_short_put | 63 227 | [50 152, 70 923] | ±16% |
| cash_secured_put | 29 034 | [22 497, 32 882] | ±18% |
| unhedged (hold) | 34 193 | [27 656, 38 041] | ±15% |
| strike_ladder | 33 103 | [26 566, 36 951] | ±16% |
| covered_call | 32 376 | [25 838, 36 223] | ±16% |
| **collar** | **5 734** | **[5 734, 5 734]** | **0% (invariant)** |
| **call_spread** | **776** | **[776, 776]** | **0% (invariant)** |

The tail metrics of tail-exposed structures swing **±15–18%** under P-parameter uncertainty alone — these
risk numbers are **not precise**, and any single point estimate overstates its own certainty.

### 2. Defined-risk structures are ROBUST to parameter uncertainty (the decision-relevant result)
The **collar** (long protective put at −10%) and the **call_spread** have their ES97.5 **capped by
construction**, so it is **invariant to the jump/vol draw** (band width 0%). The LBSP's ES swings 50k→71k as
the parameters vary; the collar's stays fixed at 5 734. **Under model/parameter uncertainty, the
defined-risk overlays are the robust choice** — their worst-case is a structural property, not an estimate.

### 3. The VRP moves MORE NEGATIVE under the richer (downside) estimate
Net VRP carry (option-overlay expected P&L), symmetric M4.6 jumps → enriched downside jumps, at central vol:

| Structure | symmetric (M4.6) | enriched | Δ |
|-----------|-----------------:|---------:|----:|
| covered_call | −679 | −1 115 | **−436** |
| long_btc_plus_short_put | −693 | −1 057 | **−364** |
| cash_secured_put | −693 | −1 057 | −364 |
| strike_ladder | −617 | −1 028 | −411 |
| collar | −47 | −198 | −150 |

The larger jumps raise E^P[option payoff], so every short-premium overlay's VRP **falls (more negative)** —
**selling volatility is less attractive under the richer physical estimate than the symmetric M4.6 anchor
implied.** This compounds M5.4's regime finding: the VRP is thin-to-negative once the fatter tail is priced.

## Honesty flags
- **The symmetric-normal jump block cannot represent the η=1.42 downside *size* asymmetry.** At α=0.05 the
  empirical jump *mean* is ≈0 (the asymmetry is in size, not mean), so the risk model widens the tail via
  **larger jumps + higher vol**, not via a downward mean. The true downside tail is therefore **if anything
  understated** here — the Phase C ρ_J<0 co-jump leverage (vol-spikes ⇔ price-drops) points the same way.
  A faithful downside representation needs an asymmetric/co-jump block (future work); the **qualitative
  conclusions (defined-risk robustness; more-negative VRP) are unaffected**.
- Parameter draws blend estimation + regime uncertainty in the P-vol (the estimators genuinely disagree
  0.42–0.77); this is honest parameter uncertainty, not a single-regime SE.

## Bottom line for the dossier
Model-calibrated, uncertainty-banded risk numbers: the tail is fatter than GBM/M4.6 and **uncertain
(±15–18%)**; **defined-risk overlays (collar/call-spread) are robust to that uncertainty**; the **VRP is
thin-to-negative** and worsens under the richer downside estimate.
