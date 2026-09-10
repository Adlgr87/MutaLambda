#!/usr/bin/env python3
"""Visitor / transformer / dump tests for UAST v2."""

import pytest

from muta_ext.uast2 import core as v2
from muta_ext.uast2.adapters import parse_to_uast
from muta_ext.uast2.visitor import (
    NodeTransformer,
    NodeVisitor,
    collect,
    count_nodes,
    dump,
    dump_python,
    find_all,
    iter_child_nodes,
    walk,
)


def sample_tree():
    return parse_to_uast("x = 1 + 2\ny = x * 3\n", prepare=True)


class TestWalkHelpers:
    def test_walk_matches_ast_walk_semantics(self):
        document = sample_tree()
        assert count_nodes(document) == document.node_count()
        assert len(list(walk(document))) == document.node_count()

    def test_iter_child_nodes_top_level(self):
        document = sample_tree()
        assert [type(n).__name__ for n in iter_child_nodes(document)] == ["Assign", "Assign"]

    def test_collect_and_find_all(self):
        document = sample_tree()
        literals = collect(document, v2.LiteralNode)
        assert [node.value for node in literals] == [1, 2, 3]
        identifiers = find_all(document, lambda node: isinstance(node, v2.Identifier))
        assert {node.name for node in identifiers} >= {"x", "y"}


class TestNodeVisitor:
    def test_dispatch_per_type_with_fallback(self):
        seen = []

        class Recorder(NodeVisitor):
            def visit_LiteralNode(self, node):
                seen.append(("literal", node.value))
                return None

            def generic_visit(self, node):
                seen.append(("generic", type(node).__name__))
                return super().generic_visit(node)

        Recorder().visit(sample_tree())
        assert ("literal", 1) in seen and ("generic", "Assign") in seen

    def test_visit_all(self):
        class Counter(NodeVisitor):
            def __init__(self):
                self.count = 0

            def visit_Identifier(self, node):
                self.count += 1

        counter = Counter()
        counter.visit_all(sample_tree())
        assert counter.count == 3  # x, y (targets) + x (value of y = x * 3)


class TestNodeTransformer:
    def test_replace_in_place(self):
        class DoubleLiterals(NodeTransformer):
            def visit_LiteralNode(self, node):
                node.value *= 2
                return node

        document = sample_tree()
        before = document.merkle_hash()
        DoubleLiterals().transform(document)
        values = [node.value for node in collect(document, v2.LiteralNode)]
        assert values == [2, 4, 6]
        assert document.merkle_hash() != before

    def test_return_new_node_replaces_child(self):
        class FoldConstants(NodeTransformer):
            def visit_BinaryOp(self, node):
                self.generic_visit(node)
                if isinstance(node.left, v2.LiteralNode) and isinstance(node.right, v2.LiteralNode):
                    return v2.LiteralNode(value=node.left.value + node.right.value)
                return node

        document = sample_tree()
        FoldConstants().transform(document)
        assert isinstance(document.body[0].value, v2.LiteralNode)
        assert document.body[0].value.value == 3
        # Parent pointers survive the replacement.
        assert document.body[0].value._parent is document.body[0]

    def test_return_none_deletes_node(self):
        class DropAssigns(NodeTransformer):
            def visit_Assign(self, node):
                return None

        document = sample_tree()
        DropAssigns().transform(document)
        assert document.body == []

    def test_list_result_splices(self):
        class DuplicateAssign(NodeTransformer):
            def visit_Assign(self, node):
                self.generic_visit(node)
                return [node, node.clone()]

        document = parse_to_uast("x = 1\n")
        DuplicateAssign().transform(document)
        assert len(document.body) == 2
        # Body roots carry no parent/slot by design.
        assert document.body[1]._slot is None and document.body[1]._parent is None

    def test_dict_slot_children_are_visited(self):
        document = parse_to_uast("y = f(a, key=b)\n", prepare=True)

        class Rename(NodeTransformer):
            def visit_Identifier(self, node):
                node.name = node.name.upper()
                return node

        Rename().transform(document)
        call = document.body[0].value
        assert call.func.name == "F"
        assert list(call.keywords) == ["key"]
        assert call.keywords["key"].name == "B"


class TestDump:
    def test_dump_looks_like_ast_dump(self):
        text = dump(v2.BinaryOp(left=v2.LiteralNode(value=1), op="+", right=v2.LiteralNode(value=2)))
        assert text == (
            "BinaryOp(left=LiteralNode(value=1, type_hint=None), op='+', "
            "right=LiteralNode(value=2, type_hint=None))"
        )

    def test_dump_without_annotations(self):
        assert dump_python(v2.Identifier(name="x")) == "Identifier('x', None)"

    def test_dump_includes_document_and_attributes(self):
        node = v2.Identifier(name="x", lineno=4)
        assert "lineno=4" in dump(node, include_attributes=True)
        text = dump(v2.CoreUAST(body=[v2.Break()]))
        assert text.startswith("CoreUAST(") and "Break()" in text
