"""
NumPy Optimizer — real AST transformations for NumPy code.

Unlike the previous heuristic detector (which emitted ``# MUTALAMBDA_VECTORIZE``
comments and deferred the actual work to an LLM), this module now performs the
transformations directly on the AST:

- ``NumPyVectorizer`` converts element-wise accumulation loops into vectorized
  ``np.arange`` expressions.
- ``NumPyEinsumOptimizer`` enables optimal contraction paths on existing
  ``np.einsum`` calls.
- ``NumPyBroadcastOptimizer`` rewrites canonical nested loops into NumPy
  broadcasting (outer products / pairwise operations).
- ``NumPyMemoryLayoutOptimizer`` pins an explicit contiguous ``order='C'`` on
  array constructors.

Every transform is a *syntactic* rewrite; semantic correctness is always
verified afterwards by the evolution engine's test suite (or the pipeline's
regression tests) — never assumed.
"""

from __future__ import annotations

import ast
import copy
import random
from typing import Any, List, Optional, Set


# ── Shared helpers ─────────────────────────────────────────────────────────

def _has_numpy_import(tree: ast.Module) -> bool:
    """True if the module already imports numpy (any common form)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "numpy" or alias.name.startswith("numpy."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("numpy"):
                return True
    return False


def _ensure_numpy_import(tree: ast.Module) -> ast.Module:
    """Prepend ``import numpy as np`` if numpy is not already imported."""
    if _has_numpy_import(tree):
        return tree

    import_node = ast.Import(names=[ast.alias(name="numpy", asname="np")])
    ast.fix_missing_locations(import_node)

    # Keep module docstring (if any) at the very top.
    insert_at = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        insert_at = 1

    tree.body.insert(insert_at, import_node)
    ast.fix_missing_locations(tree)
    return tree


def _range_bound(node: ast.AST) -> Optional[ast.AST]:
    """Return the bound expression of ``range(bound)`` or None."""
    if not isinstance(node, ast.Call):
        return None
    if not (isinstance(node.func, ast.Name) and node.func.id == "range"):
        return None
    if len(node.args) != 1:
        return None
    return node.args[0]


def _is_simple_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name)


# ── Element-wise loop vectorization ────────────────────────────────────────

class _LoopVarSubstituter(ast.NodeTransformer):
    """Replace every *load* of ``var`` with ``np.arange(bound)``."""

    def __init__(self, var: str, bound: ast.AST):
        self.var = var
        self.bound = bound

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id == self.var and isinstance(node.ctx, ast.Load):
            arange = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="np", ctx=ast.Load()),
                    attr="arange",
                    ctx=ast.Load(),
                ),
                args=[self.bound],
                keywords=[],
            )
            ast.copy_location(arange, node)
            return arange
        return node


class NumPyVectorizer(ast.NodeTransformer):
    """Transform ``for i in range(n): result[i] = expr(i)`` into a vectorized
    ``result = <expr with np.arange(n)>`` assignment."""

    def __init__(self):
        self.changes_made: List[str] = []
        self.needs_numpy = False

    def visit_For(self, node: ast.For) -> ast.AST:
        transformed = self._try_vectorize(node)
        if transformed is not None:
            self.changes_made.append("loop_to_vectorized")
            self.needs_numpy = True
            return transformed
        self.generic_visit(node)
        return node

    def _try_vectorize(self, node: ast.For) -> Optional[ast.AST]:
        # Body must be a single assignment to a subscript.
        if len(node.body) != 1:
            return None
        stmt = node.body[0]
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]
        if not isinstance(target, ast.Subscript):
            return None
        if not isinstance(target.value, ast.Name):
            return None

        # Loop iterable must be range(bound).
        bound = _range_bound(node.iter)
        if bound is None:
            return None

        # Loop variable must be a simple name.
        if not isinstance(node.target, ast.Name):
            return None
        loop_var = node.target.id

        # Index must be exactly the loop variable.
        idx = target.slice
        if not (isinstance(idx, ast.Name) and idx.id == loop_var):
            return None

        arr_name = target.value.id
        try:
            new_expr = _LoopVarSubstituter(loop_var, bound).visit(stmt.value)
        except Exception:
            return None
        if new_expr is None or not isinstance(new_expr, ast.AST):
            return None

        assign = ast.Assign(
            targets=[ast.Name(id=arr_name, ctx=ast.Store())],
            value=new_expr,
        )
        ast.copy_location(assign, stmt)
        return assign


# ── Keyword injection on np.* calls ────────────────────────────────────────

class _NpKeywordInjector(ast.NodeTransformer):
    """Add a constant keyword argument to matching ``np.<func>(...)`` calls.

    Subclasses declare the target functions, the keyword to inject and the
    label recorded in ``changes_made``.
    """

    functions: Set[str] = set()
    keyword: str = ""
    value: Any = None
    change_label: str = ""

    def __init__(self):
        self.changes_made: List[str] = []
        self.needs_numpy = False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "np"
            and node.func.attr in self.functions
        ):
            if not any(kw.arg == self.keyword for kw in node.keywords):
                node.keywords.append(
                    ast.keyword(arg=self.keyword, value=ast.Constant(value=self.value))
                )
                self.changes_made.append(self.change_label)
                self.needs_numpy = True
        return node


class NumPyEinsumOptimizer(_NpKeywordInjector):
    """Add ``optimize=True`` to existing ``np.einsum`` calls.

    This lets NumPy use an optimal contraction path (a real speed-up for
    multi-operand contractions) without changing the computation.
    """

    functions = {"einsum"}
    keyword = "optimize"
    value = True
    change_label = "einsum_optimize_true"


# ── Broadcasting (nested loops → outer product) ────────────────────────────

class NumPyBroadcastOptimizer(ast.NodeTransformer):
    """Rewrite the canonical nested loop

        for i in range(n):
            for j in range(m):
                C[i][j] = A[i] <op> B[j]

    into the vectorized broadcast

        C = A[:, None] <op> B[None, :]
    """

    def __init__(self):
        self.changes_made: List[str] = []
        self.needs_numpy = False

    def visit_For(self, node: ast.For) -> ast.AST:
        transformed = self._try_broadcast(node)
        if transformed is not None:
            self.changes_made.append("broadcast_nested_loop")
            self.needs_numpy = True
            return transformed
        self.generic_visit(node)
        return node

    def _try_broadcast(self, node: ast.For) -> Optional[ast.AST]:
        # Outer loop body is exactly one inner loop.
        if len(node.body) != 1 or not isinstance(node.body[0], ast.For):
            return None
        inner = node.body[0]
        if len(inner.body) != 1:
            return None
        stmt = inner.body[0]
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return None
        target = stmt.targets[0]

        # Target shape: C[i][j]
        if not (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Subscript)
        ):
            return None
        c_node = target.value.value
        i_node = target.value.slice
        j_node = target.slice
        if not (
            isinstance(c_node, ast.Name)
            and isinstance(i_node, ast.Name)
            and isinstance(j_node, ast.Name)
        ):
            return None

        # Loop variables must match the subscript indices.
        if not (isinstance(node.target, ast.Name) and node.target.id == i_node.id):
            return None
        if not (isinstance(inner.target, ast.Name) and inner.target.id == j_node.id):
            return None

        # Value must be a binary operation A[i] <op> B[j].
        value = stmt.value
        if not isinstance(value, ast.BinOp):
            return None

        left = self._as_outer(value.left, i_node.id, "col")
        right = self._as_outer(value.right, j_node.id, "row")
        if left is None or right is None:
            return None

        new_value = ast.BinOp(left=left, op=value.op, right=right)
        assign = ast.Assign(
            targets=[ast.Name(id=c_node.id, ctx=ast.Store())],
            value=new_value,
        )
        ast.copy_location(assign, stmt)
        return assign

    @staticmethod
    def _as_outer(node: ast.AST, var: str, orientation: str) -> Optional[ast.AST]:
        """Rewrite ``A[var]`` into ``A[:, None]`` (col) or ``A[None, :]`` (row)."""
        if not isinstance(node, ast.Subscript):
            return None
        arr = node.value
        idx = node.slice
        if not (isinstance(idx, ast.Name) and idx.id == var):
            return None
        if not isinstance(arr, ast.Name):
            return None

        colon = ast.Slice(lower=None, upper=None, step=None)
        none = ast.Constant(value=None)
        if orientation == "col":
            tup = ast.Tuple(elts=[colon, none], ctx=ast.Load())
        else:
            tup = ast.Tuple(elts=[none, colon], ctx=ast.Load())

        result = ast.Subscript(value=arr, slice=tup, ctx=ast.Load())
        ast.copy_location(result, node)
        return result


# ── Memory layout ──────────────────────────────────────────────────────────

class NumPyMemoryLayoutOptimizer(_NpKeywordInjector):
    """Pin an explicit contiguous ``order='C'`` on array constructors.

    Explicit layout avoids a run-time layout decision and ensures the arrays
    used by vectorized C-order operations are contiguous. Equivalent to the
    default for Python-list inputs, so it is a safe rewrite.
    """

    _CONSTRUCTORS = {"array", "zeros", "ones", "empty", "full"}

    functions = _CONSTRUCTORS
    keyword = "order"
    value = "C"
    change_label = "pin_c_order"


# ── Orchestrator ───────────────────────────────────────────────────────────

class NumPyMutator:
    """Apply real NumPy-specific transformations to Python code."""

    def __init__(self):
        self.vectorizer = NumPyVectorizer()
        self.einsum = NumPyEinsumOptimizer()
        self.broadcast = NumPyBroadcastOptimizer()
        self.memory_layout = NumPyMemoryLayoutOptimizer()

    # ── Analysis (unchanged API) ──────────────────────────────────────────

    def analyze(self, code: str) -> dict:
        """Analyze code for NumPy optimization opportunities."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {"optimizable": False, "reason": "syntax_error"}

        opportunities = {
            "has_numpy_import": False,
            "loop_vectorization": False,
            "einsum_candidates": False,
            "broadcasting": False,
            "memory_layout": False,
            "score": 0.0,
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "numpy" or alias.name == "np":
                        opportunities["has_numpy_import"] = True
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("numpy"):
                    opportunities["has_numpy_import"] = True

            if isinstance(node, ast.For):
                if self._is_vectorizable_loop(node):
                    opportunities["loop_vectorization"] = True
                if self._is_broadcast_loop(node):
                    opportunities["broadcasting"] = True

            if isinstance(node, ast.Call) and self._is_einsum(node):
                opportunities["einsum_candidates"] = True

            if isinstance(node, ast.Call) and self._is_constructor(node):
                opportunities["memory_layout"] = True

        score = 0.0
        if opportunities["has_numpy_import"]:
            score += 0.1
        if opportunities["loop_vectorization"]:
            score += 0.4
        if opportunities["einsum_candidates"]:
            score += 0.2
        if opportunities["broadcasting"]:
            score += 0.2
        if opportunities["memory_layout"]:
            score += 0.1

        opportunities["score"] = min(score, 1.0)
        opportunities["optimizable"] = score > 0.3

        return opportunities

    def _is_vectorizable_loop(self, node: ast.For) -> bool:
        if _range_bound(node.iter) is None:
            return False
        if not isinstance(node.target, ast.Name):
            return False
        if len(node.body) != 1:
            return False
        stmt = node.body[0]
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        if not isinstance(target, ast.Subscript):
            return False
        idx = target.slice
        return isinstance(idx, ast.Name) and idx.id == node.target.id

    def _is_broadcast_loop(self, node: ast.For) -> bool:
        if len(node.body) != 1 or not isinstance(node.body[0], ast.For):
            return False
        inner = node.body[0]
        if len(inner.body) != 1:
            return False
        stmt = inner.body[0]
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            return False
        target = stmt.targets[0]
        return (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Subscript)
            and isinstance(stmt.value, ast.BinOp)
        )

    @staticmethod
    def _is_einsum(node: ast.Call) -> bool:
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "np"
            and node.func.attr == "einsum"
        )

    @staticmethod
    def _is_constructor(node: ast.Call) -> bool:
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "np"
            and node.func.attr in NumPyMemoryLayoutOptimizer._CONSTRUCTORS
        )

    # ── Transformation ────────────────────────────────────────────────────

    def apply_mutation(self, code: str, mutation_type: str = "auto") -> str:
        """Apply a real NumPy-specific transformation and return the new code."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code

        if mutation_type == "auto":
            mutation_type = random.choice([
                "vectorize_loop",
                "einsum_matmul",
                "broadcast_ops",
                "memory_layout",
            ])

        transformers = {
            "vectorize_loop": self.vectorizer,
            "einsum_matmul": self.einsum,
            "broadcast_ops": self.broadcast,
            "memory_layout": self.memory_layout,
        }
        transformer = transformers.get(mutation_type)
        if transformer is None:
            return code

        mutated = transformer.visit(tree)
        if not isinstance(mutated, ast.Module):
            return code

        if getattr(transformer, "needs_numpy", False):
            mutated = _ensure_numpy_import(mutated)

        try:
            ast.fix_missing_locations(mutated)
            return ast.unparse(mutated)
        except Exception:
            return code


def generate_numpy_variants(code: str, n: int = 5) -> List[str]:
    """Generate n transformed variants of NumPy code.

    Variants are produced by the real AST transformers (not the LLM). Each is
    the result of applying one specific transformation to the source.
    """
    mutator = NumPyMutator()
    variants: List[str] = []
    seen: set = set()

    mutations = [
        "vectorize_loop",
        "einsum_matmul",
        "broadcast_ops",
        "memory_layout",
    ]

    for i in range(n):
        mutation = mutations[i % len(mutations)]
        variant = mutator.apply_mutation(code, mutation)
        if variant != code and variant not in seen:
            seen.add(variant)
            variants.append(variant)

    return variants
