"""Tests for O3 — AST stubs + headroom_retrieve tool (Fase 1)."""

from __future__ import annotations

import ast

from ast_stubs import (
    RETRIEVE_PROTOCOL_NOTE,
    StubStore,
    parse_retrieve_calls,
    render_retrievals,
    stubify,
)

BIG_CODE = '''"""Module with one big function and one tiny one."""
import math


def big_function(x, n=100):
    """A long body that wastes tokens in prompts."""
    total = 0
    i = 0
    while i < n:
        total = total + x * i
        x = math.sqrt(x + 1)
        if i % 7 == 0:
            total = total - 1
        i = i + 1
    extra = []
    for j in range(10):
        extra.append(j * j + total)
    return total + len(extra)


def tiny():
    return 42
'''


class TestStubify:
    def test_stubs_large_bodies_keeps_signatures(self):
        code, store, refs = stubify(BIG_CODE)
        assert len(refs) == 1
        assert refs[0].name == "def big_function"
        # Signature survives, body is a marker.
        assert "def big_function(x, n=100):" in code
        assert "while i < n:" not in code
        assert "headroom_retrieve(" in code
        # Tiny function untouched.
        assert "return 42" in code
        # Result still parses.
        ast.parse(code)
        # Stubbed code is strictly shorter.
        assert len(code) < len(BIG_CODE)

    def test_retrieval_roundtrip(self):
        code, store, refs = stubify(BIG_CODE)
        sid = refs[0].stub_id
        body = store.retrieve(sid)
        assert body is not None
        assert "while i < n:" in body
        # The original body can be restored into the stub to recover logic.
        restored = code.replace(refs[0].marker(), body.rstrip())
        assert "while i < n:" in restored
        ast.parse(restored)

    def test_no_stubbing_for_small_bodies(self):
        code, store, refs = stubify("def f():\n    return 1\n")
        assert refs == []
        assert len(store) == 0
        assert code == "def f():\n    return 1\n"

    def test_unparseable_passthrough(self):
        junk = "def broken(:\n  oops"
        code, store, refs = stubify(junk)
        assert code == junk
        assert refs == []

    def test_nested_functions_keep_outer_only(self):
        src = (
            "def outer():\n"
            + "".join(f"    s{i} = {i}\n" for i in range(30))
            + "    def inner():\n"
            + "".join(f"        t{i} = {i}\n" for i in range(30))
            + "        return t0\n"
            "    return inner()\n"
        )
        code, store, refs = stubify(src)
        # Exactly one stub: the outer (it contains the inner).
        assert len(refs) == 1
        ast.parse(code)
        assert store.retrieve(refs[0].stub_id) is not None


class TestRetrieveProtocol:
    def test_parse_retrieve_calls(self):
        text = (
            'headroom_retrieve("stub_001")\n'
            "some chatter\n"
            "headroom_retrieve(stub_002)\n"
            'headroom_retrieve("stub_001")\n'  # dup ignored
            "headroom_retrieve(stub_999) extra  # not a full-line call\n"
        )
        assert parse_retrieve_calls(text) == ["stub_001", "stub_002"]

    def test_parse_none(self):
        assert parse_retrieve_calls("plain answer\nno calls") == []
        assert parse_retrieve_calls("") == []

    def test_render_retrievals(self):
        store = StubStore()
        ref = store.add("def f", "body here")
        block = render_retrievals(store, [ref.stub_id, "stub_777"])
        assert "body here" in block
        assert ref.stub_id in block
        assert "stub_777" not in block
        assert render_retrievals(store, ["stub_777"]) == ""

    def test_protocol_note_mentions_tool(self):
        assert "headroom_retrieve" in RETRIEVE_PROTOCOL_NOTE
