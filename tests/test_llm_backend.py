import pytest

import requests

from llm_backend import (
    LLMBackend,
    LLMBackendError,
    LLMBudgetExceeded,
    LLMCircuitOpen,
    MODEL_PRICING,
    _resolve_llm_backend,
    _lookup_pricing,
    _estimate_tokens,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response_payload):
        self.calls = []
        self.response = FakeResponse(response_payload)

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def test_ollama_backend_uses_configurable_url_and_timeout(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_OLLAMA_URL", "http://ollama.example/api/generate")
    monkeypatch.setenv("MUTALAMBDA_LLM_TIMEOUT_SEC", "7")

    session = FakeSession({"response": "def f(): return 1"})
    monkeypatch.setattr(requests, "Session", lambda: session)

    llm = LLMBackend(backend="ollama", model="llama-test", timeout_sec=7)

    assert llm.generate("prompt") == "def f(): return 1"
    assert session.calls == [
        {
            "url": "http://ollama.example/api/generate",
            "json": {"model": "llama-test", "prompt": "prompt", "stream": False},
            "headers": None,
            "timeout": 7,
        }
    ]


def test_openai_backend_uses_env_endpoint_key_and_temperature(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_OPENAI_URL", "http://openai-proxy/v1/chat/completions")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MUTALAMBDA_LLM_TEMPERATURE", "0.7")

    session = FakeSession({"choices": [{"message": {"content": "def f(): return 2"}}]})
    monkeypatch.setattr(requests, "Session", lambda: session)

    llm = LLMBackend(
        backend="openai",
        model="gpt-test",
        timeout_sec=5,
        temperature=0.7,
    )

    assert llm.generate("prompt") == "def f(): return 2"
    call = session.calls[0]
    assert call["url"] == "http://openai-proxy/v1/chat/completions"
    assert call["headers"] == {"Authorization": "Bearer test-key"}
    assert call["timeout"] == 5
    assert call["json"] == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "prompt"}],
        "temperature": 0.7,
    }


def test_anthropic_backend_uses_env_version_and_key(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_ANTHROPIC_URL", "http://anthropic-proxy/v1/messages")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("MUTALAMBDA_ANTHROPIC_VERSION", "2024-01-01")

    session = FakeSession({"content": [{"type": "text", "text": "def f(): return 3"}]})
    monkeypatch.setattr(requests, "Session", lambda: session)

    llm = LLMBackend(backend="anthropic", model="claude-test", timeout_sec=9)

    assert llm.generate("prompt") == "def f(): return 3"
    call = session.calls[0]
    assert call["url"] == "http://anthropic-proxy/v1/messages"
    assert call["headers"] == {
        "x-api-key": "anthropic-key",
        "anthropic-version": "2024-01-01",
    }
    assert call["timeout"] == 9


def test_resolve_llm_backend_accepts_explicit_config(monkeypatch):
    session = FakeSession({"response": "def f(): return 4"})
    monkeypatch.setattr(requests, "Session", lambda: session)

    generate = _resolve_llm_backend(
        backend="ollama",
        model="configured-model",
        timeout_sec=11,
        temperature=0.3,
    )

    assert generate("prompt") == "def f(): return 4"
    assert session.calls[0]["timeout"] == 11
    assert session.calls[0]["json"]["model"] == "configured-model"


def test_unsupported_backend_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported LLM backend"):
        LLMBackend(backend="not-a-provider")


@pytest.mark.parametrize("backend", ["microsoft_cpp", "huggingface_cli"])
def test_legacy_cli_backends_raise_value_error(backend):
    with pytest.raises(ValueError, match="no longer supported"):
        LLMBackend(backend=backend)


def test_generation_failure_raises_llm_backend_error(monkeypatch):
    class FailingSession:
        def post(self, *args, **kwargs):
            raise requests.RequestException("network down")

    monkeypatch.setattr(requests, "Session", lambda: FailingSession())
    llm = LLMBackend(backend="ollama")
    with pytest.raises(LLMBackendError, match="generation failed"):
        llm.generate("prompt")


# ---------------------------------------------------------------------------
# Cost tracking tests
# ---------------------------------------------------------------------------

def test_estimate_tokens_approximate():
    # Heuristic: ~4 chars per token, minimum 1.
    assert _estimate_tokens("hello world") == max(1, len("hello world") // 4)
    assert _estimate_tokens("") == 1
    assert _estimate_tokens("abcdefghijklmnopqrstuvwxyz") == 6  # 26 // 4 == 6


def test_lookup_pricing_known_model():
    pricing = _lookup_pricing("gpt-4o")
    assert pricing is not None
    assert pricing["prompt"] == 2.50
    assert pricing["completion"] == 10.00


def test_lookup_pricing_with_provider_prefix():
    pricing = _lookup_pricing("openai/gpt-4o")
    assert pricing == MODEL_PRICING["gpt-4o"]


def test_lookup_pricing_unknown_model_returns_none():
    assert _lookup_pricing("nonexistent-model") is None


def test_metrics_includes_cost_and_tokens_for_known_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    session = FakeSession({"choices": [{"message": {"content": "hi"}}]})
    monkeypatch.setattr(requests, "Session", lambda: session)

    llm = LLMBackend(backend="openai", model="gpt-4o")
    result = llm.generate("prompt text here")

    assert result == "hi"
    metrics = llm.metrics()
    assert "cost_usd" in metrics
    assert metrics["cost_usd"] > 0
    assert metrics["token_usage"]["prompt_tokens"] > 0
    assert metrics["token_usage"]["completion_tokens"] > 0
    assert metrics["pricing"] is not None


def test_max_cost_usd_raises_budget_exceeded(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    session = FakeSession({"choices": [{"message": {"content": "hi"}}]})
    monkeypatch.setattr(requests, "Session", lambda: session)

    llm = LLMBackend(backend="openai", model="gpt-4o", max_cost_usd=0.000001)
    # First call consumes a tiny fraction; second call should trip the limit.
    llm.generate("first prompt to bump cost")
    with pytest.raises(LLMBudgetExceeded, match="max_cost_usd"):
        llm.generate("second prompt")


# ---------------------------------------------------------------------------
# Batch mode tests
# ---------------------------------------------------------------------------

def test_generate_batch_sequential_for_unsupported_backend(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_OLLAMA_URL", "http://ollama.example/api/generate")
    session = FakeSession({"response": "ok"})
    monkeypatch.setattr(requests, "Session", lambda: session)

    llm = LLMBackend(backend="ollama", model="test")
    results = llm.generate_batch(["prompt1", "prompt2"])

    assert results == ["ok", "ok"]
    assert len(session.calls) == 2


def test_generate_batch_empty_list_returns_empty():
    llm = LLMBackend(backend="ollama", model="test")
    assert llm.generate_batch([]) == []


def test_generate_batch_circuit_open_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    session = FakeSession({"choices": [{"message": {"content": "x"}}]})
    monkeypatch.setattr(requests, "Session", lambda: session)

    class FailingSession:
        def post(self, *a, **k):
            raise requests.RequestException("boom")

    # Force circuit open.
    llm = LLMBackend(backend="openai", model="gpt-4o", circuit_failure_threshold=1)
    llm._consecutive_failures = 1
    llm._circuit_opened_at = 9999999999
    with pytest.raises(LLMCircuitOpen):
        llm.generate_batch(["p1", "p2"])
