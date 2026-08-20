"""Runtime discovery for generated UAST mutators."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Callable, Dict


def discover_generated_mutators() -> Dict[str, Callable]:
    """Return importable generated mutators that expose ``mutate``."""
    discovered: Dict[str, Callable] = {}
    for module_info in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        mutate_fn = getattr(module, "mutate", None)
        if callable(mutate_fn):
            discovered[module_info.name] = mutate_fn
    return discovered

