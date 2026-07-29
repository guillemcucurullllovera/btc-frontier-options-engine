"""Research run manifest — records sources, dates, endpoints, checksums,
provenance, configuration, environment and git SHA for every research run.

Produces run_manifest.json and data_manifest.json with full traceability
per contracts.md §14, §17 and C3/C10 of Stage 3 evidence infrastructure.

Stage 3 extensions: structured provenance categories, coverage metadata,
DVOL provenance, git SHA, environment info, and gate-passing pointers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from config.models import Provenance


@dataclass
class DataSourceRecord:
    source: str
    endpoint: str
    retrieval_date: datetime
    record_count: int
    checksum_sha256: str
    provenance: Provenance
    notes: str = ""


@dataclass
class CoverageManifest:
    requested_start: datetime | None = None
    requested_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    observation_count: int = 0
    checksum_sha256: str = ""
    coverage_pct: float = 0.0
    coverage_passes: bool = True
    coverage_warning: str = ""
    source: str = ""
    provenance: str = ""


@dataclass
class DvolProvenance:
    source: str = ""
    provenance: str = ""
    fallback_used: bool = False
    fallback_provider: str = ""
    observation_count: int = 0
    checksum_sha256: str = ""
    retrieval_timestamp: datetime | None = None
    notes: str = ""


@dataclass
class DataManifest:
    actual_provider: str
    endpoint: str
    requested_start: datetime | None = None
    requested_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    observation_count: int = 0
    retrieval_timestamp: datetime | None = None
    checksum_sha256: str = ""
    provenance: str = ""
    fallback_used: bool = False
    fallback_provider: str = ""
    cache_path: str = ""
    notes: str = ""
    coverage: CoverageManifest | None = None
    spot_provenance: str = ""
    iv_provenance: DvolProvenance | None = None
    option_premium_provenance: str = ""
    fallback_provenance: str = ""
    stress_replay_provenance: str = ""
    simulation_provenance: str = ""
    business_requirements: list[str] = field(default_factory=list)


@dataclass
class ProvenanceMap:
    spot: str = ""
    iv: str = ""
    option_premium: str = ""
    fallback: str = ""
    stress_replay: str = ""
    simulation: str = ""


@dataclass
class RunManifest:
    run_id: str
    started_at: datetime
    config_path: str
    config_checksum: str
    output_dir: str
    status: str = "running"
    completed_at: datetime | None = None
    data_sources: list[DataSourceRecord] = field(default_factory=list)
    strategy_count: int = 0
    total_cycles: int = 0
    total_paths_mc: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: str = Provenance.CALCULATED.value
    git_sha: str = ""
    git_branch: str = ""
    environment: str = ""
    requested_coverage: tuple[str, str] = ("", "")
    actual_coverage: tuple[str, str] = ("", "")
    coverage_checksum: str = ""
    dvol_provenance: DvolProvenance | None = None
    provenance_map: ProvenanceMap | None = None
    input_checksums: dict[str, str] = field(default_factory=dict)
    output_checksums: dict[str, str] = field(default_factory=dict)
    validation_status: str = "pending"
    unresolved_decisions: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)
    run_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            d["completed_at"] = self.completed_at.isoformat()
        if self.dvol_provenance:
            d["dvol_provenance"] = asdict(self.dvol_provenance)
        if self.provenance_map:
            d["provenance_map"] = asdict(self.provenance_map)
        return d


def resolve_git_sha() -> str:
    import subprocess
    import sys
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True,
            cwd=str(sys.path[-1]) if sys.path else ".",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def resolve_git_branch() -> str:
    import subprocess
    import sys
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
            cwd=str(sys.path[-1]) if sys.path else ".",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def resolve_environment() -> str:
    import os
    import platform
    import sys
    return f"python={sys.version.split()[0]};platform={platform.system()};hostname={os.uname().nodename}"
