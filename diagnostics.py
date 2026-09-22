"""Backward-compatibility shim: this module has moved to mutalambda_security.diagnostics.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "diagnostics has moved to mutalambda_security.diagnostics. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_security.diagnostics import *  # noqa: F401,F403
