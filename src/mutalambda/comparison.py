"""Centralized value comparison for evaluation and differential tests (FIX 2.2)."""

from __future__ import annotations

import math
from typing import Any, Callable, Dict

COMPARATORS = (
    "equal",
    "float_close",
    "array_allclose",
    "contains",
    "predicate_registered",
)

_REGISTERED_PREDICATES: Dict[str, Callable[[Any], bool]] = {}


def register_predicate(name: str, fn: Callable[[Any], bool]) -> None:
    """Register a named predicate for development-mode comparisons."""
    _REGISTERED_PREDICATES[name] = fn


def compare_values(got: Any, expected: Any, comparison: str = "equal") -> bool:
    """Compare candidate output against expected value using a declared comparator."""
    comparison = (comparison or "equal").lower()
    if comparison == "equal":
        return got == expected
    if comparison == "float_close":
        try:
            return math.isclose(float(got), float(expected), rel_tol=1e-9, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False
    if comparison == "array_allclose":
        try:
            import numpy as np

            return bool(np.allclose(np.asarray(got), np.asarray(expected)))
        except Exception:
            return False
    if comparison == "contains":
        try:
            return expected in got
        except TypeError:
            return False
    if comparison == "predicate_registered":
        if not isinstance(expected, str) or expected not in _REGISTERED_PREDICATES:
            return False
        return bool(_REGISTERED_PREDICATES[expected](got))
    raise ValueError(f"Unknown comparison: {comparison!r}. Allowed: {COMPARATORS}")
