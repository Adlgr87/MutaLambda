"""Backward-compatibility shim: this module has moved to mutalambda_engines.archive.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "archive has moved to mutalambda_engines.archive. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_engines.archive import *  # noqa: F401,F403
