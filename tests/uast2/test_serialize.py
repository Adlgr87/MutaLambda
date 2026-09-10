#!/usr/bin/env python3
"""Flat-slab (msgpack) serialisation: fidelity, determinism, checkpoints."""

import json

import pytest

from muta_ext.uast import core_uast as legacy
from muta_ext.uast.adapters.python_adapter import parse_to_uast as legacy_parse
from muta_ext.uast2 import core as v2
from muta_ext.uast2.adapters import parse_to_uast
from muta_ext.uast2.serialize import (
    FORMAT_NAME,
    FORMAT_VERSION,
    SerializationError,
    dump,
    dumps,
    dumps_json,
    from_payload,
    load,
    loads,
    loads_json,
    payload,
)

SOURCE = """def f(n):
    total = 0
    for i in range(n):
        total = total + i * i
    return total
"""

MUTATED = """def f(n):
    total = 0
    while n > 0:
        total = total + n
        n = n - 1
    return total
"""


class TestPayload:
    def test_payload_is_flat_and_reference_based(self):
        data = payload(parse_to_uast(SOURCE))
        assert data["format"] == FORMAT_NAME and data["version"] == FORMAT_VERSION
        assert isinstance(data["nodes"], list) and data["nodes"]
        assert data["roots"] and all(isinstance(index, int) for index in data["roots"])
        # Children are integer references into the slab, never nested dicts.
        assert data["fields"]["BinaryOp"] == ["left", "op", "right"]
        for node in data["nodes"]:
            assert set(node) <= {"t", "f", "p", "l", "tag"}
            assert "__type__" not in json.dumps(node)  # no nested legacy dicts

    def test_payload_is_stable_across_runs(self):
        first = json.dumps(payload(parse_to_uast(SOURCE)), sort_keys=True)
        second = json.dumps(payload(parse_to_uast(SOURCE)), sort_keys=True)
        assert first == second

    def test_payload_survives_unknown_format(self):
        with pytest.raises(SerializationError):
            from_payload({"format": "other", "version": 1})


class TestRoundtrip:
    def test_document_roundtrip_is_identical(self):
        document = parse_to_uast(SOURCE)
        restored = loads(dumps(document))
        assert restored.canonical_hash() == document.canonical_hash()
        assert restored.merkle_hash() == document.merkle_hash()
        assert restored.language == document.language
        assert restored.metadata == document.metadata

    def test_locations_are_restored(self):
        document = parse_to_uast(SOURCE)
        restored = loads(dumps(document))
        pairs = [
            (node.lineno, node.col_offset)
            for node in document.walk()
        ] == [
            (node.lineno, node.col_offset)
            for node in restored.walk()
        ]
        assert pairs
        assert document.body[0].body[0].lineno == restored.body[0].body[0].lineno

    def test_arena_ids_and_parents_are_restored(self):
        from muta_ext.uast2.arena import Arena

        document = parse_to_uast(SOURCE, arena=Arena())
        restored = loads(dumps(document))
        original_ids = [node._id for node in document.walk()]
        restored_ids = [node._id for node in restored.walk()]
        assert original_ids == restored_ids
        assert original_ids and all(index is not None for index in original_ids)
        inner = restored.body[0].body[0]
        assert inner._parent is restored.body[0]
        assert inner._slot == ("body", 0)

    def test_untracked_document_gets_sequential_ids_on_load(self):
        document = parse_to_uast(SOURCE)  # no arena requested
        assert all(node._id is None for node in document.walk())
        restored = loads(dumps(document))
        assert [node._id for node in restored.walk()] == list(range(restored.node_count()))

    def test_tags_are_restored(self):
        document = v2.CoreUAST(body=[v2.Break(tag="marker")])
        restored = loads(dumps(document))
        assert restored.body[0].tag == "marker"

    def test_json_codec_roundtrip(self):
        document = parse_to_uast(SOURCE)
        restored = loads(dumps(document))
        assert dumps_json(restored) == dumps_json(document)
        assert loads_json(dumps_json(document)).canonical_hash() == document.canonical_hash()

    def test_compressed_payload_is_smaller_and_equal(self):
        document = parse_to_uast(SOURCE)
        plain = dumps(document)
        packed = dumps(document, compress=True)
        assert loads(packed).canonical_hash() == document.canonical_hash()
        assert len(packed) <= len(plain)

    def test_empty_document(self):
        document = v2.CoreUAST(body=[], language="python")
        restored = loads(dumps(document))
        assert restored.body == [] and restored.node_count() == 0

    def test_bad_payload_rejected(self):
        with pytest.raises(SerializationError):
            loads(b"")
        with pytest.raises(SerializationError):
            loads("not-bytes")  # type: ignore[arg-type]

    def test_mutated_document_roundtrip(self):
        document = parse_to_uast(SOURCE)
        other = parse_to_uast(MUTATED)
        document.body[:] = other.body
        document.prepare()
        restored = loads(dumps(document))
        assert restored.canonical_hash() == document.canonical_hash()


class TestCheckpointFormats:
    def test_dump_and_load_files(self, tmp_path):
        document = parse_to_uast(SOURCE)
        path = tmp_path / "checkpoint.uast2"
        written = dump(document, path)
        assert written == path.stat().st_size
        assert load(path).canonical_hash() == document.canonical_hash()

    def test_msgpack_is_smaller_than_legacy_json(self):
        document = parse_to_uast(SOURCE)
        legacy_json = json.dumps(
            legacy_parse(SOURCE).to_dict(), separators=(",", ":"), default=str
        ).encode("utf-8")
        packed = dumps(document)
        assert len(packed) < len(legacy_json)

    def test_legacy_v2_interop_via_dict(self):
        """Legacy JSON checkpoints must stay loadable by the v2 engine."""
        legacy_document = legacy_parse(SOURCE)
        text = json.dumps(legacy_document.to_dict(), default=str)
        restored = loads_json(text)
        assert restored.canonical_hash()
        assert isinstance(restored, v2.CoreUAST)
        # And back again: the legacy format is unchanged by the v2 roundtrip.
        assert isinstance(restored.to_legacy(), legacy.CoreUAST)
