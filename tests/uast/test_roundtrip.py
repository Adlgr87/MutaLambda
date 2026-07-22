#!/usr/bin/env python3
"""Round-trip tests: parse → mutate → emit → validate."""
import pytest
import ast


class TestRoundtrip:
    """Test end-to-end UAST roundtrip workflow."""

    def test_parse_emit_simple(self):
        """Test basic parse and emit of simple Python code."""
        from muta_ext.uast.adapters.python_adapter import parse_to_uast
        from muta_ext.uast.emitters.python_emitter import emit_from_uast
        
        source = "x = 1 + 2"
        uast = parse_to_uast(source)
        emitted = emit_from_uast(uast)
        
        # Verify UAST was created
        assert uast.language == "python"
        assert len(uast.body) == 1
        
        # Verify emit produces valid Python
        ast.parse(emitted)  # Should not raise

    def test_parse_emit_function(self):
        """Test parse and emit of function definition."""
        from muta_ext.uast.adapters.python_adapter import parse_to_uast
        from muta_ext.uast.emitters.python_emitter import emit_from_uast
        
        source = '''
def add(a, b):
    return a + b
'''
        uast = parse_to_uast(source)
        emitted = emit_from_uast(uast)
        
        # Verify valid Python output
        tree = ast.parse(emitted)
        assert len(tree.body) >= 1

    def test_validator_detects_opaque(self):
        """Test that validator detects opaque/unrecognized nodes."""
        from muta_ext.uast.validators import UASTValidator
        from muta_ext.uast.core_uast import CoreUAST, Opaque
        
        uast = CoreUAST(
            body=[Opaque(original_text="some_unknown_syntax", lang="python")],
            language="python"
        )
        
        errors = UASTValidator.validate_structure(uast)
        assert len(errors) == 1
        assert "Unrecognized construct" in errors[0]