"""Stable hashing utilities for source code (FIX 1.1).

Single definition used by lineage, evaluation cache, and runners.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Optional


def stable_code_hash(code: str, salt: Optional[str] = None) -> str:
    """Return a stable SHA-256 hex digest of *code*.

    Args:
        code: Python source (or any UTF-8 text).
        salt: Optional salt for namespaced keys.

    Returns:
        64-character lowercase hex string.
    """
    content = code if salt is None else f"{salt}:{code}"
    return sha256(content.encode("utf-8")).hexdigest()
