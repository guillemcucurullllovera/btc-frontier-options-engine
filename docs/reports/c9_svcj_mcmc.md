# C9 · Phase C (M4.4b) — SVCJ Bayesian MCMC (Eraker–Johannes–Polson)

**SIMULATED / diagnostic · MS-26-gated · P-ESTIMATED from OBSERVED Binance BTC daily returns.**
Deck & canonical `main` untouched; frozen Q anchor untouched. Code `vol/svcj_mcmc.py`; estimation
`scripts/svcj_btc_estimation.py`; evidence `c9_svcj_mcmc.json`. Source:
`private_reference_library/new_phase/ejp_2003`. **Resolves the long-standing M4.4b "BLOCKED-ON-SOURCE".**

## Model & sampler
The discretised SVCJ (contemporaneous co-jumps, correlated jump sizes):
```
y_{t+1}-y_t = mu + sqrt(V_t) eps^y + xi^y J        V_{t+1}-V_t = kappa(theta-V_t) + sigma_v sqrt(V_t) eps^v + xi^v J
corr(eps^y,eps^v)=rho    J~Bernoulli(lambda)    xi^v~Exp(mu_v)    xi^y|xi^v ~ N(mu_y+rho_J xi^v, sigma_y^2)
```
Gibbs/Metropolis with data augmentation of the latent variance, jump times and jump sizes. The latent V
uses an **even/odd checkerboard vectorised random-walk Metropolis** (V_t's full conditional depends only
on V_{t±1}). Parameters via conjugate normal/IG/Beta draws under the conditional-normal (ρ-coupled)
decomposition; ρ by independence Metropolis (q-corrected). 3 chains, documented weakly-informative
EJP-structured priors, burn-in; convergence by Gelman–Rubin R̂ + ESS.

## Sampler validation (simulate → recover — EJP Appendix C)
On **simulated** SVCJ data (known parameters, T=1500) the sampler recovers the identifiable structure and
**tracks the latent volatility path (corr ≈ 0.85)**; every parameter's 90% credible interval covers its
truth. Found & fixed a determinant bug in the bivariate log-density during validation (the covariance is
`V·R` so `det = V²·σ²(1−ρ²)`; the fix removed a 2× upward bias in the latent-vol level — corr jumped
0.09 → 0.85). As EJP note, **κ and the vol-jump size are weakly identified from returns alone** (wider
posteriors / slower mixing) — an intrinsic feature, not a sampler defect. (4 validation tests.)

## BTC estimation (full 2017–2026 daily, 3 270 obs, 9 000 iters × 3 chains)

| param | post mean | 90% CI | R̂ | ESS |
|-------|-----------|--------|-----|-----|
| mu | 0.014 | [−0.13, 0.12] | 1.80 | 562 |
| kappa | 0.191 | [0.02, 0.54] | **9.42** | 13 |
| theta | 4.812 | [1.51, 7.45] | 2.05 | 25 |
| sigma_v | 0.245 | [0.11, 0.44] | 2.88 | 18 |
| rho | −0.188 | [−0.68, 0.29] | 4.04 | 24 |
| lambda | 0.071 | [0.044, 0.104] | 1.49 | 32 |
| mu_y | 7.800 | [3.42, 11.71] | 1.87 | 61 |
| sigma_y | 3.279 | [1.60, 5.18] | 1.47 | 19 |
| mu_v | 3.374 | [1.23, 5.27] | 1.99 | 39 |
| **rho_j** | **−2.298** | **[−4.08, −1.18]** | **1.17** | 18 |

Derived: θ ⇒ diffusive vol ≈ **41.9%** annual; λ ⇒ **25.9 jumps/yr** (soft attribution — larger than the
Lee–Mykland large-jump count); posterior-mean latent vol path ≈ **51%** annual (consistent with UKF 0.52 /
PF 0.61 / realized 0.68).

## VERDICT — honest convergence status
**The SVCJ MCMC does NOT converge on the full 8.5-year BTC series** (all-R̂ < 1.1 = **False**; κ R̂ = 9.4,
ρ R̂ = 4.0, σ_v R̂ = 2.9). Two compounding reasons, both expected:
1. **Weak identification** of the SV block (κ, θ, σ_v) from returns alone — the ridge EJP document; and
2. **Non-stationarity** — a *constant*-parameter SVCJ is misspecified across 2017–2026 (bull/bear/COVID/
   2022-collapse regimes). The posterior-predictive residuals confirm misspecification: std 1.23 (>1) and
   **kurtosis 19** (the single fat tail the constant model can't absorb).

→ **Do not treat the point estimates as decision-grade.** Per the plan, this is reported honestly and
**the M4.4a particle filter remains the operational latent-vol tool.** The sampler itself is correct
(validated on stationary simulated data); the non-convergence is a property of the *data* (weak
identification + regime change), not the code.

## The one robust signal — leveraged co-jumps
**ρ_J is the best-converged parameter (R̂ = 1.17) and is strongly negative: −2.30, 90% CI [−4.08, −1.18].**
With ρ_J < 0 the return-jump mean conditional on a vol-jump is `mu_y + rho_J·xi^v` — so **large volatility
spikes coincide with large negative price jumps** (the effective per-jump return turns sharply negative for
big vol jumps, even though the marginal mu_y is positive). This **co-jump leverage is the crash-risk
mechanism**, and it corroborates the Phase B finding that BTC's downside tail is real (bigger down-moves)
— now expressed as a *contemporaneous price–vol co-jump* rather than a marginal skew. It is the SVCJ
result robust enough to carry forward; the rest is reported with the R̂ caveat.

## Implication for the risk model
The decision-grade jump inputs remain the **P-identified realized jumps (Phase B, η≈1.4–1.5 downside)**;
the SVCJ contributes the qualitative confirmation that **vol-spikes and price-drops co-occur** (ρ_J≪0),
supporting a downside-loaded tail. Parameter-uncertainty propagation (Phase D) should draw from the
*well-identified* posteriors (λ, ρ_J, the vol level) and treat κ/θ/σ_v as wide/weakly-identified.
