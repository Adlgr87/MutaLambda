"""Backward-compatibility shim: this module has moved to mutalambda_config.checkpoint_manager.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "checkpoint_manager has moved to mutalambda_config.checkpoint_manager. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_config.checkpoint_manager import *  # noqa: F401,F403
