"""Tests para operadores de dominio científicos."""
import pytest
from muta_ext.uast.core_uast import CoreUAST, LiteralNode, Identifier, BinaryOp, Function
from muta_ext.uast.mutators.scientific.strength_reduction import StrengthReductionMutator
from muta_ext.uast.mutators.scientific.numerical_stability import NumericalStabilityMutator


class TestStrengthReduction:
    """Tests para StrengthReductionMutator."""

    def test_square_to_multiply(self):
        uast = CoreUAST([
            Function(Identifier("f"), [Identifier("x")],
                     [BinaryOp(Identifier("x"), "**", LiteralNode(2))])
        ], "python")
        r = StrengthReductionMutator().mutate(uast, rng_seed=42)
        if r.applied:
            assert "Reduced" in r.description

    def test_no_change_unmatched(self):
        uast = CoreUAST([
            Function(Identifier("f"), [Identifier("x")],
                     [BinaryOp(Identifier("x"), "+", LiteralNode(2))])
        ], "python")
        r = StrengthReductionMutator().mutate(uast, rng_seed=42)
        assert not r.applied


class TestNumericalStability:
    """Tests para NumericalStabilityMutator."""

    def test_reassociation(self):
        uast = CoreUAST([
            Function(Identifier("f"), [Identifier("a"), Identifier("b"), Identifier("c")],
                     [BinaryOp(BinaryOp(Identifier("a"), "+", Identifier("b")), "-", Identifier("c"))])
        ], "python")
        r = NumericalStabilityMutator().mutate(uast, rng_seed=42)
        if r.applied:
            assert "Stabilized" in r.description

    def test_no_change_simple(self):
        uast = CoreUAST([
            Function(Identifier("f"), [Identifier("x"), Identifier("y")],
                     [BinaryOp(Identifier("x"), "+", Identifier("y"))])
        ], "python")
        r = NumericalStabilityMutator().mutate(uast, rng_seed=42)
        assert not r.applied


class TestBaseInterface:
    """Tests para interfaz base de mutadores."""

    def test_names(self):
        assert StrengthReductionMutator().name() == "strength_reduction"
        assert NumericalStabilityMutator().name() == "numerical_stability"

    def test_tags(self):
        t = StrengthReductionMutator().domain_tags()
        assert t["domain"] == "scientific"

    def test_find_functions(self):
        uast = CoreUAST([
            Function(Identifier("f"), [], []),
            Function(Identifier("g"), [], []),
        ], "python")
        f = StrengthReductionMutator().find_functions(uast)
        assert len(f) == 2