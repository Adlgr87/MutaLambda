import pytest

import requests

from llm_backend import LLMBackend, LLMBackendError, _resolve_llm_backend


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
