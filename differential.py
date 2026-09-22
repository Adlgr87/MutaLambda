"""Backward-compatibility shim: this module has moved to mutalambda_core.differential.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "differential has moved to mutalambda_core.differential. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_core.differential import *  # noqa: F401,F403
