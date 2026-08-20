"""
NumPy Optimizer — AST mutations specific to NumPy optimization.

Provides targeted transformations for NumPy code:
- Loop vectorization
- Einsum optimization
- Broadcasting optimization
- Memory layout optimization
"""

from __future__ import annotations

import ast
import copy
import random
from typing import List, Optional, Tuple


class NumPyVectorizer(ast.NodeTransformer):
    """Transform Python loops into NumPy vectorized operations."""

    def __init__(self):
        self.changes_made = []

    def visit_For(self, node: ast.For) -> ast.AST:
        """Convert simple accumulation loops to NumPy operations."""
        self.generic_visit(node)

        # Pattern: for i in range(n): result[i] = expr(i)
        if (len(node.body) == 1 and 
            isinstance(node.body[0], ast.Assign) and
            isinstance(node.body[0].targets[0], ast.Subscript)):

            # Check if it's a simple range loop
            if (isinstance(node.iter, ast.Call) and
                isinstance(node.iter.func, ast.Name) and
                node.iter.func.id == 'range'):

                self.changes_made.append("loop_to_vectorized")
                # Mark for LLM-based transformation
                return ast.Comment(f"# MUTALAMBDA_VECTORIZE: {ast.unparse(node)}") 

        return node


class NumPyEinsumOptimizer(ast.NodeTransformer):
    """Optimize matrix operations using einsum."""

    def __init__(self):
        self.changes_made = []

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        """Detect matrix multiplication patterns."""
        self.generic_visit(node)

        # Pattern: A @ B or matmul(A, B)
        if isinstance(node.op, ast.MatMult):
            self.changes_made.append("matmul_detected")

        return node


class NumPyBroadcastOptimizer(ast.NodeTransformer):
    """Optimize operations using broadcasting."""

    def __init__(self):
        self.changes_made = []

    def visit_For(self, node: ast.For) -> ast.AST:
        """Detect broadcasting opportunities."""
        self.generic_visit(node)

        # Pattern: for i in range(n): for j in range(m): result[i][j] = A[i] + B[j]
        if (len(node.body) == 1 and isinstance(node.body[0], ast.For)):
            self.changes_made.append("broadcasting_opportunity")

        return node


class NumPyMutator:
    """Apply NumPy-specific mutations to Python code."""

    def __init__(self):
        self.vectorizer = NumPyVectorizer()
        self.einsum = NumPyEinsumOptimizer()
        self.broadcast = NumPyBroadcastOptimizer()

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
            # Check for numpy import
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if 'numpy' in alias.name or alias.name == 'np':
                        opportunities["has_numpy_import"] = True

            if isinstance(node, ast.ImportFrom):
                if node.module and ('numpy' in node.module or node.module == 'np'):
                    opportunities["has_numpy_import"] = True

            # Detect loops that could be vectorized
            if isinstance(node, ast.For):
                if self._is_vectorizable_loop(node):
                    opportunities["loop_vectorization"] = True

            # Detect matmul patterns
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult):
                opportunities["einsum_candidates"] = True

        # Calculate optimization score
        score = 0.0
        if opportunities["has_numpy_import"]:
            score += 0.3
        if opportunities["loop_vectorization"]:
            score += 0.4
        if opportunities["einsum_candidates"]:
            score += 0.2
        if opportunities["broadcasting"]:
            score += 0.1

        opportunities["score"] = min(score, 1.0)
        opportunities["optimizable"] = score > 0.3

        return opportunities

    def _is_vectorizable_loop(self, node: ast.For) -> bool:
        """Check if a loop can be vectorized."""
        # Simple heuristic: range-based loop with array assignment
        if not isinstance(node.iter, ast.Call):
            return False
        if not (isinstance(node.iter.func, ast.Name) and node.iter.func.id == 'range'):
            return False

        # Check body for array operations
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                if isinstance(stmt.targets[0], ast.Subscript):
                    return True
        return False

    def apply_mutation(self, code: str, mutation_type: str = "auto") -> str:
        """Apply a NumPy-specific mutation."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code

        if mutation_type == "auto":
            # Pick random mutation
            mutation_type = random.choice([
                "vectorize_loop",
                "einsum_matmul",
                "broadcast_ops",
                "memory_layout",
            ])

        mutated = copy.deepcopy(tree)

        if mutation_type == "vectorize_loop":
            mutated = self.vectorizer.visit(mutated)
        elif mutation_type == "einsum_matmul":
            mutated = self.einsum.visit(mutated)
        elif mutation_type == "broadcast_ops":
            mutated = self.broadcast.visit(mutated)

        try:
            ast.fix_missing_locations(mutated)
            result = ast.unparse(mutated)
            return result
        except Exception:
            return code


def generate_numpy_variants(code: str, n: int = 5) -> List[str]:
    """Generate n optimized variants of NumPy code."""
    mutator = NumPyMutator()
    variants = []

    mutations = [
        "vectorize_loop",
        "einsum_matmul", 
        "broadcast_ops",
        "memory_layout",
    ]

    for i in range(n):
        mutation = mutations[i % len(mutations)]
        variant = mutator.apply_mutation(code, mutation)
        if variant != code:
            variants.append(variant)

    return variants
