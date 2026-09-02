#!/usr/bin/env python3
"""Tests for LSP server in MutaLambda."""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from lsp.server import (
    MutaLambdaLSPServer,
    LSPMessage,
    Diagnostic,
    Position,
    Range,
    CodeAction,
    InlayHint,
    LSPMethod
)


class TestLSPServer:
    """Test LSP server functionality."""

    def test_server_creation(self):
        """Test creating an LSP server."""
        server = MutaLambdaLSPServer()
        assert server is not None
        assert server.document_store == {}
        assert server._running is False

    def test_server_with_config(self):
        """Test creating server with config."""
        config = {"max_depth": 5, "threshold": 0.2}
        server = MutaLambdaLSPServer(config=config)
        assert server.config == config

    def test_start_server(self):
        """Test starting the server."""
        server = MutaLambdaLSPServer()
        server.start()
        assert server._running is True
        assert server._thread is not None
        server.stop()

    def test_ext_to_language_mapping(self):
        """Test extension to language mapping."""
        server = MutaLambdaLSPServer()
        assert server._ext_to_language('.go') == 'go'
        assert server._ext_to_language('.py') == 'python'
        assert server._ext_to_language('.rs') == 'rust'
        assert server._ext_to_language('.cpp') == 'cpp'
        assert server._ext_to_language('.c') == 'cpp'
        assert server._ext_to_language('.unknown') is None

    def test_handle_initialize(self):
        """Test initialize request handling."""
        server = MutaLambdaLSPServer()
        msg = LSPMessage(id=1, method=LSPMethod.INITIALIZE, params={})

        with patch.object(server, '_send') as mock_send:
            server._handle_initialize(msg)
            mock_send.assert_called_once()
            response = mock_send.call_args[0][0]
            assert response.result is not None
            assert 'capabilities' in response.result

    def test_handle_did_open(self):
        """Test document open handling."""
        server = MutaLambdaLSPServer()
        msg = LSPMessage(
            id=2,
            method=LSPMethod.TEXT_DOCUMENT_DID_OPEN,
            params={
                "textDocument": {
                    "uri": "file:///test.go",
                    "text": "package main\nfunc main() {}"
                }
            }
        )

        with patch.object(server, '_analyze_document'):
            server._handle_did_open(msg)
            assert "file:///test.go" in server.document_store

    def test_handle_did_close(self):
        """Test document close handling."""
        server = MutaLambdaLSPServer()
        server.document_store["file:///test.go"] = "content"

        msg = LSPMessage(
            id=3,
            method=LSPMethod.TEXT_DOCUMENT_DID_CLOSE,
            params={"textDocument": {"uri": "file:///test.go"}}
        )
        server._handle_did_close(msg)
        assert "file:///test.go" not in server.document_store

    def test_handle_shutdown(self):
        """Test shutdown request handling."""
        server = MutaLambdaLSPServer()
        msg = LSPMessage(id=4, method=LSPMethod.SHUTDOWN)

        with patch.object(server, '_send') as mock_send:
            server._handle_shutdown(msg)
            mock_send.assert_called_once()
            response = mock_send.call_args[0][0]
            assert response.result is None

    def test_handle_exit(self):
        """Test exit request handling."""
        server = MutaLambdaLSPServer()
        msg = LSPMessage(id=5, method=LSPMethod.EXIT)

        with patch.object(server, '_send'), \
             patch('sys.exit') as mock_exit:
            server._handle_exit(msg)
            assert server._running is False
            mock_exit.assert_called_once_with(0)

    def test_analyze_document_empty(self):
        """Test analyzing empty document."""
        server = MutaLambdaLSPServer()
        with patch.object(server, '_send'):
            server._analyze_document("file:///empty.go")

    def test_run_fast_analysis_python(self):
        """Test fast analysis on Python code."""
        server = MutaLambdaLSPServer()
        source = "def hello():\n    return 42"

        diagnostics = server._run_fast_analysis(source, "python")
        assert isinstance(diagnostics, list)

    def test_run_fast_analysis_go(self):
        """Test fast analysis on Go code."""
        server = MutaLambdaLSPServer()
        source = "package main\nfunc hello() string { return \"hello\" }"

        diagnostics = server._run_fast_analysis(source, "go")
        assert isinstance(diagnostics, list)

    def test_run_fast_analysis_invalid_language(self):
        """Test fast analysis with invalid language."""
        server = MutaLambdaLSPServer()
        source = "some code"

        diagnostics = server._run_fast_analysis(source, "invalid")
        # Should return a diagnostic indicating analysis error
        assert len(diagnostics) == 1
        assert diagnostics[0].code == "ANALYSIS_ERROR"

    def test_send_message(self):
        """Test sending LSP message."""
        server = MutaLambdaLSPServer()
        msg = LSPMessage(id=1, method="test", result={"data": "value"})

        with patch('sys.stdout.write') as mock_write, \
             patch('sys.stdout.flush'):
            server._send(msg)
            mock_write.assert_called_once()
            # Verify JSON output
            call_args = mock_write.call_args[0][0]
            assert 'jsonrpc' in call_args
            assert '2.0' in call_args


class TestLSPDataClasses:
    """Test LSP data classes."""

    def test_position_creation(self):
        """Test Position creation."""
        pos = Position(line=5, character=10)
        assert pos.line == 5
        assert pos.character == 10

    def test_range_creation(self):
        """Test Range creation."""
        start = Position(line=0, character=0)
        end = Position(line=1, character=5)
        rng = Range(start=start, end=end)
        assert rng.start == start
        assert rng.end == end

    def test_diagnostic_creation(self):
        """Test Diagnostic creation."""
        diag = Diagnostic(
            range=Range(Position(0, 0), Position(0, 5)),
            severity=2,
            code="WARN",
            message="Warning message"
        )
        assert diag.severity == 2
        assert diag.code == "WARN"
        assert diag.source == "mutalambda"

    def test_code_action_creation(self):
        """Test CodeAction creation."""
        action = CodeAction(title="Optimize", kind="quickfix")
        assert action.title == "Optimize"
        assert action.kind == "quickfix"
        assert action.diagnostic is None
        assert action.edit is None

    def test_inlay_hint_creation(self):
        """Test InlayHint creation."""
        hint = InlayHint(
            position=Position(line=0, character=5),
            label="int",
            kind=2
        )
        assert hint.position.line == 0
        assert hint.label == "int"
        assert hint.kind == 2

    def test_lsp_message_creation(self):
        """Test LSPMessage creation."""
        msg = LSPMessage(id=1, jsonrpc="2.0", method="test")
        assert msg.id == 1
        assert msg.jsonrpc == "2.0"
        assert msg.method == "test"
        assert msg.params is None
        assert msg.result is None
        assert msg.error is None

    def test_lsp_message_with_result(self):
        """Test LSPMessage with result."""
        msg = LSPMessage(id=1, result={"capabilities": {}})
        assert msg.result == {"capabilities": {}}


class TestLSPMethods:
    """Test LSP method enum."""

    def test_all_methods_defined(self):
        """Test all LSP methods are defined."""
        assert LSPMethod.INITIALIZE == "initialize"
        assert LSPMethod.TEXT_DOCUMENT_DID_OPEN == "textDocument/didOpen"
        assert LSPMethod.TEXT_DOCUMENT_DID_CHANGE == "textDocument/didChange"
        assert LSPMethod.TEXT_DOCUMENT_DID_CLOSE == "textDocument/didClose"
        assert LSPMethod.SHUTDOWN == "shutdown"
        assert LSPMethod.EXIT == "exit"
        assert LSPMethod.COMPLETION == "textDocument/completion"
        assert LSPMethod.HOVER == "textDocument/hover"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
