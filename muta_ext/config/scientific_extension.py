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

    Default: all features disabled (graceful degradation).
    Only safe, supported extensions should be enabled.

    Attributes
    ----------
    enable_numerical_health : bool
        Enables numerical health analysis (static).
    enable_tipping_detection : bool
        Enables tipping detection (local metadata/events).
    enable_adaptive_solver : bool
        Enables adaptive-solver-inspired meta-evaluation (safe numpy).
    """

    enable_numerical_health: bool = False
    enable_tipping_detection: bool = False
    enable_adaptive_solver: bool = False

    @classmethod
    def from_dict(
        cls, d: Dict[str, Any] | None
    ) -> "EvolutionaryExtensionConfig":
        """Build config from a dict (e.g. loaded from YAML).

        Unknown keys are ignored. If the dict is absent, returns all flags OFF.

        Graceful degradation
        ----------------------
        If the expected keys are missing, all extensions remain disabled.
        """
        if not d:
            return cls()

        # Backward/forward compatibility aliases
        enable_adaptive_mutation = bool(
            d.get("enable_adaptive_mutation", False)
        )

        enable_adaptive_solver = bool(
            d.get("enable_adaptive_solver", enable_adaptive_mutation)
        )

        return cls(
            enable_numerical_health=bool(d.get("enable_numerical_health", False)),
            enable_tipping_detection=bool(d.get("enable_tipping_detection", False)),
            enable_adaptive_solver=enable_adaptive_solver,
        )
