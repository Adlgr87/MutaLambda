"""Tests for ``canonical_hash(uast)`` (Fase 0, A2)."""

from __future__ import annotations

import json

import pytest

from muta_ext.uast import canonical_hash
from muta_ext.uast.canonical import canonical_body, canonical_payload
from muta_ext.uast.core_uast import (
    BinaryOp,
    CoreUAST,
    Function,
    Identifier,
    LiteralNode,
    Return,
)


def _build_uast(language: str = "python") -> CoreUAST:
    body = [
        Function(
            name=Identifier("square"),
            params=[Identifier("x")],
            body=[
                Return(
                    value=BinaryOp(op="*", left=Identifier("x"), right=Identifier("x")),
                )
            ],
        ),
    ]
    return CoreUAST(body=body, language=language)


def _reloc(node, loc=None, tag="mutated"):
    """Deep-copy a node forcing ``location``/``tag`` to new values."""
    from dataclasses import fields, replace

    if node is None or not hasattr(node, "__dataclass_fields__"):
        return node
    kwargs = {}
    for f in fields(node):
        value = getattr(node, f.name)
        if f.name == "location":
            value = loc
        elif f.name == "tag":
            value = tag
        elif isinstance(value, list):
            value = [
                _reloc(v, loc=loc, tag=tag) if hasattr(v, "__dataclass_fields__") else v
                for v in value
            ]
        elif hasattr(value, "__dataclass_fields__"):
            value = _reloc(value, loc=loc, tag=tag)
        kwargs[f.name] = value
    return replace(node, **kwargs)


def test_hash_is_64_hex():
    h = canonical_hash(_build_uast())
    assert len(h) == 64
    int(h, 16)  # valid hex


def test_hash_stable_across_rebuilds():
    assert canonical_hash(_build_uast()) == canonical_hash(_build_uast())


def test_hash_ignores_locations_and_tags():
    u1 = _build_uast()
    u2 = _reloc(u1.body[0], loc={"start_line": 99, "end_line": 101})
    u1 = CoreUAST(body=list(u1.body), language="python")
    u2 = CoreUAST(body=[u2], language="python")
    assert canonical_hash(u1) == canonical_hash(u2)


def test_hash_ignores_metadata():
    u1 = _build_uast()
    u2 = CoreUAST(
        body=list(u1.body),
        language="python",
        metadata={"file": "/tmp/x.py", "tool": "1.0", "commit": "abc"},
    )
    assert canonical_hash(u1) == canonical_hash(u2)


def test_hash_differs_for_different_structure():
    u1 = _build_uast()
    body = [
        Function(
            name=Identifier("triple"),
            params=[Identifier("x")],
            body=[Return(value=BinaryOp(op="*", left=Identifier("x"), right=LiteralNode(3)))],
        )
    ]
    u2 = CoreUAST(body=body, language="python")
    assert canonical_hash(u1) != canonical_hash(u2)


def test_hash_accepts_dict_and_matches_object():
    u = _build_uast()
    assert canonical_hash(u.to_dict()) == canonical_hash(u)
    # and a body-only dict with explicit language
    body_dict = u.to_dict()["body"]
    assert canonical_hash({"body": body_dict, "language": "python"}) == canonical_hash(u)


def test_hash_accepts_raw_node_list():
    u = _build_uast()
    assert canonical_hash(list(u.body)) == canonical_hash(u)


def test_hash_language_sensitive():
    assert canonical_hash(_build_uast("python")) != canonical_hash(_build_uast("rust"))


def test_hash_rejects_none():
    with pytest.raises(ValueError):
        canonical_hash(None)
    with pytest.raises(ValueError):
        canonical_hash({"language": "python"})  # missing body


def test_legacy_method_unchanged():
    """CoreUAST.canonical_hash() keeps its legacy 16-hex contract."""
    u = _build_uast()
    legacy = u.canonical_hash()
    assert len(legacy) == 16
    int(legacy, 16)


def test_payload_is_sorted_and_compact():
    u = _build_uast()
    payload = canonical_payload(list(u.body), "python")
    doc = json.loads(payload)
    assert list(doc.keys()) == sorted(doc.keys())
    assert canonical_body(list(u.body)) == doc["body"]
