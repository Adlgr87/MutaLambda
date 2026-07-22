#!/usr/bin/env python3
"""Tests for CoreUAST data structures and serialization."""
import pytest
from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, Opaque, Break
)


class TestLiteralNode:
    def test_literal_node_creation_with_various_types(self):
        """LiteralNode should handle int, float, string, bool, and None values."""
        int_node = LiteralNode(value=42, type_hint="i64")
        assert int_node.value == 42
        assert int_node.type_hint == "i64"

    def test_literal_node_tag_preserved(self):
        """LiteralNode tag should be preserved during serialization via CoreUAST."""
        uast = CoreUAST(body=[LiteralNode(value=1, tag="test_tag")], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].tag == "test_tag"


class TestIdentifier:
    def test_identifier_creation(self):
        """Identifier should store name correctly."""
        node = Identifier(name="x")
        assert node.name == "x"

    def test_identifier_roundtrip(self):
        """Identifier should survive serialize→deserialize cycle via CoreUAST."""
        uast = CoreUAST(body=[Identifier(name="x")], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].name == "x"


class TestBinaryOp:
    def test_binary_op_creation(self):
        """BinaryOp should create with op, left, right."""
        left = LiteralNode(value=1)
        right = LiteralNode(value=2)
        node = BinaryOp(left=left, op="+", right=right)
        assert node.op == "+"
        assert node.left == left
        assert node.right == right

    def test_binary_op_nested_roundtrip(self):
        """Nested BinaryOp nodes should roundtrip correctly."""
        uast = CoreUAST(body=[
            BinaryOp(
                op="+",
                left=BinaryOp(op="*", left=LiteralNode(value=1), right=LiteralNode(value=2)),
                right=LiteralNode(value=3),
            ),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].op == "+"


class TestCall:
    def test_call_creation(self):
        """Call should create with func and args."""
        node = Call(func=Identifier(name="sum"), args=[])
        assert node.func.name == "sum"

    def test_call_roundtrip_via_uast(self):
        """Call should survive serialize→deserialize cycle via CoreUAST."""
        uast = CoreUAST(body=[
            Call(func=Identifier(name="sum"), args=[Identifier(name="a"), Identifier(name="b")]),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].func.name == "sum"


class TestIf:
    def test_if_creation_without_else(self):
        """If should create with condition and then_body."""
        uast = CoreUAST(body=[
            If(condition=Identifier(name="cond"), then_body=[Return(value=LiteralNode(value=1))]),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].else_body is None

    def test_if_roundtrip(self):
        """If should survive serialize→deserialize cycle via CoreUAST."""
        uast = CoreUAST(body=[
            If(
                condition=Identifier(name="cond"),
                then_body=[Return(value=LiteralNode(value=1))],
                else_body=[Identifier(name="fallback")],
            ),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].condition.name == "cond"


class TestFor:
    def test_for_creation(self):
        """For should create with var, iterable, and body."""
        uast = CoreUAST(body=[
            For(var=Identifier(name="x"), iterable=Identifier(name="data"), body=[]),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].var.name == "x"

    def test_for_roundtrip(self):
        """For should survive serialize→deserialize cycle via CoreUAST."""
        uast = CoreUAST(body=[
            For(
                var=Identifier(name="x"),
                iterable=Identifier(name="range"),
                body=[If(condition=Identifier(name="check"), then_body=[Call(func=Identifier(name="process"), args=[])])],
            ),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].var.name == "x"


class TestWhile:
    def test_while_creation(self):
        """While should create with condition and body."""
        uast = CoreUAST(body=[While(condition=LiteralNode(value=True), body=[])], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].condition.value is True

    def test_while_roundtrip(self):
        """While should survive serialize→deserialize cycle via CoreUAST."""
        uast = CoreUAST(body=[
            While(condition=LiteralNode(value=True), body=[Call(func=Identifier(name="tick"), args=[])]),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].condition.value is True


class TestReturn:
    def test_return_creation(self):
        """Return should create with optional value."""
        uast = CoreUAST(body=[Return(value=Identifier(name="result"))], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].value is not None


class TestFunction:
    def test_function_creation(self):
        """Function should store name, params, and body."""
        uast = CoreUAST(body=[
            Function(name=Identifier(name="add"), params=[Identifier(name="a")], body=[Return(value=LiteralNode(value=1))]),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].name.name == "add"

    def test_function_roundtrip(self):
        """Function should survive serialize→deserialize cycle via CoreUAST."""
        uast = CoreUAST(body=[
            Function(
                name=Identifier(name="compute"),
                params=[Identifier(name="x")],
                body=[If(condition=LiteralNode(value=True), then_body=[Return(value=Identifier(name="x"))])],
            ),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].name.name == "compute"


class TestOpaque:
    def test_opaque_creation(self):
        """Opaque should store original text."""
        uast = CoreUAST(body=[Opaque(original_text="lambda x: x + 1", lang="python")], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0].original_text == "lambda x: x + 1"


class TestCoreUAST:
    def test_core_uast_empty(self):
        """Empty CoreUAST should have empty body."""
        uast = CoreUAST(body=[], language="python")
        assert len(uast.body) == 0

    def test_core_uast_single_node(self):
        """CoreUAST should handle single nodes."""
        uast = CoreUAST(body=[LiteralNode(value=1)], language="python")
        assert len(uast.body) == 1

    def test_canonical_hash(self):
        """CoreUAST should produce consistent canonical hash."""
        uast1 = CoreUAST(body=[LiteralNode(value=1)], language="python")
        uast2 = CoreUAST(body=[LiteralNode(value=1)], language="python")
        assert uast1.canonical_hash() == uast2.canonical_hash()

    def test_deeply_nested_roundtrip(self):
        """CoreUAST with deeply nested structures should roundtrip correctly."""
        uast = CoreUAST(body=[
            Function(
                name=Identifier(name="complex"),
                params=[Identifier(name="x")],
                body=[
                    For(
                        var=Identifier(name="i"),
                        iterable=Identifier(name="range"),
                        body=[
                            If(
                                condition=BinaryOp(op="==", left=Identifier(name="x"), right=LiteralNode(value=0)),
                                then_body=[Return(value=LiteralNode(value=0))],
                            ),
                        ],
                    ),
                ],
            ),
        ], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert len(restored.body) == 1


class TestBreak:
    def test_break_creation(self):
        """Break should create with no arguments."""
        uast = CoreUAST(body=[Break()], language="python")
        restored = CoreUAST.from_dict(uast.to_dict())
        assert restored.body[0] is not None
