"""UAST adapters for different languages."""
from muta_ext.uast.adapters.base import BaseAdapter
from muta_ext.uast.adapters.python_adapter import PythonAdapter, parse_to_uast

# Registry for known adapters
_ADAPTERS = {
    "python": PythonAdapter,
}


def get_adapter(language: str) -> BaseAdapter:
    """Get adapter for the specified language."""
    if language not in _ADAPTERS:
        raise ValueError(f"No adapter registered for language: {language}")
    return _ADAPTERS[language]()


__all__ = ["BaseAdapter", "PythonAdapter", "parse_to_uast", "get_adapter"]