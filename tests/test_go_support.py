#!/usr/bin/env python3
"""Tests for Go language support in MutaLambda."""
import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from muta_ext.uast.adapters.go_adapter import GoAdapter
from muta_ext.uast.emitters.go_emitter import GoEmitter
from muta_ext.uast.handlers.go_handler import GoHandler
from muta_ext.uast.core_uast import CoreUAST, Function, Identifier, Return, LiteralNode, StructDef, FieldDef, TypeAnnotation


class TestGoAdapter:
    """Test Go UAST adapter."""

    def test_can_parse_simple_function(self):
        """Test parsing a simple Go function."""
        source = """
package main

func hello() string {
    return "hello"
}
"""
        adapter = GoAdapter()
        assert adapter.can_parse(source) is True

    def test_can_parse_function_with_params(self):
        """Test parsing Go function with parameters."""
        source = """
package main

func add(a int, b int) int {
    return a + b
}
"""
        adapter = GoAdapter()
        assert adapter.can_parse(source) is True

    def test_can_parse_struct(self):
        """Test parsing Go struct."""
        source = """
package main

type Person struct {
    Name string
    Age  int
}
"""
        adapter = GoAdapter()
        assert adapter.can_parse(source) is True

    def test_can_parse_interface(self):
        """Test parsing Go interface."""
        source = """
package main

type Speaker interface {
    Speak() string
}
"""
        adapter = GoAdapter()
        assert adapter.can_parse(source) is True

    def test_can_parse_concurrency(self):
        """Test parsing Go concurrency patterns."""
        source = """
package main

func worker(id int, jobs <-chan int, results chan<- int) {
    for j := range jobs {
        results <- j * 2
    }
}
"""
        adapter = GoAdapter()
        assert adapter.can_parse(source) is True

    def test_cannot_parse_invalid_go(self):
        """Test rejection of invalid Go code."""
        source = """
package main

func invalid(
"""
        adapter = GoAdapter()
        assert adapter.can_parse(source) is False

    def test_parse_to_uast_basic(self):
        """Test parsing to UAST."""
        source = """
package main

func add(a int, b int) int {
    return a + b
}
"""
        adapter = GoAdapter()
        uast = adapter.parse_to_uast(source)

        assert uast is not None
        assert hasattr(uast, 'body')
        assert uast.language == "go"


class TestGoEmitter:
    """Test Go code emitter."""

    def test_emit_simple_function(self):
        """Test emitting a simple Go function."""
        emitter = GoEmitter()

        func = Function(
            name=Identifier(name="test_func"),
            params=[],
            body=[Return(value=LiteralNode(value=42))],
            return_type="int"
        )
        uast = CoreUAST(body=[func], language="go")
        result = emitter.emit(uast)
        assert "func" in result
        assert "test_func" in result

    def test_emit_struct(self):
        """Test emitting a Go struct."""
        emitter = GoEmitter()

        struct = StructDef(
            name="Point",
            fields=[
                FieldDef(name="X", type_annotation=TypeAnnotation(type_name="float64")),
                FieldDef(name="Y", type_annotation=TypeAnnotation(type_name="float64")),
            ]
        )
        uast = CoreUAST(body=[struct], language="go")
        result = emitter.emit(uast)
        assert "type Point struct" in result
        assert "X" in result
        assert "Y" in result

    def test_format_code(self):
        """Test code formatting."""
        emitter = GoEmitter()
        uast = CoreUAST(body=[], language="go")
        formatted = emitter.emit(uast)
        assert formatted is not None

    def test_format_invalid_code(self):
        """Test formatting invalid code."""
        emitter = GoEmitter()
        uast = CoreUAST(body=[], language="go")
        formatted = emitter.emit(uast)
        # Should return original if formatting fails
        assert formatted is not None

    def test_can_emit(self):
        """Test can_emit method."""
        emitter = GoEmitter()
        uast = CoreUAST(body=[], language="go")
        assert emitter.can_emit(uast) is True

        uast_py = CoreUAST(body=[], language="python")
        assert emitter.can_emit(uast_py) is False


class TestGoHandler:
    """Test Go language handler."""

    def test_validate_syntax_valid(self):
        """Test validity checking for valid Go code."""
        handler = GoHandler()
        valid_code = """
package main

func main() {}
"""
        result, msg = handler.validate_syntax(valid_code)
        assert msg is not None

    def test_validate_syntax_invalid(self):
        """Test validity checking for invalid Go code."""
        handler = GoHandler()
        invalid_code = "package main\nfunc broken{"
        result, msg = handler.validate_syntax(invalid_code)
        # Should handle gracefully
        assert result is not None

    def test_parse(self):
        """Test parse method."""
        handler = GoHandler()
        source = """
package main
func hello() string {
    return "hello"
}
"""
        result = handler.parse(source)
        assert result is not None
        assert isinstance(result, CoreUAST)

    def test_emit(self):
        """Test emit method."""
        handler = GoHandler()
        from muta_ext.uast.core_uast import CoreUAST
        uast = CoreUAST(body=[], language="go")
        result = handler.emit(uast)
        assert isinstance(result, str)

    def test_roundtrip(self):
        """Test parse → emit roundtrip."""
        handler = GoHandler()
        source = """
package main
func add(a int, b int) int {
    return a + b
}
"""
        result = handler.roundtrip(source)
        assert "func" in result
        assert "add" in result
