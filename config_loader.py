"""Backward-compatibility shim: this module has moved to mutalambda_config.config_loader.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "config_loader has moved to mutalambda_config.config_loader. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_config.config_loader import *  # noqa: F401,F403
