#!/usr/bin/env python3
"""
MutaLambda Language Server Protocol (LSP) Server.

Provides real-time optimization suggestions while coding.
Supports VS Code and Neovim integration.
"""
from __future__ import annotations
import json
import sys
import argparse
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import asyncio
import threading
from pathlib import Path

# LSP Message types
class LSPMethod(str, Enum):
    INITIALIZE = "initialize"
    INITIALIZED = "initialized"
    TEXT_DOCUMENT_DID_OPEN = "textDocument/didOpen"
    TEXT_DOCUMENT_DID_CHANGE = "textDocument/didChange"
    TEXT_DOCUMENT_DID_CLOSE = "textDocument/didClose"
    TEXT_DOCUMENT_DIAGNOSTICS = "textDocument/diagnostic"
    TEXT_DOCUMENT_CODE_ACTION = "textDocument/codeAction"
    TEXT_DOCUMENT_INLAY_HINT = "textDocument/inlayHint"
    COMPLETION = "textDocument/completion"
    HOVER = "textDocument/hover"
    SHUTDOWN = "shutdown"
    EXIT = "exit"


@dataclass
class Position:
    line: int = 0
    character: int = 0

@dataclass
class Range:
    start: Position
    end: Position

@dataclass
class Diagnostic:
    range: Range
    severity: int  # 1=error, 2=warning, 3=information, 4=hint
    code: str
    message: str
    source: str = "mutalambda"

@dataclass
class CodeAction:
    title: str
    kind: str
    diagnostic: Optional[Diagnostic] = None
    edit: Optional[Dict] = None

@dataclass
class InlayHint:
    position: Position
    label: str
    kind: int = 2  # Type hint
    tooltip: Optional[str] = None

@dataclass
class LSPMessage:
    id: Optional[int] = None
    jsonrpc: str = "2.0"
    method: Optional[str] = None
    params: Optional[Dict] = None
    result: Optional[Any] = None
    error: Optional[Dict] = None

class MutaLambdaLSPServer:
    """LSP Server for MutaLambda optimization suggestions."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.document_store: Dict[str, str] = {}
        self.analysis_queue: List[Dict] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the LSP server."""
        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def _run_server(self):
        """Main server loop reading from stdin."""
        while self._running:
            line = sys.stdin.readline()
            if not line:
                break
            self._handle_message(line.strip())

    def _handle_message(self, line: str):
        """Handle incoming LSP message."""
        try:
            msg = json.loads(line)
            lsp_msg = LSPMessage(**msg)

            if lsp_msg.method == LSPMethod.INITIALIZE:
                self._handle_initialize(lsp_msg)
            elif lsp_msg.method == LSPMethod.TEXT_DOCUMENT_DID_OPEN:
                self._handle_did_open(lsp_msg)
            elif lsp_msg.method == LSPMethod.TEXT_DOCUMENT_DID_CHANGE:
                self._handle_did_change(lsp_msg)
            elif lsp_msg.method == LSPMethod.TEXT_DOCUMENT_DID_CLOSE:
                self._handle_did_close(lsp_msg)
            elif lsp_msg.method == LSPMethod.SHUTDOWN:
                self._handle_shutdown(lsp_msg)
            elif lsp_msg.method == LSPMethod.EXIT:
                self._handle_exit(lsp_msg)
        except json.JSONDecodeError:
            pass

    def _handle_initialize(self, msg: LSPMessage):
        """Handle initialize request."""
        response = LSPMessage(
            id=msg.id,
            result={
                "capabilities": {
                    "textDocumentSync": {
                        "openClose": True,
                        "change": 1,  # Incremental
                        "willSave": False,
                        "willSaveWaitUntil": False
                    },
                    "diagnosticProvider": {
                        "identifier": "mutalambda",
                        "interFileDependencies": False,
                        "workspaceDiagnostics": False
                    },
                    "codeActionProvider": {
                        "codeActionKinds": ["quickfix", "refactor"],
                        "resolveProvider": False
                    },
                    "inlayHintProvider": True,
                    "completionProvider": {
                        "triggerCharacters": [".", "(", "="]
                    },
                    "hoverProvider": True
                }
            }
        )
        self._send(response)

    def _handle_did_open(self, msg: LSPMessage):
        """Handle document open."""
        params = msg.params or {}
        text_doc = params.get("textDocument", {})
        uri = text_doc.get("uri", "")
        self.document_store[uri] = text_doc.get("text", "")
        self._analyze_document(uri)

    def _handle_did_change(self, msg: LSPMessage):
        """Handle document change."""
        params = msg.params or {}
        uri = params.get("textDocument", {}).get("uri", "")
        changes = params.get("contentChanges", [])
        if changes and uri in self.document_store:
            # Apply changes (simplified)
            for change in changes:
                if "range" in change:
                    # Full replace for simplicity
                    pass
            self.document_store[uri] = "\n".join(
                c.get("text", "") for c in changes
            ) if changes else self.document_store.get(uri, "")
        self._analyze_document(uri)

    def _handle_did_close(self, msg: LSPMessage):
        """Handle document close."""
        params = msg.params or {}
        uri = params.get("textDocument", {}).get("uri", "")
        self.document_store.pop(uri, None)

    def _handle_shutdown(self, msg: LSPMessage):
        """Handle shutdown request."""
        self._send(LSPMessage(id=msg.id, result=None))

    def _handle_exit(self, msg: LSPMessage):
        """Handle exit request."""
        self._running = False
        sys.exit(0)

    def _analyze_document(self, uri: str):
        """Analyze document and send diagnostics."""
        source = self.document_store.get(uri, "")
        if not source:
            return

        # Detect language from URI
        ext = Path(uri).suffix
        language = self._ext_to_language(ext)
        if not language:
            return

        # Run fast analysis
        diagnostics = self._run_fast_analysis(source, language)

        # Send diagnostics
        response = LSPMessage(
            method="textDocument/publishDiagnostics",
            params={
                "uri": uri,
                "diagnostics": [asdict(d) for d in diagnostics]
            }
        )
        self._send(response)

    def _run_fast_analysis(self, source: str, language: str) -> List[Diagnostic]:
        """Run fast analysis on source code."""
        diagnostics = []

        try:
            from mutalambda.muta_ext.uast.adapters import get_adapter
            adapter = get_adapter(language)

            if not adapter.can_parse(source):
                diagnostics.append(Diagnostic(
                    range=Range(Position(0, 0), Position(0, len(source))),
                    severity=1,
                    code="SYNTAX_ERROR",
                    message="Source code has syntax errors"
                ))
                return diagnostics

            uast = adapter.parse_to_uast(source)

            # Check for optimization opportunities
            for node in uast.body:
                if hasattr(node, 'name'):
                    func_name = node.name.name if hasattr(node.name, 'name') else str(node.name)
                    # Check for potential optimizations
                    if hasattr(node, 'body') and len(node.body) > 10:
                        diagnostics.append(Diagnostic(
                            range=Range(Position(0, 0), Position(0, 0)),
                            severity=4,
                            code="OPT_SUGGESTION",
                            message=f"Function '{func_name}' may benefit from optimization",
                            source="mutalambda/fast"
                        ))
        except Exception as e:
            diagnostics.append(Diagnostic(
                range=Range(Position(0, 0), Position(0, 0)),
                severity=3,
                code="ANALYSIS_ERROR",
                message=f"Analysis error: {str(e)}"
            ))

        return diagnostics

    def _ext_to_language(self, ext: str) -> Optional[str]:
        """Map file extension to language."""
        mapping = {
            '.go': 'go',
            '.py': 'python',
            '.rs': 'rust',
            '.cpp': 'cpp',
            '.c': 'cpp',
        }
        return mapping.get(ext)

    def _send(self, message: LSPMessage):
        """Send LSP message to stdout."""
        msg_dict = {k: v for k, v in asdict(message).items() if v is not None}
        sys.stdout.write(json.dumps(msg_dict) + "\n")
        sys.stdout.flush()


def main():
    """Entry point for LSP server."""
    parser = argparse.ArgumentParser(description="MutaLambda LSP Server")
    parser.add_argument("--config", help="Path to config file")
    args = parser.parse_args()

    config = {}
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    server = MutaLambdaLSPServer(config)
    server.start()

    # Keep main thread alive
    while server._running:
        asyncio.sleep(0.1)


if __name__ == "__main__":
    main()
