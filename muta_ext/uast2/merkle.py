#!/usr/bin/env python3
"""Incremental (Merkle) hashing for UAST v2 (playbook phase 2).

The legacy engine recomputes ``canonical_hash()`` by re-serialising the *whole*
tree to JSON on every call (O(n) allocations, ~ms for large files).  UAST v2
caches a digest per node and only recomputes the path from an edited node up to
the root:

* ``invalidate_up(node)`` — called automatically by ``replace()``/``set_child()``
  and by the ``NodeTransformer``; marks ancestors dirty in O(depth).
* ``node_digest(node)`` — post-order, iterative (no recursion limits) and
  memoised, so exactly the dirty sub-path is recomputed.
* ``root_digest(uast)`` — digest over ``body``, i.e. the document identity.

The digest deliberately ignores parent pointers, arena ids and locations, so a
tree and its copy produce the same digest — the property the tests rely on.
"""

from __future__ import annotations

import hashlib
import typing as T
from typing import Any, Dict, Optional

from muta_ext.uast2.core import (
    KIND_NODE,
    KIND_NODE_DICT,
    KIND_NODE_LIST,
    UASTNode,
    CoreUAST,
    child_kinds,
    walk,
)

__all__ = [
    "node_digest",
    "child_kind",
    "invalidate_up",
    "invalidate_subtree",
    "begin_touch",
    "end_touch",
    "root_digest",
    "structure_digest",
    "recompute_all",
    "hash_stats",
    "reset_hash_stats",
]

_SEP = b"\x1f"  # field separator
_LIST_OPEN = b"["
_LIST_CLOSE = b"]"
_MAP_OPEN = b"{"
_MAP_CLOSE = b"}"
_NODE = b"("
_END = b")"
_EMPTY = b"\x1e"  # marker for "absent" values so () and (None) differ
_EQ = b"="
_COLON = b":"
_LIST_ITEM = _SEP

_STATS: Dict[str, int] = {"computed": 0, "cache_hits": 0, "invalidations": 0}

#: Active touch log (see ``begin_touch``); ``None`` when disabled.
_TOUCHED: Optional[T.List[UASTNode]] = None


#: ``((field, kind), ...)`` per node class — the hot path must not build generators.
_PLANS: Dict[type, T.Tuple[T.Tuple[str, str], ...]] = {}
_TYPE_BYTES: Dict[type, bytes] = {}
_FIELD_BYTES: Dict[str, bytes] = {}


def _plan(node_type: type) -> T.Tuple[T.Tuple[str, str], ...]:
    """Cached ``((field, kind), ...)`` plan (``kind`` is ``""`` for scalars)."""
    plan = _PLANS.get(node_type)
    if plan is None:
        kinds = child_kinds(node_type)
        plan = _PLANS[node_type] = tuple(
            (name, kinds.get(name, "")) for name in node_type._fields
        )
    return plan


def child_kind(node_type: type, field: str) -> str:
    """Kind of one field ("", "node", "node_list" or "node_dict")."""
    for name, kind in _plan(node_type):
        if name == field:
            return kind
    return ""


def node_digest(node: UASTNode) -> bytes:
    """Return the cached Merkle digest of *node*, computing only dirty paths.

    Fast path: if *node* is dirty, recompute bottom-up over its subtree in a
    single traversal (children before parents — pre-order reversed), skipping
    every node whose cached digest is still valid.  This keeps the incremental
    property (only invalidated nodes are re-hashed) without paying for a
    per-node child scan.
    """
    cached = node._hash
    if cached is not None:
        _STATS["cache_hits"] += 1
        return cached

    subtree = list(walk(node))
    if len(subtree) > 1:
        for current in reversed(subtree):
            if current._hash is None:
                current._hash = _compute_digest(current)
                _STATS["computed"] += 1
        return node._hash  # type: ignore[return-value]

    stack: T.List[UASTNode] = [node]
    kind_node = KIND_NODE
    kind_list = KIND_NODE_LIST
    kind_dict = KIND_NODE_DICT
    while stack:
        current = stack[-1]
        if current._hash is not None:
            stack.pop()
            continue
        pending = False
        for name, kind in _plan(type(current)):
            if kind is kind_node:
                value = getattr(current, name)
                if value is not None and value._hash is None:
                    stack.append(value)
                    pending = True
            elif kind is kind_list:
                value = getattr(current, name)
                if value is None:
                    continue
                if type(value) is list:
                    for item in value:
                        if item._hash is None:
                            stack.append(item)
                            pending = True
                elif value._hash is None:
                    stack.append(value)
                    pending = True
            elif kind is kind_dict:
                value = getattr(current, name)
                if value:
                    for item in value.values():
                        if item._hash is None:
                            stack.append(item)
                            pending = True
        if pending:
            continue
        current._hash = _compute_digest(current)
        _STATS["computed"] += 1
        stack.pop()
    assert node._hash is not None
    return node._hash


def _compute_digest(node: UASTNode) -> bytes:
    """Digest of a node *assuming* every child digest is already cached."""
    node_type = type(node)
    type_bytes = _TYPE_BYTES.get(node_type)
    if type_bytes is None:
        type_bytes = _TYPE_BYTES[node_type] = node_type.__name__.encode("utf-8", "replace")
    payload = bytearray(type_bytes)
    encode = _encode_value
    for field_name in node_type._fields:
        payload += _SEP
        field_bytes = _FIELD_BYTES.get(field_name)
        if field_bytes is None:
            field_bytes = _FIELD_BYTES[field_name] = field_name.encode("utf-8", "replace")
        payload += field_bytes
        payload += _EQ
        payload += encode(getattr(node, field_name))
    return hashlib.sha256(payload).digest()


def _encode_value(value: Any) -> bytes:
    """Encode a field value (child digest, primitive, list or mapping)."""
    value_type = type(value)
    if value_type is str or value_type is int or value_type is float or value_type is bool:
        return repr(value).encode("utf-8", "replace")
    if value is None:
        return _EMPTY
    if value_type is bytes:
        return value
    if value_type is list or value_type is tuple:
        parts = bytearray(_LIST_OPEN)
        for item in value:
            parts += _encode_value(item)
            parts += _SEP
        parts += _LIST_CLOSE
        return bytes(parts)
    if value_type is dict:
        parts = bytearray(_MAP_OPEN)
        encode = _encode_value
        for key in sorted(value, key=lambda item: repr(item)):
            parts += encode(key)
            parts += _COLON
            parts += encode(value[key])
            parts += _SEP
        parts += _MAP_CLOSE
        return bytes(parts)
    digest = value._hash
    if digest is not None:
        return digest
    if isinstance(value, UASTNode):  # pragma: no cover - defensive (post-order)
        return node_digest(value)
    return repr(value).encode("utf-8", "replace")


def invalidate_up(node: Optional[UASTNode], record: bool = True) -> int:
    """Invalidate the digest of *node* and its ancestors.  Returns nodes touched.

    While a touch log is active (:func:`begin_touch`) the *topmost* invalidated
    node is recorded, which gives the pipeline a minimal scope for post-pass
    verification ("verify only what the nanopass could have changed").  Pass
    ``record=False`` for *conservative* invalidations (e.g. the transformer's
    "a handler may have mutated in place" safety net) — they keep the digests
    honest without pretending the pass changed that node.
    """
    touched = 0
    current = node
    topmost: Optional[UASTNode] = node
    while current is not None and current._hash is not None:
        current._hash = None
        touched += 1
        topmost = current
        current = current._parent
    if touched == 0 and node is not None:
        # Fresh node (no cached digest): its parent chain may still be dirty.
        parent = node._parent
        while parent is not None and parent._hash is not None:
            parent._hash = None
            touched += 1
            topmost = parent
            parent = parent._parent
    if record and _TOUCHED is not None and topmost is not None:
        _TOUCHED.append(topmost)
    _STATS["invalidations"] += touched
    return touched


def begin_touch() -> List[UASTNode]:
    """Start recording the topmost node of every invalidation (see pipeline)."""
    global _TOUCHED
    _TOUCHED = []
    return _TOUCHED


def end_touch() -> List[UASTNode]:
    """Stop recording and return the touched scopes (topmost node per mutation)."""
    global _TOUCHED
    touched = _TOUCHED or []
    _TOUCHED = None
    return touched


def invalidate_subtree(node: Optional[UASTNode]) -> int:
    """Invalidate a whole subtree (used when a node's fields are set directly)."""
    if node is None:
        return 0
    touched = 0
    for current in walk(node):
        if current._hash is not None:
            current._hash = None
            touched += 1
    _STATS["invalidations"] += touched
    return touched


def fold_digest(values: T.Iterable[Any]) -> bytes:
    """Digest over an ordered sequence of nodes/values (document identity)."""
    digest = hashlib.sha256()
    for value in values:
        digest.update(_encode_value(value))
        digest.update(_SEP)
    return digest.digest()


def root_digest(uast: Any) -> str:
    """Hex digest of a ``CoreUAST`` (or node/list) using the Merkle cache."""
    if isinstance(uast, CoreUAST):
        return fold_digest(uast.body).hex()
    if isinstance(uast, (list, tuple)):
        return fold_digest(uast).hex()
    return node_digest(uast).hex()


#: Alias kept for symmetry with ``CoreUAST.canonical_hash``.
structure_digest = root_digest


def recompute_all(uast: Any) -> str:
    """Invalidate everything and recompute from scratch (debug/benchmark helper)."""
    nodes = list(uast.walk()) if isinstance(uast, CoreUAST) else list(walk(uast))
    for node in nodes:
        node._hash = None
    for node in reversed(nodes):  # children before parents (pre-order reversed)
        node._hash = _compute_digest(node)
        _STATS["computed"] += 1
    return root_digest(uast)


def hash_stats() -> Dict[str, int]:
    """Hashing counters (computed digests, cache hits, invalidations)."""
    return dict(_STATS)


def reset_hash_stats() -> None:
    """Reset the hashing counters."""
    for key in _STATS:
        _STATS[key] = 0
