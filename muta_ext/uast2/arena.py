#!/usr/bin/env python3
"""Arena slab + parent pointers for UAST v2 (playbook phase 2).

The arena is the Python analogue of the bump-pointer arena described in the
compiler note that motivated UAST v2:

* one flat slab (``list``) per compilation/mutation session,
* ``node._id`` is the slab index (stable identity, cheap to serialise),
* freed slots are recycled through a free list (bump pointer + free list),
* parent pointers (``_parent``/``_slot``) make ``node.replace()`` and
  ``node.remove()`` O(1) pointer surgery instead of tree rebuilding.

Nothing here is required to *use* v2 trees — the arena is opt-in
(``CoreUAST.prepare(arena)`` / ``parse(..., arena=True)``) and is what makes
flat msgpack checkpoints and incremental Merkle hashing possible.
"""

from __future__ import annotations

import typing as T
from typing import Any, Dict, Iterator, List, Optional

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
    "Arena",
    "assign_parents",
    "prepare",
    "clone_tree",
    "replace_node",
    "arena_of",
]


class Arena:
    """Flat slab allocator for :class:`UASTNode` instances.

    The slab is append-only during a parse and recycles indices on ``release()``,
    which keeps long evolutionary runs memory-bounded:

    >>> arena = Arena()
    >>> root = BinaryOp(left=LiteralNode(value=1), op="+", right=LiteralNode(value=2))
    >>> arena.allocate_all(root)
    3
    >>> len(arena)
    3
    >>> arena.get(root.left._id) is root.left
    True
    """

    __slots__ = ("_slab", "_free", "_live", "allocations", "recycled", "peak")

    def __init__(self) -> None:
        self._slab: List[Optional[UASTNode]] = []
        self._free: List[int] = []
        self._live: int = 0
        self.allocations: int = 0
        self.recycled: int = 0
        self.peak: int = 0

    # ── Allocation ──────────────────────────────────────────────────────────
    def alloc(self, node: UASTNode) -> UASTNode:
        """Store *node* in the slab and return it with a fresh ``_id``."""
        if self._free:
            index = self._free.pop()
            self._slab[index] = node
            self.recycled += 1
        else:
            index = len(self._slab)
            self._slab.append(node)
            self.allocations += 1
        node._id = index
        self._live += 1
        if self._live > self.peak:
            self.peak = self._live
        return node

    def allocate_subtree(self, root: Optional[UASTNode]) -> Optional[UASTNode]:
        """Allocate *root* and every descendant (pre-order, idempotent)."""
        if root is None:
            return None
        slab = self._slab
        alloc = self.alloc
        for node in walk(root):
            if not isinstance(node, UASTNode):
                continue
            node_id = node._id
            if node_id is not None and node_id < len(slab) and slab[node_id] is node:
                continue
            alloc(node)
        return root

    def allocate_all(self, uast: Any) -> int:
        """Allocate every node of a ``CoreUAST``/list/tree.

        Returns the number of *newly* allocated nodes.  Idempotent: nodes that
        already carry an ``_id`` pointing at themselves inside this slab are
        skipped (cheap re-preparation of a tree after in-place edits).
        """
        before = self.allocations + self.recycled
        targets: Iterator[Any]
        if isinstance(uast, (list, tuple)):
            targets = (node for item in uast for node in walk(item))
        else:
            targets = walk(uast)
        slab = self._slab
        alloc = self.alloc
        for node in targets:
            if not isinstance(node, UASTNode):
                continue
            node_id = node._id
            if node_id is not None and node_id < len(slab) and slab[node_id] is node:
                continue
            alloc(node)
        return (self.allocations + self.recycled) - before

    # ── Access ──────────────────────────────────────────────────────────────
    def get(self, node_id: int) -> Optional[UASTNode]:
        """Return the node stored at slab index *node_id* (``None`` when freed)."""
        if 0 <= node_id < len(self._slab):
            return self._slab[node_id]
        return None

    def release(self, node: UASTNode) -> None:
        """Free *node*'s slot for reuse (does not touch the tree structure)."""
        node_id = node._id
        if node_id is None or node_id >= len(self._slab) or self._slab[node_id] is not node:
            return
        self._slab[node_id] = None
        self._free.append(node_id)
        node._id = None
        self._live -= 1

    def release_subtree(self, root: Optional[UASTNode]) -> int:
        """Free every slot of a subtree; returns how many slots were released."""
        if root is None:
            return 0
        released = 0
        for node in walk(root):
            before = len(self._free)
            self.release(node)
            if len(self._free) > before:
                released += 1
        return released

    def compact(self) -> int:
        """Drop trailing empty slots (bounds slab growth across generations)."""
        removed = 0
        while self._slab and self._slab[-1] is None:
            self._slab.pop()
            removed += 1
        if removed:
            self._free = [index for index in self._free if index < len(self._slab)]
        return removed

    def clear(self) -> None:
        """Reset the slab (keeps cumulative statistics)."""
        self._slab.clear()
        self._free.clear()
        self._live = 0

    # ── Introspection ───────────────────────────────────────────────────────
    def nodes(self) -> Iterator[UASTNode]:
        """Iterate live nodes in slab order."""
        for node in self._slab:
            if node is not None:
                yield node

    def stats(self) -> Dict[str, Any]:
        """Allocation statistics (used by the benchmarks/reporting CLI)."""
        slots = len(self._slab)
        return {
            "slots": slots,
            "live": self._live,
            "free": len(self._free),
            "allocations": self.allocations,
            "recycled": self.recycled,
            "peak_live": self.peak,
            "utilization": (self._live / slots) if slots else 0.0,
        }

    def __len__(self) -> int:
        return len(self._slab)

    def __iter__(self) -> Iterator[UASTNode]:
        return self.nodes()

    def __getitem__(self, node_id: int) -> Optional[UASTNode]:
        return self.get(node_id)

    def __contains__(self, node: object) -> bool:
        return isinstance(node, UASTNode) and self.get(node._id if node._id is not None else -1) is node

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"Arena(slots={len(self._slab)}, live={self._live}, "
            f"free={len(self._free)}, peak={self.peak})"
        )


#: ``(field, kind)`` pairs per node class — computed once, used by every walk.
_PARENT_PLANS: T.Dict[type, T.Tuple[T.Tuple[str, str], ...]] = {}


def _parent_plan(node_type: type) -> T.Tuple[T.Tuple[str, str], ...]:
    """Cached ``((field, kind), ...)`` plan for a node class (assign_parents hot path)."""
    plan = _PARENT_PLANS.get(node_type)
    if plan is None:
        kinds = child_kinds(node_type)
        fields = tuple(kinds.items())
        plan = _PARENT_PLANS[node_type] = fields
    return plan


def assign_parents(root: Any) -> int:
    """Assign ``_parent``/``_slot`` for every node reachable from *root*.

    Accepts a :class:`CoreUAST`, a node or a list of nodes.  Returns the number
    of parent links written — one full walk, which is all the bookkeeping an
    in-place mutation session needs.
    """
    if isinstance(root, CoreUAST):
        targets: List[Any] = list(root.body)
    elif isinstance(root, (list, tuple)):
        targets = list(root)
    else:
        targets = [root]

    links = 0
    stack = [node for node in targets if isinstance(node, UASTNode)]
    seen: T.Set[int] = set()
    get_plan = _parent_plan
    kind_node = KIND_NODE
    kind_list = KIND_NODE_LIST
    kind_dict = KIND_NODE_DICT
    push = stack.append
    while stack:
        node = stack.pop()
        identity = id(node)
        if identity in seen:  # defensive: cyclic input
            continue
        seen.add(identity)
        node_type = type(node)
        for name, kind in get_plan(node_type):
            value = getattr(node, name)
            if kind is kind_node:
                if value is not None:
                    value._parent = node
                    value._slot = name
                    links += 1
                    push(value)
            elif kind is kind_list:
                if type(value) is list:
                    for index, item in enumerate(value):
                        item._parent = node
                        item._slot = (name, index)
                        links += 1
                        push(item)
                elif value is not None:  # single node in a node-list field
                    value._parent = node
                    value._slot = name
                    links += 1
                    push(value)
            elif kind is kind_dict and value:
                for key, item in value.items():
                    item._parent = node
                    item._slot = (name, key)
                    links += 1
                    push(item)
    return links


def prepare(root: Any, arena: Optional[Arena] = None) -> Any:
    """Assign parents (and arena ids when *arena* is given) for *root* in-place."""
    assign_parents(root)
    if arena is not None:
        arena.allocate_all(root)
    return root


def clone_tree(node: Optional[UASTNode], arena: Optional[Arena] = None) -> Optional[UASTNode]:
    """Deep-copy a subtree, rebuilding parent pointers (single pass, iterative).

    The copy is built with ``cls.__new__`` and a *cached clone plan* per node
    class, so every node is written exactly once (containers are created empty
    and filled with the copied children).  Digests are inherited: they describe
    structure only (ids, parents and coordinates are excluded), so an untouched
    clone keeps its cached Merkle hashes and a later edit only re-hashes the
    path from the edited node to the root.
    """
    if node is None:
        return None
    root_copy = _clone_node(node)
    copied: Dict[int, UASTNode] = {id(node): root_copy}
    stack: List[T.Tuple[UASTNode, UASTNode]] = [(node, root_copy)]
    while stack:
        source, target = stack.pop()
        for field_name, kind in _clone_plan(type(source)):
            value = getattr(source, field_name)
            if kind is KIND_NODE:
                setattr(target, field_name, _clone_child(value, target, field_name, copied, stack))
            elif kind is KIND_NODE_LIST:
                if value is None:
                    setattr(target, field_name, None)
                elif type(value) is list:
                    items = [
                        _clone_child(item, target, (field_name, index), copied, stack)
                        for index, item in enumerate(value)
                    ]
                    setattr(target, field_name, items)
                else:  # single node stored in a node-list field
                    setattr(
                        target,
                        field_name,
                        _clone_child(value, target, field_name, copied, stack),
                    )
            elif kind is KIND_NODE_DICT:
                if value is None:
                    setattr(target, field_name, None)
                elif value:
                    mapping = {
                        key: _clone_child(item, target, (field_name, key), copied, stack)
                        for key, item in value.items()
                    }
                    setattr(target, field_name, mapping)
                else:
                    setattr(target, field_name, {})
            else:
                # Scalar (or non-node container) field: copy the container so the
                # clone never aliases a mutable value held by the original.
                value_type = type(value)
                if value_type is list:
                    value = list(value)
                elif value_type is dict:
                    value = dict(value)
                elif value_type is set:
                    value = set(value)
                setattr(target, field_name, value)
    if arena is not None:
        arena.allocate_all(root_copy)
    return root_copy


#: Cache of ``((field, kind), ...)`` per node class (clone hot path).
_CLONE_PLANS: Dict[str, T.Tuple[T.Tuple[str, str], ...]] = {}


def _clone_plan(node_type: type) -> T.Tuple[T.Tuple[str, str], ...]:
    """Cached ``((field, kind), ...)`` plan for a node class."""
    plan = _CLONE_PLANS.get(node_type.__name__)
    if plan is None:
        kinds = child_kinds(node_type)
        plan = _CLONE_PLANS[node_type.__name__] = tuple(
            (name, kinds.get(name, "")) for name in node_type._fields
        )
    return plan


def _clone_node(node: UASTNode) -> UASTNode:
    """Allocate an empty copy of *node* (scalars + digest, children left unset)."""
    cls = node.__class__
    copy = cls.__new__(cls)
    copy._id = None
    copy._parent = None
    copy._slot = None
    copy._hash = node._hash
    copy.tag = node.tag
    copy.lineno = node.lineno
    copy.col_offset = node.col_offset
    copy.end_lineno = node.end_lineno
    copy.end_col_offset = node.end_col_offset
    return copy


def _clone_child(
    child: Optional[UASTNode],
    parent: UASTNode,
    slot: Any,
    copied: Dict[int, UASTNode],
    stack: List[T.Tuple[UASTNode, UASTNode]],
) -> Optional[UASTNode]:
    """Clone *child* (once per source node) and re-parent it under *parent*."""
    if child is None:
        return None
    copy = copied.get(id(child))
    if copy is None:
        copy = _clone_node(child)
        copied[id(child)] = copy
        stack.append((child, copy))
    copy._parent = parent
    copy._slot = slot
    return copy


def _shallow_copy(node: UASTNode) -> UASTNode:
    """Copy a single node *without* children (kept for backwards compatibility)."""
    copy = _clone_node(node)
    for field_name in node._fields:
        setattr(copy, field_name, getattr(node, field_name))
    return copy


def replace_node(old: UASTNode, new: UASTNode, arena: Optional[Arena] = None) -> UASTNode:
    """Swap *old* for *new* in the tree (parent pointers + arena ids refreshed)."""
    slots = old._slot
    parent = old._parent
    if parent is None:
        raise NotImplementedError("replace_node() requiere parent pointers (_parent/_slot)")
    old.replace(new)
    if arena is not None:
        if slots is not None:
            arena.allocate_subtree(new)
    return new


def arena_of(uast: Any, arena: Optional[Arena] = None) -> Arena:
    """Convenience: prepare *uast* and return the arena holding all its nodes."""
    arena = arena or Arena()
    prepare(uast, arena)
    return arena
