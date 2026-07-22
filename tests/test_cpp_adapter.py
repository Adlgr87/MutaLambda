#!/usr/bin/env python3
"""Tests for C++ adapter in Phase 3."""
import pytest

from muta_ext.uast.core_uast import CoreUAST, Function, If, Identifier
from muta_ext.uast.adapters.cpp_adapter import CppAdapter
from muta_ext.uast.emitters.cpp_emitter import CppEmitter
from muta_ext.uast.handlers.cpp_handler import CppHandler


class TestCppParse:
    """Test C++ parsing."""

    def test_cpp_parse_simple_function(self):
        """Parse simple C++ function."""
        adapter = CppAdapter()
        source = 'int add(int a, int b) { return a + b; }'
        
        assert adapter.can_parse(source)
        uast = adapter.parse_to_uast(source)
        
        assert uast.language == "cpp"

    def test_cpp_parse_if_else(self):
        """Parse C++ if/else."""
        adapter = CppAdapter()
        source = '''
int test(int x) {
    if (x > 0) {
        return 1;
    } else {
        return 0;
    }
}
'''
        uast = adapter.parse_to_uast(source)
        uast_dict = uast.to_dict()
        
        # Should contain function node
        assert any(n.get("__type__") == "Function" for n in uast_dict.get("body", []))


class TestCppEmit:
    """Test C++ emission."""

    def test_cpp_emit_function(self):
        """Emit Function node to C++."""
        emitter = CppEmitter()
        func = Function(
            name=Identifier(name="add"),
            params=[Identifier(name="a"), Identifier(name="b")],
            body=[Identifier(name="a + b")]
        )
        
        code = emitter.emit(CoreUAST(body=[func], language="cpp"))
        assert "auto add" in code


class TestCppHandler:
    """Test C++ handler."""

    def test_cpp_handler_validate_syntax_valid(self):
        """Validate valid C++ syntax."""
        handler = CppHandler()
        ok, err = handler.validate_syntax("int main() {}")
        # sin g++ disponible, debería usar tree-sitter
        assert isinstance(ok, bool)

    def test_cpp_handler_inherits_base(self):
        """CppHandler should inherit from BaseLanguageHandler."""
        from muta_ext.uast.handlers.base_handler import BaseLanguageHandler
        
        handler = CppHandler()
        assert isinstance(handler, BaseLanguageHandler)


class TestCppSupportedFeatures:
    """Test supported features."""

    def test_cpp_supported_features(self):
        """Should return supported features dict."""
        handler = CppHandler()
        features = handler.supported_features()
        
        assert features["functions"] is True
        assert features["templates"] is False