"""Backward-compatibility shim: this module has moved to mutalambda_security.api_fingerprint.

Existing imports keep working; new code should import from the package
directly. This shim is scheduled for removal in the next major release.
"""
import warnings

warnings.warn(
    "api_fingerprint has moved to mutalambda_security.api_fingerprint. Please update your import path.",
    DeprecationWarning,
    stacklevel=2,
)

from mutalambda_security.api_fingerprint import *  # noqa: F401,F403
