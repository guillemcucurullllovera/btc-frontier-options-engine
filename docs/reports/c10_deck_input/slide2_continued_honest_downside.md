# C10 Slide-2 (continued) — honest-downside & parameter band (SUPERSEDES C8)

SIMULATED / diagnostic; MS-26-gated; holder-basis; SVJJ observed-co-jump (N3.6); no best/optimal.
Central vol 0.46; observed co-jump rho_J=-0.74, mu_v central 0.17 (band 0.12-0.39).

| structure | ES97.5 central (USD) | honest-downside +% | band [%] | stress ES97.5 | VRP carry | defined-risk bounded |
|---|---:|---:|:---:|---:|---:|:---:|
| unhedged | 33,588 | +3.9% | [2.6, 8.5] | 37,989 | 0 | no |
| covered_call | 31,771 | +4.1% | [2.8, 9.0] | 36,171 | -1,002 | no |
| long_btc_plus_short_put | 62,017 | +4.2% | [2.8, 9.2] | 70,818 | -1,009 | no |
| cash_secured_put | 28,429 | +4.6% | [3.1, 10.1] | 32,830 | -1,009 | no |
| collar | 5,734 | +0.0% | [0.0, 0.0] | 5,734 | -83 | yes |
| call_spread | 776 | +-0.0% | [-0.0, -0.0] | 776 | -9 | yes |
| strike_ladder | 32,498 | +4.0% | [2.7, 8.8] | 36,899 | -912 | no |

PF parameter band (ES97.5, tail-exposed): +/-7.0% (N3.3, validated PF).
Defined-risk overlays (collar, call-spread) are INVARIANT to the downside/parameter band (capped by construction).
