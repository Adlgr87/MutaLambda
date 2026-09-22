"""Backward-compatibility shim: this module has moved to mutalambda_engines.hfc_tiers.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "hfc_tiers has moved to mutalambda_engines.hfc_tiers. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_engines.hfc_tiers import *  # noqa: F401,F403
