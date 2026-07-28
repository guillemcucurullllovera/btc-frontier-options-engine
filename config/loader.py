"""Configuration loader — reads config/params.yaml into a validated EngineConfig.

Pure pricing functions never read params.yaml directly; this layer injects
decimal values (AC-4, contracts.md §16.2).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from config.models import EngineConfig
from engine.errors import ConfigurationError

CFG_DEFAULT: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[1] / "config" / "params.yaml"
)


def load_validated_config(path: pathlib.Path | None = None) -> EngineConfig:
    """Return a validated EngineConfig from params.yaml.

    Raises ConfigurationError if:
      - params.yaml is malformed
      - primary_venue is None (D-3 unresolved)
      - fee_base is None (D-1 unresolved)
      - reference_spot_source is None (D-2 unresolved)
    """
    path = path or CFG_DEFAULT
    try:
        with open(path, encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"params.yaml not found at {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"YAML parse error in {path}: {exc}") from exc

    try:
        cfg = EngineConfig(**raw)
    except Exception as exc:
        raise ConfigurationError(f"EngineConfig validation failed for {path}: {exc}") from exc

    # Enforce unresolved-decision gates
    if cfg.primary_venue is None:
        raise ConfigurationError(
            "primary_venue is None — decision D-3 (primary venue selection) is unresolved. "
            "Set primary_venue in params.yaml or resolve the decision before proceeding."
        )
    if cfg.fee_base is None:
        raise ConfigurationError(
            "fee_base is None — decision D-1 (fee base: reference_notional vs executed_volume) "
            "is unresolved. Set fee_base in params.yaml or resolve the decision before proceeding."
        )
    if cfg.reference_spot_source is None:
        raise ConfigurationError(
            "reference_spot_source is None — decision D-2 (reference spot price source) "
            "is unresolved. Set reference_spot_source in params.yaml or resolve the decision "
            "before proceeding."
        )

    return cfg
