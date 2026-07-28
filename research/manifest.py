"""Research run manifest — records sources, dates, endpoints, checksums, provenance and configuration.

Produces run_manifest.json for each research run with full traceability.
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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            d["completed_at"] = self.completed_at.isoformat()
        return d
