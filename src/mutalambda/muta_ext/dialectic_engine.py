"""Dialectic mutation wrapper: thesis, antithesis and synthesis."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DialecticConfig:
    """Configuration for pre-sandbox dialectic filtering."""

    enabled: bool = False
    critique_intensity: str = "medium"
    reject_on_syntax_error: bool = True


@dataclass
class DialecticMetrics:
    """Telemetry for dialectic mutation."""

    critique_rejection_rate: float = 0.0
    synthesis_fitness_gain: float = 0.0
    sandbox_calls_saved: int = 0
    attempts: int = 0
    rejections: int = 0


class DialecticEngine:
    """Runs LLM critique and synthesis before sandbox evaluation."""

    def __init__(self, config: Optional[DialecticConfig] = None) -> None:
        self.config = config or DialecticConfig()
        self.metrics = DialecticMetrics()

    def refine(self, base_code: str, thesis_code: str, llm_fn: Callable[[str], str]) -> str:
        """Return synthesized code, or base/thesis fallback when disabled."""
        if not self.config.enabled:
            return thesis_code

        self.metrics.attempts += 1
        if self.config.reject_on_syntax_error and not self._valid(thesis_code):
            self.metrics.rejections += 1
            self.metrics.sandbox_calls_saved += 1
            self._update_rates()
            return base_code

        critique_prompt = (
            "You are a strict Python code reviewer. Identify correctness, "
            "security, redundancy and performance risks. Return concise bullets only.\n\n"
            f"Base code:\n{base_code}\n\nCandidate code:\n{thesis_code}"
        )
        critique = llm_fn(critique_prompt)
        if self._critique_rejects(critique):
            self.metrics.rejections += 1
            self.metrics.sandbox_calls_saved += 1
            self._update_rates()
            return base_code

        synthesis_prompt = (
            "Synthesize a corrected Python candidate from the base, candidate and critique. "
            "Return only valid Python code, no markdown.\n\n"
            f"Base:\n{base_code}\n\nCandidate:\n{thesis_code}\n\nCritique:\n{critique}"
        )
        synthesized = llm_fn(synthesis_prompt)
        if self._valid(synthesized):
            self._update_rates()
            return synthesized
        self._update_rates()
        return thesis_code if self._valid(thesis_code) else base_code

    def _critique_rejects(self, critique: str) -> bool:
        lowered = critique.lower()
        hard_terms = ("syntax error", "unsafe", "infinite loop", "does not parse")
        return any(term in lowered for term in hard_terms)

    def _valid(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _update_rates(self) -> None:
        self.metrics.critique_rejection_rate = (
            self.metrics.rejections / max(1, self.metrics.attempts)
        )
