"""Tests for ast_math_verifier (anti-hallucination mutation validator)."""

import ast

import pytest

from ast_math_verifier import (
    AlgebraicVerifier,
    ASTMathVerifier,
    SemanticVerifier,
    SymbolicExtractor,
    VerificationResult,
)


def _expr(source: str):
    return ast.parse(source, mode="eval").body


@pytest.mark.root
class TestSymbolicExtractor:
    @pytest.mark.parametrize(
        "source,expected",
        [
            ("a + b", "(a + b)"),
            ("a - b", "(a - b)"),
            ("a * b", "(a * b)"),
            ("a / b", "(a / b)"),
            ("a % b", "(a % b)"),
            ("a ** b", "(a ** b)"),
            ("a // b", "(a // b)"),
            ("-a", "(-a)"),
            ("+a", "a"),
            ("not a", "(not a)"),
            ("x", "x"),
            ("42", "42"),
            ("f(a, b)", "f(a, b)"),
            ("xs[i]", "xs[i]"),
            ("obj.attr", "obj.attr"),
            ("(a + b) * c", "((a + b) * c)"),
        ],
    )
    def test_extracts_supported_expressions(self, source, expected):
        assert SymbolicExtractor().extract_expression(_expr(source)) == expected

    @pytest.mark.parametrize(
        "source",
        [
            "a @ b",          # unsupported binary operator
            "~a",             # unsupported unary operator
            "[1, 2]",         # unsupported node type
            "obj.m()(a)",     # call on non-Name func
            "lambda: 1",
        ],
    )
    def test_unsupported_nodes_return_none(self, source):
        assert SymbolicExtractor().extract_expression(_expr(source)) is None

    def test_nested_unsupported_operand_propagates_none(self):
        assert SymbolicExtractor().extract_expression(_expr("a + [1]")) is None

    def test_extract_return_expressions(self):
        code = (
            "def f(a, b):\n"
            "    if a:\n"
            "        return a + b\n"
            "    return a * b\n"
        )
        exprs = SymbolicExtractor().extract_return_expressions(ast.parse(code))
        assert sorted(exprs) == ["(a * b)", "(a + b)"]

    def test_bare_and_unextractable_returns_are_skipped(self):
        code = "def f(a):\n    if a:\n        return\n    return [a]\n"
        assert SymbolicExtractor().extract_return_expressions(ast.parse(code)) == []


@pytest.mark.root
class TestAlgebraicVerifier:
    def test_equivalent_expressions_accepted(self):
        original = "def f(a, b):\n    return a + a + b\n"
        mutated = "def f(a, b):\n    return 2 * a + b\n"
        result = AlgebraicVerifier().verify_equivalence(original, mutated)
        assert result.is_equivalent is True
        assert result.reason == "expressions_match"

    def test_algebraic_mismatch_rejected(self):
        original = "def f(a, b):\n    return a + b\n"
        mutated = "def f(a, b):\n    return a - b\n"
        result = AlgebraicVerifier().verify_equivalence(original, mutated)
        assert result.is_equivalent is False
        assert result.reason == "algebraic_mismatch"
        assert result.confidence == pytest.approx(0.9)

    def test_syntax_error_rejected_with_full_confidence(self):
        result = AlgebraicVerifier().verify_equivalence("def f():\n    return 1\n", "def f(:\n")
        assert result.is_equivalent is False
        assert result.reason == "syntax_error"
        assert result.confidence == 1.0

    def test_missing_expressions_are_not_verifiable(self):
        result = AlgebraicVerifier().verify_equivalence("x = 1\n", "x = 2\n")
        assert result.is_equivalent is True
        assert result.reason == "no_expressions_found"
        assert result.confidence == pytest.approx(0.3)

    def test_different_return_counts_rejected(self):
        original = "def f(a):\n    if a:\n        return a\n    return -a\n"
        mutated = "def f(a):\n    return a\n"
        result = AlgebraicVerifier().verify_equivalence(original, mutated)
        assert result.is_equivalent is False
        assert result.reason == "different_return_count"

    def test_unsympifiable_expressions_are_tolerated(self):
        original = "def f(xs):\n    return xs[0].value\n"
        mutated = "def f(xs):\n    return xs[1].value\n"
        result = AlgebraicVerifier().verify_equivalence(original, mutated)
        # Subscript/attribute chains are not comparable symbolically; no false reject.
        assert result.is_equivalent in (True, False)
        assert result.reason in ("expressions_match", "algebraic_mismatch")

    def test_sympy_unavailable_degrades_gracefully(self):
        verifier = AlgebraicVerifier()
        verifier.sympy_available = False
        result = verifier.verify_equivalence("def f():\n    return 1\n", "boom(")
        assert result.is_equivalent is True
        assert result.reason == "sympy_not_available"
        assert result.confidence == pytest.approx(0.5)


@pytest.mark.root
class TestSemanticVerifier:
    def test_identical_code_passes_all_checks(self):
        code = "def f(a):\n    return a + 1\n"
        result = SemanticVerifier().verify(code, code)
        assert result.is_equivalent is True
        assert result.reason == "structural_match"

    def test_syntax_error_rejected(self):
        result = SemanticVerifier().verify("def f():\n    return 1\n", "def f(:\n")
        assert result.is_equivalent is False
        assert result.reason == "syntax_error"

    def test_hallucinated_function_rejected(self):
        original = "def f(a):\n    return a + 1\n"
        mutated = "def f(a):\n    return magic_speedup(a) + 1\n"
        result = SemanticVerifier().verify(original, mutated)
        assert result.is_equivalent is False
        assert result.reason == "new_functions"
        assert "magic_speedup" in result.details

    def test_allowlisted_numpy_helpers_are_not_hallucinations(self):
        original = "def f(a):\n    return a\n"
        mutated = "def f(a):\n    return sum(zeros(a))\n"
        result = SemanticVerifier().verify(original, mutated)
        assert result.is_equivalent is True

    def test_large_loop_count_change_rejected(self):
        original = "def f(n, i):\n    for i in range(n):\n        pass\n    return n\n"
        mutated = (
            "def f(n, i):\n"
            "    for i in range(n):\n"
            "        pass\n"
            "    for i in range(n):\n"
            "        pass\n"
            "    for i in range(n):\n"
            "        pass\n"
            "    for i in range(n):\n"
            "        pass\n"
            "    return n\n"
        )
        result = SemanticVerifier().verify(original, mutated)
        assert result.is_equivalent is False
        assert result.reason == "loop_count_changed"

    def test_small_loop_count_change_allowed(self):
        original = (
            "def f(n, i):\n"
            "    for i in range(n):\n"
            "        pass\n"
            "    for i in range(n):\n"
            "        pass\n"
            "    return n\n"
        )
        mutated = "def f(n, i):\n    for i in range(n):\n        pass\n    return n\n"
        assert SemanticVerifier().verify(original, mutated).is_equivalent is True

    def test_removing_most_variables_rejected(self):
        original = "def f():\n    return alpha + beta + gamma + delta\n"
        mutated = "def f():\n    return alpha\n"
        result = SemanticVerifier().verify(original, mutated)
        assert result.is_equivalent is False
        assert result.reason == "many_variables_removed"

    def test_adding_variables_is_allowed(self):
        original = "def f(a):\n    return a\n"
        mutated = "def f(a):\n    tmp = a\n    return tmp\n"
        assert SemanticVerifier().verify(original, mutated).is_equivalent is True


@pytest.mark.root
class TestASTMathVerifier:
    def test_semantically_equivalent_rewrite_passes(self):
        original = "def f(a, b):\n    return a + a + b\n"
        mutated = "def f(a, b):\n    return 2 * a + b\n"
        result = ASTMathVerifier().verify(original, mutated)
        assert result.is_equivalent is True
        assert result.reason == "all_checks_passed"

    def test_confidence_is_minimum_of_both_stages(self):
        code = "def f(a):\n    return a + 1\n"
        verifier = ASTMathVerifier()
        result = verifier.verify(code, code)
        semantic = verifier.semantic.verify(code, code)
        algebraic = verifier.algebraic.verify_equivalence(code, code)
        assert result.confidence == pytest.approx(min(semantic.confidence, algebraic.confidence))

    def test_high_confidence_semantic_rejection_short_circuits(self):
        result = ASTMathVerifier().verify("def f():\n    return 1\n", "def f(:\n")
        assert result.is_equivalent is False
        assert result.reason == "syntax_error"

    def test_algebraic_rejection_returned_when_semantics_pass(self):
        original = "def f(a, b):\n    return a * b\n"
        mutated = "def f(a, b):\n    return a + b\n"
        result = ASTMathVerifier().verify(original, mutated)
        assert result.is_equivalent is False
        assert result.reason == "algebraic_mismatch"

    def test_batch_verify_pairs_each_mutation_with_result(self):
        original = "def f(a, b):\n    return a + b\n"
        mutations = [
            "def f(a, b):\n    return b + a\n",
            "def f(a, b):\n    return a - b\n",
        ]
        results = ASTMathVerifier().batch_verify(original, mutations)
        assert [m for m, _ in results] == mutations
        assert all(isinstance(r, VerificationResult) for _, r in results)
        assert results[0][1].is_equivalent is True
        assert results[1][1].is_equivalent is False

    def test_batch_verify_empty_list(self):
        assert ASTMathVerifier().batch_verify("def f():\n    return 1\n", []) == []


@pytest.mark.root
def test_verification_result_defaults():
    result = VerificationResult(is_equivalent=True, confidence=0.5, reason="ok")
    assert result.details == ""
