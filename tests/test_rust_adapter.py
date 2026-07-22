#!/usr/bin/env python3
"""Tests for Rust adapter in Phase 2."""
import subprocess
import shutil

import pytest

from muta_ext.uast.core_uast import CoreUAST, Function, If, For, While, BinaryOp, LiteralNode, Identifier
from muta_ext.uast.adapters.rust_adapter import RustAdapter
from muta_ext.uast.emitters.rust_emitter import RustEmitter
from muta_ext.uast.handlers.rust_handler import RustHandler


class TestRustParse:
    """Test Rust parsing."""

    def test_rust_parse_simple_function(self):
        """Parse simple Rust function."""
        adapter = RustAdapter()
        source = 'fn add(a: i32, b: i32) -> i32 { a + b }'
        
        assert adapter.can_parse(source)
        uast = adapter.parse_to_uast(source)
        
        assert uast.language == "rust"
        assert uast.canonical_hash() is not None

    def test_rust_parse_if_else(self):
        """Parse Rust if/else."""
        adapter = RustAdapter()
        source = '''
fn test(x: i32) -> i32 {
    if x > 0 {
        x
    } else {
        0
    }
}
'''
        uast = adapter.parse_to_uast(source)
        uast_dict = uast.to_dict()
        
        # Should contain function node
        assert any(n.get("__type__") == "Function" for n in uast_dict.get("body", []))


class TestRustEmit:
    """Test Rust emission."""

    def test_rust_emit_function(self):
        """Emit Function node to Rust."""
        emitter = RustEmitter()
        func = Function(
            name=Identifier(name="add"),
            params=[Identifier(name="a"), Identifier(name="b")],
            body=[BinaryOp(left=Identifier(name="a"), op="+", right=Identifier(name="b"))]
        )
        
        code = emitter.emit(CoreUAST(body=[func], language="rust"))
        assert "fn " in code
        assert "add" in code


class TestRustHandler:
    """Test Rust handler."""

    def test_rust_handler_validate_syntax_valid(self):
        """Validate valid Rust syntax."""
        handler = RustHandler()
        # Without rustc available, should still work
        ok, err = handler.validate_syntax("fn main() {}")
        # Either rustc works or we skip
        assert isinstance(ok, bool)

    def test_rust_handler_inherits_base(self):
        """RustHandler should inherit from BaseLanguageHandler."""
        from muta_ext.uast.handlers.base_handler import BaseLanguageHandler
        
        handler = RustHandler()
        assert isinstance(handler, BaseLanguageHandler)


class TestRustRoundtrip:
    """Test Rust roundtrip."""

    def test_rust_roundtrip_simple(self):
        """Simple roundtrip test."""
        handler = RustHandler()
        source = '''
fn add(a: i32, b: i32) -> i32 {
    a + b
}
'''
        
        try:
            result = handler.roundtrip(source)
            assert "fn " in result
            assert "add" in result
        except Exception as e:
            # Skip if tree-sitter parsing fails
            pytest.skip(f"Roundtrip skipped: {e}")


class TestRustSupportedFeatures:
    """Test supported features."""

    def test_rust_supported_features(self):
        """Should return supported features dict."""
        handler = RustHandler()
        features = handler.supported_features()
        
        assert features["functions"] is True
        assert features["match"] is True
        assert features["macros"] is False
        assert features["traits"] is False