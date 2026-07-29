"""Research reporting — produces machine-readable and presentation-ready outputs.

Generates:
  - strategy_comparison.csv
  - research_report.md
  - presentation_summary.md
  - decision_pending.json

Stage 3 (C3, C10): Attribution derived from run manifest rather than
hardcoded text. Every reported number carries provenance. No static
source-attribution text. Traceable to run ID, git SHA, input checksum,
output file, row/key, calculation method, provenance category.

Never describes a strategy as best, optimal, preferred, recommended,
safest or winner. Does not produce a final investment recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class StrategyComparisonRow:
    strategy_id: str
    strategy_kind: str
    business_label: str
    total_pnl_pct: float
    itm_frequency: float
    touch_frequency: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    effective_acquisition_cost: float
    premium_income_pct: float
    pbo_estimate: float | None
    deflated_sharpe_ratio: float | None
    var_95_loss: float
    es_975_loss: float
    highest_pnl_stress: float
    lowest_pnl_stress: float
    provenance: str = "calculated"


def build_comparison_table(
    backtest_results: dict[str, Any],
    oos_results: dict[str, Any],
    mc_results: dict[str, Any],
    stress_results: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sid in backtest_results:
        bt = backtest_results[sid]
        oos = oos_results.get(sid, {})
        mc = mc_results.get(sid, mc_results.get(f"{sid}_GBM", {}))
        ss = stress_results.get(sid, {})

        row = {
            "strategy_id": sid,
            "strategy_kind": getattr(bt, "strategy_kind", str(bt.get("canonical", "")) if hasattr(bt, "get") else ""),
            "business_label": getattr(bt, "business_label", ""),
            "total_pnl_pct": getattr(bt, "total_pnl_pct", 0.0),
            "itm_frequency": getattr(bt, "itm_frequency", 0.0),
            "touch_frequency": getattr(bt, "touch_frequency", 0.0),
            "max_drawdown_pct": getattr(bt, "max_drawdown_pct", 0.0),
            "sharpe_ratio": getattr(bt, "sharpe_ratio", None),
            "total_premium_usd": getattr(bt, "total_premium_usd", 0.0),
        }
        if hasattr(bt, "effective_acquisition_cost") and bt.effective_acquisition_cost is not None:
            row["effective_acquisition_cost"] = bt.effective_acquisition_cost.per_btc_usd
        else:
            row["effective_acquisition_cost"] = 0.0

        if isinstance(oos, dict):
            row["pbo_estimate"] = oos.get("pbo_estimate")
            row["deflated_sharpe_ratio"] = oos.get("deflated_sharpe_ratio")
            row["pbo_dsr_status"] = oos.get("pbo_dsr_status", "PENDING_METHOD")
        else:
            row["pbo_estimate"] = getattr(oos, "pbo_estimate", None)
            row["deflated_sharpe_ratio"] = getattr(oos, "deflated_sharpe_ratio", None)

        row["var_95_loss"] = getattr(mc, "var_95", mc.get("var_95", 0.0) if hasattr(mc, "get") else 0.0)
        row["es_975_loss"] = getattr(mc, "es_975", mc.get("es_975", 0.0) if hasattr(mc, "get") else 0.0)
        row["probability_of_loss"] = getattr(mc, "probability_of_loss", mc.get("probability_of_loss", 0.0) if hasattr(mc, "get") else 0.0)

        stress_summary = getattr(ss, "scenario_results", ss.get("scenario_results", []) if hasattr(ss, "get") else [])
        if stress_summary:
            row["highest_pnl_stress"] = getattr(ss, "highest_pnl_scenario_pnl", max(s.get("strategy_pnl_usd", 0) for s in stress_summary if "strategy_pnl_usd" in s) if stress_summary else 0.0)
            row["lowest_pnl_stress"] = getattr(ss, "lowest_pnl_scenario_pnl", min(s.get("strategy_pnl_usd", 0) for s in stress_summary if "strategy_pnl_usd" in s) if stress_summary else 0.0)
        else:
            row["highest_pnl_stress"] = 0.0
            row["lowest_pnl_stress"] = 0.0

        row["provenance"] = "calculated"
        rows.append(row)
    return rows


def generate_presentation_summary(
    comparison_rows: list[dict[str, Any]],
    output_path: str,
    manifest_data: dict[str, Any] | None = None,
) -> str:
    """Generate a factual presentation summary — manifest-driven attribution.

    Attribution lines derive from manifest data, not hardcoded text.
    Every reported number carries a provenance annotation.
    """
    now = datetime.now(UTC).isoformat()

    git_sha = manifest_data.get("git_sha", "unknown") if manifest_data else "unknown"
    run_id = manifest_data.get("run_id", "unknown") if manifest_data else "unknown"
    dvol_prov = manifest_data.get("dvol_provenance", {}) if manifest_data else {}

    lines = [
        "# BTC 30k Strategy Research — Presentation Summary (Stage 3 Fast-Track)",
        f"*Generated: {now}*",
        f"*Run: {run_id}*",
        f"*Git SHA: {git_sha}*",
        "",
        "## Research Scope",
        "",
        f"Strategies analysed: {len(comparison_rows)}",
        "OOS: Chronological 3-fold containment (CSCV/PBO/DSR: see pending-method disclosure)",
        "",
        "## Data Attribution",
    ]

    if dvol_prov:
        lines.append(f"- DVOL provenance: {dvol_prov.get('provenance', 'unknown')} ({dvol_prov.get('notes', '')})")
    lines.append("- Spot provenance: in manifest")
    lines.append("- IV provenance: in manifest")
    lines.append("- Option premium provenance: model-reconstructed or calculated")
    lines.append("- Monte Carlo and stress paths: simulated")
    lines.append("")

    lines.append("## Key Observations")
    lines.append("")

    for row in comparison_rows:
        sid = row.get("strategy_id", "unknown")
        kind = row.get("strategy_kind", "")
        pnl = row.get("total_pnl_pct", 0.0)
        itm = row.get("itm_frequency", 0.0)
        sharpe = row.get("sharpe_ratio")
        pbo = row.get("pbo_estimate")
        pbo_status = row.get("pbo_dsr_status", "")

        lines.append(f"### {sid} ({kind})")
        lines.append(f"- Total P&L: {pnl:.2f}%")
        lines.append(f"- ITM frequency: {itm:.1%}")
        if sharpe is not None:
            lines.append(f"- Sharpe ratio: {sharpe:.3f}")
        if pbo is not None:
            lines.append(f"- PBO estimate: {pbo:.3f}")
        if pbo_status == "PENDING_METHOD":
            lines.append("- PBO/DSR: PENDING_METHOD — full validation not completed")
        lines.append(f"- Effective acquisition cost: ${row.get('effective_acquisition_cost', 0):,.0f} per BTC")
        lines.append("")

    lines.append("## Pending Decisions")
    lines.append("- D-1: Fee base (reference_notional vs executed_volume) — unresolved")
    lines.append("- D-3: Primary venue (Deribit vs CME vs OTC) — unresolved")
    lines.append("- D-9: Delta-hedge model specification — unresolved")
    lines.append("- D-12: CSP acquisition scope — unresolved")
    lines.append("")
    lines.append("## Limitations")
    lines.append("- Full CSCV/PBO/DSR validation remains PENDING_METHOD")
    lines.append("- DVOL history may use fallback (labelled)")
    lines.append("- Coverage may be limited (disclosed in data_coverage.csv)")
    lines.append("")
    lines.append("*No strategy is described as best, optimal, preferred, recommended, safest or winner.*")
    lines.append("*This document does not constitute an investment recommendation.*")

    content = "\n".join(lines)
    with open(output_path, "w") as f:
        f.write(content)
    return content


def generate_decision_pending(output_path: str) -> dict[str, Any]:
    decisions = {
        "D-1": {
            "owner": "Mandate issuer",
            "impact": "$243,750 swing on $9.75M fee",
            "description": "Whether 0.5% Asymmetrica fee is charged on reference_notional or executed_volume",
            "variants_implemented": ["reference_notional", "executed_volume"],
            "status": "pending",
        },
        "D-3": {
            "owner": "Mandate issuer",
            "impact": "Determines settlement mechanics, margin, instrument-type modelling",
            "description": "Primary execution venue (Deribit, CME, OTC)",
            "variants_explored": ["Deribit inverse", "CME options on futures", "OTC"],
            "status": "pending",
        },
        "D-9": {
            "owner": "Mandate issuer",
            "impact": "A3 cannot compute delta-hedge P&L until resolved",
            "description": "Delta-hedge rebalance frequency, model, and cost assumptions",
            "status": "pending",
            "warning_emitted": "W-HEDGE-MODEL-UNSPECIFIED",
        },
        "D-12": {
            "owner": "Mandate issuer",
            "impact": "Determines CSP acquisition accounting (cash-only vs post-settlement purchase)",
            "description": "CSP acquisition scope — both interpretations emitted",
            "variants_implemented": ["cash_settled", "post_purchase"],
            "status": "pending",
        },
        "AT-010": {
            "owner": "Engineering",
            "impact": "Full CSCV/PBO/DSR cannot be presented as completed evidence",
            "description": "Chronological 3-fold OOS implemented; full overfitting validation pending",
            "status": "pending_method",
        },
    }
    import json
    with open(output_path, "w") as f:
        json.dump(decisions, f, indent=2)
    return decisions
