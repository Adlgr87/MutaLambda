#!/usr/bin/env python3
"""Lightweight counters for the UAST v2 engine.

Deliberately dependency-free (a dict + a lock) so the UAST layer can never drag
the metrics stack into a hot path.  Values are exposed through
:func:`snapshot`, which the CLI/CI reporting and the shadow-mode comparison
consume; an optional sink lets ``metrics_exporter`` mirror them into Prometheus
without importing it here.
"""

from __future__ import annotations

import threading
import typing as T
from typing import Any, Callable, Dict, Optional

__all__ = ["incr", "set_gauge", "snapshot", "reset", "set_sink", "counter"]

_LOCK = threading.Lock()
_COUNTERS: Dict[str, float] = {}
_GAUGES: Dict[str, float] = {}
_SINK: Optional[Callable[[Dict[str, float], Dict[str, float]], None]] = None


def incr(name: str, value: float = 1.0) -> float:
    """Increment counter *name* by *value* (thread-safe) and return the total."""
    with _LOCK:
        total = _COUNTERS.get(name, 0.0) + value
        _COUNTERS[name] = total
        sink = _SINK
    if sink is not None:  # pragma: no cover - external integration
        sink(dict(_COUNTERS), dict(_GAUGES))
    return total


def set_gauge(name: str, value: float) -> None:
    """Set gauge *name* to *value*."""
    with _LOCK:
        _GAUGES[name] = float(value)
        sink = _SINK
    if sink is not None:  # pragma: no cover - external integration
        sink(dict(_COUNTERS), dict(_GAUGES))


def snapshot() -> Dict[str, float]:
    """Point-in-time copy of every counter and gauge."""
    with _LOCK:
        merged = dict(_COUNTERS)
        merged.update(_GAUGES)
        return merged


def reset() -> None:
    """Clear every counter/gauge (used between benchmark phases and tests)."""
    with _LOCK:
        _COUNTERS.clear()
        _GAUGES.clear()


def set_sink(sink: Optional[Callable[[Dict[str, float], Dict[str, float]], None]]) -> None:
    """Install (or remove) an integration callback invoked after each update."""
    global _SINK
    with _LOCK:
        _SINK = sink


def counter(name: str) -> float:
    """Read a single counter value (0.0 when unknown)."""
    with _LOCK:
        return _COUNTERS.get(name, 0.0)
