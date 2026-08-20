"""LLM backend adapters used by MutaLambda.

Remediation (ML-LLM01..03):
- exponential retries with separate connect/read timeouts
- circuit breaker + optional local fallback
- call budget (per generation / total)
- structured response contract with code extraction
- optional replay log (hash + provider metadata, not full secrets)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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


class LLMBudgetExceeded(LLMBackendError):
    """Raised when the configured call budget is exhausted."""


class LLMCircuitOpen(LLMBackendError):
    """Raised when the circuit breaker is open."""


@dataclass
class StructuredLLMResponse:
    """Internal contract for LLM outputs (ML-LLM02)."""

    code: str
    changed_functions: List[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "changed_functions": list(self.changed_functions),
            "reason": self.reason,
            "confidence": self.confidence,
        }


def parse_structured_response(text: str) -> StructuredLLMResponse:
    """Parse JSON contract or fall back to fenced/raw code extraction."""
    raw = text or ""
    # Try JSON object first.
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            code = str(data.get("code", "") or "")
            if code.strip():
                return StructuredLLMResponse(
                    code=code,
                    changed_functions=list(data.get("changed_functions") or []),
                    reason=str(data.get("reason") or ""),
                    confidence=float(data.get("confidence") or 0.0),
                    raw=raw,
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Fenced python block.
    fence = re.search(r"```(?:python)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        code = fence.group(1).strip()
        return StructuredLLMResponse(code=code, raw=raw, confidence=0.5)

    # Heuristic: first def/class to end.
    m = re.search(r"(?m)^(def |class |async def ).*", raw)
    if m:
        code = raw[m.start():].strip()
        return StructuredLLMResponse(code=code, raw=raw, confidence=0.3)

    return StructuredLLMResponse(code=raw.strip(), raw=raw, confidence=0.1)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class LLMBackend:
    """Abstracción de generación de texto para diferentes back‑ends."""

    def __init__(
        self,
        backend: str = DEFAULT_BACKEND,
        model: str = DEFAULT_MODEL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        temperature: float = DEFAULT_TEMPERATURE,
        *,
        max_retries: int = 3,
        backoff_base_sec: float = 0.5,
        connect_timeout_sec: Optional[float] = None,
        read_timeout_sec: Optional[float] = None,
        max_calls_per_generation: int = 0,
        max_total_calls: int = 0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_sec: float = 30.0,
        fallback_fn: Optional[Callable[[str], str]] = None,
        replay_log_path: Optional[str] = None,
        privacy_allow_external: bool = True,
    ) -> None:
        self.backend = (backend or DEFAULT_BACKEND).lower()
        self.model = model or DEFAULT_MODEL
        self.timeout_sec = float(timeout_sec)
        self.temperature = float(temperature)
        self.max_retries = max(0, int(max_retries))
        self.backoff_base_sec = max(0.0, float(backoff_base_sec))
        # Default both to timeout_sec so existing clients see a scalar timeout.
        # Pass connect_timeout_sec/read_timeout_sec explicitly to split them.
        self.connect_timeout_sec = float(
            connect_timeout_sec if connect_timeout_sec is not None else self.timeout_sec
        )
        self.read_timeout_sec = float(
            read_timeout_sec if read_timeout_sec is not None else self.timeout_sec
        )
        self.max_calls_per_generation = max(0, int(max_calls_per_generation))
        self.max_total_calls = max(0, int(max_total_calls))
        self.circuit_failure_threshold = max(1, int(circuit_failure_threshold))
        self.circuit_cooldown_sec = float(circuit_cooldown_sec)
        self.fallback_fn = fallback_fn
        self.replay_log_path = replay_log_path
        self.privacy_allow_external = privacy_allow_external

        self._total_calls = 0
        self._gen_calls = 0
        self._consecutive_failures = 0
        self._circuit_opened_at: float = 0.0
        self._request_errors: List[str] = []

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

        if not self.privacy_allow_external and self.backend not in {"ollama"}:
            raise ValueError(
                f"privacy.allow_external_llm=false forbids backend={self.backend}"
            )

    def reset_generation_budget(self) -> None:
        self._gen_calls = 0

    def metrics(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "total_calls": self._total_calls,
            "generation_calls": self._gen_calls,
            "consecutive_failures": self._consecutive_failures,
            "circuit_open": self._circuit_is_open(),
            "recent_errors": list(self._request_errors[-10:]),
        }

    def _circuit_is_open(self) -> bool:
        if self._consecutive_failures < self.circuit_failure_threshold:
            return False
        if time.time() - self._circuit_opened_at >= self.circuit_cooldown_sec:
            # Half-open: allow one try.
            return False
        return True

    def _check_budget(self) -> None:
        if self.max_total_calls and self._total_calls >= self.max_total_calls:
            raise LLMBudgetExceeded(
                f"max_total_calls={self.max_total_calls} exhausted"
            )
        if self.max_calls_per_generation and self._gen_calls >= self.max_calls_per_generation:
            raise LLMBudgetExceeded(
                f"max_calls_per_generation={self.max_calls_per_generation} exhausted"
            )

    def _timeout_arg(self):
        """Use scalar timeout when connect==read (keeps tests/clients simple)."""
        if abs(self.connect_timeout_sec - self.read_timeout_sec) < 1e-9:
            return self.read_timeout_sec
        return (self.connect_timeout_sec, self.read_timeout_sec)

    def _single_request(self, prompt: str) -> str:
        timeout = self._timeout_arg()
        if self.backend == "ollama":
            payload = {"model": self.model, "prompt": prompt, "stream": False}
            resp = self._session.post(
                self._url,
                json=payload,
                timeout=timeout,
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
                timeout=timeout,
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
                timeout=timeout,
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
                timeout=timeout,
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
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content_blocks = data.get("content", [])
            text = "".join(
                block.get("text", "") for block in content_blocks if isinstance(block, dict)
            )
            return text

        raise ValueError(f"Unsupported LLM backend: {self.backend}")

    def _log_replay(
        self,
        prompt: str,
        response: str,
        *,
        ok: bool,
        error: str = "",
        attempts: int = 1,
    ) -> None:
        if not self.replay_log_path:
            return
        try:
            path = Path(self.replay_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": time.time(),
                "provider": self.backend,
                "model": self.model,
                "temperature": self.temperature,
                "prompt_hash": prompt_hash(prompt),
                "ok": ok,
                "attempts": attempts,
                "error": error[:300],
                "response_hash": prompt_hash(response) if response else "",
                "response_preview": (response or "")[:200],
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.debug("replay log write failed: %s", exc)

    def generate(self, prompt: str) -> str:
        """Genera texto con retries, budget y circuit breaker."""
        self._check_budget()
        if self._circuit_is_open():
            if self.fallback_fn is not None:
                logger.warning("LLM circuit open — using fallback")
                return self.fallback_fn(prompt)
            raise LLMCircuitOpen(
                f"circuit open after {self._consecutive_failures} failures"
            )

        last_exc: Optional[Exception] = None
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            try:
                text = self._single_request(prompt)
                self._total_calls += 1
                self._gen_calls += 1
                self._consecutive_failures = 0
                self._log_replay(prompt, text, ok=True, attempts=attempts)
                return text
            except Exception as exc:
                last_exc = exc
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.circuit_failure_threshold:
                    self._circuit_opened_at = time.time()
                err = str(exc)[:200]
                self._request_errors.append(err)
                logger.warning(
                    "LLMBackend (%s) attempt %d/%d failed: %s",
                    self.backend,
                    attempts,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    delay = self.backoff_base_sec * (2 ** attempt)
                    delay *= 0.5 + random.random()  # jitter
                    time.sleep(delay)

        self._log_replay(prompt, "", ok=False, error=str(last_exc), attempts=attempts)
        if self.fallback_fn is not None:
            logger.warning("LLMBackend falling back after failures")
            return self.fallback_fn(prompt)
        raise LLMBackendError(
            f"LLMBackend '{self.backend}' generation failed: {last_exc}"
        ) from last_exc

    def generate_structured(self, prompt: str) -> StructuredLLMResponse:
        """Generate and validate the structured code contract."""
        text = self.generate(prompt)
        parsed = parse_structured_response(text)
        if not (parsed.code or "").strip():
            raise LLMBackendError("structured response missing non-empty 'code'")
        return parsed


def _resolve_llm_backend(
    backend: str | None = None,
    model: str | None = None,
    timeout_sec: float | None = None,
    temperature: float | None = None,
    **kwargs: Any,
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
        **kwargs,
    )

    def generate(prompt: str) -> str:
        return llm.generate(prompt)

    # Attach backend instance for budget reset / metrics (bound methods cannot take attrs).
    generate.__self_backend__ = llm  # type: ignore[attr-defined]
    return generate


__all__ = [
    "LLMBackend",
    "LLMBackendError",
    "LLMBudgetExceeded",
    "LLMCircuitOpen",
    "StructuredLLMResponse",
    "parse_structured_response",
    "prompt_hash",
    "_resolve_llm_backend",
]
