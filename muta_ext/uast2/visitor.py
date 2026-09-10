#!/usr/bin/env python3
"""Generic visitors for UAST v2 — ``ast``-style ``walk``/``NodeVisitor``/``dump``.

``NodeTransformer`` mutates *in place* (the central promise of UAST v2): child
slots are re-assigned through the parent-aware slot writer, so parent pointers
and Merkle hashes stay consistent without rebuilding frozen dataclasses.
"""

from __future__ import annotations

import typing as T
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from muta_ext.uast2.core import (
    UASTNode,
    CoreUAST,
    set_child,
    walk as _core_walk,
)

__all__ = [
    "walk",
    "iter_fields",
    "iter_child_nodes",
    "iter_child_slots",
    "NodeVisitor",
    "NodeTransformer",
    "dump",
    "dump_python",
    "collect",
    "count_nodes",
    "find_all",
]

Slot = Union[str, Tuple[str, Any]]


def walk(node: Any) -> Iterator[Any]:
    """Flat pre-order iterator (same contract as :func:`ast.walk`)."""
    return _core_walk(node)


def iter_fields(node: Any) -> Iterator[Tuple[str, Any]]:
    """Yield ``(field, value)`` pairs for a v2 node (or a legacy dataclass)."""
    from muta_ext.uast2.core import iter_fields as _iter_fields

    return _iter_fields(node)


def iter_child_nodes(node: Any) -> Iterator[UASTNode]:
    """Direct children of *node* (v2 nodes only; lists/dicts are flattened)."""
    if isinstance(node, UASTNode):
        return node.iter_child_nodes()
    if isinstance(node, CoreUAST):
        return iter([child for child in node.body if isinstance(child, UASTNode)])
    if isinstance(node, (list, tuple)):
        return iter([child for child in node if isinstance(child, UASTNode)])
    return iter(())


def iter_child_slots(node: UASTNode) -> Iterator[Tuple[UASTNode, Slot]]:
    """Yield ``(child, slot)`` pairs — used by parent assignment and mutators."""
    return node.iter_child_slots()


class NodeVisitor:
    """Dispatch a method per node class name (``visit_BinaryOp`` ...).

    Returning a value from a handler propagates it to the caller; the default
    ``generic_visit`` returns ``None``.
    """

    def visit(self, node: Any) -> Any:
        """Dispatch to ``visit_<ClassName>`` falling back to ``generic_visit``."""
        method = getattr(self, "visit_" + type(node).__name__, None)
        if method is None:
            return self.generic_visit(node)
        return method(node)

    def generic_visit(self, node: Any) -> Any:
        """Visit every child of *node*."""
        for child in iter_child_nodes(node):
            self.visit(child)
        return None

    # Convenience alias used by several call sites in the docs.
    def visit_all(self, node: Any) -> Any:
        """Visit *node* itself (dispatch on the root)."""
        return self.visit(node)


class NodeTransformer(NodeVisitor):
    """In-place tree transformer (``ast.NodeTransformer`` semantics).

    Handler contract:

    * return ``None`` → delete the node from its slot,
    * return a node → replace in place,
    * return the same node → keep it,
    * return a list → splice the list into the parent list slot.

    Parent pointers and cached Merkle hashes are refreshed automatically for
    every slot that changes, so ``uast.merkle_hash()`` stays correct after a
    transformation without a full re-walk.
    """

    def visit(self, node: Any) -> Any:
        """Dispatch, then invalidate the Merkle digest of the visited node.

        Handlers commonly mutate fields directly (``node.value *= 2``) without
        going through the slot writer; invalidating here (a short-circuited hop
        chain) guarantees cached digests can never go stale.  The next
        ``merkle_hash()`` recomputes only the dirty path.
        """
        result = super().visit(node)
        if isinstance(node, UASTNode) and node._hash is not None:
            from muta_ext.uast2.merkle import invalidate_up

            invalidate_up(node, record=False)
        return result

    def generic_visit(self, node: Any) -> Any:
        """Visit and re-assign every child of *node* (mutating in place)."""
        if isinstance(node, CoreUAST):
            new_body: List[Any] = []
            for item in node.body:
                result = self.visit(item) if isinstance(item, UASTNode) else item
                if result is None:
                    continue
                if isinstance(result, list):
                    new_body.extend(result)
                else:
                    new_body.append(result)
            node.body[:] = new_body
            _refresh_list_slots(node.body, parent=None, field_name="body")
            return node

        if not isinstance(node, UASTNode):
            return node

        for field_name in node._fields:
            value = getattr(node, field_name)
            value_type = type(value)
            if isinstance(value, UASTNode):
                result = self.visit(value)
                if result is None:
                    set_child(node, field_name, None)
                    value._parent = value._slot = None
                elif isinstance(result, list):
                    set_child(node, field_name, result)
                    _refresh_list_slots(result, node, field_name)
                elif result is not value:
                    set_child(node, field_name, result)
            elif value_type is list:
                changed = False
                new_items: List[Any] = []
                for item in value:
                    if isinstance(item, UASTNode):
                        result = self.visit(item)
                        if result is None:
                            item._parent = item._slot = None
                            changed = True
                            continue
                        if isinstance(result, list):
                            new_items.extend(result)
                            changed = True
                            continue
                        if result is not item:
                            changed = True
                        new_items.append(result)
                    else:
                        new_items.append(item)
                if changed or len(new_items) != len(value):
                    value[:] = new_items  # mutate the list object in place
                    _refresh_list_slots(value, node, field_name)
            elif value_type is dict:
                changed = False
                for key, item in list(value.items()):
                    if not isinstance(item, UASTNode):
                        continue
                    result = self.visit(item)
                    if result is None:
                        del value[key]
                        item._parent = item._slot = None
                        changed = True
                    elif result is not item:
                        if isinstance(result, UASTNode):
                            value[key] = result
                            result._parent = node
                            result._slot = (field_name, key)
                        else:  # pragma: no cover - defensive
                            value[key] = result
                        changed = True
                if changed:
                    from muta_ext.uast2.merkle import invalidate_up

                    invalidate_up(node)
        # Handlers often mutate fields directly (``node.value *= 2``); invalidate
        # conservatively so cached Merkle digests can never go stale.  The call
        # short-circuits at the first dirty ancestor, so a full transform costs
        # O(nodes) pointer hops with a tiny constant.
        from muta_ext.uast2.merkle import invalidate_up

        invalidate_up(node, record=False)
        return node

    # ``visit`` returns the (possibly new) node; the transformer keeps the tree.
    def transform(self, uast: Any) -> Any:
        """Run the transformer over a whole document and return it."""
        return self.visit(uast)


def _refresh_list_slots(items: List[Any], parent: Optional[UASTNode], field_name: str) -> None:
    """Re-index ``_slot`` for children stored in a list slot."""
    if parent is None:
        for item in items:
            if isinstance(item, UASTNode):
                item._parent = None
                item._slot = None
        return
    for index, item in enumerate(items):
        if isinstance(item, UASTNode):
            item._parent = parent
            item._slot = (field_name, index)
    from muta_ext.uast2.merkle import invalidate_up

    invalidate_up(parent)


# ── Debugging helpers ────────────────────────────────────────────────────────


def dump(
    node: Any,
    annotate_fields: bool = True,
    include_attributes: bool = False,
    indent: Optional[int] = None,
    _level: int = 0,
) -> str:
    """Render a node (or document) like :func:`ast.dump`, for debugging/tests."""
    if isinstance(node, CoreUAST):
        parts = [
            dump(child, annotate_fields, include_attributes, indent, _level + 1)
            for child in node.body
        ]
        return _join_block("CoreUAST", parts, indent, _level)
    if isinstance(node, (list, tuple)):
        parts = [
            dump(item, annotate_fields, include_attributes, indent, _level + 1) for item in node
        ]
        return "[" + ", ".join(parts) + "]"

    if not isinstance(node, UASTNode):
        return repr(node)

    parts: List[str] = []
    for field_name in node._fields:
        value = getattr(node, field_name)
        field_str = _dump_value(value, annotate_fields, include_attributes, indent, _level)
        parts.append(f"{field_name}={field_str}" if annotate_fields else field_str)

    if include_attributes:
        for attribute in ("lineno", "col_offset", "end_lineno", "end_col_offset", "tag"):
            value = getattr(node, attribute, None)
            if value is not None:
                parts.append(f"{attribute}={value!r}")

    return f"{type(node).__name__}({', '.join(parts)})"


def _dump_value(
    value: Any,
    annotate_fields: bool,
    include_attributes: bool,
    indent: Optional[int],
    level: int,
) -> str:
    if isinstance(value, UASTNode):
        return dump(value, annotate_fields, include_attributes, indent, level + 1)
    if isinstance(value, list):
        return "[" + ", ".join(
            _dump_value(item, annotate_fields, include_attributes, indent, level + 1)
            for item in value
        ) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(
            f"{key!r}: {_dump_value(item, annotate_fields, include_attributes, indent, level + 1)}"
            for key, item in value.items()
        ) + "}"
    return repr(value)


def _join_block(name: str, parts: List[str], indent: Optional[int], level: int) -> str:
    if indent is None or not parts:
        return f"{name}({', '.join(parts)})"
    pad = " " * (indent * (level + 1))
    closing = " " * (indent * level)
    inner = (",\n" + pad).join(parts)
    return f"{name}(\n{pad}{inner}\n{closing})"


def dump_python(node: Any, indent: Optional[int] = None) -> str:
    """Alias of :func:`dump` with ``annotate_fields=False`` (compact form)."""
    return dump(node, annotate_fields=False, indent=indent)


def collect(uast: Any, node_type: type) -> List[UASTNode]:
    """Return every node of *node_type* in *uast* (pre-order)."""
    return [node for node in walk(uast) if isinstance(node, node_type)]


def find_all(uast: Any, predicate: T.Callable[[UASTNode], bool]) -> List[UASTNode]:
    """Return every node matching *predicate*."""
    return [node for node in walk(uast) if isinstance(node, UASTNode) and predicate(node)]


def count_nodes(uast: Any) -> int:
    """Number of nodes reachable from *uast*."""
    return sum(1 for _ in walk(uast))
