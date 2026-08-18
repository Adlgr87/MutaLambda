"""Stable hashing utilities for source code (FIX 1.1).

Single definition used by lineage, evaluation cache, and runners.
"""

from __future__ import annotations

import ast
import functools
from hashlib import sha256
from typing import Optional

__all__ = ["stable_code_hash", "cached_parse", "clear_ast_cache", "ast_cache"]


@functools.lru_cache(maxsize=1024)
def cached_parse(code: str) -> ast.AST:
    """Parse *code* into an AST, returning a cached result on repeat calls.

    The cache key is the source string itself (Python interns short strings and
    ``lru_cache`` hashes strings efficiently).  The AST is immutable once
    created, so caching it is safe.  Callers that need to mutate the tree should
    operate on a ``copy.deepcopy`` of the returned object.

    Args:
        code: Python source text.

    Returns:
        The parsed ``ast.AST`` tree.
    """
    return ast.parse(code)


def clear_ast_cache() -> None:
    """Clear the AST parse cache.

    Safe to call between independent runs or when memory pressure is high.
    """
    cached_parse.cache_clear()


# Backwards-compatible handle to the LRU-wrapped function for introspection.
ast_cache = cached_parse


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
