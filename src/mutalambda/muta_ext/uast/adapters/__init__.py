"""UAST adapters for different languages."""
from mutalambda.muta_ext.uast.adapters.base import BaseAdapter
from mutalambda.muta_ext.uast.adapters.python_adapter import PythonAdapter, parse_to_uast
from mutalambda.muta_ext.uast.adapters.rust_adapter import RustAdapter
from mutalambda.muta_ext.uast.adapters.cpp_adapter import CppAdapter
from mutalambda.muta_ext.uast.adapters.go_adapter import GoAdapter

# Registry for known adapters
_ADAPTERS = {
    "python": PythonAdapter,
    "rust": RustAdapter,
    "cpp": CppAdapter,
    "go": GoAdapter,
}


def get_adapter(language: str) -> BaseAdapter:
    """Get adapter for the specified language."""
    if language not in _ADAPTERS:
        raise ValueError(f"No adapter registered for language: {language}")
    return _ADAPTERS[language]()


__all__ = ["BaseAdapter", "PythonAdapter", "RustAdapter", "CppAdapter", "GoAdapter", "parse_to_uast", "get_adapter"]