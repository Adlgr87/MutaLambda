#!/usr/bin/env python3
"""Bidirectional converter legacy ``muta_ext.uast.core_uast`` ⇄ UAST v2.

This is the keystone of the parallel-engine strategy: adapters, emitters,
mutators, validators and the CLI keep using the frozen legacy types, while v2
consumers get mutable nodes — and trees can travel back and forth losslessly.

Guarantees exercised by ``tests/uast2/test_convert.py``:

* ``v2_to_legacy(legacy_to_v2(x)) == x`` field-by-field for every legacy node
  type, including ``tag`` and ``location``.
* ``legacy_to_v2(v2_to_legacy(y))`` reproduces the same *structure* for v2 trees
  (equal ``canonical_hash`` / ``merkle_hash``).
* Unknown legacy node types raise :class:`ConversionError` instead of silently
  dropping data (pass ``on_unknown="opaque"`` to degrade gracefully).

Conversions are iterative (explicit worklist) so very deep expressions — e.g.
generated corpora with thousands of chained operators — cannot hit Python's
recursion limit.
"""

from __future__ import annotations

import typing as T
from typing import Any, Dict, List, Optional

from muta_ext.uast import core_uast as legacy
from muta_ext.uast2 import core as v2

__all__ = [
    "ConversionError",
    "legacy_to_v2",
    "v2_to_legacy",
    "to_v2",
    "to_legacy",
    "legacy_document_to_v2",
    "v2_document_to_legacy",
    "is_legacy_node",
    "is_v2_node",
]

#: Legacy field names that map onto node slots instead of fields.
_LEGACY_SLOT_FIELDS = ("tag", "location")


class ConversionError(TypeError):
    """Raised when a value cannot be converted between the two engines."""


def is_v2_node(value: Any) -> bool:
    """True when *value* is a UAST v2 node."""
    return isinstance(value, v2.UASTNode)


def is_legacy_node(value: Any) -> bool:
    """True when *value* is a legacy (frozen dataclass) node."""
    return (
        hasattr(value, "__dataclass_fields__")
        and not isinstance(value, v2.UASTNode)
        and not hasattr(value, "canonical_hash")
    )


# ── legacy → v2 ──────────────────────────────────────────────────────────────


def legacy_to_v2(value: Any, on_unknown: str = "raise") -> Any:
    """Convert a legacy node/subtree/document into v2 objects.

    Args:
        value: legacy node, list, dict, primitive or ``legacy.CoreUAST``.
        on_unknown: ``"raise"`` (default) or ``"opaque"`` to wrap unknown legacy
            node classes in :class:`v2.Opaque` instead of failing.
    """
    if isinstance(value, legacy.CoreUAST):
        return legacy_document_to_v2(value, on_unknown=on_unknown)
    if isinstance(value, v2.CoreUAST):
        return value
    if isinstance(value, v2.UASTNode) or value is None:
        return value
    if type(value) in (str, int, float, bool, bytes):
        return value
    if isinstance(value, (list, tuple)):
        return [legacy_to_v2(item, on_unknown) for item in value]
    if isinstance(value, dict):
        return {key: legacy_to_v2(item, on_unknown) for key, item in value.items()}
    if is_legacy_node(value):
        return _legacy_node_to_v2(value, on_unknown)
    return value  # opaque primitive (e.g. numpy scalar) — passthrough


def _legacy_node_to_v2(legacy_node: Any, on_unknown: str) -> v2.UASTNode:
    """Iteratively convert a legacy node subtree into v2 nodes."""
    root = _shallow_legacy_to_v2(legacy_node, on_unknown)
    stack: List[T.Tuple[Any, v2.UASTNode]] = [(legacy_node, root)]
    while stack:
        source, target = stack.pop()
        for field_name in target._fields:
            value = getattr(source, field_name, None)
            value_type = type(value)
            if value is None or value_type in (str, int, float, bool, bytes):
                continue  # already copied by the shallow step
            if value_type is list or value_type is tuple:
                new_items: List[Any] = []
                for item in value:
                    if is_legacy_node(item):
                        child = _shallow_legacy_to_v2(item, on_unknown)
                        child._parent = target
                        child._slot = (field_name, len(new_items))
                        stack.append((item, child))
                        new_items.append(child)
                    else:
                        new_items.append(legacy_to_v2(item, on_unknown))
                setattr(target, field_name, new_items)
            elif value_type is dict:
                new_mapping: Dict[Any, Any] = {}
                for key, item in value.items():
                    if is_legacy_node(item):
                        child = _shallow_legacy_to_v2(item, on_unknown)
                        child._parent = target
                        child._slot = (field_name, key)
                        stack.append((item, child))
                        new_mapping[key] = child
                    else:
                        new_mapping[key] = legacy_to_v2(item, on_unknown)
                setattr(target, field_name, new_mapping)
            elif is_legacy_node(value):
                child = _shallow_legacy_to_v2(value, on_unknown)
                child._parent = target
                child._slot = field_name
                stack.append((value, child))
                setattr(target, field_name, child)
            else:
                setattr(target, field_name, legacy_to_v2(value, on_unknown))
    return root


def _shallow_legacy_to_v2(legacy_node: Any, on_unknown: str) -> v2.UASTNode:
    """Create the v2 counterpart of *legacy_node* (children copied verbatim)."""
    type_name = type(legacy_node).__name__
    node_cls = v2.NODE_REGISTRY.get(type_name)
    if node_cls is None:
        if on_unknown == "opaque":
            return v2.Opaque(original_text=repr(legacy_node), lang="unknown")
        raise ConversionError(
            f"Unsupported legacy node type {type_name!r}: no UAST v2 counterpart. "
            "Pass on_unknown='opaque' to degrade to an Opaque node."
        )
    kwargs: Dict[str, Any] = {}
    for field_name in node_cls._fields:
        kwargs[field_name] = getattr(legacy_node, field_name, None)
    location = getattr(legacy_node, "location", None)
    if location:
        kwargs["lineno"] = location.get("line")
        kwargs["col_offset"] = location.get("col")
        kwargs["end_lineno"] = location.get("end_line")
        kwargs["end_col_offset"] = location.get("end_col")
    return node_cls(tag=getattr(legacy_node, "tag", None), **kwargs)


def legacy_document_to_v2(legacy_uast: Any, on_unknown: str = "raise") -> v2.CoreUAST:
    """Convert a whole legacy ``CoreUAST`` document into a v2 document."""
    body = [legacy_to_v2(node, on_unknown) for node in legacy_uast.body]
    return v2.CoreUAST(
        body=body,
        language=getattr(legacy_uast, "language", "python"),
        metadata=legacy_to_v2(dict(getattr(legacy_uast, "metadata", {}) or {}), on_unknown),
        engine="v2",
    )


# ── v2 → legacy ──────────────────────────────────────────────────────────────


def v2_to_legacy(value: Any) -> Any:
    """Convert v2 nodes/subtrees/documents back into legacy objects."""
    if isinstance(value, v2.CoreUAST):
        return v2_document_to_legacy(value)
    if isinstance(value, legacy.CoreUAST) or value is None:
        return value
    if type(value) in (str, int, float, bool, bytes):
        return value
    if isinstance(value, (list, tuple)):
        return [v2_to_legacy(item) for item in value]
    if isinstance(value, dict):
        return {key: v2_to_legacy(item) for key, item in value.items()}
    if isinstance(value, v2.UASTNode):
        return _v2_node_to_legacy(value)
    return value


def _v2_node_to_legacy(v2_node: v2.UASTNode) -> Any:
    """Iteratively convert a v2 subtree into legacy frozen dataclasses."""
    root = _shallow_v2_to_legacy(v2_node)
    stack: List[T.Tuple[v2.UASTNode, Any]] = [(v2_node, root)]
    while stack:
        source, target = stack.pop()
        legacy_fields = target.__dataclass_fields__
        for field_name in source._fields:
            if field_name not in legacy_fields:
                continue
            value = getattr(source, field_name)
            value_type = type(value)
            if value is None or value_type in (str, int, float, bool, bytes):
                continue
            if value_type is list or value_type is tuple:
                items: List[Any] = []
                for item in value:
                    if isinstance(item, v2.UASTNode):
                        child = _shallow_v2_to_legacy(item)
                        stack.append((item, child))
                        items.append(child)
                    else:
                        items.append(v2_to_legacy(item))
                object.__setattr__(target, field_name, items)
            elif value_type is dict:
                mapping: Dict[Any, Any] = {}
                for key, item in value.items():
                    if isinstance(item, v2.UASTNode):
                        child = _shallow_v2_to_legacy(item)
                        stack.append((item, child))
                        mapping[key] = child
                    else:
                        mapping[key] = v2_to_legacy(item)
                object.__setattr__(target, field_name, mapping)
            elif isinstance(value, v2.UASTNode):
                child = _shallow_v2_to_legacy(value)
                stack.append((value, child))
                object.__setattr__(target, field_name, child)
            else:
                object.__setattr__(target, field_name, v2_to_legacy(value))
    return root


def _shallow_v2_to_legacy(v2_node: v2.UASTNode) -> Any:
    """Build the legacy counterpart of *v2_node* (children copied verbatim)."""
    type_name = type(v2_node).__name__
    legacy_cls = getattr(legacy, type_name, None)
    if legacy_cls is None or not hasattr(legacy_cls, "__dataclass_fields__"):
        raise ConversionError(
            f"Unsupported UAST v2 node type {type_name!r}: the legacy engine has no "
            "node with that name."
        )
    legacy_fields = legacy_cls.__dataclass_fields__
    kwargs: Dict[str, Any] = {}
    for field_name in v2_node._fields:
        if field_name in legacy_fields:
            kwargs[field_name] = getattr(v2_node, field_name)
    kwargs["tag"] = v2_node.tag
    kwargs["location"] = v2_node.get_location()
    return legacy_cls(**kwargs)


def v2_document_to_legacy(v2_uast: v2.CoreUAST) -> Any:
    """Convert a whole v2 document into a legacy ``CoreUAST`` document."""
    body = [v2_to_legacy(node) for node in v2_uast.body]
    metadata = v2_to_legacy(dict(v2_uast.metadata or {}))
    document = legacy.CoreUAST(body=body, language=v2_uast.language, metadata=metadata)
    return document


# ── Short aliases ────────────────────────────────────────────────────────────

to_v2 = legacy_to_v2
to_legacy = v2_to_legacy
