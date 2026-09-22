"""Backward-compatibility shim: this module has moved to mutalambda_engines.nsga2.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "nsga2 has moved to mutalambda_engines.nsga2. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_engines.nsga2 import *  # noqa: F401,F403
