"""Backward-compatibility shim: this module has moved to mutalambda_core.evolution_engine.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "evolution_engine has moved to mutalambda_core.evolution_engine. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_core.evolution_engine import *  # noqa: F401,F403
