"""Engine error hierarchy — frozen per contracts.md §15.1."""

from __future__ import annotations


class EngineError(Exception):
    """Base for all engine errors."""


class ConfigurationError(EngineError):
    """Malformed params.yaml or unresolved pending decision."""


class ValidationError(EngineError):
    """Invariant violation."""


class PricingError(EngineError):
    """Root-finding failure, NaN in numerical output."""


class DataError(EngineError):
    """Missing or corrupt market data."""


class VenueError(EngineError):
    """Unsupported settlement path."""


class SettlementError(EngineError):
    """Unsupported SettlementMechanism x Venue combination."""


class ClassificationError(EngineError):
    """Cannot derive StrategyKind from legs."""


class ProvenanceError(EngineError):
    """Simulated or model-reconstructed value presented as observed."""


class SensitivityError(EngineError):
    """Sensitivity analysis parameter out of range."""


class ReportingError(EngineError):
    """Chart generation failure."""
