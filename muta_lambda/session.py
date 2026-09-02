"""MutaLambdaSession — context-manager lifecycle wrapper (Phase 2C extraction).

Extracted from ``__init__.py`` so the slim coordinator only re-exports.
``MutaLambdaSession`` is a tiny (~30 lines) context manager that guarantees the
agent is shut down even on early-exit or exception.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from muta_lambda.agent import MutaLambdaAgent

__all__ = ["MutaLambdaSession"]


class MutaLambdaSession:
    """Context manager for construct → run → shutdown lifecycle (ML-E02)."""

    def __init__(self, agent: "MutaLambdaAgent"):
        self.agent = agent

    def __enter__(self) -> "MutaLambdaAgent":
        return self.agent

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.agent.shutdown()
        except Exception:
            pass
        return False

    def run(self, task: str = "", **kwargs: Any):
        """Proxy to ``agent.run`` so callers can chain ``Session(...).run()``."""
        return self.agent.run(task=task, **kwargs)