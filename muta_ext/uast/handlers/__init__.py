#!/usr/bin/env python3
"""Language handlers for UAST multi-language support."""
from muta_ext.uast.handlers.base_handler import BaseLanguageHandler
from muta_ext.uast.handlers.rust_handler import RustHandler
from muta_ext.uast.handlers.cpp_handler import CppHandler
from muta_ext.uast.handlers.go_handler import GoHandler

# Registry for known handlers
_HANDLERS = {
    "rust": RustHandler,
    "cpp": CppHandler,
    "go": GoHandler,
}


def get_handler(language: str) -> BaseLanguageHandler:
    """Get handler for the specified language."""
    if language not in _HANDLERS:
        raise ValueError(f"No handler registered for language: {language}")
    return _HANDLERS[language]()


__all__ = ["BaseLanguageHandler", "RustHandler", "CppHandler", "GoHandler", "get_handler"]