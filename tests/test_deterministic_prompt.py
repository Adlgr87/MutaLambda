"""Tests for deterministic prompts (Fase 0, O2).

Acceptance: two identical (twin) LLM calls must send byte-identical prompts.
"""

from __future__ import annotations

import os

import pytest

from llm_backend import (
    LLMBackend,
    deterministic_prompt,
    sanitize_prompt_for_determinism,
)

UUID_A = "3f2b8c1e-9d4a-4c6f-8b21-0e5d7a9c3f10"
TS_ISO = "2026-09-10T12:34:56.789Z"
TS_CTIME = "Wed Sep 10 12:34:56 UTC 2026"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MUTALAMBDA_OPT_"):
            monkeypatch.delenv(name)
    from optimization_flags import reset_optimization_flags

    reset_optimization_flags()
    yield
    reset_optimization_flags()


# ── Sanitizer unit tests ─────────────────────────────────────────────────────


def test_sanitizer_strips_uuids_and_timestamps():
    prompt = f"run {UUID_A} started at {TS_ISO} (host said {TS_CTIME})\nDo the job."
    out = sanitize_prompt_for_determinism(prompt)
    assert UUID_A not in out
    assert TS_ISO not in out
    assert TS_CTIME not in out
    assert "[UUID]" in out
    assert out.count("[TIMESTAMP]") == 2


def test_sanitizer_is_idempotent():
    prompt = f"one {UUID_A} two {TS_ISO}"
    once = sanitize_prompt_for_determinism(prompt)
    twice = sanitize_prompt_for_determinism(once)
    assert once == twice


def test_sanitizer_preserves_plain_text():
    prompt = "def f(x):\n    return x + 1\n"
    assert sanitize_prompt_for_determinism(prompt) == prompt


def test_deterministic_prompt_fixed_order():
    a = "HEADER"
    b = "BODY-1"
    c = "BODY-2"
    assert deterministic_prompt(a, b, c, sep="\n\n") == "HEADER\n\nBODY-1\n\nBODY-2"
    # Fixed order: swapping inputs changes output (no hidden shuffling).
    assert deterministic_prompt(a, c, b, sep="\n\n") != deterministic_prompt(a, b, c, sep="\n\n")
    # None blocks are dropped without changing separators.
    assert deterministic_prompt(a, None, c, sep="\n") == "HEADER\nBODY-2"


def test_twin_calls_byte_identical_prompt(monkeypatch):
    """Acceptance: two gemela calls ⇒ identical outgoing prompt bytes."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-det")
    backend = LLMBackend(backend="openai", model="gpt-4o-mini", timeout_sec=1.0)
    sent: list[str] = []

    def fake_request(prompt: str) -> str:
        sent.append(prompt)
        return "ok"

    monkeypatch.setattr(backend, "_single_request", fake_request)

    prompt = f"job {UUID_A}\nlogged at {TS_ISO}\nsource code below\n"
    backend.generate(prompt)
    backend.generate(prompt)
    assert len(sent) == 2
    assert sent[0] == sent[1]  # byte-identical
    assert UUID_A not in sent[0]
    assert TS_ISO not in sent[0]


def test_flag_disables_sanitization(monkeypatch):
    """deterministic_prompt.enabled=false restores the raw prompt path."""
    monkeypatch.setenv("MUTALAMBDA_OPT_DETERMINISTIC_PROMPT__ENABLED", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-det")
    backend = LLMBackend(backend="openai", model="gpt-4o-mini", timeout_sec=1.0)
    sent: list[str] = []
    monkeypatch.setattr(
        backend, "_single_request", lambda p: (sent.append(p), "ok")[1]
    )
    prompt = f"job {UUID_A}"
    backend.generate(prompt)
    assert sent[0] == prompt  # untouched


def test_batch_twin_calls_byte_identical(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-det")
    backend = LLMBackend(backend="openai", model="gpt-4o-mini", timeout_sec=1.0)
    sent: list[str] = []
    monkeypatch.setattr(
        backend, "_single_request", lambda p: (sent.append(p), "ok")[1]
    )
    prompts = [f"m1 {UUID_A}", f"m2 {TS_ISO}"]
    backend.generate_batch(prompts)
    backend.generate_batch(prompts)
    assert sent[:2] == sent[2:]
    assert all(UUID_A not in p and TS_ISO not in p for p in sent)
