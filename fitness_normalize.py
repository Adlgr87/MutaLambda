"""Backward-compatibility shim: this module has moved to mutalambda_engines.fitness_normalize.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "fitness_normalize has moved to mutalambda_engines.fitness_normalize. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_engines.fitness_normalize import *  # noqa: F401,F403
