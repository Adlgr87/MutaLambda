"""Backward-compatibility shim: this module has moved to mutalambda_core.island_evolution.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "island_evolution has moved to mutalambda_core.island_evolution. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_core.island_evolution import *  # noqa: F401,F403
