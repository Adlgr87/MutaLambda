#!/usr/bin/env python3
"""CoreUAST - Universal AST representation for multi-language mutation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union
import json
import hashlib


# Forward reference for Node types
Node = Union[
    "LiteralNode", "Identifier", "BinaryOp", "UnaryOp", "Call",
    "Assign", "If", "For", "While", "Return", "Function",
    "ParallelFor", "Comment", "Opaque", "Break", "TryExcept",
    "ExceptClause", "StructDef", "FieldDef", "TypeAnnotation",
    "MatchArm", "Match", "Reference", dict
]

# Registry for deserialization
_NODE_REGISTRY: Dict[str, Any] = {}


def _register_node(cls):
    """Decorator to register node classes."""
    _NODE_REGISTRY[cls.__name__] = cls
    return cls


def _to_serializable(obj: Any) -> Any:
    """Convert object to JSON-serializable form."""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        d = {"__type__": obj.__class__.__name__}
        for f in obj.__dataclass_fields__:
            d[f] = _to_serializable(getattr(obj, f))
        return d
    return str(obj)


def _from_serializable(obj: Any, registry: Optional[Dict[str, Any]] = None) -> Any:
    """Reconstruct object from serializable form."""
    if registry is None:
        registry = _NODE_REGISTRY
    
    if isinstance(obj, dict) and "__type__" in obj:
        node_type = obj["__type__"]
        if node_type in registry:
            node_cls = registry[node_type]
            import inspect
            fields = {}
            for k, v in obj.items():
                if k != "__type__":
                    fields[k] = _from_serializable(v, registry)
            # Handle defaults for missing fields
            sig = inspect.signature(node_cls)
            for param_name, param in sig.parameters.items():
                if param_name not in fields:
                    if param.default is not inspect.Parameter.empty:
                        fields[param_name] = param.default
            return node_cls(**fields)
    if isinstance(obj, list):
        return [_from_serializable(x, registry) for x in obj]
    if isinstance(obj, dict):
        return {k: _from_serializable(v, registry) for k, v in obj.items()}
    return obj


@_register_node
@dataclass(frozen=True)
class LiteralNode:
    value: Any
    type_hint: Optional[str] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Identifier:
    name: str
    qualified: Optional[str] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class BinaryOp:
    left: Node
    op: str
    right: Node
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: Node
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Call:
    func: Identifier
    args: List[Node] = field(default_factory=list)
    keywords: Dict[str, Node] = field(default_factory=dict)
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Assign:
    target: Union[Identifier, List[Identifier]]
    value: Node
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class If:
    condition: Node
    then_body: List[Node]
    else_body: Optional[List[Node]] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class For:
    var: Identifier
    iterable: Node
    body: List[Node]
    is_traditional: bool = False
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class While:
    condition: Node
    body: List[Node]
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Return:
    value: Optional[Node] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Function:
    name: Identifier
    params: List[Identifier] = field(default_factory=list)
    body: List[Node] = field(default_factory=list)
    decorators: List[Call] = field(default_factory=list)
    return_type: Optional[str] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class ParallelFor:
    var: Identifier
    start: Node
    end: Node
    body: List[Node]
    reduction: Optional[Literal["sum", "max", "min", "prod"]] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Comment:
    text: str
    position: Literal["before", "inline", "after"] = "before"
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Opaque:
    original_text: str
    lang: str
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Break:
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class TryExcept:
    """Try/except/finally block. Maps to Rust match on Result, C++ try/catch."""
    body: List[Node] = field(default_factory=list)
    except_clauses: List["ExceptClause"] = field(default_factory=list)
    finally_body: Optional[List[Node]] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class ExceptClause:
    """Single except/catch clause."""
    exception_type: Optional[Node] = None  # None = catch-all
    binding: Optional[str] = None     # variable name for the exception
    body: List[Node] = field(default_factory=list)
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class StructDef:
    """Struct/class definition. Maps to Rust struct, C++ struct/class."""
    name: str
    fields: List["FieldDef"] = field(default_factory=list)
    methods: List[Function] = field(default_factory=list)
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class FieldDef:
    """A field in a struct/class."""
    name: str
    type_annotation: Optional[Node] = None
    default: Optional[Node] = None
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class TypeAnnotation:
    """Type annotation node. Critical for Rust (mandatory) and C++."""
    type_name: str
    generic_args: List[Node] = field(default_factory=list)
    is_reference: bool = False
    is_mutable: bool = False  # Rust &mut
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class MatchArm:
    """Pattern matching arm. Maps to Rust match, C++ pattern matching."""
    pattern: Node
    guard: Optional[Node] = None
    body: List[Node] = field(default_factory=list)
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Match:
    """Match/switch expression. Maps to Rust match, C++ switch."""
    subject: Node
    arms: List[MatchArm] = field(default_factory=list)
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@_register_node
@dataclass(frozen=True)
class Reference:
    """Reference/pointer. Maps to Rust &/&mut, C++ */&."""
    target: Node
    is_mutable: bool = False
    tag: Optional[str] = None
    location: Optional[Dict[str, int]] = None


@dataclass
class CoreUAST:
    body: List[Node]
    language: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def canonical_hash(self) -> str:
        """For evaluation cache and deduplication. Structure only."""
        payload = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d = {"body": [(_to_serializable(n) if hasattr(n, "__dataclass_fields__") else n) for n in self.body]}
        d["language"] = self.language
        d["metadata"] = _to_serializable(self.metadata)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoreUAST":
        body = _from_serializable(data.get("body", []))
        return cls(
            body=body,
            language=data.get("language", "python"),
            metadata=data.get("metadata", {})
        )
