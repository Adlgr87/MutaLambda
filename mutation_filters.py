"""Backward-compatibility shim: this module has moved to mutalambda_core.mutation_filters.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "mutation_filters has moved to mutalambda_core.mutation_filters. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_core.mutation_filters import *  # noqa: F401,F403
