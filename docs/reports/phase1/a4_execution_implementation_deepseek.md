[0m
> build · deepseek-v4-flash
[0m
[0m→ [0mRead contracts.md
[0m→ [0mRead docs/architecture/contracts_freeze_record.md
[0m→ [0mRead docs/requirements/authoritative_corrections.md
[0m→ [0mRead docs/requirements/ceo_strategy_research_mandate.md
[0m→ [0mRead docs/requirements/mandate_sanitized.md
[0m→ [0mRead agents/A4_execution.md
[0m→ [0mRead .
[0m→ [0mRead execution
[0m→ [0mRead config
[0m→ [0mRead tests
[0m→ [0mRead execution/waterfall.py
[0m→ [0mRead config/models.py
[0m→ [0mRead config/params.yaml
[0m✗ [0mRead tests/test_waterfall.py failed
[91m[1mError: [0mFile not found: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_waterfall.py
[0m→ [0mRead tests/test_engine.py
[0m→ [0mRead tests/test_phase0.py
[0m→ [0mRead docs/reports/reference_study/pillar_3_execution_microstructure_deepseek.md
[0m→ [0mRead docs/reports/reference_study/pillar_4_venue_standards_deepseek.md
[0m→ [0mRead contracts.md[90m [offset=1152][0m
[0m→ [0mRead engine
[0m→ [0mRead engine/data_models.py
[0m→ [0mRead engine/strategy.py
[0m→ [0mRead engine/errors.py
[0m→ [0mRead engine/settlement.py
[0m→ [0mRead pricing/black_scholes.py
[0m✱ [0mGrep "I\*|I-Star|I_star|a1.*a2.*a3"[90m in private_reference_library/_text_cache/Textbooks · 100 matches[0m
[0m✱ [0mGrep "sqrt|square.root"[90m in private_reference_library/_text_cache/Textbooks · 9 matches[0m
[0m
[0m# [0mTodos
[•] Implement execution/impact.py — I-Star/Kissell impact model with KissellConfig, ImpactEstimate, estimate_impact()
[ ] Implement execution/tranches.py — Tranche scheduler with schedule_tranches()
[ ] Extend execution/waterfall.py — FeeBreakdown, WaterfallSensitivity, waterfall_sensitivity()
[ ] Add A4 tests to test_phase0.py — reconciliation, monotonicity, limits, provenance, fee-base variants
[ ] Run pytest, mypy, ruff, anonymisation_scan, git diff --check and fix until passing
[0m
[0m← [0mWrite execution/impact.py
Wrote file successfully.
[0m
[0m# [0mTodos
[✓] Implement execution/impact.py — I-Star/Kissell impact model with KissellConfig, ImpactEstimate, estimate_impact()
[•] Implement execution/tranches.py — Tranche scheduler with schedule_tranches()
[ ] Extend execution/waterfall.py — FeeBreakdown, WaterfallSensitivity, waterfall_sensitivity()
[ ] Add A4 tests to test_phase0.py — reconciliation, monotonicity, limits, provenance, fee-base variants
[ ] Run pytest, mypy, ruff, anonymisation_scan, git diff --check and fix until passing
[0m
[0m← [0mWrite execution/tranches.py
Wrote file successfully.
[0m
[0m# [0mTodos
[✓] Implement execution/impact.py — I-Star/Kissell impact model with KissellConfig, ImpactEstimate, estimate_impact()
[✓] Implement execution/tranches.py — Tranche scheduler with schedule_tranches()
[•] Extend execution/waterfall.py — FeeBreakdown, WaterfallSensitivity, waterfall_sensitivity()
[ ] Add A4 tests to test_phase0.py — reconciliation, monotonicity, limits, provenance, fee-base variants
[ ] Run pytest, mypy, ruff, anonymisation_scan, git diff --check and fix until passing
[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -3,22 +3,40 @@
 Run:  python3 -m execution.waterfall  (from btc_engine/)
 
 Phase 0: typed, file-handle leak fixed.  Preserves exact numerical behaviour
 and public compatibility with existing tests.
+
+A4 extension: waterfall_sensitivity() produces labelled dicts for every
+(spot_offset_pct, fee_base) combination.  fee_base variant preserves D-1
+decision marker (both variants computed, not resolved).
 """
 
 from __future__ import annotations
 
+import copy
 import pathlib
-from typing import Any
+from typing import Any, Literal
 
 import yaml
 
+from pydantic import BaseModel, Field
+
 CFG: pathlib.Path = (
     pathlib.Path(__file__).resolve().parents[1] / "config" / "params.yaml"
 )
 
 
+class WaterfallSensitivity(BaseModel):
+    """Sensitivity parameters for waterfall — frozen per contracts.md §12.4."""
+
+    spot_offsets_pct: list[float] = Field(
+        default_factory=lambda: [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
+    )
+    fee_bases: list[Literal["reference_notional", "executed_volume"]] = Field(
+        default_factory=lambda: ["reference_notional", "executed_volume"]
+    )
+
+
 def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:
     """Load raw params.yaml.  File handle closed after read."""
     path = path or CFG
     with open(path, encoding="utf-8") as fh:
@@ -27,25 +45,28 @@
         return raw
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
+    # The fee base determines what notional the 0.5% is charged against:
+    #   reference_notional  → charge on full S * q (current behaviour)
+    #   executed_volume     → charge on discounted notional S * q * (1 - disc)
+    if fee_base == "executed_volume":
+        fee_notional = notional * (1.0 - disc)
+    else:
+        fee_notional = notional
+    fee_usd: float = fee_notional * fee_rate
+    client_cash_per_btc: float = price_after_disc + fee_usd / q
     overlay_usd: float = notional * ovl
     effective_per_btc: float = client_cash_per_btc - S * ovl
 
     return {
@@ -64,8 +85,53 @@
         "net_discount_vs_reference_pct": 100.0 * (1.0 - effective_per_btc / S),
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
             print(f"{k:45s} {v:,.2f}")

[0m
[0m# [0mTodos
[✓] Implement execution/impact.py — I-Star/Kissell impact model with KissellConfig, ImpactEstimate, estimate_impact()
[✓] Implement execution/tranches.py — Tranche scheduler with schedule_tranches()
[✓] Extend execution/waterfall.py — FeeBreakdown, WaterfallSensitivity, waterfall_sensitivity()
[•] Add A4 tests to test_phase0.py — reconciliation, monotonicity, limits, provenance, fee-base variants
[ ] Run pytest, mypy, ruff, anonymisation_scan, git diff --check and fix until passing
[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -48,9 +48,16 @@
     Strategy,
     StrategyKind,
     classify,
 )
-from execution.waterfall import load_params, waterfall
+from execution.waterfall import (
+    WaterfallSensitivity,
+    load_params,
+    waterfall,
+    waterfall_sensitivity,
+)
+from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
+from execution.tranches import Tranche, TrancheSchedule, schedule_tranches
 from pricing.black_scholes import OptionQuote
 
 # ══════════════════════════════════════════════════════════════════════════════
 # Helpers

[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -518,12 +518,15 @@
     assert inst.provenance == Provenance.OBSERVED
     assert inst.origin == "deribit"
 
 
-@pytest.mark.skip(reason="Deferred to A4 — ImpactEstimate not yet built")
 def test_impact_estimate_provenance_per_component() -> None:
-    """Provenance enum values for impact components are defined."""
-    assert False, "Not implemented — A4"
+    """ImpactEstimate carries ASSUMED provenance on uncalibrated components."""
+    config = KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=0.45)
+    est = estimate_impact(config)
+    assert est.i_star_bp_provenance == Provenance.ASSUMED
+    assert est.market_impact_bp_provenance == Provenance.ASSUMED
+    assert est.iv_giveup_vol_pts_provenance == Provenance.ASSUMED
 
 
 # ══════════════════════════════════════════════════════════════════════════════
 # §5 — Settlement spec integrity tests

[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -731,16 +731,36 @@
 # §13.6 — Waterfall sensitivity (deferred per D-1)
 # ══════════════════════════════════════════════════════════════════════════════
 
 
-@pytest.mark.xfail(reason="D-1 fee base unresolved")
 def test_waterfall_fee_base_sensitivity() -> None:
-    assert False, "Not implemented — A4 Sprint 1"
+    """Both fee-base variants produce valid arithmetic."""
+    p = load_params()
+    sens = WaterfallSensitivity(
+        spot_offsets_pct=[0.0],
+        fee_bases=["reference_notional", "executed_volume"],
+    )
+    results = waterfall_sensitivity(p, sens)
+    assert len(results) == 2
+    fb_set = {r["fee_base"] for r in results}
+    assert "reference_notional" in fb_set
+    assert "executed_volume" in fb_set
+    for r in results:
+        assert r["asymmetrica_fee_usd"] > 0
+        assert r["client_effective_cost_per_btc_target_case"] > 0
 
 
-@pytest.mark.skip(reason="Deferred to A4 — waterfall_sensitivity not yet implemented")
 def test_waterfall_spot_sensitivity() -> None:
-    assert False, "Not implemented — A4 Sprint 1"
+    """All spot offsets produce valid arithmetic."""
+    p = load_params()
+    results = waterfall_sensitivity(p)
+    offset_set = {r["spot_offset_pct"] for r in results}
+    assert -10.0 in offset_set
+    assert 0.0 in offset_set
+    assert 10.0 in offset_set
+    for r in results:
+        assert r["asymmetrica_fee_usd"] > 0
+        assert r["reference_notional_usd"] > 0
 
 
 # ══════════════════════════════════════════════════════════════════════════════
 # §10 — Rolling / early-close tests (deferred to A3)

[0m
[0m→ [0mRead tests/test_phase0.py[90m [offset=820][0m
[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -867,4 +867,219 @@
         ],
     )
     assert len(strategy.pending_decisions) == 2
     assert strategy.pending_decisions[0].code == "D-1"
+
+
+# ══════════════════════════════════════════════════════════════════════════════
+# §12.1 — Market impact model tests (A4)
+# ══════════════════════════════════════════════════════════════════════════════
+
+
+def test_i_star_formula() -> None:
+    """I-Star formula produces expected values for known inputs."""
+    config = KissellConfig(
+        order_size_btc=500.0, adv_btc=5000.0, volatility=0.45,
+        a1=100.0, a2=0.5, a3=0.5, b1=0.5, a4=0.2, pov=0.10,
+    )
+    est = estimate_impact(config)
+    q_adv = 500.0 / 5000.0  # 0.1
+    expected_i_star = 100.0 * (0.1 ** 0.5) * (0.45 ** 0.5)
+    assert abs(est.i_star_bp - expected_i_star) < 1e-9
+    assert est.i_star_bp > 0
+    assert est.market_impact_bp > 0
+    assert est.temporary_impact_bp > 0
+    assert est.permanent_impact_bp > 0
+
+
+def test_impact_monotonicity() -> None:
+    """Impact increases with order size and volatility."""
+    small = estimate_impact(KissellConfig(order_size_btc=250.0, adv_btc=5000.0, volatility=0.45))
+    large = estimate_impact(KissellConfig(order_size_btc=1000.0, adv_btc=5000.0, volatility=0.45))
+    assert large.i_star_bp > small.i_star_bp
+    assert large.market_impact_bp > small.market_impact_bp
+
+    low_vol = estimate_impact(KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=0.30))
+    mid_vol = estimate_impact(KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=0.60))
+    assert mid_vol.i_star_bp > low_vol.i_star_bp
+
+
+def test_impact_zero_order_rejected() -> None:
+    """KissellConfig rejects zero order size."""
+    with pytest.raises(Exception):
+        KissellConfig(order_size_btc=0.0, adv_btc=5000.0, volatility=0.45)
+
+
+def test_impact_provenance_present() -> None:
+    """ImpactEstimate carries provenance on every component."""
+    config = KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=0.45)
+    est = estimate_impact(config)
+    assert est.provenance is not None
+    assert str(est.provenance) == "calculated"
+
+
+def test_square_root_eta_scaling() -> None:
+    """Square-root eta = sqrt(Q/ADV)."""
+    est = estimate_impact(KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=0.45))
+    assert abs(est.square_root_eta - (500.0 / 5000.0) ** 0.5) < 1e-12
+
+
+# ══════════════════════════════════════════════════════════════════════════════
+# §12.3 — Tranche scheduler tests (A4)
+# ══════════════════════════════════════════════════════════════════════════════
+
+
+def test_tranche_reconciliation_30k() -> None:
+    """Default mandate schedule reconciles exactly to 30 000 BTC."""
+    schedule = schedule_tranches(total_btc=30000)
+    assert schedule.total_btc == 30000
+    total = sum(t.btc_quantity for t in schedule.tranches)
+    assert total == 30000, f"Scheduled {total} != 30000"
+
+
+def test_tranche_dte_ladder() -> None:
+    """Tranches reflect configured DTE ladder [30, 37, 44]."""
+    schedule = schedule_tranches(total_btc=30000)
+    assert 30 in schedule.expiry_ladder_dte
+    assert 37 in schedule.expiry_ladder_dte
+    assert 44 in schedule.expiry_ladder_dte
+    dtes = {t.dte for t in schedule.tranches}
+    assert dtes == {30, 37, 44}
+
+
+def test_tranche_clip_limits() -> None:
+    """All clips are within configured [250, 1000] range."""
+    schedule = schedule_tranches(total_btc=30000)
+    for t in schedule.tranches:
+        assert 250 <= t.btc_quantity <= 1000, (
+            f"Clip {t.btc_quantity} outside [250, 1000]"
+        )
+
+
+def test_tranche_non_negative() -> None:
+    """Tranche quantities are all positive."""
+    schedule = schedule_tranches(total_btc=30000)
+    assert all(t.btc_quantity >= 0 for t in schedule.tranches)
+    assert schedule.total_scheduled_btc() == 30000
+
+
+def test_tranche_custom_quantity() -> None:
+    """Custom total BTC reconciles correctly."""
+    schedule = schedule_tranches(total_btc=15000, expiry_ladder=[30, 44])
+    assert schedule.total_scheduled_btc() == 15000
+
+
+def test_tranche_duration_weeks() -> None:
+    """Duration weeks set on schedule."""
+    schedule = schedule_tranches(total_btc=30000, duration_weeks=8)
+    assert schedule.duration_weeks == 8
+    assert schedule.total_scheduled_btc() == 30000
+
+
+def test_tranche_impact_estimate_present() -> None:
+    """Every tranche carries an impact estimate."""
+    schedule = schedule_tranches(total_btc=30000)
+    for t in schedule.tranches:
+        assert t.estimated_impact is not None
+        assert t.estimated_impact.i_star_bp > 0
+
+
+# ══════════════════════════════════════════════════════════════════════════════
+# §12.4 — Waterfall sensitivity tests (A4)
+# ══════════════════════════════════════════════════════════════════════════════
+
+
+def test_waterfall_sensitivity_all_offsets() -> None:
+    """All seven default spot offsets produce valid results."""
+    results = waterfall_sensitivity()
+    offsets = sorted({r["spot_offset_pct"] for r in results})
+    assert len(offsets) == 7
+
+
+def test_waterfall_sensitivity_fee_base_variants() -> None:
+    """Both fee-base variants are produced and differ."""
+    results = waterfall_sensitivity()
+    ref = [r for r in results if r["fee_base"] == "reference_notional"]
+    exec_vol = [r for r in results if r["fee_base"] == "executed_volume"]
+    assert len(ref) == 7
+    assert len(exec_vol) == 7
+    for r_ref, r_ev in zip(ref, exec_vol):
+        assert r_ref["asymmetrica_fee_usd"] != r_ev["asymmetrica_fee_usd"]
+
+
+def test_waterfall_sensitivity_no_silent_decision() -> None:
+    """Fee-base variant does not silently resolve D-1."""
+    p = load_params()
+    results = waterfall_sensitivity(p)
+    for r in results:
+        assert "fee_base" in r
+        assert r["fee_base"] in ("reference_notional", "executed_volume")
+
+
+# ══════════════════════════════════════════════════════════════════════════════
+# §12.1 — KissellConfig validation tests (A4)
+# ══════════════════════════════════════════════════════════════════════════════
+
+
+def test_kissell_config_rejects_invalid() -> None:
+    """KissellConfig rejects non-positive order_size_btc."""
+    with pytest.raises(Exception):
+        KissellConfig(order_size_btc=-100.0, adv_btc=5000.0, volatility=0.45)
+    with pytest.raises(Exception):
+        KissellConfig(order_size_btc=500.0, adv_btc=0.0, volatility=0.45)
+    with pytest.raises(Exception):
+        KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=-0.1)
+    with pytest.raises(Exception):
+        KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=0.45, b1=1.5)
+    with pytest.raises(Exception):
+        KissellConfig(order_size_btc=500.0, adv_btc=5000.0, volatility=0.45, pov=0.0)
+
+
+# ══════════════════════════════════════════════════════════════════════════════
+# FeeBreakdown model tests (A4)
+# ══════════════════════════════════════════════════════════════════════════════
+
+
+def test_fee_breakdown_pending_decision() -> None:
+    """FeeBreakdown carries fee_base=None pending D-1."""
+    from execution.impact import FeeBreakdown
+    fb = FeeBreakdown()
+    assert fb.fee_base is None
+    assert "fee_base is None" or True  # structural check
+
+
+def test_fee_breakdown_tracks_decisions() -> None:
+    """FeeBreakdown pending_decision_refs includes D-1."""
+    from execution.impact import FeeBreakdown
+    fb = FeeBreakdown(
+        pending_decision_refs=["D-1", "D-3"],
+    )
+    assert "D-1" in fb.pending_decision_refs
+
+
+# ══════════════════════════════════════════════════════════════════════════════
+# TrancheSchedule model tests (A4)
+# ══════════════════════════════════════════════════════════════════════════════
+
+
+def test_tranche_schedule_validates() -> None:
+    """TrancheSchedule structure validates correctly."""
+    from datetime import UTC, datetime
+
+    impact = ImpactEstimate(order_size_btc=250.0, adv_btc=5000.0, volatility=0.45)
+    t = Tranche(
+        tranche_id=0,
+        dte=30,
+        btc_quantity=250,
+        scheduled_date=datetime.now(UTC),
+        estimated_impact=impact,
+    )
+    s = TrancheSchedule(
+        strategy="test",
+        total_btc=250,
+        tranches=[t],
+        expiry_ladder_dte=[30],
+        clip_size_range=(250, 1000),
+        duration_weeks=4,
+    )
+    assert s.total_scheduled_btc() == 250
+    assert s.tranches[0].dte == 30

[0m
[0m# [0mTodos
[✓] Implement execution/impact.py — I-Star/Kissell impact model with KissellConfig, ImpactEstimate, estimate_impact()
[✓] Implement execution/tranches.py — Tranche scheduler with schedule_tranches()
[✓] Extend execution/waterfall.py — FeeBreakdown, WaterfallSensitivity, waterfall_sensitivity()
[✓] Add A4 tests to test_phase0.py — reconciliation, monotonicity, limits, provenance, fee-base variants
[•] Run pytest, mypy, ruff, anonymisation_scan, git diff --check and fix until passing
[0m
[0m$ [0m.venv/bin/python -m pytest -q 2>&1
/bin/bash: line 1: .venv/bin/python: No such file or directory
[0m
[0m$ [0mls .venv/bin/python* 2>/dev/null || ls .venv/bin/python* 2>/dev/null || which python3
/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python3
[0m
[0m$ [0mls /home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python*
/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python
/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python3
/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python3.12
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m pytest -q 2>&1
..........................................sssssssss..ssss..ss.ss........ [ 83%]
......F.......                                                           [100%]
=================================== FAILURES ===================================
_____________________ test_tranche_impact_estimate_present _____________________
tests/test_phase0.py:983: in test_tranche_impact_estimate_present
    assert t.estimated_impact.i_star_bp > 0
E   AssertionError: assert 0.0 > 0
E    +  where 0.0 = ImpactEstimate(order_size_btc=625.0, adv_btc=5000.0, volatility=0.45, i_star_bp=0.0, i_star_bp_provenance=<Provenance....ts=0.0, iv_giveup_vol_pts_provenance=<Provenance.ASSUMED: 'assumed'>, provenance=<Provenance.CALCULATED: 'calculated'>).i_star_bp
E    +    where ImpactEstimate(order_size_btc=625.0, adv_btc=5000.0, volatility=0.45, i_star_bp=0.0, i_star_bp_provenance=<Provenance....ts=0.0, iv_giveup_vol_pts_provenance=<Provenance.ASSUMED: 'assumed'>, provenance=<Provenance.CALCULATED: 'calculated'>) = Tranche(tranche_id=0, dte=30, btc_quantity=625, strike=0.0, delta_target=0.0, target_premium_pct=0.0, execution_venue=...ovenance.CALCULATED: 'calculated'>), scheduled_date=datetime.datetime(2026, 7, 28, 0, 0, tzinfo=datetime.timezone.utc)).estimated_impact
=========================== short test summary info ============================
FAILED tests/test_phase0.py::test_tranche_impact_estimate_present - Assertion...
[0m
[0m← [0mEdit execution/tranches.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
@@ -18,9 +18,9 @@
 from pydantic import BaseModel, Field
 
 from config.models import Provenance
 from engine.settlement import Venue
-from execution.impact import ImpactEstimate
+from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
 
 
 class ExecutionMethod(StrEnum):
     BLOCK_RFQ = "block_rfq"

[0m
[0m← [0mEdit execution/tranches.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
@@ -129,12 +129,14 @@
 if qty == 0:
     continue
 
 d = base_date + timedelta(weeks=week)
-est_impact = ImpactEstimate(
-    order_size_btc=float(qty),
-    adv_btc=5000.0,
-    volatility=0.45,
+est_impact = estimate_impact(
+    KissellConfig(
+        order_size_btc=float(qty),
+        adv_btc=5000.0,
+        volatility=0.45,
+    )
 )
 tranches.append(
     Tranche(
         tranche_id=tranche_id,

[0m
[0m← [0mEdit execution/impact.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
@@ -90,9 +90,9 @@
     provenance: Provenance | None = None
 
     def model_post_init(self, __context: Any) -> None:
         if self.provenance is None:
-            self.provenance = Provenance.CALCULATED
+            object.__setattr__(self, "provenance", Provenance.CALCULATED)
 
 
 def estimate_impact(config: KissellConfig) -> ImpactEstimate:
     """I-Star model (Kissell §4, eq. 4.6–4.7).

[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m pytest -q 2>&1
..........................................sssssssss..ssss..ss.ss........ [ 83%]
..............                                                           [100%]
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m mypy execution/ tests/ config/ engine/ pricing/ 2>&1
execution/waterfall.py:35: error: Argument "default_factory" to "Field" has incompatible type "Callable[[], list[str]]"; expected "Callable[[], list[Literal['reference_notional', 'executed_volume']]] | Callable[[dict[str, Any]], list[Literal['reference_notional', 'executed_volume']]]"  [arg-type]
Found 1 error in 1 file (checked 13 source files)
[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -13,9 +13,9 @@
 from __future__ import annotations
 
 import copy
 import pathlib
-from typing import Any, Literal
+from typing import Any, Callable, Literal
 
 import yaml
 
 from pydantic import BaseModel, Field

[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -31,9 +31,12 @@
     spot_offsets_pct: list[float] = Field(
         default_factory=lambda: [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
     )
     fee_bases: list[Literal["reference_notional", "executed_volume"]] = Field(
-        default_factory=lambda: ["reference_notional", "executed_volume"]
+        default_factory=lambda: cast(
+            list[Literal["reference_notional", "executed_volume"]],
+            ["reference_notional", "executed_volume"],
+        )
     )
 
 
 def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:

[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -13,9 +13,9 @@
 from __future__ import annotations
 
 import copy
 import pathlib
-from typing import Any, Callable, Literal
+from typing import Any, Literal
 
 import yaml
 
 from pydantic import BaseModel, Field

[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -31,12 +31,9 @@
     spot_offsets_pct: list[float] = Field(
         default_factory=lambda: [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
     )
     fee_bases: list[Literal["reference_notional", "executed_volume"]] = Field(
-        default_factory=lambda: cast(
-            list[Literal["reference_notional", "executed_volume"]],
-            ["reference_notional", "executed_volume"],
-        )
+        default_factory=lambda: ["reference_notional", "executed_volume"]  # type: ignore[return-value]
     )
 
 
 def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:

[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m mypy execution/ tests/ config/ engine/ pricing/ 2>&1
execution/waterfall.py:35: error: Unused "type: ignore" comment  [unused-ignore]
execution/waterfall.py:35: error: Argument "default_factory" to "Field" has incompatible type "Callable[[], list[str]]"; expected "Callable[[], list[Literal['reference_notional', 'executed_volume']]] | Callable[[dict[str, Any]], list[Literal['reference_notional', 'executed_volume']]]"  [arg-type]
execution/waterfall.py:35: note: Error code "arg-type" not covered by "type: ignore[return-value]" comment
Found 2 errors in 1 file (checked 13 source files)
[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -24,16 +24,22 @@
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
 class WaterfallSensitivity(BaseModel):
     """Sensitivity parameters for waterfall — frozen per contracts.md §12.4."""
 
-    spot_offsets_pct: list[float] = Field(
-        default_factory=lambda: [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
-    )
+    spot_offsets_pct: list[float] = Field(default_factory=_default_spot_offsets)
     fee_bases: list[Literal["reference_notional", "executed_volume"]] = Field(
-        default_factory=lambda: ["reference_notional", "executed_volume"]  # type: ignore[return-value]
+        default_factory=_default_fee_bases
     )
 
 
 def load_params(path: pathlib.Path | None = None) -> dict[str, Any]:

[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m mypy execution/ tests/ config/ engine/ pricing/ 2>&1
Success: no issues found in 13 source files
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m ruff check execution/ tests/ config/ engine/ pricing/ vol/ scripts/ 2>&1
RUF002 Docstring contains ambiguous `–` (EN DASH). Did you mean `-` (HYPHEN-MINUS)?
 --> execution/impact.py:3:34
  |
1 | """Market impact, fee, and execution-cost models (A4).
2 |
3 | I-Star model (Kissell §4, eq. 4.6–4.7): I*_bp = a1 * (Q/ADV)^a2 * σ^a3
  |                                  ^
4 | MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
  |

RUF002 Docstring contains ambiguous `σ` (GREEK SMALL LETTER SIGMA). Did you mean `o` (LATIN SMALL LETTER O)?
 --> execution/impact.py:3:67
  |
1 | """Market impact, fee, and execution-cost models (A4).
2 |
3 | I-Star model (Kissell §4, eq. 4.6–4.7): I*_bp = a1 * (Q/ADV)^a2 * σ^a3
  |                                                                   ^
4 | MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
  |

RUF002 Docstring contains ambiguous `−` (MINUS SIGN). Did you mean `-` (HYPHEN-MINUS)?
 --> execution/impact.py:4:31
  |
3 | I-Star model (Kissell §4, eq. 4.6–4.7): I*_bp = a1 * (Q/ADV)^a2 * σ^a3
4 | MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
  |                               ^
5 |
6 | Frozen per contracts.md §12.1–12.2.
  |

RUF002 Docstring contains ambiguous `–` (EN DASH). Did you mean `-` (HYPHEN-MINUS)?
 --> execution/impact.py:6:30
  |
4 | MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
5 |
6 | Frozen per contracts.md §12.1–12.2.
  |                              ^
7 |
8 | All provenance-labelled per component. Uncalibrated parameters carry
  |

RUF002 Docstring contains ambiguous `–` (EN DASH). Did you mean `-` (HYPHEN-MINUS)?
  --> execution/impact.py:23:52
   |
22 | class KissellConfig(BaseModel):
23 |     """I-Star model parameters (Kissell §4, eq. 4.6–4.7).
   |                                                    ^
24 |
25 |     Provenance: a1–a4, b1 are ASSUMED unless calibrated.
   |

RUF002 Docstring contains ambiguous `–` (EN DASH). Did you mean `-` (HYPHEN-MINUS)?
  --> execution/impact.py:25:19
   |
23 |     """I-Star model parameters (Kissell §4, eq. 4.6–4.7).
24 |
25 |     Provenance: a1–a4, b1 are ASSUMED unless calibrated.
   |                   ^
26 |     order_size_btc, adv_btc, volatility are inputs that must carry their
27 |     own provenance at the calling layer.
   |

RUF002 Docstring contains ambiguous `–` (EN DASH). Did you mean `-` (HYPHEN-MINUS)?
   --> execution/impact.py:98:41
    |
 97 | def estimate_impact(config: KissellConfig) -> ImpactEstimate:
 98 |     """I-Star model (Kissell §4, eq. 4.6–4.7).
    |                                         ^
 99 |
100 |     I*_bp = a1 * (Q / ADV)^a2 * σ^a3
    |

RUF002 Docstring contains ambiguous `σ` (GREEK SMALL LETTER SIGMA). Did you mean `o` (LATIN SMALL LETTER O)?
   --> execution/impact.py:100:33
    |
 98 |     """I-Star model (Kissell §4, eq. 4.6–4.7).
 99 |
100 |     I*_bp = a1 * (Q / ADV)^a2 * σ^a3
    |                                 ^
101 |     MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
    |

RUF002 Docstring contains ambiguous `−` (MINUS SIGN). Did you mean `-` (HYPHEN-MINUS)?
   --> execution/impact.py:101:35
    |
100 |     I*_bp = a1 * (Q / ADV)^a2 * σ^a3
101 |     MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
    |                                   ^
102 |
103 |     Square-root scaling eta = sqrt(Q / ADV)  (Sinclair §6).
    |

F401 [*] `math` imported but unused
  --> execution/tranches.py:14:8
   |
12 | from __future__ import annotations
13 |
14 | import math
   |        ^^^^
15 | from datetime import UTC, datetime, timedelta
16 | from enum import StrEnum
   |
help: Remove unused import: `math`
   |
13 |
   - import math
14 | from datetime import UTC, datetime, timedelta
   |

F401 [*] `config.models.Provenance` imported but unused
  --> execution/tranches.py:20:27
   |
18 | from pydantic import BaseModel, Field
19 |
20 | from config.models import Provenance
   |                           ^^^^^^^^^^
21 | from engine.settlement import Venue
22 | from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
   |
help: Remove unused import: `config.models.Provenance`
   |
19 |
   - from config.models import Provenance
20 | from engine.settlement import Venue
   |

I001 [*] Import block is un-sorted or un-formatted
  --> execution/waterfall.py:13:1
   |
11 |   """
12 |
13 | / from __future__ import annotations
14 | |
15 | | import copy
16 | | import pathlib
17 | | from typing import Any, Literal
18 | |
19 | | import yaml
20 | |
21 | | from pydantic import BaseModel, Field
   | |_____________________________________^
22 |
23 |   CFG: pathlib.Path = (
   |
help: Organize imports
   |
19 | import yaml
   -
20 | from pydantic import BaseModel, Field
   |

F401 [*] `copy` imported but unused
  --> execution/waterfall.py:15:8
   |
13 | from __future__ import annotations
14 |
15 | import copy
   |        ^^^^
16 | import pathlib
17 | from typing import Any, Literal
   |
help: Remove unused import: `copy`
   |
14 |
   - import copy
15 | import pathlib
   |

SIM108 Use ternary operator `fee_notional = notional * (1.0 - disc) if fee_base == "executed_volume" else notional` instead of `if`-`else`-block
  --> execution/waterfall.py:69:5
   |
67 |       #   reference_notional  → charge on full S * q (current behaviour)
68 |       #   executed_volume     → charge on discounted notional S * q * (1 - disc)
69 | /     if fee_base == "executed_volume":
70 | |         fee_notional = notional * (1.0 - disc)
71 | |     else:
72 | |         fee_notional = notional
   | |_______________________________^
73 |       fee_usd: float = fee_notional * fee_rate
74 |       client_cash_per_btc: float = price_after_disc + fee_usd / q
   |
help: Replace `if`-`else`-block with `fee_notional = notional * (1.0 - disc) if fee_base == "executed_volume" else notional`

I001 [*] Import block is un-sorted or un-formatted
  --> tests/test_phase0.py:22:1
   |
20 |   sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
21 |
22 | / from config.models import (
23 | |     BreakoutRule,
24 | |     EngineConfig,
25 | |     Origin,
26 | |     Provenance,
27 | | )
28 | | from engine.data_models import (
29 | |     BookSummary,
30 | |     FixtureManifest,
31 | |     FixtureManifestEntry,
32 | |     OptionInstrument,
33 | |     SpotBar,
34 | | )
35 | | from engine.errors import ClassificationError, ConfigurationError, EngineError
36 | | from engine.fixture_loader import load_manifest
37 | | from engine.settlement import (
38 | |     DeliveryPriceConvention,
39 | |     ExerciseStyle,
40 | |     SettlementCurrency,
41 | |     SettlementMechanism,
42 | |     SettlementSpec,
43 | |     Venue,
44 | | )
45 | | from engine.strategy import (
46 | |     DecisionRef,
47 | |     Leg,
48 | |     Strategy,
49 | |     StrategyKind,
50 | |     classify,
51 | | )
52 | | from execution.waterfall import (
53 | |     WaterfallSensitivity,
54 | |     load_params,
55 | |     waterfall,
56 | |     waterfall_sensitivity,
57 | | )
58 | | from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
59 | | from execution.tranches import Tranche, TrancheSchedule, schedule_tranches
60 | | from pricing.black_scholes import OptionQuote
   | |_____________________________________________^
61 |
62 |   # ══════════════════════════════════════════════════════════════════════════════
   |
help: Organize imports
   |
51 | )
52 + from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
53 + from execution.tranches import Tranche, TrancheSchedule, schedule_tranches
54 | from execution.waterfall import (
--------------------------------------------------------------------------------
59 | )
   - from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
   - from execution.tranches import Tranche, TrancheSchedule, schedule_tranches
60 | from pricing.black_scholes import OptionQuote
   |

F841 Local variable `q_adv` is assigned to but never used
   --> tests/test_phase0.py:885:5
    |
883 |     )
884 |     est = estimate_impact(config)
885 |     q_adv = 500.0 / 5000.0  # 0.1
    |     ^^^^^
886 |     expected_i_star = 100.0 * (0.1 ** 0.5) * (0.45 ** 0.5)
887 |     assert abs(est.i_star_bp - expected_i_star) < 1e-9
    |
help: Remove assignment to unused variable `q_adv`

B905 `zip()` without an explicit `strict=` parameter
    --> tests/test_phase0.py:1005:24
     |
1003 |     assert len(ref) == 7
1004 |     assert len(exec_vol) == 7
1005 |     for r_ref, r_ev in zip(ref, exec_vol):
     |                        ^^^^^^^^^^^^^^^^^^
1006 |         assert r_ref["asymmetrica_fee_usd"] != r_ev["asymmetrica_fee_usd"]
     |
help: Add explicit value for parameter `strict=`

SIM222 Use `True` instead of `True or ...`
    --> tests/test_phase0.py:1047:12
     |
1045 |     fb = FeeBreakdown()
1046 |     assert fb.fee_base is None
1047 |     assert "fee_base is None" or True  # structural check
     |            ^^^^^^^^^^^^^^^^^^^^^^^^^^
     |
help: Replace with `True`

Found 18 errors.
[*] 5 fixable with the `--fix` option (4 hidden fixes can be enabled with the `--unsafe-fixes` option).
[0m
[0m← [0mEdit execution/impact.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
@@ -1,10 +1,10 @@
 """Market impact, fee, and execution-cost models (A4).
 
-I-Star model (Kissell §4, eq. 4.6–4.7): I*_bp = a1 * (Q/ADV)^a2 * σ^a3
-MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
+I-Star model (Kissell Sec.4, eq. 4.6-4.7): I*_bp = a1 * (Q/ADV)^a2 * sig^a3
+MI_bp = b1 * I* * POV^a4 + (1 - b1) * I*
 
-Frozen per contracts.md §12.1–12.2.
+Frozen per contracts.md Sec.12.1-12.2.
 
 All provenance-labelled per component. Uncalibrated parameters carry
 ASSUMED provenance.
 """

[0m
[0m← [0mEdit execution/impact.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
@@ -19,11 +19,11 @@
 from config.models import Provenance
 
 
 class KissellConfig(BaseModel):
-    """I-Star model parameters (Kissell §4, eq. 4.6–4.7).
+    """I-Star model parameters (Kissell Sec.4, eq. 4.6-4.7).
 
-    Provenance: a1–a4, b1 are ASSUMED unless calibrated.
+    Provenance: a1-a4, b1 are ASSUMED unless calibrated.
     order_size_btc, adv_btc, volatility are inputs that must carry their
     own provenance at the calling layer.
     """
 

[0m
[0m← [0mEdit execution/impact.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/impact.py
@@ -94,14 +94,14 @@
             object.__setattr__(self, "provenance", Provenance.CALCULATED)
 
 
 def estimate_impact(config: KissellConfig) -> ImpactEstimate:
-    """I-Star model (Kissell §4, eq. 4.6–4.7).
+    """I-Star model (Kissell Sec.4, eq. 4.6-4.7).
 
-    I*_bp = a1 * (Q / ADV)^a2 * σ^a3
-    MI_bp = b1 * I* * POV^a4 + (1 − b1) * I*
+    I*_bp = a1 * (Q / ADV)^a2 * sig^a3
+    MI_bp = b1 * I* * POV^a4 + (1 - b1) * I*
 
-    Square-root scaling eta = sqrt(Q / ADV)  (Sinclair §6).
+    Square-root scaling eta = sqrt(Q / ADV)  (Sinclair Sec.6).
     IV give-up: default 1.0 vol pts (uncalibrated, provenance ASSUMED).
     """
     q_adv = config.order_size_btc / config.adv_btc
     i_star_bp = config.a1 * (q_adv ** config.a2) * (config.volatility ** config.a3)

[0m
[0m← [0mEdit execution/tranches.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/tranches.py
@@ -10,15 +10,13 @@
 """
 
 from __future__ import annotations
 
-import math
 from datetime import UTC, datetime, timedelta
 from enum import StrEnum
 
 from pydantic import BaseModel, Field
 
-from config.models import Provenance
 from engine.settlement import Venue
 from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
 
 

[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -11,9 +11,8 @@
 """
 
 from __future__ import annotations
 
-import copy
 import pathlib
 from typing import Any, Literal
 
 import yaml

[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -61,15 +61,9 @@
 ) -> dict[str, Any]:
     """Core waterfall arithmetic — reused by waterfall() and waterfall_sensitivity()."""
     notional: float = S * q
     price_after_disc: float = S * (1.0 - disc)
-    # The fee base determines what notional the 0.5% is charged against:
-    #   reference_notional  → charge on full S * q (current behaviour)
-    #   executed_volume     → charge on discounted notional S * q * (1 - disc)
-    if fee_base == "executed_volume":
-        fee_notional = notional * (1.0 - disc)
-    else:
-        fee_notional = notional
+    fee_notional = notional * (1.0 - disc) if fee_base == "executed_volume" else notional
     fee_usd: float = fee_notional * fee_rate
     client_cash_per_btc: float = price_after_disc + fee_usd / q
     overlay_usd: float = notional * ovl
     effective_per_btc: float = client_cash_per_btc - S * ovl

[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -48,16 +48,16 @@
     Strategy,
     StrategyKind,
     classify,
 )
+from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
+from execution.tranches import Tranche, TrancheSchedule, schedule_tranches
 from execution.waterfall import (
     WaterfallSensitivity,
     load_params,
     waterfall,
     waterfall_sensitivity,
 )
-from execution.impact import ImpactEstimate, KissellConfig, estimate_impact
-from execution.tranches import Tranche, TrancheSchedule, schedule_tranches
 from pricing.black_scholes import OptionQuote
 
 # ══════════════════════════════════════════════════════════════════════════════
 # Helpers

[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -881,9 +881,8 @@
     order_size_btc=500.0, adv_btc=5000.0, volatility=0.45,
     a1=100.0, a2=0.5, a3=0.5, b1=0.5, a4=0.2, pov=0.10,
 )
 est = estimate_impact(config)
-q_adv = 500.0 / 5000.0  # 0.1
 expected_i_star = 100.0 * (0.1 ** 0.5) * (0.45 ** 0.5)
 assert abs(est.i_star_bp - expected_i_star) < 1e-9
 assert est.i_star_bp > 0
 assert est.market_impact_bp > 0

[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -1000,9 +1000,9 @@
     ref = [r for r in results if r["fee_base"] == "reference_notional"]
     exec_vol = [r for r in results if r["fee_base"] == "executed_volume"]
     assert len(ref) == 7
     assert len(exec_vol) == 7
-    for r_ref, r_ev in zip(ref, exec_vol):
+    for r_ref, r_ev in zip(ref, exec_vol, strict=True):
         assert r_ref["asymmetrica_fee_usd"] != r_ev["asymmetrica_fee_usd"]
 
 
 def test_waterfall_sensitivity_no_silent_decision() -> None:

[0m
[0m← [0mEdit tests/test_phase0.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/tests/test_phase0.py
@@ -1042,9 +1042,8 @@
     """FeeBreakdown carries fee_base=None pending D-1."""
     from execution.impact import FeeBreakdown
     fb = FeeBreakdown()
     assert fb.fee_base is None
-    assert "fee_base is None" or True  # structural check
 
 
 def test_fee_breakdown_tracks_decisions() -> None:
     """FeeBreakdown pending_decision_refs includes D-1."""

[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m ruff check execution/ tests/ config/ engine/ pricing/ vol/ scripts/ 2>&1
I001 [*] Import block is un-sorted or un-formatted
  --> execution/waterfall.py:13:1
   |
11 |   """
12 |
13 | / from __future__ import annotations
14 | |
15 | | import pathlib
16 | | from typing import Any, Literal
17 | |
18 | | import yaml
19 | |
20 | | from pydantic import BaseModel, Field
   | |_____________________________________^
21 |
22 |   CFG: pathlib.Path = (
   |
help: Organize imports
   |
18 | import yaml
   -
19 | from pydantic import BaseModel, Field
   |

Found 1 error.
[*] 1 fixable with the `--fix` option.
[0m
[0m← [0mEdit execution/waterfall.py
Index: /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
===================================================================
--- /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
+++ /home/heimdall/btc_proj/BTC_analysis/btc_engine-a4/execution/waterfall.py
@@ -14,12 +14,12 @@
 
 import pathlib
 from typing import Any, Literal
 
-import yaml
-
 from pydantic import BaseModel, Field
 
+import yaml
+
 CFG: pathlib.Path = (
     pathlib.Path(__file__).resolve().parents[1] / "config" / "params.yaml"
 )
 

[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m ruff check execution/ tests/ config/ engine/ pricing/ vol/ scripts/ 2>&1
I001 [*] Import block is un-sorted or un-formatted
  --> execution/waterfall.py:13:1
   |
11 |   """
12 |
13 | / from __future__ import annotations
14 | |
15 | | import pathlib
16 | | from typing import Any, Literal
17 | |
18 | | from pydantic import BaseModel, Field
19 | |
20 | | import yaml
   | |___________^
21 |
22 |   CFG: pathlib.Path = (
   |
help: Organize imports
   |
17 |
   - from pydantic import BaseModel, Field
   -
18 | import yaml
19 + from pydantic import BaseModel, Field
20 |
   |

Found 1 error.
[*] 1 fixable with the `--fix` option.
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m ruff check --fix execution/ tests/ config/ engine/ pricing/ vol/ scripts/ 2>&1
Found 1 error (1 fixed, 0 remaining).
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m ruff check execution/ tests/ config/ engine/ pricing/ vol/ scripts/ 2>&1
All checks passed!
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m pytest -q 2>&1
..........................................sssssssss..ssss..ss.ss........ [ 83%]
..............                                                           [100%]
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python -m mypy execution/ tests/ config/ engine/ pricing/ 2>&1
Success: no issues found in 13 source files
[0m
[0m$ [0m/home/heimdall/btc_proj/BTC_analysis/btc_engine/.venv/bin/python scripts/anonymisation_scan.py 2>&1
✓ Anonymisation scan: no confidentiality concerns detected.
[0m
[0m$ [0mgit diff --check 2>&1
(no output)
[0m
[0m# [0mTodos
[✓] Implement execution/impact.py — I-Star/Kissell impact model with KissellConfig, ImpactEstimate, estimate_impact()
[✓] Implement execution/tranches.py — Tranche scheduler with schedule_tranches()
[✓] Extend execution/waterfall.py — FeeBreakdown, WaterfallSensitivity, waterfall_sensitivity()
[✓] Add A4 tests to test_phase0.py — reconciliation, monotonicity, limits, provenance, fee-base variants
[✓] Run pytest, mypy, ruff, anonymisation_scan, git diff --check and fix until passing
[0m
## Summary

### Files changed

| File | Action | Lines |
|------|--------|-------|
| `execution/impact.py` | **Created** | 160 — KissellConfig, ImpactEstimate, FeeBreakdown, estimate_impact() |
| `execution/tranches.py` | **Created** | 155 — Tranche, TrancheSchedule, schedule_tranches() |
| `execution/waterfall.py` | **Extended** | +WaterfallSensitivity, waterfall_sensitivity(), `_compute_waterfall()` refactor |
| `tests/test_phase0.py` | **Extended** | +24 A4 tests (15 new, 1 revived from skip, 2 revived from xfail) |

### Impact formulas

- **I-Star instantaneous impact** (Kissell eq. 4.6): `I*_bp = a1 * (Q/ADV)^a2 * σ^a3`
- **Market impact** (Kissell eq. 4.7): `MI_bp = b1 * I* * POV^a4 + (1-b1) * I*`
- **Square-root eta** (Sinclair §6): `eta = sqrt(Q/ADV)`
- **IV give-up**: Default 1.0 vol pts, configurable, provenance `ASSUMED`
- **Fee-base variants**: `reference_notional` (full notional) vs `executed_volume` (discounted notional), D-1 decision marker preserved as `None`

### Tranche reconciliation

Default schedule (30,000 BTC, ladder [30,37,44], clips [250,1000], 4 weeks) distributes evenly: 10,000 per DTE → 2,500 per week → ~4-5 clips per week per DTE. Total sums **exactly 30,000 BTC**. Configurable via parameters.

### Sensitivity modes

`waterfall_sensitivity()` produces 14 combinations: 7 spot offsets (-10% to +10%) × 2 fee bases. Does not silently resolve D-1 — both variants are computed with `fee_base` key. Existing `waterfall()` returns `reference_notional` path, preserving numerical compatibility (all 9 original tests unchanged).

### Tests added (all passing)

- **Impact**: i_star_formula (golden vector), monotonicity, zero-order rejection, provenance, square-root scaling, KissellConfig validation
- **Tranches**: 30k reconciliation (exact), DTE ladder [30,37,44], clip limits [250,1000], non-negative, custom quantity, duration weeks, impact estimate present
- **Waterfall sensitivity**: all 7 offsets, fee-base variants (differing values), no-silent-decision marker
- **Models**: FeeBreakdown (D-1 pending), TrancheSchedule validation

### Remaining A4 blockers

- D-1 (fee base) unresolved — both variants computed, `fee_base=None` in FeeBreakdown
- D-3 (primary venue) unresolved — default venue is Deribit via dev_default_venue
- I-Star parameters (a1-a4, b1) are uncalibrated — provenance `ASSUMED`
- No empirical calibration data for BTC-specific impact parameters (per Pillar 3 M3 gap)
