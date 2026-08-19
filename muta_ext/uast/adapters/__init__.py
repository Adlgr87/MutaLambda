"""UAST adapters for different languages — lazy registry.

Rust/C/C++/Go adapters depend on optional ``tree-sitter`` bindings (the
``uast`` extra).  To keep Python-only mode (``use_uast=False``) working
without those dependencies installed, we do NOT import the heavy adapter
modules at package import time.  Adapters are loaded on first use through
:func:`get_adapter` and the module-level lazy attribute hook
(:data:`__getattr__`), raising a friendly :class:`ImportError` with install
instructions when the optional dependencies are missing.
"""
from __future__ import annotations

from importlib import import_module
from typing import Dict, Optional, Tuple

from muta_ext.uast.adapters.base import BaseAdapter
from muta_ext.uast.adapters.python_adapter import PythonAdapter, parse_to_uast

# language -> (module_path, class_name, optional extra required for the language)
_ADAPTERS: Dict[str, Tuple[str, str, Optional[str]]] = {
    "python": ("muta_ext.uast.adapters.python_adapter", "PythonAdapter", None),
    "rust": ("muta_ext.uast.adapters.rust_adapter", "RustAdapter", "uast"),
    "cpp": ("muta_ext.uast.adapters.cpp_adapter", "CppAdapter", "uast"),
    "go": ("muta_ext.uast.adapters.go_adapter", "GoAdapter", "uast"),
}

# Module-level names kept for backward compatibility with `from ... import
# RustAdapter` style usage.  Resolved lazily via __getattr__ so importing the
# package never pulls in tree-sitter.
_LAZY_NAMES: Dict[str, str] = {
    "PythonAdapter": "muta_ext.uast.adapters.python_adapter",
    "RustAdapter": "muta_ext.uast.adapters.rust_adapter",
    "CppAdapter": "muta_ext.uast.adapters.cpp_adapter",
    "GoAdapter": "muta_ext.uast.adapters.go_adapter",
}


def _missing_extra_message(language: str, extra: Optional[str]) -> ImportError:
    """Build the friendly ImportError for missing tree-sitter bindings."""
    hint = f"pip install 'mutalambda[{extra}]'" if extra else "pip install tree-sitter"
    return ImportError(
        f"The '{language}' UAST adapter requires optional tree-sitter bindings. "
        f"Install them with: {hint}"
    )


def _load_class(language: str, module_path: str, class_name: str, extra: Optional[str]):
    """Import and return an adapter class, translating missing deps."""
    try:
        module = import_module(module_path)
    except ImportError as exc:
        # Re-raise as a friendly ImportError mentioning the install command
        # when the failure is tied to the optional tree-sitter bindings.
        if extra is not None:
            raise _missing_extra_message(language, extra) from exc
        raise
    try:
        return getattr(module, class_name)
    except AttributeError as exc:  # pragma: no cover - defensive
        raise ImportError(
            f"Module {module_path!r} does not expose {class_name!r}"
        ) from exc


def get_adapter(language: str) -> BaseAdapter:
    """Return an adapter instance for *language*.

    Python is always available.  Rust/C/C++/Go require the ``uast`` extra;
    if the underlying tree-sitter bindings cannot be imported an
    :class:`ImportError` with install instructions is raised (not a
    :class:`NameError`).
    """
    language = language.lower()
    if language not in _ADAPTERS:
        raise ValueError(f"No adapter registered for language: {language}")
    module_path, class_name, extra = _ADAPTERS[language]
    adapter_cls = _load_class(language, module_path, class_name, extra)
    try:
        return adapter_cls()
    except ImportError as exc:
        # The adapter module imported but instantiation failed because an
        # optional tree-sitter binding was unavailable — surface the friendly
        # install hint instead of a raw error.
        if extra is not None:
            raise _missing_extra_message(language, extra) from exc
        raise


def __getattr__(name: str):
    """Lazily expose adapter classes so `from ... import RustAdapter` works
    without importing tree-sitter at package import time."""
    if name in _LAZY_NAMES:
        language = _reverse_language(name)
        module_path, class_name, extra = _ADAPTERS[language]
        cls = _load_class(language, module_path, class_name, extra)
        globals()[name] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _reverse_language(class_name: str) -> str:
    """Map an adapter class name back to its registry language key."""
    for language, (_module_path, name, _extra) in _ADAPTERS.items():
        if name == class_name:
            return language
    # Fallback for PythonAdapter if registry ever changes
    return "python" if class_name == "PythonAdapter" else class_name.lower()


__all__ = [
    "BaseAdapter",
    "PythonAdapter",
    "RustAdapter",
    "CppAdapter",
    "GoAdapter",
    "parse_to_uast",
    "get_adapter",
]