"""MutaLambda Extensions — optional evolutionary modules."""

from __future__ import annotations

__all__ = [
    "advanced_selection",
    "dialectic_engine",
    "pattern_memory",
    "spatial_topology",
    "thc_engine",
    "uast",
]


def __getattr__(name: str):
    """Lazy attribute access so importing muta_ext does not load heavy engines."""
    if name in __all__:
        import importlib

        return importlib.import_module(f"muta_ext.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
