"""Backward-compatibility shim: this module has moved to mutalambda_config.muta_config.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "muta_config has moved to mutalambda_config.muta_config. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_config.muta_config import *  # noqa: F401,F403
