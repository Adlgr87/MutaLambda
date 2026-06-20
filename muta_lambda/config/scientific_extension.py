"""
Scientific extensions configuration (opt-in).

This module defines a typed, frozen configuration object that controls
which optional scientific evaluators/diagnostics are enabled.

Default: all extensions are OFF (graceful degradation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class EvolutionaryExtensionConfig:
    """Opt-in flags for scientific runtime extensions.

    Attributes
    ----------
    enable_numerical_health : bool
        Enables numerical_health as an optional meta-evaluator.
    enable_tipping_detection : bool
        Enables evolutionary tipping-point diagnostics.
    enable_adaptive_mutation : bool
        Enables adaptive mutation logic driven by diagnostics.
    """

    enable_numerical_health: bool = False
    enable_tipping_detection: bool = False
    enable_adaptive_mutation: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "EvolutionaryExtensionConfig":
        """Build config from a dict (e.g. loaded from YAML).

        Parameters
        ----------
        data : Dict[str, Any] | None
            Input dictionary; unknown keys are ignored.

        Returns
        -------
        EvolutionaryExtensionConfig
            Typed config with defaults (all OFF) when fields are absent.
        """
        if not data:
            return cls()

        return cls(
            enable_numerical_health=bool(data.get("enable_numerical_health", False)),
            enable_tipping_detection=bool(data.get("enable_tipping_detection", False)),
            enable_adaptive_mutation=bool(data.get("enable_adaptive_mutation", False)),
        )
