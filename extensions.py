"""Common contract for experimental evolution extensions (workflow §14).

HFC, THC, Dialectic, PatternMemory and Spatial should plug into this
lifecycle instead of ad-hoc attribute poking on MigrationBus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ExtensionContext:
    """Per-generation context passed to extensions."""

    generation: int
    run_id: str = ""
    task: str = ""
    islands: List[Any] = field(default_factory=list)
    best: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvolutionExtension(Protocol):
    """Lifecycle hooks for experimental modules."""

    name: str

    def on_generation_start(self, context: ExtensionContext) -> None: ...

    def on_candidate(self, candidate: Any, context: ExtensionContext) -> Any: ...

    def on_generation_end(self, context: ExtensionContext) -> None: ...

    def metrics(self) -> dict: ...


class ExtensionRegistry:
    """Ordered registry of evolution extensions."""

    def __init__(self) -> None:
        self._extensions: List[Any] = []

    def register(self, ext: Any) -> None:
        if ext is None:
            return
        name = getattr(ext, "name", None) or type(ext).__name__
        # Avoid duplicates by name
        self._extensions = [
            e for e in self._extensions if getattr(e, "name", type(e).__name__) != name
        ]
        # Attach name if missing
        if not hasattr(ext, "name"):
            try:
                ext.name = name
            except Exception:
                pass
        self._extensions.append(ext)

    def __iter__(self):
        return iter(self._extensions)

    def on_generation_start(self, context: ExtensionContext) -> None:
        for ext in self._extensions:
            hook = getattr(ext, "on_generation_start", None)
            if callable(hook):
                try:
                    hook(context)
                except Exception:
                    pass

    def on_candidate(self, candidate: Any, context: ExtensionContext) -> Any:
        current = candidate
        for ext in self._extensions:
            hook = getattr(ext, "on_candidate", None)
            if callable(hook):
                try:
                    out = hook(current, context)
                    if out is not None:
                        current = out
                except Exception:
                    pass
        return current

    def on_generation_end(self, context: ExtensionContext) -> None:
        for ext in self._extensions:
            hook = getattr(ext, "on_generation_end", None)
            if callable(hook):
                try:
                    hook(context)
                except Exception:
                    pass

    def all_metrics(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for ext in self._extensions:
            name = getattr(ext, "name", type(ext).__name__)
            m = getattr(ext, "metrics", None)
            if callable(m):
                try:
                    out[name] = dict(m() or {})
                except Exception:
                    out[name] = {}
            elif hasattr(ext, "metrics") and not callable(ext.metrics):
                metrics_obj = ext.metrics
                out[name] = getattr(metrics_obj, "__dict__", {}) or {}
        return out


class NoOpExtension:
    """Reference no-op extension."""

    name = "noop"

    def on_generation_start(self, context: ExtensionContext) -> None:
        return None

    def on_candidate(self, candidate: Any, context: ExtensionContext) -> Any:
        return candidate

    def on_generation_end(self, context: ExtensionContext) -> None:
        return None

    def metrics(self) -> dict:
        return {}
