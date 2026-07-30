# C8 Slide-5 MC Diagnostic Pack (SIMULATED / diagnostic — not decision evidence)

Snapshot as of **2026-07-30T10:43:16.778096+00:00**; calibrated vol **0.3402** (28AUG26 ATM IV; DVOL 0.3589); r **0.0** (observed (deribit interest_rate)); drift band **[-0.1, 0.0, 0.1]** (ASSUMED; neutral 0 = no-view anchor). 14,400,000 simulated paths; MS-26 pending.

prob-of-loss is BTC-inherent (near-identical across archetypes at drift 0); the collar's value is the collapsed tail. No ranking / optimality / convergence claim.

| Archetype (role) | drift | P&L mean | P&L p5 | P&L p95 | prob-loss | VaR95%cap | ES97.5%cap | maxDD%cap | ITM | touch |
|---|---|---|---|---|---|---|---|---|---|---|
| covered_call (premium) | -0.10 | -171,768,045 | -910,258,685 | 798,182,505 | 0.671 | 47.0 | 57.3 | 31.0 | 0.16 | 0.28 |
| covered_call (premium) | +0.00 | -29,911,417 | -825,751,262 | 1,011,100,966 | 0.572 | 42.7 | 53.7 | 28.7 | 0.17 | 0.31 |
| covered_call (premium) | +0.10 | 122,080,966 | -734,636,604 | 1,237,037,688 | 0.468 | 38.0 | 50.0 | 26.6 | 0.19 | 0.33 |
| long_btc_plus_short_put (accumulation) | -0.10 | -265,172,587 | -1,427,671,594 | 1,214,514,599 | 0.669 | 73.8 | 91.5 | 46.7 | 0.31 | 0.52 |
| long_btc_plus_short_put (accumulation) | +0.00 | -43,350,544 | -1,289,722,920 | 1,552,032,618 | 0.568 | 66.6 | 85.6 | 43.0 | 0.29 | 0.49 |
| long_btc_plus_short_put (accumulation) | +0.10 | 195,966,429 | -1,142,329,429 | 1,918,126,325 | 0.462 | 59.0 | 79.2 | 39.7 | 0.26 | 0.47 |
| collar (protection) | -0.10 | -116,401,033 | -684,078,522 | 675,933,220 | 0.664 | 35.3 | 42.5 | 24.4 | 0.16 | 0.28 |
| collar (protection) | +0.00 | -1,891,354 | -624,202,947 | 861,426,621 | 0.564 | 32.3 | 40.1 | 22.8 | 0.17 | 0.31 |
| collar (protection) | +0.10 | 123,267,161 | -557,476,656 | 1,061,252,596 | 0.461 | 28.8 | 37.4 | 21.3 | 0.19 | 0.33 |
| partial_overlay (coverage-varied premium) | -0.10 | -178,676,746 | -956,587,526 | 877,265,909 | 0.675 | 49.4 | 59.6 | 33.1 | 0.16 | 0.28 |
| partial_overlay (coverage-varied premium) | +0.00 | -19,748,632 | -866,892,046 | 1,128,526,150 | 0.572 | 44.8 | 55.9 | 30.6 | 0.17 | 0.31 |
| partial_overlay (coverage-varied premium) | +0.10 | 153,050,465 | -769,144,282 | 1,401,196,478 | 0.464 | 39.7 | 51.8 | 28.4 | 0.19 | 0.33 |

Holding-vs-overlay decomposition (drift 0, USD):

- **covered_call**: holding (BTC-inherent) 90,555; overlay (advised, pre-fee) -20,325,570
- **long_btc_plus_short_put**: holding (BTC-inherent) 90,555; overlay (advised, pre-fee) -33,764,697
- **collar**: holding (BTC-inherent) 90,555; overlay (advised, pre-fee) 7,694,492
- **partial_overlay**: holding (BTC-inherent) 90,555; overlay (advised, pre-fee) -10,162,785
