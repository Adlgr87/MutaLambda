"""🔴 DEPRECATED: This module has been moved to mutalambda_security.diagnostics.
FIX #43: Package reorganization. This shim maintains backward compatibility.
Import from the new location instead. Will be removed in next major version.
"""
import warnings
warnings.warn(
    f"This module has been moved to mutalambda_security.diagnostics. "
    "Please update your import path.",
    DeprecationWarning,
    stacklevel=2
)

from mutalambda_security.diagnostics import *  # noqa: F401,F403
