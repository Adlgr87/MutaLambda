"""
Inferless integration wrapper (optional legacy adapter).

This file is intentionally isolated from the core evolutionary engine. It is
kept for deployments that still need the old InferlessPythonModel entrypoint.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from llm_backend import LLMBackend


class InferlessPythonModel:
    def __init__(self) -> None:
        self._llm: Optional[LLMBackend] = None

    def initialize(self) -> None:
        import os

        backend = os.getenv("MUTALAMBDA_LLM_BACKEND", "ollama")
        model = os.getenv("MUTALAMBDA_LLM_MODEL", "llama3.2:3b")
        self._llm = LLMBackend(backend=backend, model=model)

    def infer(self, inputs: Dict[str, Any]) -> Dict[str, str]:
        if not self._llm:
            raise RuntimeError("InferlessPythonModel not initialized. Call initialize() first.")

        prompt = inputs.get("prompt", "")
        out = self._llm.generate(prompt)
        return {"generated_text": out}

    def finalize(self) -> None:
        self._llm = None
