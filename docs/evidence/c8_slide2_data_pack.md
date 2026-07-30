# C8 Slide-2 / Slide-2-continued Data Pack (computed comparative matrix)

Snapshot as of **2026-07-30T10:43:16.778096+00:00**; S0 **64,509.34**; expiry **28AUG26** (~29d); 100% coverage; representative strike per structure. Every number computed off the frozen snapshot. No best/optimal/preferred language.

The computed successor to the qualitative choice matrix. Full 210-row grid (all strikes x both expiries x coverage {25/50/75/100}%, standalone + total-portfolio views) in the CSV/JSON.

| Structure | prem %spot | prob-win | max-loss/BTC (hold+opt=total) | %cap | breakeven | delta/BTC | theta/day/BTC | opp-cost +2sig/BTC | attractive when |
|---|---|---|---|---|---|---|---|---|---|
| Unhedged BTC Holding *(benchmark)* | n/a | n/a | -64,509+0.000=-64,509 | -100.0 | [64509.0] | 0.0 | 0.0 | 0.000 | Reference: full upside and full downside on the held BTC; no overlay. |
| Covered Call (Long BTC + Short Call) **[HERO]** | 1.656 | 0.732 | -64,509+1,068=-63,441 | -98.3 | [63441.0] | -0.299 | 35.6 | 7,789 | When the view is neutral-to-mildly-bullish and generating premium on the held BTC is prioritised over retaining uncapped upside. |
| Long BTC + Short Put **[HERO]** | 1.867 | 0.687 | -64,509+-59,796=-124,305 | -192.7 | [63305.0] | 0.277 | 38.7 | 0.000 | When willing to acquire more BTC on a decline (accepting amplified downside below the strike) in exchange for premium; a neutral-to-mildly-bullish view with conviction to hold. |
| Cash-Secured Put | 1.867 | 0.687 | 0.000+-59,796=-59,796 | -98.0 | [59796.0] | 0.277 | 38.7 | 0.000 | When seeking to acquire BTC at a net price below spot, funded by premium, with cash collateral set aside. |
| Collar (Long BTC + Short Call + Long Put, 10% floor) | 0.677 | 0.732 | -64,509+58,437=-6,072 | -9.4 | [64072.0] | -0.456 | 5.3 | 8,420 | When downside protection is prioritised and some upside/premium is given up to fund the floor. |
| Call Spread (5%/10%) | 0.963 | 0.732 | 0.000+-2,379=-2,379 | -100.0 | [68621.0] | -0.145 | 11.7 | 2,379 | When a defined-risk, option-only bullish payoff is wanted without holding spot. |
| Strike Ladder (Long BTC + laddered Short Calls) | 0.885 | 0.732 | -64,509+571.000=-63,939 | -99.1 | [63939.0] | -0.176 | 24.7 | 5,286 | When graduated upside participation across multiple strikes is preferred to a single cap. |

**Hero highlights (28AUG26, 100% coverage, strike sweep):**

| Hero | strike% | prem %spot | prob-win | max-loss/BTC | +2sigma terminal/BTC (capped) |
|---|---|---|---|---|---|
| Covered Call (Long BTC + Short Call) | 1.5 | 3.463 | 0.551 | -62,275 | 2,725 |
| Covered Call (Long BTC + Short Call) | 3.0 | 2.768 | 0.614 | -62,723 | 3,277 |
| Covered Call (Long BTC + Short Call) | 5.0 | 1.656 | 0.732 | -63,441 | 4,559 |
| Covered Call (Long BTC + Short Call) | 10.0 | 0.693 | 0.867 | -64,062 | 6,938 |
| Covered Call (Long BTC + Short Call) | 15.0 | 0.305 | 0.936 | -64,313 | 9,687 |
| Long BTC + Short Put | -3.0 | 2.869 | 0.574 | -125,659 | 14,198 |
| Long BTC + Short Put | -5.0 | 1.867 | 0.687 | -124,305 | 13,552 |
| Long BTC + Short Put | -10.0 | 0.979 | 0.814 | -121,878 | 12,979 |

Pending decisions carried: D-1, D-4, D-7, D-9, D-10, MS-25, MS-26.
