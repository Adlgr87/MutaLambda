"""Backward-compatibility shim: this module has moved to mutalambda_engines.fitness_vector.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "fitness_vector has moved to mutalambda_engines.fitness_vector. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_engines.fitness_vector import *  # noqa: F401,F403
