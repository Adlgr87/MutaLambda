"""Tests for UAST emitters - testing NotImplementedError for unsupported nodes."""
import pytest

from muta_ext.uast.core_uast import (
    CoreUAST,
    LiteralNode,
    Identifier,
    BinaryOp,
    Function,
    If,
    For,
    While,
    Return,
    Comment,
    Opaque,
    TypeAnnotation,
    TryExcept,
    ExceptClause,
    StructDef,
    FieldDef,
    Match,
    MatchArm,
    Reference,
    Break,
    ParallelFor,
)
from muta_ext.uast.emitters.rust_emitter import RustEmitter
from muta_ext.uast.emitters.cpp_emitter import CppEmitter


class TestRustEmitterUnsupported:
    """Test that Rust emitter raises NotImplementedError for unsupported nodes."""

    def test_rust_emitter_raises_not_implemented_for_opaque(self):
        """Opaque nodes should raise NotImplementedError."""
        emitter = RustEmitter()
        opaque = Opaque(original_text="some opaque construct", lang="python")
        uast = CoreUAST(body=[opaque], language="rust")
        with pytest.raises(NotImplementedError, match="does not support|cannot emit"):
            emitter.emit(uast)

    def test_rust_emitter_raises_not_implemented_for_unknown_node(self):
        """Unknown node types should raise NotImplementedError."""
        emitter = RustEmitter()
        class UnknownNode:
            pass
        uast = CoreUAST(
            body=[UnknownNode()],
            language="rust",
        )
        with pytest.raises(NotImplementedError, match="RustEmitter does not support"):
            emitter.emit(uast)


class TestCppEmitterUnsupported:
    """Test that C++ emitter raises NotImplementedError for unsupported nodes."""

    def test_cpp_emitter_raises_not_implemented_for_opaque(self):
        """Opaque nodes should raise NotImplementedError."""
        emitter = CppEmitter()
        opaque = Opaque(original_text="some opaque construct", lang="python")
        uast = CoreUAST(body=[opaque], language="cpp")
        with pytest.raises(NotImplementedError, match="does not support|cannot emit"):
            emitter.emit(uast)

    def test_cpp_emitter_raises_not_implemented_for_unknown_node(self):
        """Unknown node types should raise NotImplementedError."""
        emitter = CppEmitter()
        class UnknownNode:
            pass
        uast = CoreUAST(
            body=[UnknownNode()],
            language="cpp",
        )
        with pytest.raises(NotImplementedError, match="CppEmitter does not support"):
            emitter.emit(uast)


class TestEmittersSupportedNodes:
    """Verify that supported nodes still emit correctly."""

    def test_rust_emitter_supports_function(self):
        """Function nodes should emit successfully."""
        emitter = RustEmitter()
        func = Function(
            name=Identifier(name="add"),
            params=[Identifier(name="a"), Identifier(name="b")],
            body=[BinaryOp(left=Identifier(name="a"), op="+", right=Identifier(name="b"))]
        )
        code = emitter.emit(CoreUAST(body=[func], language="rust"))
        assert "fn " in code
        assert "add" in code

    def test_cpp_emitter_supports_function(self):
        """Function nodes should emit successfully."""
        emitter = CppEmitter()
        func = Function(
            name=Identifier(name="add"),
            params=[Identifier(name="a"), Identifier(name="b")],
            body=[BinaryOp(left=Identifier(name="a"), op="+", right=Identifier(name="b"))]
        )
        code = emitter.emit(CoreUAST(body=[func], language="cpp"))
        assert "add" in code
        assert "auto" in code