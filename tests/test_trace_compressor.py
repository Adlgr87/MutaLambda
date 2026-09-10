"""Tests for O1 — trace/log compression before LLM prompts (Fase 1)."""

from __future__ import annotations

import json
import os
from typing import Callable, List

import pytest

import trace_compressor as tc
from trace_compressor import (
    TraceCompressor,
    compress_for_llm,
    get_trace_compressor,
    reset_trace_compressor,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MUTALAMBDA_OPT_"):
            monkeypatch.delenv(name)
    from optimization_flags import reset_optimization_flags

    reset_optimization_flags()
    reset_trace_compressor()
    yield
    reset_trace_compressor()
    reset_optimization_flags()


LOG_80_LINES = "\n".join([f"[INFO] step {i} ok" for i in range(80)]) + (
    "\n[ERROR] Traceback (most recent call last):\n"
    '  File "sandbox_worker.py", line 42, in run\n'
    "ValueError: candidate produced wrong result for args=[3]\n"
)


class TestCompressorDirect:
    def test_short_text_passthrough(self):
        c = TraceCompressor()
        r = c.compress("ValueError: oops")
        assert r.method == "passthrough"
        assert r.text == "ValueError: oops"

    def test_log_compression_keeps_errors(self):
        c = TraceCompressor()
        r = c.compress(LOG_80_LINES)
        assert r.method in {"headroom_log", "builtin"}
        assert "ValueError: candidate produced wrong result" in r.text
        assert r.compressed_chars < r.original_chars
        assert r.ratio < 0.5
        # passing noise must be gone or collapsed
        assert r.text.count("step") <= 10

    def test_json_compression(self):
        payload = json.dumps(
            {"items": [{"level": "INFO", "msg": f"row {i}"} for i in range(120)]}
        )
        c = TraceCompressor()
        r = c.compress(payload)
        assert r.method in {"headroom_json", "builtin", "passthrough"}
        if r.method == "headroom_json":
            assert r.compressed_chars < r.original_chars

    def test_builtin_fallback_deterministic(self, monkeypatch):
        # Simulate headroom being unavailable.
        c = TraceCompressor()
        c._hr_checked = True
        c._hr_log = None
        c._hr_json = None
        r1 = c.compress(LOG_80_LINES)
        r2 = c.compress(LOG_80_LINES)
        assert r1.method == "builtin"
        assert r1.text == r2.text
        assert "dropped" in r1.text
        assert "ValueError" in r1.text

    def test_never_raises_on_garbage(self):
        c = TraceCompressor()
        for garbage in ["\x00\x01", "{" * 50, "\n" * 500, None]:
            if garbage is None:
                assert c.compress(garbage).method == "passthrough"
            else:
                r = c.compress(garbage)
                assert isinstance(r.text, str)

    def test_compression_not_worth_it_keeps_original(self):
        c = TraceCompressor()
        c._hr_checked = True
        c._hr_log = None
        c._hr_json = None
        # All lines look like errors → nothing to drop.
        text = "\n".join("ERROR line %d" % i for i in range(60))
        r = c.compress(text)
        assert r.compressed_chars <= len(text)


class TestFlagGating:
    def test_flag_off_passthrough(self):
        # Default (repo yaml → headroom.smart_crusher.enabled=false)
        assert compress_for_llm(LOG_80_LINES) == LOG_80_LINES

    def test_flag_override_nested_off(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED", "0")
        assert compress_for_llm(LOG_80_LINES) == LOG_80_LINES


def test_flag_on_compresses_env(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED", "1")
    out = compress_for_llm(LOG_80_LINES)
    assert out != LOG_80_LINES
    assert "ValueError" in out


def test_ledger_event_on_compression(monkeypatch):
    import cost_ledger as cl

    monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED", "1")
    cl.reset_cost_ledger()
    compress_for_llm(LOG_80_LINES)
    events = [
        e for e in cl.get_cost_ledger().entries() if e["kind"] == "event"
    ]
    assert any(e["event_kind"] == "trace_compressed" for e in events)
    cl.reset_cost_ledger()
