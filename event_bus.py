"""Backward-compatibility shim: this module has moved to mutalambda_core.event_bus.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "event_bus has moved to mutalambda_core.event_bus. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_core.event_bus import *  # noqa: F401,F403
