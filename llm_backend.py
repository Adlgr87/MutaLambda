"""LLM backend adapters used by MutaLambda."""

from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger("MutaLambda")

DEFAULT_BACKEND = "ollama"
DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_TIMEOUT_SEC = 60.0
DEFAULT_TEMPERATURE = 0.2
SUPPORTED_BACKENDS = {
    "ollama",
    "openai",
    "anthropic",
    "openrouter",
    "mistral",
}


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


class LLMBackendError(RuntimeError):
    """Raised when a configured LLM backend fails to generate a response."""


class LLMBackend:
    """Abstracción de generación de texto para diferentes back‑ends."""

    def __init__(
        self,
        backend: str = DEFAULT_BACKEND,
        model: str = DEFAULT_MODEL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        self.backend = (backend or DEFAULT_BACKEND).lower()
        self.model = model or DEFAULT_MODEL
        self.timeout_sec = float(timeout_sec)
        self.temperature = float(temperature)
        self._init_backend()

    def _init_backend(self) -> None:
        import requests

        if self.backend == "ollama":
            self._session = requests.Session()
            self._url = _env("MUTALAMBDA_OLLAMA_URL", "http://localhost:11434/api/generate")
            self._headers = {}
        elif self.backend == "openai":
            self._session = requests.Session()
            self._url = _env(
                "MUTALAMBDA_OPENAI_URL",
                "https://api.openai.com/v1/chat/completions",
            )
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is required for backend=openai")
            self._headers = {"Authorization": f"Bearer {api_key}"}
        elif self.backend == "anthropic":
            self._session = requests.Session()
            self._url = _env(
                "MUTALAMBDA_ANTHROPIC_URL",
                "https://api.anthropic.com/v1/messages",
            )
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is required for backend=anthropic")
            self._headers = {
                "x-api-key": api_key,
                "anthropic-version": _env("MUTALAMBDA_ANTHROPIC_VERSION", "2023-06-01"),
            }
        elif self.backend == "openrouter":
            self._session = requests.Session()
            self._url = _env(
                "MUTALAMBDA_OPENROUTER_URL",
                "https://openrouter.ai/api/v1/chat/completions",
            )
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError("OPENROUTER_API_KEY is required for backend=openrouter")
            self._headers = {"Authorization": f"Bearer {api_key}"}
        elif self.backend == "mistral":
            self._session = requests.Session()
            self._url = _env(
                "MUTALAMBDA_MISTRAL_URL",
                "https://api.mistral.ai/v1/chat/completions",
            )
            api_key = os.getenv("MISTRAL_API_KEY")
            if not api_key:
                raise ValueError("MISTRAL_API_KEY is required for backend=mistral")
            self._headers = {"Authorization": f"Bearer {api_key}"}
        elif self.backend in {"microsoft_cpp", "huggingface_cli"}:
            raise ValueError(
                f"LLM backend '{self.backend}' is no longer supported. "
                "Use one of: ollama, openai, anthropic, openrouter, mistral."
            )
        else:
            raise ValueError(f"Unsupported LLM backend: {self.backend}")

    def generate(self, prompt: str) -> str:
        """Genera texto a partir de ``prompt`` usando el back‑end seleccionado."""
        try:
            if self.backend == "ollama":
                payload = {"model": self.model, "prompt": prompt, "stream": False}
                resp = self._session.post(
                    self._url,
                    json=payload,
                    timeout=self.timeout_sec,
                )
                resp.raise_for_status()
                return resp.json().get("response", "")

            if self.backend == "openai":
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                }
                resp = self._session.post(
                    self._url,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout_sec,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

            if self.backend == "openrouter":
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                }
                resp = self._session.post(
                    self._url,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout_sec,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

            if self.backend == "mistral":
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                }
                resp = self._session.post(
                    self._url,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout_sec,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

            if self.backend == "anthropic":
                payload = {
                    "model": self.model,
                    "max_tokens": int(_env("MUTALAMBDA_ANTHROPIC_MAX_TOKENS", "1024")),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                }
                resp = self._session.post(
                    self._url,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout_sec,
                )
                resp.raise_for_status()
                data = resp.json()
                content_blocks = data.get("content", [])
                text = "".join(
                    block.get("text", "") for block in content_blocks if isinstance(block, dict)
                )
                return text

        except Exception as exc:
            logger.error("LLMBackend (%s) generation failed: %s", self.backend, exc)
            raise LLMBackendError(
                f"LLMBackend '{self.backend}' generation failed: {exc}"
            ) from exc


def _resolve_llm_backend(
    backend: str | None = None,
    model: str | None = None,
    timeout_sec: float | None = None,
    temperature: float | None = None,
) -> Callable[[str], str]:
    """Factory que devuelve una función ``generate`` basada en la configuración."""
    resolved_backend = backend or os.getenv("MUTALAMBDA_LLM_BACKEND", DEFAULT_BACKEND)
    resolved_model = model or os.getenv("MUTALAMBDA_LLM_MODEL", DEFAULT_MODEL)
    resolved_timeout = timeout_sec if timeout_sec is not None else DEFAULT_TIMEOUT_SEC
    resolved_temperature = (
        temperature if temperature is not None else DEFAULT_TEMPERATURE
    )
    llm = LLMBackend(
        backend=resolved_backend,
        model=resolved_model,
        timeout_sec=float(_env("MUTALAMBDA_LLM_TIMEOUT_SEC", str(resolved_timeout))),
        temperature=float(_env("MUTALAMBDA_LLM_TEMPERATURE", str(resolved_temperature))),
    )
    return llm.generate


__all__ = ["LLMBackend", "LLMBackendError", "_resolve_llm_backend"]
