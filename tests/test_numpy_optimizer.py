"""
Tests for numpy_optimizer — real AST transformations for NumPy code.

These verify that the optimizer performs *actual* code rewrites (not comments
or "mark for LLM" stubs) and that each rewrite is semantically equivalent to
the original for array inputs.
"""

import ast

import numpy as np
import pytest

from numpy_optimizer import (
    NumPyBroadcastOptimizer,
    NumPyEinsumOptimizer,
    NumPyMemoryLayoutOptimizer,
    NumPyMutator,
    NumPyVectorizer,
    generate_numpy_variants,
)


def _run(code, fn_name, args):
    ns = {"np": np}
    exec(compile(code, "<test>", "exec"), ns, ns)
    return ns[fn_name](*args)


# ── Vectorization ───────────────────────────────────────────────────────────

VECTORIZE_SRC = """\
def f(n):
    result = [0] * n
    for i in range(n):
        result[i] = i * 2
    return result
"""


class TestVectorizer:
    def test_produces_real_code_not_comment(self):
        out = NumPyMutator().apply_mutation(VECTORIZE_SRC, "vectorize_loop")
        assert "MUTALAMBDA_VECTORIZE" not in out
        assert "#" not in out.splitlines()[0]
        assert "np.arange" in out

    def test_no_crash_on_vectorizable_loop(self):
        # Regression: previously raised AttributeError (ast.Comment missing).
        out = NumPyMutator().apply_mutation(VECTORIZE_SRC, "vectorize_loop")
        ast.parse(out)  # must be valid Python

    def test_semantically_equivalent(self):
        out = NumPyMutator().apply_mutation(VECTORIZE_SRC, "vectorize_loop")
        assert list(_run(out, "f", (5,))) == [0, 2, 4, 6, 8]

    def test_adds_numpy_import(self):
        out = NumPyMutator().apply_mutation(VECTORIZE_SRC, "vectorize_loop")
        assert "import numpy as np" in out

    def test_skips_non_vectorizable_loop(self):
        src = "def g(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total\n"
        out = NumPyMutator().apply_mutation(src, "vectorize_loop")
        # Reduction loop is not this transform's job — must remain a loop.
        assert "for i in range(n)" in out
        assert "np.arange" not in out


# ── Einsum ──────────────────────────────────────────────────────────────────

class TestEinsum:
    def test_adds_optimize_true(self):
        src = (
            "import numpy as np\n"
            "def g(A, B):\n    return np.einsum('ij,jk->ik', A, B)\n"
        )
        out = NumPyMutator().apply_mutation(src, "einsum_matmul")
        assert "optimize=True" in out

    def test_idempotent(self):
        src = (
            "import numpy as np\n"
            "def g(A, B):\n    return np.einsum('ij,jk->ik', A, B, optimize=True)\n"
        )
        out = NumPyMutator().apply_mutation(src, "einsum_matmul")
        assert out.count("optimize=True") == 1

    def test_semantically_equivalent(self):
        src = (
            "import numpy as np\n"
            "def g(A, B, C):\n    return np.einsum('ij,jk,kl->il', A, B, C)\n"
        )
        out = NumPyMutator().apply_mutation(src, "einsum_matmul")
        A = np.random.rand(2, 3)
        B = np.random.rand(3, 4)
        C = np.random.rand(4, 2)
        assert np.allclose(_run(src, "g", (A, B, C)), _run(out, "g", (A, B, C)))


# ── Broadcasting ────────────────────────────────────────────────────────────

BROADCAST_SRC = """\
import numpy as np
def h(A, B):
    C = np.zeros((len(A), len(B)))
    for i in range(len(A)):
        for j in range(len(B)):
            C[i][j] = A[i] + B[j]
    return C
"""


class TestBroadcast:
    def test_rewrites_nested_loop(self):
        out = NumPyMutator().apply_mutation(BROADCAST_SRC, "broadcast_ops")
        assert "for i in range" not in out
        assert "[:, None]" in out
        assert "[None, :]" in out

    def test_semantically_equivalent(self):
        out = NumPyMutator().apply_mutation(BROADCAST_SRC, "broadcast_ops")
        A = np.array([1.0, 2.0, 3.0])
        B = np.array([10.0, 20.0])
        assert np.allclose(_run(BROADCAST_SRC, "h", (A, B)), _run(out, "h", (A, B)))


# ── Memory layout ───────────────────────────────────────────────────────────

class TestMemoryLayout:
    def test_pins_c_order(self):
        src = "import numpy as np\ndef k(n):\n    a = np.zeros((n, n))\n    return a\n"
        out = NumPyMutator().apply_mutation(src, "memory_layout")
        assert "order='C'" in out

    def test_semantically_equivalent(self):
        src = "import numpy as np\ndef k(n):\n    a = np.zeros((n, n))\n    return a\n"
        out = NumPyMutator().apply_mutation(src, "memory_layout")
        assert np.array_equal(_run(src, "k", (3,)), _run(out, "k", (3,)))


# ── Analysis & variants ─────────────────────────────────────────────────────

class TestAnalyzeAndVariants:
    def test_analyze_detects_vectorizable_loop(self):
        result = NumPyMutator().analyze(VECTORIZE_SRC)
        assert result["loop_vectorization"] is True
        assert result["optimizable"] is True

    def test_analyze_detects_broadcast(self):
        result = NumPyMutator().analyze(BROADCAST_SRC)
        assert result["broadcasting"] is True

    def test_generate_variants_returns_real_transforms(self):
        variants = generate_numpy_variants(VECTORIZE_SRC, n=4)
        assert len(variants) >= 1
        for v in variants:
            ast.parse(v)
            assert v != VECTORIZE_SRC

    def test_apply_mutation_auto_returns_valid_code(self):
        out = NumPyMutator().apply_mutation(VECTORIZE_SRC, "auto")
        ast.parse(out)


# ── Transformer classes are independently usable ────────────────────────────

class TestTransformerInstances:
    def test_vectorizer_records_changes(self):
        tree = ast.parse(VECTORIZE_SRC)
        v = NumPyVectorizer()
        v.visit(tree)
        assert "loop_to_vectorized" in v.changes_made

    def test_einsum_records_changes(self):
        tree = ast.parse(
            "import numpy as np\ndef g(A, B):\n    return np.einsum('ij,jk->ik', A, B)\n"
        )
        e = NumPyEinsumOptimizer()
        e.visit(tree)
        assert "einsum_optimize_true" in e.changes_made

    def test_broadcast_records_changes(self):
        tree = ast.parse(BROADCAST_SRC)
        b = NumPyBroadcastOptimizer()
        b.visit(tree)
        assert "broadcast_nested_loop" in b.changes_made

    def test_memory_layout_records_changes(self):
        tree = ast.parse("import numpy as np\ndef k(n):\n    a = np.zeros((n, n))\n    return a\n")
        m = NumPyMemoryLayoutOptimizer()
        m.visit(tree)
        assert "pin_c_order" in m.changes_made
