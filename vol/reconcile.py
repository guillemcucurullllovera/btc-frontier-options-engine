"""Q-vs-P reconciliation of the SV dynamics and the jump component (C9 · M4.5).

SIMULATED / diagnostic; MS-26-gated; canonical main untouched. Contrasts the risk-neutral (Q)
calibration (M2 Heston / M3 Bates) with the physical-measure (P) estimation (M4 UKF/GARCH SV + M4.3
realized jumps), and records the model-risk resolution:

  * SV level: the Q-calibrated long-run vol (from theta) vs the P-filtered vol are compared and
    expected to be broadly consistent (a Q vol-risk-premium can leave Q modestly above P).
  * JUMPS: the M3 Bates Q-jumps are DEGENERATE (unidentified) and must NOT be used as jump risk; the
    P-identified realized jumps (downward-asymmetric, moderate intensity) are the tail-jump source.

This is the concrete resolution of the M3 finding: Heston is the identified Q-core; the tail jumps
come from physical estimation, not the Q-calibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vol.jumps import JumpIdentifiability, JumpParams, flag_jump_degeneracy


@dataclass(frozen=True)
class QvsPReconciliation:
    q_vol_level: float               # annualised, from Q theta: sqrt(theta)
    p_vol_level: float               # annualised, P-filtered/estimated
    vol_ratio_q_over_p: float
    vol_consistent: bool             # within a plausible vol-risk-premium band
    q_jump: JumpIdentifiability       # Q Bates-jump identifiability (M3)
    p_jump: JumpParams                # P realized-jump params (M4.3)
    tail_jump_source: str            # which jump component feeds the tail
    notes: list[str]


def reconcile_q_vs_p(
    q_theta: float, p_vol_annual: float, q_bates_lam: float, q_bates_sigma_j: float,
    p_jumps: JumpParams, q_lam_ub: float = 20.0, vol_band: float = 0.5,
) -> QvsPReconciliation:
    """Compare Q vs P SV levels and Q-degenerate vs P-identified jumps; pick the tail-jump source.

    ``vol_band`` is the tolerated relative gap between the Q and P vol levels (a Q vol-risk premium
    plus estimation error). Returns a structured reconciliation with an explicit tail-jump source.
    """
    q_vol = math.sqrt(max(q_theta, 0.0))
    ratio = q_vol / p_vol_annual if p_vol_annual > 0 else math.inf
    vol_consistent = abs(ratio - 1.0) <= vol_band
    q_jump = flag_jump_degeneracy(q_bates_lam, q_bates_sigma_j, lam_ub=q_lam_ub)

    notes: list[str] = []
    if q_jump.degenerate:
        notes.append(f"Q Bates jumps DEGENERATE ({q_jump.reason}) -> not used as jump risk.")
    p_identified = p_jumps.n_jumps >= 1 and math.isfinite(p_jumps.jump_mean)
    if p_identified:
        asym = "downward-asymmetric" if p_jumps.frac_downward >= 0.5 else "symmetric/upward"
        notes.append(
            f"P realized jumps identified: lambda~{p_jumps.lam_annual:.1f}/yr, mean {p_jumps.jump_mean:+.3f}, "
            f"{p_jumps.frac_downward:.0%} down ({asym}).")
    tail_source = "P-identified realized jumps" if (q_jump.degenerate and p_identified) else (
        "Q Bates jumps" if not q_jump.degenerate else "none (no identified jumps)")
    notes.append(f"Tail-jump source := {tail_source}.")
    if vol_consistent:
        notes.append(f"SV level consistent (Q vol {q_vol:.2f} vs P vol {p_vol_annual:.2f}, ratio {ratio:.2f}).")
    else:
        notes.append(f"SV level gap (Q vol {q_vol:.2f} vs P vol {p_vol_annual:.2f}, ratio {ratio:.2f}) — vol-risk premium / small-sample.")

    return QvsPReconciliation(
        q_vol_level=q_vol, p_vol_level=p_vol_annual, vol_ratio_q_over_p=ratio,
        vol_consistent=vol_consistent, q_jump=q_jump, p_jump=p_jumps,
        tail_jump_source=tail_source, notes=notes,
    )
