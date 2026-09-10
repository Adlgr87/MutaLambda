#!/usr/bin/env python3
"""Core node model tests for UAST v2."""

import pytest

from muta_ext.uast2 import core as v2


class TestNodeModel:
    def test_fields_match_legacy_order(self):
        assert v2.BinaryOp._fields == ("left", "op", "right")
        assert v2.Function._fields == (
            "name",
            "params",
            "body",
            "decorators",
            "return_type",
        )
        assert v2.Break._fields == ()

    def test_nodes_are_mutable(self):
        node = v2.BinaryOp(left=v2.LiteralNode(value=1), op="+", right=v2.LiteralNode(value=2))
        node.op = "-"
        node.left.value = 42
        assert node.op == "-"
        assert node.left.value == 42
        assert node.left.type_hint is None

    def test_unknown_kwargs_raise_type_error(self):
        with pytest.raises(TypeError, match="Campos inesperados"):
            v2.Break(tag="t", bogus=1)

    def test_positional_construction_mirrors_dataclass(self):
        node = v2.BinaryOp(v2.LiteralNode(value=1), "+", v2.LiteralNode(value=2))
        assert node.op == "+"
        assert node.left.value == 1

    def test_container_defaults_are_fresh_per_instance(self):
        first = v2.Call(func=v2.Identifier(name="f"))
        second = v2.Call(func=v2.Identifier(name="f"))
        first.args.append(v2.LiteralNode(value=1))
        assert second.args == []
        assert first.keywords == {} and second.keywords == {}
        assert isinstance(first.args, list) and isinstance(first.keywords, dict)

    def test_scalar_defaults(self):
        assert v2.Comment(text="x").position == "before"
        assert v2.For(var=v2.Identifier(name="i"), iterable=None, body=[]).is_traditional is False
        assert v2.TypeAnnotation(type_name="T").generic_args == []

    def test_slots_prevent_attribute_creation(self):
        node = v2.Identifier(name="x")
        assert not hasattr(node, "__dict__")
        with pytest.raises(AttributeError):
            node.unknown_attribute = 1

    def test_node_repr_roundtrip_ish(self):
        text = repr(v2.LiteralNode(value=3, type_hint="i64"))
        assert text.startswith("LiteralNode(") and "value=3" in text

    def test_required_fields_follow_legacy_defaults(self):
        assert v2.required_fields(v2.LiteralNode) == ("value",)
        assert v2.required_fields(v2.Identifier) == ("name",)
        assert v2.required_fields(v2.If) == ("condition", "then_body")
        assert v2.required_fields(v2.Break) == ()
        assert "args" not in v2.required_fields(v2.Call)

    def test_child_kinds_schema(self):
        assert v2.child_kinds(v2.BinaryOp) == {"left": "node", "right": "node"}
        assert v2.child_kinds(v2.Call)["args"] == "nodelist"
        assert v2.child_kinds(v2.Call)["keywords"] == "nodedict"


class TestTraversal:
    def make_tree(self):
        return v2.CoreUAST(
            body=[
                v2.Function(
                    name=v2.Identifier(name="f"),
                    params=[v2.Identifier(name="x")],
                    body=[
                        v2.Assign(
                            target=v2.Identifier(name="y"),
                            value=v2.BinaryOp(
                                left=v2.LiteralNode(value=1),
                                op="+",
                                right=v2.LiteralNode(value=2),
                            ),
                        ),
                        v2.Return(value=v2.Identifier(name="y")),
                    ],
                )
            ],
            language="python",
        )

    def test_iter_child_nodes_and_slots(self):
        node = v2.If(
            condition=v2.Identifier(name="c"),
            then_body=[v2.Break(), v2.Return(value=None)],
            else_body=None,
        )
        children = list(node.iter_child_nodes())
        assert [type(child).__name__ for child in children] == ["Identifier", "Break", "Return"]
        slots = [(type(child).__name__, slot) for child, slot in node.iter_child_slots()]
        assert slots == [("Identifier", "condition"), ("Break", ("then_body", 0)), ("Return", ("then_body", 1))]

    def test_walk_and_node_count(self):
        document = self.make_tree()
        assert document.node_count() == 10
        assert len(list(v2.walk(document))) == 10
        types = [type(node).__name__ for node in document.walk()]
        assert types[0] == "Function" and "Return" in types

    def test_walk_handles_lists_and_nodes(self):
        nodes = [v2.Break(), v2.Return(value=None)]
        assert sum(1 for _ in v2.walk(nodes)) == 2
        assert sum(1 for _ in v2.walk(nodes[0])) == 1


class TestEditing:
    def test_replace_requires_parents(self):
        document = v2.CoreUAST(
            body=[v2.Assign(target=v2.Identifier(name="x"), value=v2.LiteralNode(value=1))]
        )
        with pytest.raises(NotImplementedError):
            document.body[0].value.replace(v2.LiteralNode(value=2))

    def test_replace_updates_parent_and_slot(self):
        document = v2.CoreUAST(
            body=[
                v2.Assign(
                    target=v2.Identifier(name="x"), value=v2.LiteralNode(value=1)
                )
            ]
        )
        document.prepare()
        old = document.body[0].value
        new = v2.LiteralNode(value=9)
        old.replace(new)
        assert document.body[0].value is new
        assert new._parent is document.body[0] and new._slot == "value"
        assert old._parent is None

    def test_remove_nested_node_refreshes_siblings(self):
        document = v2.CoreUAST(
            body=[
                v2.Function(
                    name=v2.Identifier(name="f"),
                    body=[v2.Break(), v2.Return(value=None), v2.Break()],
                )
            ],
            language="python",
        )
        document.prepare()
        document.body[0].body[1].remove()
        assert len(document.body[0].body) == 2
        assert document.body[0].body[1]._slot == ("body", 1)

    def test_document_remove_and_insert_root(self):
        document = v2.CoreUAST(body=[v2.Break(), v2.Return(value=None)])
        assert document.remove(document.body[0]) is True
        assert len(document.body) == 1
        document.insert(0, v2.Break())
        assert type(document.body[0]).__name__ == "Break"
        assert document.remove(v2.Break()) is False

    def test_sibling_list_of_nested_node(self):
        function = v2.Function(
            name=v2.Identifier(name="f"), body=[v2.Break(), v2.Break()]
        )
        document = v2.CoreUAST(body=[function])
        document.prepare()
        assert function.body[0].sibling_list() is function.body


class TestLocations:
    def test_get_and_set_location(self):
        node = v2.Identifier(name="x")
        assert node.get_location() is None
        node.set_location({"line": 3, "col": 4, "end_line": 5, "end_col": 6})
        assert node.get_location() == {"line": 3, "col": 4, "end_line": 5, "end_col": 6}

    def test_location_kwarg_is_legacy_compatible(self):
        node = v2.LiteralNode(value=1, location={"line": 2, "col": 0})
        assert node.lineno == 2 and node.col_offset == 0


class TestSerializableForm:
    def test_to_from_dict_roundtrip(self):
        document = v2.CoreUAST(
            body=[
                v2.Function(
                    name=v2.Identifier(name="f", qualified="m"),
                    body=[v2.Return(value=v2.LiteralNode(value=1, type_hint="i64", tag="t"))],
                )
            ],
            language="python",
            metadata={"k": "v"},
        )
        payload = document.to_dict()
        restored = v2.CoreUAST.from_dict(payload)
        assert restored.to_dict() == payload
        assert restored.metadata == {"k": "v"}

    def test_dict_omits_engine_by_default(self):
        document = v2.CoreUAST(body=[v2.Break()], language="python")
        assert "engine" not in document.to_dict()
        assert document.to_dict(include_engine=True)["engine"] == "v2"

    def test_unknown_type_degrades_to_opaque(self):
        payload = {"body": [{"__type__": "AlienNode", "x": 1}], "language": "python"}
        restored = v2.CoreUAST.from_dict(payload)
        assert type(restored.body[0]).__name__ == "Opaque"
        with pytest.raises(ValueError):
            v2.CoreUAST.from_dict(payload, strict=True)


class TestCanonicalHash:
    def test_hash_is_stable_across_parses(self):
        from muta_ext.uast2.adapters import parse_to_uast

        source = "def f(x):\n    return x + 1\n"
        first = parse_to_uast(source)
        second = parse_to_uast(source, use_cache=False)
        assert first.canonical_hash() == second.canonical_hash()

    def test_hash_ignores_metadata(self):
        body = [v2.Break()]
        first = v2.CoreUAST(body=[v2.Break()], language="python", metadata={"a": 1})
        second = v2.CoreUAST(body=[v2.Break()], language="python", metadata={"a": 2})
        assert first.canonical_hash() == second.canonical_hash()
        assert first.structure_digest() == second.structure_digest()

    def test_hash_detects_change(self):
        first = v2.CoreUAST(body=[v2.Break()])
        second = v2.CoreUAST(body=[v2.Break(), v2.Break()])
        assert first.canonical_hash() != second.canonical_hash()
