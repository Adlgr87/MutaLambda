#!/usr/bin/env python3
"""Bidirectional conversion tests (legacy ⇄ v2) — the keystone of the migration."""

import glob

import pytest

from muta_ext.uast import core_uast as legacy
from muta_ext.uast.adapters.python_adapter import parse_to_uast as legacy_parse
from muta_ext.uast2 import core as v2
from muta_ext.uast2.convert import (
    ConversionError,
    is_legacy_node,
    is_v2_node,
    legacy_to_v2,
    v2_to_legacy,
)


def all_legacy_node_types():
    """One legacy instance per node type (exercises the whole converter table)."""
    return [
        legacy.LiteralNode(value=1, type_hint="i64"),
        legacy.Identifier(name="x", qualified="m"),
        legacy.BinaryOp(left=legacy.Identifier(name="a"), op="+", right=legacy.LiteralNode(value=1)),
        legacy.UnaryOp(op="-", operand=legacy.LiteralNode(value=1)),
        legacy.Call(
            func=legacy.Identifier(name="f"),
            args=[legacy.LiteralNode(value=1)],
            keywords={"k": legacy.LiteralNode(value=2)},
        ),
        legacy.Assign(target=legacy.Identifier(name="x"), value=legacy.LiteralNode(value=1)),
        legacy.Assign(
            target=[legacy.Identifier(name="a"), legacy.Identifier(name="b")],
            value=legacy.Call(func=legacy.Identifier(name="f")),
        ),
        legacy.If(
            condition=legacy.Identifier(name="c"),
            then_body=[legacy.Break()],
            else_body=[legacy.Return(value=None)],
        ),
        legacy.For(
            var=legacy.Identifier(name="i"),
            iterable=legacy.Call(func=legacy.Identifier(name="range")),
            body=[legacy.Break()],
            is_traditional=True,
        ),
        legacy.While(condition=legacy.Identifier(name="c"), body=[legacy.Break()]),
        legacy.Return(value=legacy.LiteralNode(value=1)),
        legacy.Function(
            name=legacy.Identifier(name="f"),
            params=[legacy.Identifier(name="x")],
            body=[legacy.Return(value=legacy.Identifier(name="x"))],
            decorators=[legacy.Call(func=legacy.Identifier(name="dec"))],
            return_type="int",
        ),
        legacy.ParallelFor(
            var=legacy.Identifier(name="i"),
            start=legacy.LiteralNode(value=0),
            end=legacy.LiteralNode(value=10),
            body=[legacy.Break()],
            reduction="sum",
        ),
        legacy.Comment(text="hi", position="inline"),
        legacy.Opaque(original_text="raw", lang="python"),
        legacy.Break(),
        legacy.TryExcept(
            body=[legacy.Break()],
            except_clauses=[
                legacy.ExceptClause(
                    exception_type=legacy.Identifier(name="ValueError"), binding="e", body=[]
                )
            ],
            finally_body=[legacy.Break()],
        ),
        legacy.ExceptClause(exception_type=None, binding=None, body=[]),
        legacy.StructDef(
            name="S",
            fields=[legacy.FieldDef(name="x", type_annotation=None, default=legacy.LiteralNode(value=1))],
            methods=[legacy.Function(name=legacy.Identifier(name="m"))],
        ),
        legacy.FieldDef(name="x", type_annotation=legacy.TypeAnnotation(type_name="int"), default=None),
        legacy.TypeAnnotation(
            type_name="Vec",
            generic_args=[legacy.TypeAnnotation(type_name="i64")],
            is_reference=True,
            is_mutable=True,
        ),
        legacy.MatchArm(
            pattern=legacy.Identifier(name="p"), guard=legacy.Identifier(name="g"), body=[legacy.Break()]
        ),
        legacy.Match(subject=legacy.Identifier(name="s"), arms=[legacy.MatchArm(pattern=legacy.Identifier(name="p"))]),
        legacy.Reference(target=legacy.Identifier(name="x"), is_mutable=True),
    ]


class TestLegacyToV2:
    @pytest.mark.parametrize("node", all_legacy_node_types())
    def test_every_legacy_node_type_converts_and_roundtrips(self, node):
        converted = legacy_to_v2(node)
        assert is_v2_node(converted)
        assert type(converted).__name__ == type(node).__name__
        restored = v2_to_legacy(converted)
        assert restored == node  # frozen dataclasses compare field-by-field

    def test_tags_and_locations_are_preserved(self):
        node = legacy.LiteralNode(value=1, tag="keep", location={"line": 7, "col": 3})
        converted = legacy_to_v2(node)
        assert converted.tag == "keep"
        assert (converted.lineno, converted.col_offset) == (7, 3)
        restored = v2_to_legacy(converted)
        assert restored.tag == "keep" and restored.location == {"line": 7, "col": 3}

    def test_document_conversion(self):
        converted = legacy_to_v2(
            legacy.CoreUAST(
                body=[legacy.Break()], language="rust", metadata={"k": 1}
            )
        )
        assert isinstance(converted, v2.CoreUAST)
        assert converted.language == "rust" and converted.metadata == {"k": 1}

    def test_unknown_legacy_type_raises(self):
        class AlienNode:
            __dataclass_fields__ = {"x": None}

        with pytest.raises(ConversionError):
            legacy_to_v2(AlienNode())
        opaque = legacy_to_v2(AlienNode(), on_unknown="opaque")
        assert type(opaque).__name__ == "Opaque"

    def test_primitives_pass_through(self):
        assert legacy_to_v2(None) is None
        assert legacy_to_v2(5) == 5
        assert legacy_to_v2([legacy.Break(), 3])[1] == 3
        assert legacy_to_v2({"a": legacy.Break()})["a"]._fields == ()


class TestV2ToLegacy:
    def test_v2_node_without_legacy_counterpart_raises(self):
        class NotANode(v2.UASTNode):  # pragma: no cover - only built for this test
            _fields = ()

        with pytest.raises(ConversionError):
            v2_to_legacy(NotANode())

    def test_document_roundtrip_preserves_structure(self):
        document = v2.CoreUAST(
            body=[
                v2.Function(
                    name=v2.Identifier(name="f"),
                    body=[v2.Return(value=v2.LiteralNode(value=1))],
                )
            ],
            language="python",
        )
        legacy_document = v2_to_legacy(document)
        assert isinstance(legacy_document, legacy.CoreUAST)
        back = legacy_to_v2(legacy_document)
        assert back.canonical_hash() == document.canonical_hash()

    def test_is_legacy_node_helper(self):
        assert is_legacy_node(legacy.Break())
        assert not is_legacy_node(v2.Break())
        assert not is_legacy_node({})


class TestExampleCorpus:
    @pytest.mark.parametrize("path", sorted(glob.glob("examples/**/*.py", recursive=True)))
    def test_roundtrip_identity_over_examples(self, path):
        source = open(path, encoding="utf-8").read()
        original = legacy_parse(source)
        # legacy → v2 → legacy  (identical structure, locations excluded)
        converted = legacy_to_v2(original)
        restored = v2_to_legacy(converted)
        assert legacy_to_v2(restored).canonical_hash() == converted.canonical_hash()
        assert list(restored.to_dict()["body"]) == list(original.to_dict()["body"])

    @pytest.mark.parametrize("path", sorted(glob.glob("examples/**/*.py", recursive=True)))
    def test_v2_roundtrip_through_legacy(self, path):
        source = open(path, encoding="utf-8").read()
        from muta_ext.uast2.adapters import parse_to_uast

        document = parse_to_uast(source)
        back = legacy_to_v2(v2_to_legacy(document))
        assert back.canonical_hash() == document.canonical_hash()
        assert back.merkle_hash() == document.merkle_hash()
