#!/usr/bin/env python3
"""Structural, schema, math and security verification for UAST v2.

Every verifier is a :class:`~muta_ext.uast2.passes.Pass` whose ``run`` is a no-op,
so the same objects can be registered in a :class:`~muta_ext.uast2.passes.Pipeline`
and executed after each mutation.  This module is where the "confiable" half of
the playbook lives — and it deliberately *reuses* the existing tooling:

* ``muta_ext.uast.validators.UASTValidator`` → :class:`LegacyValidatorVerify`
* ``ast_math_verifier.ASTMathVerifier``       → :class:`MathFidelityVerify`
* ``mutation_filters.run_all_filters``        → :class:`SecurityGate`

Optional dependencies degrade into *warnings*, never crashes.
"""

from __future__ import annotations

import typing as T
from typing import Any, Callable, Dict, List, Optional

from muta_ext.uast2.core import (
    KIND_NODE,
    KIND_NODE_DICT,
    KIND_NODE_LIST,
    UASTNode,
    CoreUAST,
    child_kinds,
    iter_child_nodes_any,
    required_fields,
    walk,
)
from muta_ext.uast2.passes import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Diagnostic,
    MutationPass,
    Pass,
    Pipeline,
)

__all__ = [
    "ChildSchemaVerify",
    "ParentLinkVerify",
    "StructuralVerify",
    "LegacyValidatorVerify",
    "MathFidelityVerify",
    "NumericSanityVerify",
    "SecurityGate",
    "default_pipeline",
    "verify_tree",
]

#: Expected child-kind per node type, derived from the UAST v2 field schema.
_SCHEMA: Dict[str, Dict[str, str]] = {}


def _schema_for(node: UASTNode) -> Dict[str, str]:
    name = type(node).__name__
    kinds = _SCHEMA.get(name)
    if kinds is None:
        kinds = child_kinds(type(node))
        _SCHEMA[name] = kinds
    return kinds


def _scan_tree(root: CoreUAST) -> T.Iterator[T.Tuple[Any, bool]]:
    """Yield ``(node, repeated)`` in pre-order, flagging shares and cycles.

    One traversal does everything the structural checks need: v2 nodes are
    walked through their cached field plans (no generator per node) and legacy
    dataclasses fall back to duck-typed children.  ``repeated`` is ``True`` when
    a node is reachable twice (shared subtree) or is its own ancestor (cycle) —
    both are hard errors for in-place mutation.
    """
    seen: T.Set[int] = set()
    path: T.Set[int] = set()
    stack: List[T.Tuple[Any, bool]] = [
        (node, False) for node in reversed(list(root.body))
    ]
    while stack:
        node, exiting = stack.pop()
        if exiting:
            path.discard(id(node))
            continue
        identity = id(node)
        if identity in path or identity in seen:
            yield node, True
            continue
        seen.add(identity)
        path.add(identity)
        yield node, False
        stack.append((node, True))
        if isinstance(node, UASTNode):
            children: List[Any] = []
            for name, kind in _node_plan(type(node)):
                value = getattr(node, name)
                if kind is KIND_NODE:
                    if value is not None:
                        children.append(value)
                elif kind is KIND_NODE_LIST:
                    if value is None:
                        continue
                    if type(value) is list:
                        children.extend(value)
                    else:
                        children.append(value)
                elif kind is KIND_NODE_DICT and value:
                    children.extend(value.values())
        else:  # pragma: no cover - legacy fallback (defensive)
            children = [item for item in iter_child_nodes_any(node) if item is not None]
        for child in reversed(children):
            stack.append((child, False))


_PLANS: Dict[str, T.Tuple[T.Tuple[str, str], ...]] = {}


def _scan_scope(scope: T.Sequence[Any]) -> T.Iterator[T.Tuple[Any, bool]]:
    """Like :func:`_scan_tree` but limited to the given (sub)tree roots."""
    seen: T.Set[int] = set()
    stack: List[T.Tuple[Any, bool]] = [(node, False) for node in reversed(list(scope))]
    while stack:
        node, exiting = stack.pop()
        identity = id(node)
        if identity in seen:
            yield node, True
            continue
        seen.add(identity)
        yield node, False
        if isinstance(node, UASTNode):
            children: List[Any] = []
            for name, kind in _node_plan(type(node)):
                value = getattr(node, name)
                if kind is KIND_NODE:
                    if value is not None:
                        children.append(value)
                elif kind is KIND_NODE_LIST:
                    if value is None:
                        continue
                    children.extend(value) if type(value) is list else children.append(value)
                elif kind is KIND_NODE_DICT and value:
                    children.extend(value.values())
        else:  # pragma: no cover - legacy fallback (defensive)
            children = [item for item in iter_child_nodes_any(node) if item is not None]
        for child in reversed(children):
            stack.append((child, False))


def _iter_checks(
    root: CoreUAST, scope: Optional[T.Sequence[Any]]
) -> T.Iterator[T.Tuple[Any, bool]]:
    """Nodes to check: the whole document, or only the touched subtrees."""
    if scope is None:
        return _scan_tree(root)
    return _scan_scope(scope)


def _node_plan(node_type: type) -> T.Tuple[T.Tuple[str, str], ...]:
    """Cached ``((field, kind), ...)`` plan for a node class."""
    plan = _PLANS.get(node_type.__name__)
    if plan is None:
        kinds = child_kinds(node_type)
        plan = _PLANS[node_type.__name__] = tuple(
            (name, kinds.get(name, "")) for name in node_type._fields
        )
    return plan


class StructuralVerify(Pass):
    """Invariants that must hold for *any* well-formed v2 tree."""

    name = "structural"
    mutating = False
    description = "Required fields present, unique parents, sane locations, no cycles."

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:  # noqa: D102
        return None

    def verify(  # noqa: C901 - explicit checks
        self, root: CoreUAST, scope: Optional[Any] = None
    ) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        append = diagnostics.append
        for node, repeated in _iter_checks(root, scope):
            if repeated:
                append(
                    Diagnostic(
                        SEVERITY_ERROR,
                        "Node reachable more than once (shared subtree or cycle)",
                        self.name,
                        node,
                        code="cycle_or_share",
                    )
                )
                continue
            if not isinstance(node, UASTNode):  # pragma: no cover - defensive
                append(
                    Diagnostic(SEVERITY_ERROR, f"Non-node object in tree: {node!r}", self.name)
                )
                continue

            node_type = type(node)
            for field_name in required_fields(node_type):
                if getattr(node, field_name, None) is None:
                    append(
                        Diagnostic(
                            SEVERITY_ERROR,
                            f"{node_type.__name__}.{field_name} is required but None",
                            self.name,
                            node,
                            code="missing_required_field",
                        )
                    )

            if node.lineno is not None and node.lineno < 0:
                append(
                    Diagnostic(
                        SEVERITY_ERROR,
                        f"Negative line number ({node.lineno})",
                        self.name,
                        node,
                        code="bad_location",
                    )
                )
            if node.tag is not None and not isinstance(node.tag, str):
                append(
                    Diagnostic(
                        SEVERITY_WARNING,
                        f"Non-string tag: {node.tag!r}",
                        self.name,
                        node,
                        code="bad_tag",
                    )
                )
            if node_type.__name__ == "Opaque" and not getattr(node, "original_text", ""):
                append(
                    Diagnostic(
                        SEVERITY_ERROR,
                        "Opaque node without original_text",
                        self.name,
                        node,
                        code="empty_opaque",
                    )
                )
        return diagnostics


class ChildSchemaVerify(Pass):
    """Checks every child slot against the declared schema (per node type)."""

    name = "child_schema"
    mutating = False
    description = "Field kinds (node / node-list / node-dict) respected per node type."

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:  # noqa: D102
        return None

    def verify(self, root: CoreUAST, scope: Optional[Any] = None) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        for node, repeated in _iter_checks(root, scope):
            if repeated or not isinstance(node, UASTNode):
                continue
            for field_name, kind in _schema_for(node).items():
                value = getattr(node, field_name, None)
                if value is None:
                    continue
                if kind == KIND_NODE:
                    if not isinstance(value, UASTNode):
                        diagnostics.append(
                            self._diag(node, field_name, kind, value)
                        )
                elif kind in (KIND_NODE_LIST, KIND_NODE_DICT):
                    if kind == KIND_NODE_LIST and isinstance(value, UASTNode):
                        continue  # ``Assign.target`` accepts a single node too
                    elements = value.values() if isinstance(value, dict) else value
                    if not isinstance(elements, (list, tuple)) and not hasattr(elements, "__iter__"):
                        diagnostics.append(self._diag(node, field_name, kind, value))
                        continue
                    for index, item in enumerate(elements):
                        if not isinstance(item, UASTNode):
                            diagnostics.append(
                                self._diag(node, f"{field_name}[{index}]", kind, item)
                            )
        return diagnostics

    def _diag(self, node: UASTNode, field: str, kind: str, value: Any) -> Diagnostic:
        return Diagnostic(
            SEVERITY_ERROR,
            f"{type(node).__name__}.{field} expects {kind}, got "
            f"{type(value).__name__} ({value!r:.60})",
            self.name,
            node,
            code="child_schema",
        )


class ParentLinkVerify(Pass):
    """Confirms parent pointers agree with the actual tree structure."""

    name = "parent_links"
    mutating = False
    description = "Every child's _parent/_slot matches its real position."

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:  # noqa: D102
        return None

    def verify(self, root: CoreUAST, scope: Optional[Any] = None) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        for parent, repeated in _iter_checks(root, scope):
            if repeated or not isinstance(parent, UASTNode):
                continue
            for child, slot in parent.iter_child_slots():
                if child._parent is None:
                    continue  # tree not prepared (arena disabled) — not an error
                if child._parent is not parent or child._slot != slot:
                    diagnostics.append(
                        Diagnostic(
                            SEVERITY_ERROR,
                            f"Stale parent link on {type(child).__name__}: "
                            f"expected slot {slot!r} of {type(parent).__name__}",
                            self.name,
                            child,
                            code="stale_parent_link",
                        )
                    )
        return diagnostics


class LegacyValidatorVerify(Pass):
    """Reuses the frozen ``UASTValidator`` as a v2 verification pass.

    ``Opaque`` findings are downgraded to warnings: an Opaque node is a legitimate
    (if unmutatable) construct in UAST, not an error — the legacy validator is
    stricter because it is used for mutation-safety gating.
    """

    name = "legacy_validator"
    per_pass_guard = False
    mutating = False
    description = "Wraps muta_ext.uast.validators.UASTValidator over the legacy view."

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:  # noqa: D102
        return None

    def verify(self, root: CoreUAST, scope: Optional[Any] = None) -> List[Diagnostic]:
        try:
            from muta_ext.uast.validators import UASTValidator
        except Exception as exc:  # pragma: no cover - optional import
            return [
                Diagnostic(
                    SEVERITY_WARNING,
                    f"legacy validator unavailable: {exc}",
                    self.name,
                    code="validator_unavailable",
                )
            ]
        diagnostics: List[Diagnostic] = []
        for message in UASTValidator.validate_structure(root.to_legacy()):
            severity = (
                SEVERITY_WARNING if message.startswith("Unrecognized construct") else SEVERITY_ERROR
            )
            diagnostics.append(
                Diagnostic(severity, message, self.name, code="legacy_validator")
            )
        return diagnostics


class MathFidelityVerify(Pass):
    """Arithmetic-fidelity gate built on ``ast_math_verifier`` (SymPy/Z3).

    Two modes:

    * with ``original_source`` — emits the (mutated) v2 document and asks the
      existing verifier whether arithmetic semantics are preserved;
    * without it — skips silently (documented as a warning once) because
      equivalence needs a reference program.
    """

    name = "math_fidelity"
    per_pass_guard = False
    mutating = False
    description = "Reuses ast_math_verifier for algebraic equivalence after mutation."

    def __init__(
        self,
        original_source: Optional[str] = None,
        emitter: Optional[Callable[[CoreUAST], str]] = None,
        severity: str = SEVERITY_ERROR,
        language: str = "python",
    ) -> None:
        super().__init__()
        self.original_source = original_source
        self.emitter = emitter
        self.severity = severity
        self.language = language
        self.enabled = original_source is not None

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:  # noqa: D102
        return None

    def verify(self, root: CoreUAST, scope: Optional[Any] = None) -> List[Diagnostic]:
        if self.original_source is None:
            return []
        if self.language != "python":
            return [
                Diagnostic(
                    SEVERITY_WARNING,
                    f"math fidelity check skipped for language {self.language!r}",
                    self.name,
                    code="unsupported_language",
                )
            ]
        try:
            from ast_math_verifier import ASTMathVerifier
        except Exception as exc:  # pragma: no cover - optional dependency
            return [
                Diagnostic(
                    SEVERITY_WARNING,
                    f"ast_math_verifier unavailable: {exc}",
                    self.name,
                    code="verifier_unavailable",
                )
            ]
        try:
            mutated_source = (self.emitter or (lambda doc: doc.emit()))(root)
        except Exception as exc:
            return [
                Diagnostic(
                    SEVERITY_ERROR,
                    f"could not emit mutated source for verification: {exc}",
                    self.name,
                    code="emit_failed",
                )
            ]
        # Cheap, deterministic guard first: a mutation that changes the multiset
        # of numeric literals cannot preserve arithmetic semantics (``x + 1`` →
        # ``x + 999``), while reorderings such as ``1 + x`` still pass because
        # the comparison is order-insensitive.
        drift = _literal_drift(self.original_source, mutated_source)
        if drift is not None:
            return [
                Diagnostic(
                    self.severity,
                    f"numeric literals changed: {drift}",
                    self.name,
                    code="math_mismatch",
                )
            ]
        try:
            result = ASTMathVerifier().verify(self.original_source, mutated_source)
        except Exception as exc:  # pragma: no cover - defensive
            return [
                Diagnostic(
                    SEVERITY_WARNING,
                    f"math verifier crashed: {type(exc).__name__}: {exc}",
                    self.name,
                    code="verifier_crash",
                )
            ]
        if getattr(result, "is_equivalent", True):
            return []
        message = getattr(result, "message", "") or "arithmetic semantics changed"
        return [Diagnostic(self.severity, message, self.name, code="math_mismatch")]


def _numeric_literals(source: str) -> Optional[T.List[float]]:
    """Sorted multiset of numeric literals in *source*, or ``None`` if unparsable."""
    import ast as stdlib_ast

    try:
        tree = stdlib_ast.parse(source)
    except SyntaxError:
        return None
    values: T.List[float] = []
    for node in stdlib_ast.walk(tree):
        if isinstance(node, stdlib_ast.Constant) and isinstance(node.value, (int, float)):
            if not isinstance(node.value, bool):
                values.append(float(node.value))
        elif isinstance(node, stdlib_ast.Num):  # pragma: no cover - py<3.8 shim
            values.append(float(node.n))
    return sorted(values)


def _literal_drift(original_source: str, mutated_source: str) -> Optional[str]:
    """Describe how numeric literals differ, or ``None`` when they are equivalent."""
    before = _numeric_literals(original_source)
    after = _numeric_literals(mutated_source)
    if before is None or after is None or before == after:
        return None
    return f"{before} -> {after}"


class NumericSanityVerify(Pass):
    """Tree-level numeric checks (catches mutation side effects early)."""

    name = "numeric_sanity"
    mutating = False
    description = "No NaN/inf literals introduced, no literal division by zero."

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:  # noqa: D102
        return None

    def verify(self, root: CoreUAST, scope: Optional[Any] = None) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        for node, repeated in _iter_checks(root, scope):
            if repeated or not isinstance(node, UASTNode):
                continue
            if type(node).__name__ == "LiteralNode":
                value = getattr(node, "value", None)
                if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
                    diagnostics.append(
                        Diagnostic(
                            SEVERITY_ERROR,
                            f"Non-finite literal introduced: {value}",
                            self.name,
                            node,
                            code="non_finite_literal",
                        )
                    )
            elif type(node).__name__ == "BinaryOp" and getattr(node, "op", None) == "/":
                right = getattr(node, "right", None)
                if (
                    right is not None
                    and type(right).__name__ == "LiteralNode"
                    and getattr(right, "value", None) in (0, 0.0)
                ):
                    diagnostics.append(
                        Diagnostic(
                            SEVERITY_WARNING,
                            "Division by literal zero",
                            self.name,
                            node,
                            code="division_by_zero",
                        )
                    )
        return diagnostics


#: Names that must never appear in a mutated candidate (tree-level backstop).
_BANNED_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "input",
    "system",
    "popen",
    "Popen",
    "call",
    "check_output",
    "run",
    "socket",
    "urlopen",
    "requests",
}
_BANNED_ATTRIBUTES = {"system", "popen", "spawn", "execv", "execve", "remove", "rmtree", "unlink"}


class SecurityGate(Pass):
    """Reuses ``mutation_filters`` as the security pass, with a tree-level backstop.

    Source-level mode (default when the document can be emitted) runs the
    repository's own filter suite; the AST-level checks always run so the gate
    still protects candidates whose language has no emitter configured.
    """

    name = "security"
    per_pass_guard = False
    mutating = False
    description = "Reuses mutation_filters.run_all_filters + banned-call AST scan."

    def __init__(self, profile: str = "balanced", source: Optional[str] = None) -> None:
        super().__init__()
        self.profile = profile
        self.source = source

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:  # noqa: D102
        return None

    def verify(self, root: CoreUAST, scope: Optional[Any] = None) -> List[Diagnostic]:
        diagnostics = self._verify_tree(root)
        source = self.source
        if source is None:
            try:
                source = root.emit()
            except Exception:
                source = None
        if source:
            diagnostics.extend(self._verify_source(source))
        return diagnostics

    # ── tree level (always available) ───────────────────────────────────────
    def _verify_tree(self, root: CoreUAST) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        from muta_ext.uast2.core import Call, Identifier

        for node in walk(root):
            if isinstance(node, Call):
                func = node.func
                name = func.name if isinstance(func, Identifier) else None
                if name in _BANNED_CALLS:
                    diagnostics.append(
                        Diagnostic(
                            SEVERITY_ERROR,
                            f"Banned call introduced: {name}()",
                            self.name,
                            node,
                            code="banned_call",
                        )
                    )
            elif isinstance(node, Identifier) and node.name in _BANNED_ATTRIBUTES:
                diagnostics.append(
                    Diagnostic(
                        SEVERITY_WARNING,
                        f"Sensitive identifier present: {node.name}",
                        self.name,
                        node,
                        code="sensitive_identifier",
                    )
                )
        return diagnostics

    # ── source level (reuses mutation_filters) ──────────────────────────────
    def _verify_source(self, source: str) -> List[Diagnostic]:
        try:
            from mutation_filters import run_all_filters
        except Exception as exc:  # pragma: no cover - optional import
            return [
                Diagnostic(
                    SEVERITY_WARNING,
                    f"mutation_filters unavailable: {exc}",
                    self.name,
                    code="filters_unavailable",
                )
            ]
        try:
            report = run_all_filters(source, profile=self.profile)
        except Exception as exc:  # pragma: no cover - defensive
            return [
                Diagnostic(
                    SEVERITY_WARNING,
                    f"mutation_filters crashed: {type(exc).__name__}: {exc}",
                    self.name,
                    code="filters_crash",
                )
            ]
        passed = getattr(report, "passed", True)
        if passed:
            return []
        issues = getattr(report, "issues", None) or []
        messages = [
            getattr(issue, "message", None) or str(issue) for issue in issues
        ] or ["security filters rejected the candidate"]
        return [
            Diagnostic(SEVERITY_ERROR, message, self.name, code="security_filter")
            for message in messages
        ]


def verify_tree(root: CoreUAST, passes: Optional[T.Sequence[Pass]] = None) -> List[Diagnostic]:
    """Convenience: run a list of verifiers (defaults to the standard set)."""
    pipeline = Pipeline(passes or default_verifiers(root), strict=False, rollback=False)
    return pipeline.verify_only(root)


def default_verifiers(root: Optional[CoreUAST] = None) -> List[Pass]:
    """The standard verification set (structure, schema, parents, legacy rules)."""
    return [
        StructuralVerify(),
        ChildSchemaVerify(),
        ParentLinkVerify(),
        LegacyValidatorVerify(),
        NumericSanityVerify(),
    ]


def default_pipeline(
    strict: bool = False,
    original_source: Optional[str] = None,
    language: str = "python",
    security_profile: str = "balanced",
) -> Pipeline:
    """Standard v2 pipeline: security gate + structural + math fidelity.

    The returned pipeline contains verification passes plus the built-in
    in-place mutators (imported lazily to avoid a circular dependency).
    """
    from muta_ext.uast2.mutators import default_mutators

    passes: List[Pass] = [SecurityGate(profile=security_profile)]
    passes.extend(default_verifiers())
    mutators = default_mutators()
    if all(getattr(pass_, "preserves_math", True) for pass_ in mutators):
        passes.append(MathFidelityVerify(original_source=original_source, language=language))
    passes.extend(mutators)
    return Pipeline(passes, strict=strict, rollback=True)
