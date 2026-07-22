"""UAST adapters for different languages."""
from muta_ext.uast.adapters.base import BaseAdapter
from muta_ext.uast.adapters.python_adapter import PythonAdapter, parse_to_uast
from muta_ext.uast.adapters.rust_adapter import RustAdapter
from muta_ext.uast.adapters.cpp_adapter import CppAdapter

# Registry for known adapters
_ADAPTERS = {
    "python": PythonAdapter,
    "rust": RustAdapter,
    "cpp": CppAdapter,
}


def get_adapter(language: str) -> BaseAdapter:
    """Get adapter for the specified language."""
    if language not in _ADAPTERS:
        raise ValueError(f"No adapter registered for language: {language}")
    return _ADAPTERS[language]()


__all__ = ["BaseAdapter", "PythonAdapter", "RustAdapter", "CppAdapter", "parse_to_uast", "get_adapter"]