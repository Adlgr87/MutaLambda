#!/usr/bin/env python3
"""Adapter (locations, dialects) and emitter reuse tests."""

import ast

import pytest

from muta_ext.uast.adapters.python_adapter import parse_to_uast as legacy_parse
from muta_ext.uast.emitters.python_emitter import emit_from_uast as legacy_emit
from muta_ext.uast2 import core as v2
from muta_ext.uast2.adapters import (
    AdapterUnavailable,
    PythonAdapterV2,
    available_languages,
    get_adapter_v2,
    parse_to_arena,
    parse_to_uast,
)
from muta_ext.uast2.arena import Arena
from muta_ext.uast2.emitters import EmitterWrapperV2, emit, emit_from_uast
from muta_ext.uast2.verify import ChildSchemaVerify, StructuralVerify

SOURCE = """def solution(n):
    total = 0
    for i in range(n):
        if i % 2 == 0:
            total = total + i * i
    return total
"""


class TestPythonAdapterV2:
    def test_locations_are_propagated(self):
        document = parse_to_uast(SOURCE)
        function = document.body[0]
        assert function.lineno == 1 and function.col_offset == 0
        assert function.body[0].lineno == 2
        inner_if = function.body[1].body[0]
        assert inner_if.lineno == 4
        # Nested expressions get coordinates too.
        binary = function.body[0].value
        assert binary.lineno == 2 and binary.end_lineno == 2

    def test_metadata_is_deterministic(self):
        first = parse_to_uast("x = 1\n").metadata
        second = parse_to_uast("x = 1\n").metadata
        assert first["source_hash"] == second["source_hash"]
        assert first["dialect"] == "legacy-parity"

    def test_structure_matches_legacy_engine(self):
        document = parse_to_uast(SOURCE)
        converted = v2.CoreUAST.from_legacy(legacy_parse(SOURCE))
        assert document.canonical_hash() == converted.canonical_hash()

    def test_can_parse(self):
        adapter = PythonAdapterV2()
        assert adapter.can_parse("x = 1")
        assert not adapter.can_parse("def broken(:\n")

    def test_parse_error_is_value_error(self):
        with pytest.raises(ValueError):
            parse_to_uast("def broken(:\n")

    def test_unknown_adapter_language(self):
        with pytest.raises(ValueError):
            get_adapter_v2("cobol")
        assert set(available_languages()) >= {"python", "rust", "cpp", "go"}

    def test_parse_into_arena(self):
        arena = Arena()
        document = parse_to_arena("x = 1 + 2\n", arena)
        assert len(arena) == document.node_count()
        assert document.prepared is True

    def test_verification_passes_accept_parsed_documents(self):
        document = parse_to_uast(SOURCE)
        assert StructuralVerify().verify(document) == []
        assert ChildSchemaVerify().verify(document) == []


class TestExtendedDialect:
    def test_comparisons_become_real_nodes(self):
        document = parse_to_uast("if a > 1:\n    x = 1\n", extended=True)
        condition = document.body[0].condition
        assert isinstance(condition, v2.BinaryOp) and condition.op == ">"

    def test_boolop_lowered_when_safe(self):
        document = parse_to_uast("if a > 1 and b < 2:\n    x = 1\n", extended=True)
        condition = document.body[0].condition
        assert isinstance(condition, v2.BinaryOp) and condition.op == "and"
        assert isinstance(condition.left, v2.BinaryOp)

    def test_chained_comparison_stays_opaque(self):
        document = parse_to_uast("if a < b < c:\n    x = 1\n", extended=True)
        assert isinstance(document.body[0].condition, v2.Opaque)

    def test_nested_boolop_stays_opaque(self):
        document = parse_to_uast("if (a or b) and c:\n    x = 1\n", extended=True)
        assert isinstance(document.body[0].condition, v2.Opaque)

    def test_augassign_lowered(self):
        document = parse_to_uast("x = 0\nx += 2\n", extended=True)
        assignment = document.body[1]
        assert isinstance(assignment, v2.Assign)
        assert isinstance(assignment.value, v2.BinaryOp) and assignment.value.op == "+"

    def test_extended_document_is_valid_and_emittable(self):
        document = parse_to_uast(SOURCE, extended=True)
        assert StructuralVerify().verify(document) == []
        emitted = emit(document)
        ast.parse(emitted)
        assert "for i in range(n):" in emitted

    def test_extended_adds_nodes_compared_to_parity(self):
        parity = parse_to_uast(SOURCE)
        extended = parse_to_uast(SOURCE, extended=True)
        assert extended.node_count() > parity.node_count()


class TestTreeSitterAdapters:
    @pytest.mark.parametrize(
        "language,source",
        [
            ("rust", "fn add(a: i64, b: i64) -> i64 { a + b }\n"),
            ("cpp", "int add(int a, int b) { return a + b; }\n"),
            ("go", "package main\nfunc add(a int, b int) int { return a + b }\n"),
        ],
    )
    def test_languages_parse_or_raise_cleanly(self, language, source):
        adapter = get_adapter_v2(language)
        try:
            document = adapter.parse_to_uast(source)
        except AdapterUnavailable:
            pytest.skip(f"tree-sitter grammars for {language} not installed")
        assert document.language == language
        assert document.node_count() > 0
        assert StructuralVerify().verify(document) == []

    def test_rust_roundtrip_parity_with_legacy(self):
        from muta_ext.uast.adapters import get_adapter as get_legacy_adapter

        source = "fn add(a: i64, b: i64) -> i64 { a + b }\n"
        try:
            document = get_adapter_v2("rust").parse_to_uast(source)
            legacy_document = get_legacy_adapter("rust").parse_to_uast(source)
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"rust adapter unavailable: {exc}")
        converted = v2.CoreUAST.from_legacy(legacy_document)
        assert document.canonical_hash() == converted.canonical_hash()


class TestEmitters:
    def test_emit_v2_document(self):
        document = parse_to_uast("x = 1 + 2\n")
        assert emit(document).strip() == "x = 1 + 2"

    def test_emit_matches_legacy_emitter(self):
        source = "def f(x):\n    return x + 1\n"
        assert emit(parse_to_uast(source)) == legacy_emit(legacy_parse(source))

    def test_emitter_wrapper_api(self):
        wrapper = EmitterWrapperV2()
        assert wrapper.language is None
        assert wrapper.can_emit(parse_to_uast("x = 1\n"))
        assert emit_from_uast(parse_to_uast("x = 1\n")).strip() == "x = 1"

    def test_emit_legacy_document_passthrough(self):
        assert emit(legacy_parse("y = 2\n")).strip() == "y = 2"
