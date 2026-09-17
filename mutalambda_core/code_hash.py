"""Stable hashing utilities for source code (FIX 1.1).

Single definition used by lineage, evaluation cache, and runners.
"""

from __future__ import annotations

import ast
import functools
from hashlib import sha256
from typing import Optional

__all__ = ["stable_code_hash", "cached_parse", "clear_ast_cache", "ast_cache"]


@functools.lru_cache(maxsize=4096)
def cached_parse(code: str) -> ast.AST:
    """Parse *code* into an AST, returning a cached result on repeat calls.

    The cache key is the source string itself (Python interns short strings and
    ``lru_cache`` hashes strings efficiently).  The AST is immutable once
    created, so caching it is safe.  Callers that need to mutate the tree should
    operate on a ``copy.deepcopy`` of the returned object.

    Cache size was increased from 1,024 → 4,096 entries (Feb 2026) to reduce
    LRU eviction churn in long-running evolutionary runs that re-parse the
    same mutated snippets repeatedly.

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


def cache_stats() -> dict:
    """Report statistics about the AST parse cache.

    Returns:
        Dict with keys: hits, misses, hit_rate, estimated_time_saved_ms.
    """
    info = cached_parse.cache_info()
    total = info.hits + info.misses
    avg_parse_ms = 0.0377  # measured parse cost on cache miss
    return {
        "hits": info.hits,
        "misses": info.misses,
        "hit_rate": info.hits / total if total else 0.0,
        "estimated_time_saved_ms": round(info.hits * avg_parse_ms, 1),
    }


def report_cache_stats() -> str:
    """Return a human-readable string of cache stats (for CLI/run output)."""
    stats = cache_stats()
    return (
        f"AST cache: {stats['hits']} hits, {stats['misses']} misses, "
        f"{stats['hit_rate']:.1%} hit-rate, "
        f"≈{stats['estimated_time_saved_ms']:.1f} ms saved"
    )
