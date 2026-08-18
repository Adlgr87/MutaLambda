"""UAST emitters for different languages."""
from muta_ext.uast.emitters.base import BaseEmitter
from muta_ext.uast.emitters.python_emitter import PythonEmitter, emit_from_uast
from muta_ext.uast.emitters.rust_emitter import RustEmitter
from muta_ext.uast.emitters.cpp_emitter import CppEmitter
from muta_ext.uast.emitters.go_emitter import GoEmitter

# Registry for known emitters
_EMITTERS = {
    "python": PythonEmitter,
    "rust": RustEmitter,
    "cpp": CppEmitter,
    "go": GoEmitter,
}


def get_emitter(language: str) -> BaseEmitter:
    """Get emitter for the specified language."""
    if language not in _EMITTERS:
        raise ValueError(f"No emitter registered for language: {language}")
    return _EMITTERS[language]()


__all__ = ["BaseEmitter", "PythonEmitter", "RustEmitter", "CppEmitter", "GoEmitter", "emit_from_uast", "get_emitter"]