#!/usr/bin/env python3
"""Adapters for UAST v2 — parse source into mutable nodes *with* locations.

Two strategies are used, both reusing what already works:

* **Python** — a native adapter that mirrors the frozen legacy visitor exactly
  (so shadow mode reports zero structural differences) but *additionally*
  records ``lineno``/``col_offset``/``end_lineno``/``end_col_offset`` and stores
  a deterministic ``source_hash`` in the metadata.
* **Rust / C++ / Go** — the legacy tree-sitter adapters are reused verbatim and
  their output is converted with :func:`muta_ext.uast2.convert.legacy_to_v2`.
  Optional best-effort location enrichment reuses the adapter's own ``_visit``
  to align top-level declarations with their tree-sitter nodes (no guessing).

Everything degrades gracefully: importing this module never requires
tree-sitter, and requesting an unavailable language raises
:class:`AdapterUnavailable` with an actionable message.
"""

from __future__ import annotations

import ast as stdlib_ast
import sys
import typing as T
from typing import Any, Dict, List, Optional

from code_hash import stable_code_hash

from muta_ext.uast2 import core as v2
from muta_ext.uast2.convert import legacy_to_v2

__all__ = [
    "AdapterUnavailable",
    "BaseAdapterV2",
    "PythonAdapterV2",
    "RustAdapterV2",
    "CppAdapterV2",
    "GoAdapterV2",
    "get_adapter_v2",
    "parse_to_uast",
    "parse_to_arena",
    "available_languages",
    "register_adapter",
]

TREE_SITTER_AVAILABLE = True
try:  # pragma: no cover - environment dependent
    import tree_sitter  # noqa: F401
except ImportError:  # pragma: no cover
    TREE_SITTER_AVAILABLE = False


class AdapterUnavailable(RuntimeError):
    """Raised when an optional parser dependency is missing."""


class BaseAdapterV2:
    """Base adapter contract for the v2 engine."""

    language: str = ""

    def can_parse(self, source: str) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def parse_to_uast(self, source: str, **kwargs: Any) -> v2.CoreUAST:  # pragma: no cover
        raise NotImplementedError

    def parse_to_arena(self, source: str, arena: Any, **kwargs: Any) -> v2.CoreUAST:
        """Parse and allocate every node in *arena* (parents assigned too)."""
        uast = self.parse_to_uast(source, **kwargs)
        uast.prepare(arena)
        return uast

    @staticmethod
    def _metadata(source: str, engine: str) -> Dict[str, Any]:
        """Deterministic metadata (stable across processes, unlike ``hash(tree)``)."""
        return {
            "source_hash": stable_code_hash(source)[:16],
            "source_length": len(source),
            "engine": engine,
        }


# ── Python ───────────────────────────────────────────────────────────────────


class PythonAdapterV2(BaseAdapterV2):
    """Python → UAST v2 using the stdlib ``ast`` module (locations included).

    Two dialects are available (the "dialects instead of one universal AST"
    lesson from the design note):

    ``extended=False`` (default)
        Mirrors ``muta_ext.uast.adapters.python_adapter.PythonAdapter``
        node-for-node, so **shadow mode reports zero differences** and parity
        with the frozen engine is guaranteed.  ``tests/uast2/test_shadow.py``
        enforces that over every file in ``examples/``.
    ``extended=True``
        Additionally lowers the constructs the legacy adapter leaves as
        ``Opaque`` and that matter most for mutation: comparisons, boolean
        operators and augmented assignments become real nodes
        (``BinaryOp``/``Assign``), so condition-flip and folding passes can act
        on them.  Conservative rules keep emission faithful: chained
        comparisons, nested boolean expressions and non-trivial augmented
        targets stay ``Opaque``.
    """

    language = "python"

    _CMP_OPS = {
        stdlib_ast.Eq: "==",
        stdlib_ast.NotEq: "!=",
        stdlib_ast.Lt: "<",
        stdlib_ast.LtE: "<=",
        stdlib_ast.Gt: ">",
        stdlib_ast.GtE: ">=",
        stdlib_ast.Is: "is",
        stdlib_ast.IsNot: "is not",
        stdlib_ast.In: "in",
        stdlib_ast.NotIn: "not in",
    }

    # Operator tables mirroring the legacy adapter exactly.
    _BIN_OPS = {
        stdlib_ast.Add: "+",
        stdlib_ast.Sub: "-",
        stdlib_ast.Mult: "*",
        stdlib_ast.Div: "/",
        stdlib_ast.Mod: "%",
        stdlib_ast.And: "and",
        stdlib_ast.Or: "or",
        stdlib_ast.Eq: "==",
        stdlib_ast.Lt: "<",
        stdlib_ast.LtE: "<=",
        stdlib_ast.Gt: ">",
        stdlib_ast.GtE: ">=",
    }
    _UNARY_OPS = {stdlib_ast.Not: "not", stdlib_ast.USub: "-", stdlib_ast.UAdd: "+"}

    def __init__(
        self,
        use_tree_sitter: bool = False,
        extended: bool = False,
        with_locations: bool = True,
    ) -> None:
        # ``use_tree_sitter`` is kept for constructor compatibility with the
        # legacy adapter; the stdlib parser is always used because it is faster
        # and gives exact locations.
        self.use_tree_sitter = False
        self.extended = extended
        #: ``False`` skips source coordinates — exactly the legacy adapter's
        #: behaviour (less memory, faster parse, useful for pure parity work).
        self.with_locations = with_locations

    # ── Public API ──────────────────────────────────────────────────────────
    def can_parse(self, source: str) -> bool:
        """Return ``True`` when *source* is valid Python."""
        try:
            stdlib_ast.parse(source)
            return True
        except SyntaxError:
            return False

    def parse_to_uast(
        self, source: str, extended: Optional[bool] = None, use_cache: bool = True, **kwargs: Any
    ) -> v2.CoreUAST:
        """Parse *source* into a mutable v2 document (locations filled in).

        ``use_cache`` reuses the repository's LRU parse cache
        (:func:`code_hash.cached_parse`): evolutionary loops re-emit the same
        candidate many times, and the cached stdlib AST is never mutated (v2
        builds fresh nodes), so the cache is safe here and removes the dominant
        cost of repeated parses.
        """
        previous = self.extended
        if extended is not None:
            self.extended = bool(extended)
        try:
            if use_cache:
                from code_hash import cached_parse

                tree = cached_parse(source)
            else:
                tree = stdlib_ast.parse(source)
            body = [self._visit(node) for node in tree.body]
        except SyntaxError as exc:
            raise ValueError(f"Cannot parse Python source: {exc}") from exc
        finally:
            self.extended = previous
        metadata = self._metadata(source, "uast2.python")
        metadata["dialect"] = "extended" if (extended or previous) else "legacy-parity"
        return v2.CoreUAST(
            body=[node for node in body if node is not None],
            language="python",
            metadata=metadata,
        )

    # ── Visitor plumbing ────────────────────────────────────────────────────
    def _visit(self, node: Optional[stdlib_ast.AST]) -> Optional[v2.UASTNode]:
        if node is None:
            return None
        visitor = getattr(self, f"_visit_{node.__class__.__name__}", self._visit_unknown)
        result = visitor(node)
        if result is not None and result.lineno is None:
            self._with_loc(result, node)
        return result

    def _with_loc(self, node: v2.UASTNode, stdlib_node: stdlib_ast.AST) -> v2.UASTNode:
        """Copy source coordinates from a stdlib AST node onto a v2 node."""
        if not self.with_locations:
            return node
        node.lineno = getattr(stdlib_node, "lineno", None)
        node.col_offset = getattr(stdlib_node, "col_offset", None)
        node.end_lineno = getattr(stdlib_node, "end_lineno", None)
        node.end_col_offset = getattr(stdlib_node, "end_col_offset", None)
        return node

    @staticmethod
    def _unparse(node: stdlib_ast.AST) -> str:
        return stdlib_ast.unparse(node) if hasattr(stdlib_ast, "unparse") else str(node)

    # ── Literals / names ────────────────────────────────────────────────────
    def _visit_Constant(self, node: stdlib_ast.Constant) -> v2.LiteralNode:
        value = node.value
        type_hint = None
        # NOTE: mirrors the legacy adapter exactly (no bool branch → ``True`` gets
        # "i64", because ``isinstance(True, int)`` is True).  Divergence here would
        # show up as a shadow-mode mismatch, and shadow parity is a hard gate.
        if isinstance(value, int):
            type_hint = "i64"
        elif isinstance(value, float):
            type_hint = "f64"
        elif isinstance(value, str):
            type_hint = "str"
        return self._with_loc(v2.LiteralNode(value=value, type_hint=type_hint), node)

    def _visit_Name(self, node: stdlib_ast.Name) -> v2.Identifier:
        return self._with_loc(v2.Identifier(name=node.id), node)

    # ── Expressions ─────────────────────────────────────────────────────────
    def _visit_BinOp(self, node: stdlib_ast.BinOp) -> v2.BinaryOp:
        op = self._BIN_OPS.get(type(node.op), "?")
        return self._with_loc(
            v2.BinaryOp(left=self._visit(node.left), op=op, right=self._visit(node.right)), node
        )

    def _visit_UnaryOp(self, node: stdlib_ast.UnaryOp) -> v2.UnaryOp:
        op = self._UNARY_OPS.get(type(node.op), "?")
        return self._with_loc(v2.UnaryOp(op=op, operand=self._visit(node.operand)), node)

    def _visit_Call(self, node: stdlib_ast.Call) -> v2.Call:
        func = (
            self._visit(node.func)
            if isinstance(node.func, stdlib_ast.Name)
            else v2.Identifier(name="unknown")
        )
        args = [self._visit(arg) for arg in node.args]
        keywords = {kw.arg: self._visit(kw.value) for kw in node.keywords if kw.arg}
        return self._with_loc(
            v2.Call(func=func, args=[a for a in args if a is not None], keywords=keywords), node
        )

    # ── Extended dialect (opt-in: real conditions instead of Opaque) ─────────
    def _visit_Compare(self, node: stdlib_ast.Compare) -> v2.UASTNode:
        """Lower a simple comparison to ``BinaryOp`` (chained ones stay Opaque)."""
        if not self.extended or len(node.ops) != 1:
            return self._visit_unknown(node)
        op = self._CMP_OPS.get(type(node.ops[0]))
        if op is None:
            return self._visit_unknown(node)
        return self._with_loc(
            v2.BinaryOp(
                left=self._visit(node.left), op=op, right=self._visit(node.comparators[0])
            ),
            node,
        )

    def _visit_BoolOp(self, node: stdlib_ast.BoolOp) -> v2.UASTNode:
        """Lower ``and``/``or`` chains to left-associative ``BinaryOp``.

        Nested boolean expressions are left as ``Opaque`` because the reused
        emitter does not add parentheses; keeping them opaque preserves exact
        source semantics.
        """
        if not self.extended or len(node.values) < 2:
            return self._visit_unknown(node)
        if any(isinstance(value, stdlib_ast.BoolOp) for value in node.values):
            return self._visit_unknown(node)
        op = "and" if isinstance(node.op, stdlib_ast.And) else "or"
        expression = self._visit(node.values[0])
        for value in node.values[1:]:
            expression = v2.BinaryOp(left=expression, op=op, right=self._visit(value))
        return self._with_loc(expression, node)

    def _visit_AugAssign(self, node: stdlib_ast.AugAssign) -> v2.UASTNode:
        """Lower ``x += y`` to ``Assign(x, BinaryOp(x, '+', y))`` (simple names)."""
        if not self.extended or not isinstance(node.target, stdlib_ast.Name):
            return self._visit_unknown(node)
        op = self._BIN_OPS.get(type(node.op), "?")
        if op == "?":
            return self._visit_unknown(node)
        target = self._visit(node.target)
        mirrored = v2.Identifier(name=node.target.id)
        self._with_loc(mirrored, node.target)
        return self._with_loc(
            v2.Assign(
                target=target,
                value=v2.BinaryOp(left=mirrored, op=op, right=self._visit(node.value)),
            ),
            node,
        )

    # ── Statements ──────────────────────────────────────────────────────────
    def _visit_Assign(self, node: stdlib_ast.Assign) -> v2.Assign:
        targets = [self._visit(t) for t in node.targets if isinstance(t, stdlib_ast.Name)]
        target = targets[0] if len(targets) == 1 else targets
        return self._with_loc(v2.Assign(target=target, value=self._visit(node.value)), node)

    def _visit_If(self, node: stdlib_ast.If) -> v2.If:
        return self._with_loc(
            v2.If(
                condition=self._visit(node.test),
                then_body=[self._visit(n) for n in node.body],
                else_body=[self._visit(n) for n in node.orelse] if node.orelse else None,
            ),
            node,
        )

    def _visit_For(self, node: stdlib_ast.For) -> v2.For:
        return self._with_loc(
            v2.For(
                var=self._visit(node.target),
                iterable=self._visit(node.iter),
                body=[self._visit(n) for n in node.body],
            ),
            node,
        )

    def _visit_While(self, node: stdlib_ast.While) -> v2.While:
        return self._with_loc(
            v2.While(condition=self._visit(node.test), body=[self._visit(n) for n in node.body]),
            node,
        )

    def _visit_Return(self, node: stdlib_ast.Return) -> v2.Return:
        return self._with_loc(
            v2.Return(value=self._visit(node.value) if node.value else None), node
        )

    def _visit_FunctionDef(self, node: stdlib_ast.FunctionDef) -> v2.Function:
        params = [v2.Identifier(name=arg.arg) for arg in node.args.args]
        decorators = [
            self._visit(d) for d in node.decorator_list if isinstance(d, stdlib_ast.Call)
        ]
        return self._with_loc(
            v2.Function(
                name=v2.Identifier(name=node.name),
                params=params,
                body=[self._visit(n) for n in node.body],
                decorators=[d for d in decorators if d is not None],
            ),
            node,
        )

    def _visit_Try(self, node: stdlib_ast.Try) -> v2.TryExcept:
        except_clauses = []
        for handler in node.handlers:
            except_clauses.append(
                v2.ExceptClause(
                    exception_type=self._visit(handler.type) if handler.type else None,
                    binding=handler.name,
                    body=[self._visit(n) for n in handler.body],
                )
            )
        return self._with_loc(
            v2.TryExcept(
                body=[self._visit(n) for n in node.body],
                except_clauses=except_clauses,
                finally_body=[self._visit(n) for n in node.finalbody] if node.finalbody else None,
            ),
            node,
        )

    def _visit_ClassDef(self, node: stdlib_ast.ClassDef) -> v2.UASTNode:
        if node.decorator_list or node.bases or node.keywords:
            return self._with_loc(
                v2.Opaque(original_text=self._unparse(node), lang="python"), node
            )
        fields: List[v2.UASTNode] = []
        methods: List[v2.UASTNode] = []
        for item in node.body:
            if isinstance(item, stdlib_ast.Assign):
                for target in item.targets:
                    if isinstance(target, stdlib_ast.Name):
                        fields.append(
                            v2.FieldDef(
                                name=target.id,
                                type_annotation=None,
                                default=self._visit(item.value),
                            )
                        )
            elif isinstance(item, stdlib_ast.FunctionDef):
                methods.append(self._visit(item))
        return self._with_loc(
            v2.StructDef(name=node.name, fields=fields, methods=methods), node
        )

    def _visit_Match(self, node: stdlib_ast.Match) -> v2.UASTNode:
        if sys.version_info < (3, 10):  # pragma: no cover - old interpreters
            return v2.Opaque(original_text=self._unparse(node), lang="python")
        arms = []
        for case in node.cases:
            arms.append(
                v2.MatchArm(
                    pattern=self._visit(case.pattern),
                    guard=self._visit(case.guard) if case.guard else None,
                    body=[self._visit(n) for n in case.body],
                )
            )
        return self._with_loc(
            v2.Match(subject=self._visit(node.subject), arms=arms), node
        )

    def _visit_AnnAssign(self, node: stdlib_ast.AnnAssign) -> v2.UASTNode:
        if isinstance(node.target, stdlib_ast.Name) and node.value is not None:
            return self._with_loc(
                v2.Assign(target=self._visit(node.target), value=self._visit(node.value)), node
            )
        return self._with_loc(v2.Opaque(original_text=self._unparse(node), lang="python"), node)

    def _visit_unknown(self, node: stdlib_ast.AST) -> v2.Opaque:
        return self._with_loc(
            v2.Opaque(original_text=self._unparse(node), lang="python"), node
        )


# ── Tree-sitter backed languages (legacy adapters reused) ────────────────────


class _LegacyBackedAdapter(BaseAdapterV2):
    """Common behaviour: run the frozen legacy adapter and convert to v2."""

    language = ""
    _legacy_module = ""
    _legacy_class = ""

    def __init__(self, enrich_locations: bool = False) -> None:
        self.enrich_locations = enrich_locations
        self._legacy = None  # lazily instantiated (needs tree-sitter)

    # ── plumbing ────────────────────────────────────────────────────────────
    def _get_legacy(self) -> Any:
        if self._legacy is not None:
            return self._legacy
        try:
            import importlib

            module = importlib.import_module(self._legacy_module)
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise AdapterUnavailable(
                f"Language {self.language!r} requires tree-sitter grammars: {exc}. "
                "Install with `pip install -e .[uast]`."
            ) from exc
        try:
            self._legacy = getattr(module, self._legacy_class)()
        except Exception as exc:  # pragma: no cover - environment dependent
            raise AdapterUnavailable(
                f"Could not initialise the {self.language!r} tree-sitter parser: {exc}"
            ) from exc
        return self._legacy

    def can_parse(self, source: str) -> bool:
        return bool(self._get_legacy().can_parse(source))

    def parse_to_uast(self, source: str, **kwargs: Any) -> v2.CoreUAST:
        enrich = kwargs.pop("enrich_locations", self.enrich_locations)
        adapter = self._get_legacy()
        legacy_uast = adapter.parse_to_uast(source)
        uast = legacy_to_v2(legacy_uast)
        metadata = dict(uast.metadata or {})
        metadata.setdefault("source_hash", stable_code_hash(source)[:16])
        metadata["engine"] = f"uast2.{self.language}"
        uast.metadata = metadata
        if enrich:
            enrich_top_level_locations(adapter, source, uast)
        return uast


class RustAdapterV2(_LegacyBackedAdapter):
    """Rust → UAST v2 (tree-sitter, delegated to the frozen adapter)."""

    language = "rust"
    _legacy_module = "muta_ext.uast.adapters.rust_adapter"
    _legacy_class = "RustAdapter"


class CppAdapterV2(_LegacyBackedAdapter):
    """C++ → UAST v2 (tree-sitter, delegated to the frozen adapter)."""

    language = "cpp"
    _legacy_module = "muta_ext.uast.adapters.cpp_adapter"
    _legacy_class = "CppAdapter"


class GoAdapterV2(_LegacyBackedAdapter):
    """Go → UAST v2 (tree-sitter, delegated to the frozen adapter)."""

    language = "go"
    _legacy_module = "muta_ext.uast.adapters.go_adapter"
    _legacy_class = "GoAdapter"


def enrich_top_level_locations(adapter: Any, source: str, uast: v2.CoreUAST) -> int:
    """Attach tree-sitter coordinates to top-level v2 nodes (best effort).

    The legacy adapters build ``body`` by visiting the root's children in order,
    so re-visiting those same children with the adapter's own ``_visit`` gives an
    exact 1:1 alignment with ``uast.body`` — no heuristic text matching.
    Returns the number of top-level nodes enriched.
    """
    parser = getattr(adapter, "_parser", None)
    if parser is None:
        return 0
    try:
        tree = parser.parse(bytes(source, "utf-8") if isinstance(source, str) else source)
    except Exception:  # pragma: no cover - parser specific
        return 0
    enriched = 0
    index = 0
    for child in tree.root_node.children:
        try:
            legacy_node = adapter._visit(child, source)
        except Exception:  # pragma: no cover - defensive
            legacy_node = None
        if legacy_node is None:
            continue
        if index >= len(uast.body):
            break
        target = uast.body[index]
        index += 1
        if type(target).__name__ != type(legacy_node).__name__:
            continue
        target.lineno = child.start_point[0] + 1
        target.col_offset = child.start_point[1]
        target.end_lineno = child.end_point[0] + 1
        target.end_col_offset = child.end_point[1]
        enriched += 1
    return enriched


# ── Registry ─────────────────────────────────────────────────────────────────

_ADAPTERS: Dict[str, T.Type[BaseAdapterV2]] = {
    "python": PythonAdapterV2,
    "rust": RustAdapterV2,
    "cpp": CppAdapterV2,
    "go": GoAdapterV2,
}


def register_adapter(language: str, adapter_cls: T.Type[BaseAdapterV2]) -> None:
    """Register a custom adapter (extension point for new languages)."""
    _ADAPTERS[language] = adapter_cls


def available_languages() -> List[str]:
    """Languages with a registered v2 adapter."""
    return sorted(_ADAPTERS)


def get_adapter_v2(language: str, **kwargs: Any) -> BaseAdapterV2:
    """Instantiate the v2 adapter for *language* (raises ``ValueError`` if unknown)."""
    try:
        adapter_cls = _ADAPTERS[language]
    except KeyError as exc:
        raise ValueError(
            f"No UAST v2 adapter registered for language: {language}. "
            f"Available: {available_languages()}"
        ) from exc
    return adapter_cls(**kwargs)


def parse_to_uast(
    source: str,
    language: str = "python",
    prepare: bool = True,
    arena: Any = None,
    **kwargs: Any,
) -> v2.CoreUAST:
    """Parse *source* into a v2 document (parents assigned by default)."""
    adapter = get_adapter_v2(language)
    uast = adapter.parse_to_uast(source, **kwargs)
    if prepare or arena is not None:
        uast.prepare(arena)
    return uast


def parse_to_arena(source: str, arena: Any, language: str = "python", **kwargs: Any) -> v2.CoreUAST:
    """Parse *source* straight into an :class:`~muta_ext.uast2.arena.Arena`."""
    return parse_to_uast(source, language=language, arena=arena, **kwargs)
