"""UAST mutators for transforming CoreUAST nodes."""

from __future__ import annotations

from muta_ext.uast.mutators.generated import discover_generated_mutators
from typing import Callable, Dict

__all__ = ["discover_mutators"]


def discover_mutators() -> Dict[str, Callable]:
    """Discover all available mutators including generated ones."""
    mutators: Dict[str, Callable] = {}
    mutators.update(discover_generated_mutators())
    return mutators