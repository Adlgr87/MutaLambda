#!/usr/bin/env python3
"""UAST v2 — mutable core node model (``ast``-style, arena-friendly).

This module is the heart of the *parallel* UAST v2 engine described in the
UAST v2 implementation playbook.  It never replaces ``muta_ext.uast.core_uast``
(the legacy frozen dataclasses stay untouched and remain the default engine);
it provides a mutable, ``__slots__``-based representation designed for:

* **In-place mutation** — ``NodeTransformer`` / ``node.replace()`` are O(1)
  pointer swaps instead of rebuilding frozen dataclasses.
* **Low memory footprint** — every node class declares ``__slots__`` (injected
  automatically from ``_fields``), so instances carry no ``__dict__``.
* **Uniform schema** — every node exposes ``_fields`` (ordering identical to the
  legacy dataclass field order) and ``iter_child_nodes()``/``iter_child_slots()``
  so generic visitors, serializers and verifiers work on *any* node type.
* **API compatibility** — ``CoreUAST`` here exposes the same surface used by the
  evolutionary engine (``.body``, ``.language``, ``.metadata``,
  ``.canonical_hash()``, ``.to_dict()``, ``.from_dict()``).

Node construction is intentionally permissive (missing fields become ``None``,
exactly like ``ast.AST``), and the verification pipeline (``muta_ext.uast2.verify``)
reports missing *required* fields as diagnostics.  Required fields are derived
from the legacy dataclasses: a field is required when the legacy node declares
it without a default (``required_fields()``).
"""

from __future__ import annotations

import hashlib
import json
import typing as T
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "UASTNode",
    "CoreUAST",
    "Node",
    "MISSING",
    "NODE_REGISTRY",
    "node_class",
    "required_fields",
    "child_kinds",
    "iter_fields",
    "iter_child_nodes_any",
    "walk",
    "to_serializable",
    "from_serializable",
    "node_to_dict",
    "node_from_dict",
    # Node types (23, same names/fields as the legacy engine)
    "LiteralNode",
    "Identifier",
    "BinaryOp",
    "UnaryOp",
    "Call",
    "Assign",
    "If",
    "For",
    "While",
    "Return",
    "Function",
    "ParallelFor",
    "Comment",
    "Opaque",
    "Break",
    "TryExcept",
    "ExceptClause",
    "StructDef",
    "FieldDef",
    "TypeAnnotation",
    "MatchArm",
    "Match",
    "Reference",
]

#: ``Node`` mirrors the legacy union so annotations type-check across engines.
Node = "UASTNode"


class _Missing:
    """Sentinel for "argument not supplied" (distinct from an explicit ``None``)."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "MISSING"

    def __bool__(self) -> bool:  # pragma: no cover - defensive
        return False


MISSING = _Missing()

#: Slots owned by the base class.  Subclasses must not reuse these names.
_BASE_SLOTS = (
    "_id",
    "_parent",
    "_slot",
    "_hash",
    "lineno",
    "col_offset",
    "end_lineno",
    "end_col_offset",
    "tag",
    "__weakref__",
)

#: Field kinds used by the (de)serializer and the schema verifier.
KIND_SCALAR = "scalar"
KIND_NODE = "node"
KIND_NODE_LIST = "nodelist"
KIND_NODE_DICT = "nodedict"


def _reject_kwargs(node: Any, kw: Dict[str, Any]) -> None:
    """Raise a ``TypeError`` listing unexpected constructor keywords."""
    raise TypeError(
        f"Campos inesperados para {type(node).__name__}: {sorted(kw)}"
    )


def _generate_init(
    cls_name: str,
    fields: T.Tuple[str, ...],
    defaults: Dict[str, Any],
) -> str:
    """Build the source of a specialised ``__init__`` for one node class.

    Specialised constructors (code-generated per class instead of a generic
    ``**kwargs`` loop) are ~2x faster than the dict-popping reference
    implementation and keep positional-argument compatibility with the legacy
    dataclasses (``BinaryOp(left, op, right)`` keeps working).
    """
    params: List[str] = []
    lines: List[str] = []
    for name in fields:
        default = defaults.get(name, MISSING)
        if default is MISSING:
            params.append(f"{name}=None")
            lines.append(f"    self.{name} = {name}")
        elif default is list or default is dict:
            params.append(f"{name}=_MISSING")
            literal = "[]" if default is list else "{}"
            lines.append(f"    self.{name} = {literal} if {name} is _MISSING else {name}")
        else:
            params.append(f"{name}={default!r}")
            lines.append(f"    self.{name} = {name}")

    params.append("lineno=None")
    params.append("col_offset=None")
    params.append("end_lineno=None")
    params.append("end_col_offset=None")
    params.append("tag=None")
    params.append("location=None")
    params.append("**kw")

    header = f"def __init__(self, {', '.join(params)}):"
    body = [
        "    if kw:",
        "        _reject_kwargs(self, kw)",
        "    self._id = None",
        "    self._parent = None",
        "    self._slot = None",
        "    self._hash = None",
        "    self.tag = tag",
        "    if location is not None:",
        "        lineno = location.get('line', lineno)",
        "        col_offset = location.get('col', col_offset)",
        "        end_lineno = location.get('end_line', end_lineno)",
        "        end_col_offset = location.get('end_col', end_col_offset)",
        "    self.lineno = lineno",
        "    self.col_offset = col_offset",
        "    self.end_lineno = end_lineno",
        "    self.end_col_offset = end_col_offset",
    ]
    body.extend(lines)
    source = "\n".join([header, *body]) + "\n"
    return source


class _NodeMeta(type):
    """Metaclass: injects ``__slots__`` + a specialised ``__init__`` per node."""

    def __new__(mcls, name: str, bases: T.Tuple[type, ...], ns: Dict[str, Any], **kw):
        if name != "UASTNode" and "_fields" in ns:
            fields = tuple(ns["_fields"])
            if len(set(fields)) != len(fields):
                raise TypeError(f"{name}._fields contains duplicates: {fields}")
            clash = [f for f in fields if f in _BASE_SLOTS]
            if clash:
                raise TypeError(f"{name}._fields clashes with reserved slots: {clash}")
            ns.setdefault("__slots__", fields)
            defaults = dict(ns.get("_defaults") or {})
            unknown = set(defaults) - set(fields)
            if unknown:
                raise TypeError(f"{name}._defaults references unknown fields: {sorted(unknown)}")
            ns["_defaults"] = defaults
            source = _generate_init(name, fields, defaults)
            code = compile(source, f"<uast2:{name}>", "exec")
            local_ns: Dict[str, Any] = {}
            exec(code, {"_MISSING": MISSING, "_reject_kwargs": _reject_kwargs}, local_ns)  # noqa: S102
            init = local_ns["__init__"]
            init.__qualname__ = f"{name}.__init__"
            init.__doc__ = "Initialise this node (see class docstring for field semantics)."
            ns["__init__"] = init
        cls = super().__new__(mcls, name, bases, ns, **kw)
        if hasattr(cls, "_child_kinds") and cls._child_kinds:
            # Validate that declared child kinds reference real fields.
            bad = set(cls._child_kinds) - set(cls._fields)
            if bad:
                raise TypeError(f"{name}._child_kinds references unknown fields: {sorted(bad)}")
        return cls


class UASTNode(metaclass=_NodeMeta):
    """Mutable base node — the ``ast.AST`` analogue of UAST v2.

    Slots (all present on every node, never serialised except ``tag``):

    ``_id``       Arena slab index (``None`` until allocated).
    ``_parent``   Parent node (``None`` for roots).
    ``_slot``     Where this node lives inside its parent: a field name (``str``)
                  or a ``(field_name, index)`` tuple for list slots.
    ``_hash``     Cached Merkle digest (``bytes``) or ``None`` when dirty.
    ``lineno``/``col_offset``/``end_lineno``/``end_col_offset``
                  Source position (0-based columns, like ``ast`` / tree-sitter).
    ``tag``       Free-form marker preserved from the legacy engine.
    """

    _fields: T.Tuple[str, ...] = ()
    _defaults: Dict[str, Any] = {}
    _child_kinds: Dict[str, str] = {}

    __slots__ = _BASE_SLOTS

    # ── Traversal ────────────────────────────────────────────────────────────
    def iter_fields(self) -> T.Iterator[T.Tuple[str, Any]]:
        """Yield ``(field_name, value)`` pairs in canonical order."""
        for name in self._fields:
            yield name, getattr(self, name)

    def iter_child_nodes(self) -> T.Iterator["UASTNode"]:
        """Yield direct child nodes (values of node/list/dict fields)."""
        for name in self._fields:
            value = getattr(self, name)
            value_type = type(value)
            if value_type is list:
                for item in value:
                    if isinstance(item, UASTNode):
                        yield item
            elif isinstance(value, UASTNode):
                yield value
            elif value_type is dict:
                for item in value.values():
                    if isinstance(item, UASTNode):
                        yield item

    def iter_child_slots(self) -> T.Iterator[T.Tuple["UASTNode", T.Union[str, T.Tuple[str, int]]]]:
        """Yield ``(child, slot)`` pairs — used to (re)assign parent pointers.

        ``slot`` is the field name for single-child fields and a
        ``(field_name, index)`` tuple for children stored inside lists.
        """
        for name in self._fields:
            value = getattr(self, name)
            value_type = type(value)
            if value_type is list:
                for index, item in enumerate(value):
                    if isinstance(item, UASTNode):
                        yield item, (name, index)
            elif isinstance(value, UASTNode):
                yield value, name
            elif value_type is dict:
                for key, item in value.items():
                    if isinstance(item, UASTNode):
                        yield item, (name, key)

    # ── Structural editing ───────────────────────────────────────────────────
    def replace(self, new: "UASTNode") -> "UASTNode":
        """Replace this node by *new* in its parent, in O(1).

        Requires parent pointers (``CoreUAST.prepare()`` / ``assign_parents()``).
        Hashes of the replaced node and every ancestor are invalidated
        automatically.  Returns *new* for chaining.
        """
        parent, slot = self._parent, self._slot
        if parent is None:
            raise NotImplementedError(
                "replace() requiere parent pointers; llama a CoreUAST.prepare() o "
                "muta_ext.uast2.arena.assign_parents(root) antes de mutar in-situ"
            )
        _store_slot(parent, slot, new)
        self._parent = None
        self._slot = None
        return new

    def sibling_list(self) -> Optional[List[Any]]:
        """Return the list that contains this node, or ``None`` for field slots."""
        parent, slot = self._parent, self._slot
        if parent is None or not isinstance(slot, tuple):
            return None
        return getattr(parent, slot[0], None)

    def remove(self) -> None:
        """Detach this node from its parent (lists shrink, fields become ``None``)."""
        parent, slot = self._parent, self._slot
        if parent is None:
            raise NotImplementedError("remove() requiere parent pointers")
        if isinstance(slot, tuple):
            container = getattr(parent, slot[0])
            key = slot[1]
            if isinstance(container, list):
                container.pop(key)
                # Re-index the remaining siblings so their slots stay valid.
                for index, child in enumerate(container):
                    if isinstance(child, UASTNode):
                        child._slot = (slot[0], index)
            elif isinstance(container, dict):
                container.pop(key, None)
        else:
            setattr(parent, slot, None)
        from muta_ext.uast2.merkle import invalidate_up

        invalidate_up(parent)
        self._parent = None
        self._slot = None

    # ── Locations ────────────────────────────────────────────────────────────
    def get_location(self) -> Optional[Dict[str, int]]:
        """Return a legacy-compatible location dict (``None`` when unknown)."""
        if self.lineno is None and self.col_offset is None:
            return None
        location: Dict[str, int] = {}
        if self.lineno is not None:
            location["line"] = self.lineno
        if self.col_offset is not None:
            location["col"] = self.col_offset
        if self.end_lineno is not None:
            location["end_line"] = self.end_lineno
        if self.end_col_offset is not None:
            location["end_col"] = self.end_col_offset
        return location or None

    def set_location(self, location: Optional[Dict[str, Any]]) -> "UASTNode":
        """Assign location from a legacy dict (``{"line", "col", ...}``)."""
        if not location:
            return self
        self.lineno = location.get("line", self.lineno)
        self.col_offset = location.get("col", self.col_offset)
        self.end_lineno = location.get("end_line", self.end_lineno)
        self.end_col_offset = location.get("end_col", self.end_col_offset)
        return self

    # ── Copying ──────────────────────────────────────────────────────────────
    def clone(self) -> "UASTNode":
        """Deep copy of this subtree (parent pointers are refreshed by the copy)."""
        from muta_ext.uast2.arena import clone_tree

        copy = clone_tree(self)
        assert copy is not None
        return copy

    # ── Hash cache ───────────────────────────────────────────────────────────
    def invalidate_hash(self) -> None:
        """Mark this node and every ancestor as hash-dirty (O(depth))."""
        from muta_ext.uast2.merkle import invalidate_up

        invalidate_up(self)

    def __repr__(self) -> str:
        inner = ", ".join(f"{name}={getattr(self, name)!r}" for name in self._fields)
        return f"{type(self).__name__}({inner})"

    def __reduce__(self):  # pragma: no cover - pickle support (checkpoints/MP)
        return (_rebuild_node, (type(self).__name__, node_to_dict(self, include_location=True)))


def _invalidate_document(document: "CoreUAST") -> None:
    """Invalidate every cached digest after a body-level edit."""
    for node in document.body:
        if isinstance(node, UASTNode):
            node._hash = None


def _rebuild_node(type_name: str, payload: Dict[str, Any]) -> "UASTNode":
    """Pickle helper: reconstruct a node from its dict form."""
    node = node_from_dict(payload)
    if node is None:  # pragma: no cover - defensive
        raise TypeError(f"cannot rebuild node of type {type_name!r}")
    return node


def _store_slot(
    parent: "UASTNode",
    slot: T.Union[str, T.Tuple[str, Any]],
    value: Any,
) -> None:
    """Write *value* into *parent*'s *slot*, refresh pointers and invalidate hashes."""
    from muta_ext.uast2.merkle import invalidate_up

    if isinstance(slot, tuple):
        container = getattr(parent, slot[0])
        key = slot[1]
        if isinstance(container, list):
            container[key] = value
        else:  # dict slot
            container[key] = value
    else:
        setattr(parent, slot, value)
    if isinstance(value, UASTNode):
        value._parent = parent
        value._slot = slot
    invalidate_up(parent)


def set_child(node: "UASTNode", slot: T.Union[str, T.Tuple[str, Any]], value: Any) -> None:
    """Public alias of the slot writer (updates parents + invalidates hashes)."""
    _store_slot(node, slot, value)


# ── Node classes (same names and field order as the legacy engine) ───────────


class LiteralNode(UASTNode):
    """Constant value (int/float/str/bool/None) with an optional ``type_hint``."""

    _fields = ("value", "type_hint")
    #: ``None``-defaulted fields are optional; fields absent here are required.
    _defaults: Dict[str, Any] = {"type_hint": None}


class Identifier(UASTNode):
    """Named reference; ``qualified`` keeps module/namespace prefixes."""

    _fields = ("name", "qualified")
    _defaults: Dict[str, Any] = {"qualified": None}


class BinaryOp(UASTNode):
    """Binary operation.  ``op`` is a language-neutral symbol (``+``, ``and``...)."""

    _fields = ("left", "op", "right")
    _defaults: Dict[str, Any] = {}
    _child_kinds = {"left": KIND_NODE, "right": KIND_NODE}


class UnaryOp(UASTNode):
    """Unary operation (``-``, ``not``, ``~``)."""

    _fields = ("op", "operand")
    _defaults: Dict[str, Any] = {}
    _child_kinds = {"operand": KIND_NODE}


class Call(UASTNode):
    """Function call: ``func(args, **keywords)``."""

    _fields = ("func", "args", "keywords")
    _defaults: Dict[str, Any] = {"args": list, "keywords": dict}
    _child_kinds = {"func": KIND_NODE, "args": KIND_NODE_LIST, "keywords": KIND_NODE_DICT}


class Assign(UASTNode):
    """Assignment.  ``target`` is an ``Identifier`` or a list of them."""

    _fields = ("target", "value")
    _defaults: Dict[str, Any] = {}
    # ``target`` may be a single node OR a list of nodes → "nodelist" decoding
    # accepts both, which keeps chained/parallel assignment lossless.
    _child_kinds = {"target": KIND_NODE_LIST, "value": KIND_NODE}


class If(UASTNode):
    """Conditional: ``then_body`` is mandatory, ``else_body`` optional."""

    _fields = ("condition", "then_body", "else_body")
    _defaults: Dict[str, Any] = {"else_body": None}
    _child_kinds = {
        "condition": KIND_NODE,
        "then_body": KIND_NODE_LIST,
        "else_body": KIND_NODE_LIST,
    }


class For(UASTNode):
    """Iteration (``for var in iterable`` / traditional C-style loop)."""

    _fields = ("var", "iterable", "body", "is_traditional")
    _defaults: Dict[str, Any] = {"is_traditional": False}
    _child_kinds = {"var": KIND_NODE, "iterable": KIND_NODE, "body": KIND_NODE_LIST}


class While(UASTNode):
    """Pre-tested loop."""

    _fields = ("condition", "body")
    _defaults: Dict[str, Any] = {}
    _child_kinds = {"condition": KIND_NODE, "body": KIND_NODE_LIST}


class Return(UASTNode):
    """Return statement (``value`` may be ``None``)."""

    _fields = ("value",)
    _defaults: Dict[str, Any] = {"value": None}
    _child_kinds = {"value": KIND_NODE}


class Function(UASTNode):
    """Function/method definition."""

    _fields = ("name", "params", "body", "decorators", "return_type")
    _defaults: Dict[str, Any] = {
        "params": list,
        "body": list,
        "decorators": list,
        "return_type": None,
    }
    _child_kinds = {
        "name": KIND_NODE,
        "params": KIND_NODE_LIST,
        "body": KIND_NODE_LIST,
        "decorators": KIND_NODE_LIST,
    }


class ParallelFor(UASTNode):
    """Data-parallel loop (``reduction`` in ``sum|max|min|prod``)."""

    _fields = ("var", "start", "end", "body", "reduction")
    _defaults: Dict[str, Any] = {"reduction": None}
    _child_kinds = {
        "var": KIND_NODE,
        "start": KIND_NODE,
        "end": KIND_NODE,
        "body": KIND_NODE_LIST,
    }


class Comment(UASTNode):
    """Comment with a relative ``position`` (``before``/``inline``/``after``)."""

    _fields = ("text", "position")
    _defaults: Dict[str, Any] = {"position": "before"}


class Opaque(UASTNode):
    """Unparsed source fragment — never mutated, always emitted verbatim."""

    _fields = ("original_text", "lang")
    _defaults: Dict[str, Any] = {}


class Break(UASTNode):
    """Loop break."""

    _fields: T.Tuple[str, ...] = ()
    _defaults: Dict[str, Any] = {}


class TryExcept(UASTNode):
    """try/except/finally block."""

    _fields = ("body", "except_clauses", "finally_body")
    _defaults: Dict[str, Any] = {"body": list, "except_clauses": list, "finally_body": None}
    _child_kinds = {
        "body": KIND_NODE_LIST,
        "except_clauses": KIND_NODE_LIST,
        "finally_body": KIND_NODE_LIST,
    }


class ExceptClause(UASTNode):
    """Single ``except``/``catch`` clause (``None`` type == catch-all)."""

    _fields = ("exception_type", "binding", "body")
    _defaults: Dict[str, Any] = {"body": list, "exception_type": None, "binding": None}
    _child_kinds = {"exception_type": KIND_NODE, "body": KIND_NODE_LIST}


class StructDef(UASTNode):
    """Struct/class definition."""

    _fields = ("name", "fields", "methods")
    _defaults: Dict[str, Any] = {"fields": list, "methods": list}
    _child_kinds = {"fields": KIND_NODE_LIST, "methods": KIND_NODE_LIST}


class FieldDef(UASTNode):
    """Struct/class field with optional annotation and default value."""

    _fields = ("name", "type_annotation", "default")
    _defaults: Dict[str, Any] = {"type_annotation": None, "default": None}
    _child_kinds = {"type_annotation": KIND_NODE, "default": KIND_NODE}


class TypeAnnotation(UASTNode):
    """Type expression (``type_name`` + generic args + reference/mutability flags)."""

    _fields = ("type_name", "generic_args", "is_reference", "is_mutable")
    _defaults: Dict[str, Any] = {"generic_args": list, "is_reference": False, "is_mutable": False}
    _child_kinds = {"generic_args": KIND_NODE_LIST}


class MatchArm(UASTNode):
    """Pattern-matching arm (pattern, optional guard, body)."""

    _fields = ("pattern", "guard", "body")
    _defaults: Dict[str, Any] = {"body": list, "guard": None}
    _child_kinds = {"pattern": KIND_NODE, "guard": KIND_NODE, "body": KIND_NODE_LIST}


class Match(UASTNode):
    """Pattern match / switch over a subject expression."""

    _fields = ("subject", "arms")
    _defaults: Dict[str, Any] = {"arms": list}
    _child_kinds = {"subject": KIND_NODE, "arms": KIND_NODE_LIST}


class Reference(UASTNode):
    """Reference/pointer (Rust ``&``/``&mut``, C++ ``*``/``&``)."""

    _fields = ("target", "is_mutable")
    _defaults: Dict[str, Any] = {"is_mutable": False}
    _child_kinds = {"target": KIND_NODE}


#: Registry of every concrete node type, keyed by class name.
NODE_REGISTRY: Dict[str, T.Type[UASTNode]] = {
    cls.__name__: cls
    for cls in (
        LiteralNode,
        Identifier,
        BinaryOp,
        UnaryOp,
        Call,
        Assign,
        If,
        For,
        While,
        Return,
        Function,
        ParallelFor,
        Comment,
        Opaque,
        Break,
        TryExcept,
        ExceptClause,
        StructDef,
        FieldDef,
        TypeAnnotation,
        MatchArm,
        Match,
        Reference,
    )
}

#: Cache for :func:`child_kinds`.
_CHILD_KINDS_CACHE: Dict[str, Dict[str, str]] = {}


def node_class(type_name: str) -> T.Type[UASTNode]:
    """Look up a node class by name (raises ``KeyError`` when unknown)."""
    try:
        return NODE_REGISTRY[type_name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(
            f"Unknown UAST v2 node type {type_name!r}. Known types: {sorted(NODE_REGISTRY)}"
        ) from exc


def required_fields(cls: T.Type[UASTNode]) -> T.Tuple[str, ...]:
    """Fields the legacy dataclass declares without default (must be non-``None``)."""
    defaults = cls._defaults
    return tuple(name for name in cls._fields if name not in defaults)


def child_kinds(cls: T.Type[UASTNode]) -> Dict[str, str]:
    """Field-name → kind map for *cls* (cached; inherited declarations merge)."""
    cached = _CHILD_KINDS_CACHE.get(cls.__name__)
    if cached is not None:
        return cached
    kinds: Dict[str, str] = {}
    for base in reversed(cls.__mro__):
        kinds.update(getattr(base, "_child_kinds", None) or {})
    _CHILD_KINDS_CACHE[cls.__name__] = kinds
    return kinds


def iter_fields(node: Any) -> T.Iterator[T.Tuple[str, Any]]:
    """Yield ``(name, value)`` pairs for a v2 *or* legacy node (duck-typed)."""
    fields = getattr(node, "_fields", None)
    if fields is not None:
        for name in fields:
            yield name, getattr(node, name)
        return
    legacy_fields = getattr(node, "__dataclass_fields__", None)
    if legacy_fields:
        for name in legacy_fields:
            yield name, getattr(node, name)


def iter_child_nodes_any(node: Any) -> T.Iterator[Any]:
    """Direct children of a v2 node *or* a legacy dataclass node (duck-typed)."""
    if isinstance(node, UASTNode):
        yield from node.iter_child_nodes()
        return
    fields = getattr(node, "__dataclass_fields__", None)
    if not fields:
        return
    for name in fields:
        value = getattr(node, name)
        if isinstance(value, UASTNode) or hasattr(value, "__dataclass_fields__"):
            yield value
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, UASTNode) or hasattr(item, "__dataclass_fields__"):
                    yield item
        elif isinstance(value, dict):
            for item in value.values():
                if isinstance(item, UASTNode) or hasattr(item, "__dataclass_fields__"):
                    yield item


def walk(node: Any) -> T.Iterator[Any]:
    """Flat pre-order generator over v2 nodes (and legacy nodes) — like ``ast.walk``."""
    stack: List[Any] = [node]
    seen: T.Set[int] = set()
    while stack:
        current = stack.pop()
        if hasattr(current, "canonical_hash") and hasattr(current, "body"):
            # CoreUAST document (v2 or legacy): descend into its body.
            stack.extend(reversed(list(current.body)))
        elif isinstance(current, UASTNode) or hasattr(current, "__dataclass_fields__"):
            if id(current) in seen:  # defensive: malformed (cyclic) trees
                continue
            seen.add(id(current))
            yield current
            # Reverse so children pop left-to-right (true pre-order, like ast.walk).
            stack.extend(reversed(list(iter_child_nodes_any(current))))
        elif isinstance(current, (list, tuple)):
            stack.extend(reversed(current))


# ── Serialisation (legacy-compatible dict form) ──────────────────────────────


def to_serializable(value: Any, include_location: bool = True) -> Any:
    """Convert a v2 subtree to the legacy JSON-compatible structure.

    Primitives pass through; nodes become ``{"__type__": ..., <fields>, "tag",
    "location"}`` exactly like ``muta_ext.uast.core_uast._to_serializable``.
    """
    value_type = type(value)
    if value is None or value_type is str or value_type is int or value_type is float:
        return value
    if value_type is bool:
        return value
    if value_type is bytes:
        return value.decode("utf-8", "replace")
    if value_type is list or value_type is tuple:
        return [to_serializable(item, include_location) for item in value]
    if value_type is dict:
        return {key: to_serializable(item, include_location) for key, item in value.items()}
    if isinstance(value, UASTNode):
        return node_to_dict(value, include_location=include_location)
    return str(value)


def node_to_dict(node: UASTNode, include_location: bool = True) -> Dict[str, Any]:
    """Serialise a single node (and its subtree) to a plain dict."""
    payload: Dict[str, Any] = {"__type__": type(node).__name__}
    for name in node._fields:
        payload[name] = to_serializable(getattr(node, name), include_location)
    payload["tag"] = node.tag
    payload["location"] = node.get_location() if include_location else None
    return payload


def from_serializable(value: Any, strict: bool = False) -> Any:
    """Rebuild a v2 subtree from the legacy dict form."""
    value_type = type(value)
    if value_type is dict:
        if "__type__" in value:
            return node_from_dict(value, strict=strict)
        return {key: from_serializable(item, strict=strict) for key, item in value.items()}
    if value_type is list or value_type is tuple:
        return [from_serializable(item, strict=strict) for item in value]
    return value


def node_from_dict(payload: Dict[str, Any], strict: bool = False) -> UASTNode:
    """Rebuild a single node (and subtree) from :func:`node_to_dict` output."""
    type_name = payload.get("__type__")
    cls = NODE_REGISTRY.get(type_name)
    if cls is None:
        if strict:
            raise ValueError(f"Unknown UAST v2 node type: {type_name!r}")
        return Opaque(
            original_text=json.dumps(payload, sort_keys=True, default=str), lang="unknown"
        )
    kwargs: Dict[str, Any] = {}
    for name in cls._fields:
        if name in payload:
            kwargs[name] = from_serializable(payload[name], strict=strict)
        elif name in cls._defaults:
            default = cls._defaults[name]
            kwargs[name] = default() if default is list or default is dict else default
    kwargs["tag"] = payload.get("tag")
    location = payload.get("location")
    if location:
        kwargs["lineno"] = location.get("line")
        kwargs["col_offset"] = location.get("col")
        kwargs["end_lineno"] = location.get("end_line")
        kwargs["end_col_offset"] = location.get("end_col")
    return cls(**kwargs)


# ── CoreUAST wrapper (same public surface as the legacy wrapper) ─────────────


@dataclass
class CoreUAST:
    """Mutable UAST document — drop-in for the legacy ``CoreUAST``.

    ``body`` holds :class:`UASTNode` instances.  ``language``/``metadata``/
    ``canonical_hash()``/``to_dict()``/``from_dict()`` keep the legacy contract so
    the evolutionary engine, checkpoint manager and sandbox keep working without
    changes.
    """

    body: List[UASTNode] = field(default_factory=list)
    language: str = "python"
    metadata: Dict[str, Any] = field(default_factory=dict)
    engine: str = "v2"
    #: True once parent pointers were assigned (kept out of the serialised form).
    prepared: bool = False

    # ── Construction helpers ────────────────────────────────────────────────
    @classmethod
    def from_legacy(cls, legacy_uast: Any) -> "CoreUAST":
        """Convert a legacy (frozen) ``CoreUAST`` into a mutable v2 document."""
        from muta_ext.uast2.convert import legacy_to_v2

        return cls(
            body=legacy_to_v2(list(legacy_uast.body)),
            language=getattr(legacy_uast, "language", "python"),
            metadata=dict(getattr(legacy_uast, "metadata", {}) or {}),
        )

    def to_legacy(self) -> Any:
        """Convert back to the legacy representation (emitters/mutators reuse)."""
        from muta_ext.uast2.convert import v2_to_legacy

        return v2_to_legacy(self)

    # ── Traversal / preparation ─────────────────────────────────────────────
    def walk(self) -> T.Iterator[UASTNode]:
        """Iterate every node of the document in pre-order."""
        for node in self.body:
            yield from walk(node)

    def node_count(self) -> int:
        """Total number of nodes in the document."""
        return sum(1 for _ in self.walk())

    def prepare(self, arena: Optional[Any] = None) -> "CoreUAST":
        """Assign parent pointers (and arena ids when *arena* is given), in-place."""
        from muta_ext.uast2.arena import assign_parents

        assign_parents(self)
        self.prepared = True
        if arena is not None:
            arena.allocate_all(self)
        return self

    def assign_parents(self) -> "CoreUAST":
        """Alias of :meth:`prepare` (readability in user code)."""
        return self.prepare()

    def clone(self, arena: Optional[Any] = None) -> "CoreUAST":
        """Deep copy of the document (parent pointers refreshed, hashes reset)."""
        from muta_ext.uast2.arena import clone_tree

        body = [clone_tree(node) for node in self.body]
        copy = CoreUAST(
            body=[node for node in body if node is not None],
            language=self.language,
            metadata=dict(self.metadata),
            engine=self.engine,
        )
        # ``clone_tree`` already rebuilt every ``_parent``/``_slot`` pair, so the
        # clone is prepared by construction; only a requested arena needs ids.
        copy.prepared = True
        if arena is not None:
            arena.allocate_all(copy)
        return copy

    # ── Hashing ─────────────────────────────────────────────────────────────
    def canonical_hash(self, include_location: bool = False) -> str:
        """Deterministic structure hash (16 hex chars), like the legacy engine.

        Unlike the legacy implementation this one is *stable across parses*: it
        hashes ``body`` + ``language`` only, deliberately excluding ``metadata``
        (which historically carried a process-local ``hash(tree)`` value and made
        the legacy digest non-reproducible).  Locations are excluded by default so
        a v2 tree and its legacy equivalent produce the same digest.
        """
        payload = json.dumps(
            {
                "body": [to_serializable(node, include_location) for node in self.body],
                "language": self.language,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def structure_digest(self, include_location: bool = False) -> str:
        """Alias of :meth:`canonical_hash` (structural identity)."""
        return self.canonical_hash(include_location=include_location)

    def merkle_hash(self) -> str:
        """Incremental (Merkle) digest — O(changed path) after in-place edits."""
        from muta_ext.uast2.merkle import root_digest

        return root_digest(self)

    def invalidate_hashes(self) -> None:
        """Drop every cached Merkle digest in the document."""
        for node in self.walk():
            node._hash = None

    # ── Serialisation ───────────────────────────────────────────────────────
    def to_dict(
        self, include_location: bool = True, include_engine: bool = False
    ) -> Dict[str, Any]:
        """Legacy-compatible dict form (``body``/``language``/``metadata``)."""
        payload: Dict[str, Any] = {
            "body": [to_serializable(node, include_location) for node in self.body],
            "language": self.language,
            "metadata": to_serializable(self.metadata, include_location),
        }
        if include_engine:
            payload["engine"] = self.engine
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any], strict: bool = False) -> "CoreUAST":
        """Rebuild a document from :meth:`to_dict` output (legacy dicts included)."""
        body_payload = data.get("body", [])
        body = from_serializable(body_payload, strict=strict)
        if not isinstance(body, list):
            body = [body]
        return cls(
            body=body,
            language=data.get("language", "python"),
            metadata=dict(data.get("metadata") or {}),
            engine=data.get("engine", "v2"),
        )

    # ── Document-level editing (body nodes are roots: no parent pointer) ────
    def insert(self, index: int, node: UASTNode) -> UASTNode:
        """Insert a root node into ``body`` at *index*."""
        self.body.insert(index, node)
        node._parent = None
        node._slot = None
        _invalidate_document(self)
        return node

    def remove(self, node: UASTNode) -> bool:
        """Remove a root node from ``body``; returns ``True`` when it was present."""
        for index, item in enumerate(self.body):
            if item is node:
                self.body.pop(index)
                node._parent = None
                node._slot = None
                _invalidate_document(self)
                return True
        return False

    def append(self, node: UASTNode) -> UASTNode:
        """Append a root node to ``body``."""
        return self.insert(len(self.body), node)

    # ── Misc ────────────────────────────────────────────────────────────────
    def emit(self, language: Optional[str] = None) -> str:
        """Emit source code through the (reused) legacy emitters."""
        from muta_ext.uast2.emitters import emit

        return emit(self, language)

    def __len__(self) -> int:
        return len(self.body)

    def __iter__(self) -> T.Iterator[UASTNode]:
        return iter(self.body)
