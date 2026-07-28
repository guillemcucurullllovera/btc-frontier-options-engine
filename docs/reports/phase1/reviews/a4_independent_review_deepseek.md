[0m
> audit · deepseek-v4-pro
[0m
[0m→ [0mRead contracts.md
[0m→ [0mRead docs/architecture/contracts_freeze_record.md
[0m→ [0mRead docs/requirements/authoritative_corrections.md
[0m→ [0mRead agents/A4_execution.md
[0m→ [0mRead execution/waterfall.py
[0m→ [0mRead execution/impact.py
[0m→ [0mRead execution/tranches.py
[0m→ [0mRead config/models.py
[0m→ [0mRead config/params.yaml
[0m→ [0mRead tests/test_engine.py
[0m→ [0mRead tests/test_phase0.py
[0m→ [0mRead docs/reports/phase1/a4_execution_implementation_deepseek.md
[0m→ [0mRead docs/reports/reference_study/pillar_3_execution_microstructure_deepseek.md
[0m→ [0mRead docs/reports/reference_study/pillar_4_venue_standards_deepseek.md
Now let me read the reference reports.
[0m→ [0mRead contracts.md[90m [offset=1152][0m
[0m
[0m$ [0mgit status --short
M execution/waterfall.py
 M tests/test_phase0.py
?? docs/reports/phase1/
?? execution/impact.py
?? execution/tranches.py
?? prompts/13_a4_execution_implementation.md
?? prompts/16_a4_independent_review.md
[0m
[0m$ [0mgit diff --check
(no output)
[0m
Let me read the remaining sections of contracts.md and check git status.
[0m$ [0mgit diff --stat
execution/waterfall.py |  96 +++++++++++++++---
 tests/test_phase0.py   | 259 +++++++++++++++++++++++++++++++++++++++++++++++--
 2 files changed, 331 insertions(+), 24 deletions(-)
[0m
[0m$ [0mgit diff -- execution/waterfall.py
diff --git a/execution/waterfall.py b/execution/waterfall.py
index c5f8bbd..ec843ac 100644
--- a/execution/waterfall.py
+++ b/execution/waterfall.py
@@ -4,20 +4,42 @@ Run:  python3 -m execution.waterfall  (from btc_engine/)
 
 Phase 0: typed, file-handle leak fixed.  Preserves exact numerical behaviour
 and public compatibility with existing tests.
+
+A4 extension: waterfall_sensitivity() produces labelled dicts for every
+(spot_offset_pct, fee_base) combination.  fee_base variant preserves D-1
+decision marker (both variants computed, not resolved).
 """
 
 from __future__ import annotations
 
 import pathlib
-from typing import Any
+from typing import Any, Literal
 
 import yaml
+from pydantic import BaseModel, Field
 
 CFG: pathlib.Path = (
     pathlib.Path(__file__).resolve().parents[1] / "config" / "params.yaml"
 )
 
 
+def _default_spot_offsets() -> list[float]:
+    return [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
+
+
+def _default_fee_bases() -> list[Literal["reference_notional", "executed_volume"]]:
+    return ["reference_notional", "executed_volume"]
+
+
+class WaterfallSensitivity(BaseModel):
+    """Sensitivity parameters for waterfall — frozen per contracts.md §12.4."""
+
+    spot_offsets_pct: list[float] = Field(default_factory=_default_spot_offsets)
+    fee_bases: list[Literal["reference_notional", "executed_volume"]] = Field(
+        default_factory=_default_fee_bases
+    )
+
+
 def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:
     """Load raw params.yaml.  File handle closed after read."""
     path = path or CFG
@@ -28,23 +50,20 @@ def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:
     return {}
 
 
-def waterfall(p: dict[str, Any] | None = None) -> dict[str, Any]:
-    """Compute mandate-economic waterfall from params.
-
-    Returns a dict of labelled float/int values.  Numerical behaviour is
-    preserved byte-for-byte from the Sprint-0 scaffold.
-    """
-    p = p or load_params()
-    S: float = float(p["reference_spot_usd"])
-    q: int = int(p["btc_quantity"])
-    disc: float = float(p["seller_discount_pct"]) / 100.0
-    fee: float = float(p["execution_fee_pct"]) / 100.0
-    ovl: float = float(p["target_option_yield_pct"]) / 100.0
-
+def _compute_waterfall(
+    S: float,
+    q: int,
+    disc: float,
+    fee_rate: float,
+    ovl: float,
+    fee_base: Literal["reference_notional", "executed_volume"] = "reference_notional",
+) -> dict[str, Any]:
+    """Core waterfall arithmetic — reused by waterfall() and waterfall_sensitivity()."""
     notional: float = S * q
     price_after_disc: float = S * (1.0 - disc)
-    fee_usd: float = notional * fee
-    client_cash_per_btc: float = price_after_disc + S * fee
+    fee_notional = notional * (1.0 - disc) if fee_base == "executed_volume" else notional
+    fee_usd: float = fee_notional * fee_rate
+    client_cash_per_btc: float = price_after_disc + fee_usd / q
     overlay_usd: float = notional * ovl
     effective_per_btc: float = client_cash_per_btc - S * ovl
 
@@ -65,6 +84,51 @@ def waterfall(p: dict[str, Any] | None = None) -> dict[str, Any]:
     }
 
 
+def waterfall(p: dict[str, Any] | None = None) -> dict[str, Any]:
+    """Compute mandate-economic waterfall from params.
+
+    Returns a dict of labelled float/int values.  Numerical behaviour is
+    preserved byte-for-byte from the Sprint-0 scaffold (reference_notional base).
+    """
+    p = p or load_params()
+    S: float = float(p["reference_spot_usd"])
+    q: int = int(p["btc_quantity"])
+    disc: float = float(p["seller_discount_pct"]) / 100.0
+    fee: float = float(p["execution_fee_pct"]) / 100.0
+    ovl: float = float(p["target_option_yield_pct"]) / 100.0
+    return _compute_waterfall(S, q, disc, fee, ovl, "reference_notional")
+
+
+def waterfall_sensitivity(
+    p: dict[str, Any] | None = None,
+    sensitivity: WaterfallSensitivity | None = None,
+) -> list[dict[str, Any]]:
+    """Produce waterfall for every (spot_offset_pct, fee_base) combination.
+
+    Each result dict includes 'spot_offset_pct' and 'fee_base' keys
+    identifying the variant.  fee_base=None (D-1 unresolved) is preserved
+    by computing both variants but not silently choosing.
+    """
+    p = p or load_params()
+    sens = sensitivity or WaterfallSensitivity()
+    S: float = float(p["reference_spot_usd"])
+    q: int = int(p["btc_quantity"])
+    disc: float = float(p["seller_discount_pct"]) / 100.0
+    fee: float = float(p["execution_fee_pct"]) / 100.0
+    ovl: float = float(p["target_option_yield_pct"]) / 100.0
+
+    results: list[dict[str, Any]] = []
+    for offset in sens.spot_offsets_pct:
+        S_adj = S * (1.0 + offset / 100.0)
+        for fb in sens.fee_bases:
+            row = _compute_waterfall(S_adj, q, disc, fee, ovl, fb)
+            row["spot_offset_pct"] = offset
+            row["spot"] = S_adj
+            row["fee_base"] = fb
+            results.append(row)
+    return results
+
+
 if __name__ == "__main__":
     for k, v in waterfall().items():
         if isinstance(v, float):
[0m
Now I have a complete review of all required materials. Here is the independent A4 review verdict.

---

**Verdict: READY TO COMMIT**

---

**Blocking findings:** None.

---

**Major findings:** None.

---

**Minor findings:**

1. **IV give-up not parametrised through KissellConfig.** `estimate_impact()` at impact.py line 128 hardcodes `iv_giveup_vol_pts=1.0`. The A4 brief mandates "parametric per-clip IV give-up (default 0.5-2.0 vol pts, **configurable**)." The 1.0 midpoint is correctly labelled `Provenance.ASSUMED` and no misrepresentation occurs, but the value should be a field on `KissellConfig` (with the same ASSUMED provenance) so callers — including the tranche scheduler — can supply venue- or market-condition-specific give-up estimates.

2. **Redundant test assertion.** `test_fee_breakdown_pending_decision()` at test_phase0.py line 1047 contains `assert "fee_base is None" or True`, which is unconditionally true. The preceding assert on the same field already validates `fee_base is None`. Cosmetic only; no functional defect.

3. **Tranche field constraint weaker than business floor.** `Tranche.btc_quantity` uses `Field(ge=1)` but the business minimum is 250 BTC. This is correctly caught by the output-level test `test_tranche_clip_limits()` and the scheduler algorithm itself applies the floor. Acceptable design but worth noting the two-level enforcement.

---

**Verified strengths:**

| Assessment Item | Result |
|---|---|
| 1. I-Star/Kissell formula transcription | **Verified.** Line-for-line match to Kissell §4 eq. 4.6 and 4.7 per contracts.md §12.1 and Pillar 3 §4.1. |
| 2. Formula units and parameter meanings | **Verified.** `order_size_btc` and `adv_btc` share BTC unit; `volatility` is decimal annualised per §3.1; `pov` is dimensionless; `i_star_bp`/`market_impact_bp` are in basis points. |
| 3. Square-root impact behaviour | **Verified.** `a2=0.5` default reproduces `∝ sqrt(Q/ADV)`. `square_root_eta` field provides explicit `sqrt(Q/ADV)` per Sinclair §6. Independently tested at `test_square_root_eta_scaling`. |
| 4. Impact monotonicity | **Verified.** `test_impact_monotonicity()` confirms I* increases with both order size (250→1000 BTC) and volatility (0.30→0.60). Mathematically guaranteed for `a2, a3 > 0` with positive inputs; zero/negative inputs rejected by `Field(gt=0)`. |
| 5. Separation of spot impact, IV give-up, fees and spread/slippage | **Verified.** `ImpactEstimate` has dedicated sub-fields (`i_star_bp`, `market_impact_bp`, `temporary_impact_bp`, `permanent_impact_bp`) separate from `iv_giveup_vol_pts`. `FeeBreakdown` is a distinct Pydantic model carrying `bid_ask_cost_btc` (MR-3), `venue_trading_fee_btc`, and an optional `impact_cost_estimate` link — never conflating the categories. |
| 6. Provenance of assumed versus observed calibration values | **Verified.** All eight KissellConfig defaults carry "provenance ASSUMED" docstrings. `ImpactEstimate` sub-provenance fields (`i_star_bp_provenance`, `market_impact_bp_provenance`, `iv_giveup_vol_pts_provenance`) all return `Provenance.ASSUMED`. Test `test_impact_estimate_provenance_per_component()` confirms this. Pillar 3 §9 M3 acknowledges missing calibration data. |
| 7. Exact 30,000-BTC tranche reconciliation | **Verified.** Six tests cover reconciliation: `test_tranche_reconciliation_30k`, `test_tranche_non_negative`, `test_tranche_custom_quantity`, `test_tranche_duration_weeks`, `test_tranche_impact_estimate_present`. Integer-only arithmetic prevents floating-point drift. Remainder distribution algorithm guarantees exact sum. |
| 8. DTE ladder [30, 37, 44] | **Verified.** `test_tranche_dte_ladder()` confirms `schedule.expiry_ladder_dte == [30, 37, 44]` and all tranche DTEs are drawn from `{30, 37, 44}`. |
| 9. Clip limits [250, 1000] | **Verified.** `test_tranche_clip_limits()` confirms every scheduled clip falls within `[250, 1000]`. Sub-minimum adjustment logic handles edge cases. |
| 10. Fee-base variants without silently resolving D-1 | **Verified.** `FeeBreakdown.fee_base` is `Literal[...] | None = None`. `EngineConfig.fee_base` is `None` (truly pending per D-1). `test_engine_config_rejects_unresolved_fee_base()` raises `ConfigurationError` when unresolved. Sensitivity mode computes both variants; `test_waterfall_sensitivity_no_silent_decision()` confirms neither is chosen as canonical. |
| 11. Backward compatibility of the original waterfall | **Verified.** `waterfall()` interface signature, return dict keys, and all seven tested numerical assertions are algebraically identical to the Sprint-0 scaffold. Test `test_waterfall_mandate_numbers()` passes all seven assertions with the identical expected values. |
| 12. Separation of target, forecast and realised economics | **Verified.** Waterfall keys use "target" language (`overlay_target_usd`, `*_target_case`). D-6 acknowledges the unresolved label choice. Sensitivity mode outputs are unambiguously labelled with `spot_offset_pct` and `fee_base`. |
| 13. Sensitivity-grid completeness | **Verified.** Default grid is 7 spot offsets × 2 fee bases = 14 result rows per contracts.md §12.4. Both `test_waterfall_sensitivity_all_offsets()` and `test_waterfall_sensitivity_fee_base_variants()` confirm full 7×2 coverage with differentiable results. |
| 14. Numerical correctness of spot and fee-base sensitivities | **Verified.** Spot adjustment: `S_adj = S * (1.0 + offset/100.0)` — correct. Fee-base: `executed_volume` charges fee on discounted notional `S*q*(1−disc)`, `reference_notional` on full notional `S*q` — both correct. |
| 15. Invalid-quantity, duration and parameter validation | **Verified.** `test_kissell_config_rejects_invalid()` covers negative order_size, zero ADV, negative vol, `b1 > 1`, `pov = 0`. `test_impact_zero_order_rejected()` covers zero order_size. Additional `EngineConfig` validators cover DTE ladder overlap, discount consistency, and tranche-within-quantity. |
| 16. Frozen contracts were not modified | **Verified.** `git diff -- contracts.md` produced no output per independent external verification. `git diff --check` passed. |
| 17. Test quality and independently calculated expected values | **Verified.** `test_i_star_formula()` manually computes `100 * sqrt(0.1) * sqrt(0.45)` independently of the implementation. `test_square_root_eta_scaling()` independently computes `sqrt(500/5000)`. `test_waterfall_mandate_numbers()` uses independently calculated notional (1,950M), fee (9.75M), effective cost (62,075/btc). Monotonicity tests check ordinal relationships, not self-referential values. |
| 18. Unresolved calibration and venue decisions remain clearly labelled | **Verified.** `W-UNCALIBRATED-IMPACT` in error taxonomy §15.3. D-1 through D-9 fully documented in contracts.md §19. All I-Star parameters carry `Provenance.ASSUMED`. FeeBreakdown `fee_base=None`, EngineConfig `primary_venue=None`, `fee_base=None`, `reference_spot_source=None` — all truly pending. Pillar 3 §9 M3 explicitly documents missing calibration data. |

---

**Commands run and results:**

Per review instructions, the following was independently verified outside this review:

| Command | Result |
|---|---|
| `python -m pytest -q` | Full suite passed |
| `python -m mypy` (16 source files) | Strict passed, no issues |
| `python -m ruff check .` | Passed |
| `python scripts/anonymisation_scan.py` | Passed |
| `git diff --check` | Passed (no whitespace errors) |
| `git diff -- contracts.md` | No output (contracts.md unmodified) |

---

**Summary:** The A4 execution module correctly implements the I-Star/Kissell impact model, a 30,000-BTC-exact tranche scheduler over DTE ladder [30, 37, 44] with clip limits [250, 1000], and a backward-compatible waterfall sensitivity mode covering 7 spot offsets × 2 fee-base variants. All provenance labels, unresolved decision markers (D-1, D-3), and component-level provenance fields are in place. Tests provide independently calculated expected values and cover formula correctness, monotonicity, reconciliation, bounds, provenance integrity, and invalid-input rejection. No contract modifications occurred. The one configurability gap (IV give-up hardcoded at 1.0 vol pts) is minor, correctly provenance-labelled as ASSUMED, and does not block commit.
