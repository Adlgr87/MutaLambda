"""Public API fingerprinting for candidate promotion gates (ML-F03).

Extracts a structural fingerprint of a Python module's public surface
(functions, classes, signatures, public imports) and rejects candidates
that break the baseline API under a strict policy.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class FunctionFingerprint:
    name: str
    arg_names: Tuple[str, ...]
    defaults_count: int
    has_varargs: bool
    has_varkw: bool
    is_async: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arg_names": list(self.arg_names),
            "defaults_count": self.defaults_count,
            "has_varargs": self.has_varargs,
            "has_varkw": self.has_varkw,
            "is_async": self.is_async,
        }


@dataclass(frozen=True)
class ClassFingerprint:
    name: str
    methods: Tuple[str, ...]
    bases: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "methods": list(self.methods),
            "bases": list(self.bases),
        }


@dataclass
class APIFingerprint:
    """Public surface of a candidate module."""

    functions: Dict[str, FunctionFingerprint] = field(default_factory=dict)
    classes: Dict[str, ClassFingerprint] = field(default_factory=dict)
    public_imports: Set[str] = field(default_factory=set)
    parse_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "functions": {k: v.to_dict() for k, v in self.functions.items()},
            "classes": {k: v.to_dict() for k, v in self.classes.items()},
            "public_imports": sorted(self.public_imports),
            "parse_error": self.parse_error,
        }

    @property
    def ok(self) -> bool:
        return not self.parse_error


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def extract_api_fingerprint(code: str) -> APIFingerprint:
    """Build an APIFingerprint from source code."""
    fp = APIFingerprint()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        fp.parse_error = f"syntax_error:{exc}"
        return fp

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_public(node.name):
                continue
            args = node.args
            arg_names = tuple(a.arg for a in args.args if a.arg != "self")
            fp.functions[node.name] = FunctionFingerprint(
                name=node.name,
                arg_names=arg_names,
                defaults_count=len(args.defaults),
                has_varargs=args.vararg is not None,
                has_varkw=args.kwarg is not None,
                is_async=isinstance(node, ast.AsyncFunctionDef),
            )
        elif isinstance(node, ast.ClassDef):
            if not _is_public(node.name):
                continue
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _is_public(item.name) or item.name in {"__init__", "__call__"}:
                        methods.append(item.name)
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)
            fp.classes[node.name] = ClassFingerprint(
                name=node.name,
                methods=tuple(methods),
                bases=tuple(bases),
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if _is_public(root):
                    fp.public_imports.add(root)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if _is_public(root):
                fp.public_imports.add(root)
    return fp


@dataclass
class APICompatibilityResult:
    compatible: bool
    policy: str
    missing_functions: List[str] = field(default_factory=list)
    signature_mismatches: List[str] = field(default_factory=list)
    missing_classes: List[str] = field(default_factory=list)
    missing_methods: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compatible": self.compatible,
            "policy": self.policy,
            "missing_functions": self.missing_functions,
            "signature_mismatches": self.signature_mismatches,
            "missing_classes": self.missing_classes,
            "missing_methods": self.missing_methods,
            "messages": self.messages,
        }


def compare_api(
    baseline: APIFingerprint,
    candidate: APIFingerprint,
    *,
    policy: str = "strict",
) -> APICompatibilityResult:
    """Compare candidate API against baseline.

    Policies:
    - strict: all public functions/classes/methods and signatures must match
    - relaxed: function names must exist; arity may grow (extra optional args ok)
    """
    policy = (policy or "strict").lower()
    result = APICompatibilityResult(compatible=True, policy=policy)

    if not baseline.ok:
        result.messages.append(f"baseline_unusable:{baseline.parse_error}")
        result.compatible = False
        return result
    if not candidate.ok:
        result.messages.append(f"candidate_unusable:{candidate.parse_error}")
        result.compatible = False
        return result

    for name, bfn in baseline.functions.items():
        cfn = candidate.functions.get(name)
        if cfn is None:
            result.missing_functions.append(name)
            continue
        if policy == "strict":
            if cfn.arg_names != bfn.arg_names:
                result.signature_mismatches.append(
                    f"{name}:args {list(cfn.arg_names)} != {list(bfn.arg_names)}"
                )
            if cfn.is_async != bfn.is_async:
                result.signature_mismatches.append(f"{name}:async mismatch")
            if cfn.has_varargs != bfn.has_varargs or cfn.has_varkw != bfn.has_varkw:
                result.signature_mismatches.append(f"{name}:varargs mismatch")
        else:  # relaxed
            if len(cfn.arg_names) < len(bfn.arg_names):
                result.signature_mismatches.append(
                    f"{name}:fewer args {len(cfn.arg_names)} < {len(bfn.arg_names)}"
                )

    for name, bcls in baseline.classes.items():
        ccls = candidate.classes.get(name)
        if ccls is None:
            result.missing_classes.append(name)
            continue
        missing = [m for m in bcls.methods if m not in ccls.methods]
        if missing:
            result.missing_methods.extend(f"{name}.{m}" for m in missing)

    if (
        result.missing_functions
        or result.signature_mismatches
        or result.missing_classes
        or result.missing_methods
    ):
        result.compatible = False
        result.messages.append("api_incompatible")
    else:
        result.messages.append("api_compatible")
    return result


def fingerprint_from_callable(fn: Any) -> FunctionFingerprint:
    """Build fingerprint from a live Python callable (optional helper)."""
    sig = inspect.signature(fn)
    params = [
        p
        for p in sig.parameters.values()
        if p.name not in {"self", "cls"}
    ]
    return FunctionFingerprint(
        name=getattr(fn, "__name__", "anonymous"),
        arg_names=tuple(p.name for p in params if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )),
        defaults_count=sum(1 for p in params if p.default is not inspect.Parameter.empty),
        has_varargs=any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params),
        has_varkw=any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params),
        is_async=inspect.iscoroutinefunction(fn),
    )
