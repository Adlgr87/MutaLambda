#!/usr/bin/env python3
"""
MutaLambda Language Server Protocol (LSP) Server.

Provides real-time optimization suggestions while coding.
Supports VS Code and Neovim integration.
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
import threading
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("mutalambda.lsp")


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

    def __init__(self, config: Optional[Dict] = None, *, framing: str = "lsp"):
        self.config = config or {}
        self.document_store: Dict[str, str] = {}
        self.analysis_queue: List[Dict] = []
        # "lsp"  -> Content-Length framed output (what editors expect)
        # "line" -> one JSON object per line (legacy / scripting)
        self.framing = framing
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the LSP server."""
        self._running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the LSP server and release the stdin-reading worker thread."""
        self._running = False
        if self._thread is not None:
            try:
                self._thread.join(timeout=2)
            except Exception:
                pass

    def _run_server(self):
        """Main server loop reading JSON-RPC frames from stdin.

        Accepts both wire formats:

        * ``Content-Length: N\\r\\n\\r\\n<body>`` — the base protocol every real
          LSP client (VS Code, Neovim, Helix, ...) speaks. The server used to
          only read newline-delimited JSON, so no editor could talk to it.
        * one JSON object per line — kept for scripts and the test-suite.

        Uses select() with a short timeout so the loop can re-check
        ``self._running`` periodically, allowing ``stop()`` to cleanly
        release the thread without depending on stdin being closed.
        """
        import select

        stream = getattr(sys.stdin, "buffer", None) or sys.stdin

        while self._running:
            try:
                ready, _, _ = select.select([stream], [], [], 0.1)
            except (ValueError, OSError):
                break
            if not ready:
                continue
            try:
                frame = self._read_frame(stream)
            except (ValueError, OSError):
                break
            if frame is None:
                break
            if frame:
                self._handle_message(frame)

    def _read_frame(self, stream) -> Optional[str]:
        """Read one JSON-RPC frame. Returns None at EOF, "" to skip."""
        line = stream.readline()
        if not line:
            return None
        if isinstance(line, bytes):
            text = line.decode("utf-8", errors="replace")
        else:
            text = line
        stripped = text.strip()
        if not stripped:
            return ""
        if not stripped.lower().startswith("content-length:"):
            # Legacy newline-delimited frame.
            return stripped

        try:
            length = int(stripped.split(":", 1)[1].strip())
        except ValueError:
            log.warning("Malformed Content-Length header: %r", stripped)
            return ""
        # Consume the remaining headers up to the blank separator line.
        while True:
            header = stream.readline()
            if not header:
                return None
            header_text = header.decode("utf-8", "replace") if isinstance(header, bytes) else header
            if not header_text.strip():
                break
        body = stream.read(length) if hasattr(stream, "read") else ""
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        return body

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
            elif lsp_msg.method == LSPMethod.TEXT_DOCUMENT_CODE_ACTION:
                self._handle_code_action(lsp_msg)
            elif lsp_msg.method == LSPMethod.TEXT_DOCUMENT_INLAY_HINT:
                self._handle_inlay_hint(lsp_msg)
            elif lsp_msg.method == LSPMethod.HOVER:
                self._handle_hover(lsp_msg)
            elif lsp_msg.method == LSPMethod.COMPLETION:
                self._handle_completion(lsp_msg)
            elif lsp_msg.method == LSPMethod.SHUTDOWN:
                self._handle_shutdown(lsp_msg)
            elif lsp_msg.method == LSPMethod.EXIT:
                self._handle_exit(lsp_msg)
            elif lsp_msg.id is not None:
                # Any *request* (it carries an id) must get a reply, otherwise
                # the client blocks forever waiting for it.
                log.debug("Unsupported LSP request %s", lsp_msg.method)
                self._send(LSPMessage(id=lsp_msg.id, result=None))
        except json.JSONDecodeError:
            # A malformed frame must not kill the server loop, but silently
            # dropping it made client/server desyncs undebuggable.
            log.warning("Discarding malformed JSON-RPC frame: %.200r", line)

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
                        "willSaveWaitUntil": False,
                    },
                    "diagnosticProvider": {
                        "identifier": "mutalambda",
                        "interFileDependencies": False,
                        "workspaceDiagnostics": False,
                    },
                    "codeActionProvider": {
                        "codeActionKinds": ["quickfix", "refactor"],
                        "resolveProvider": False,
                    },
                    "inlayHintProvider": True,
                    "completionProvider": {"triggerCharacters": [".", "(", "="]},
                    "hoverProvider": True,
                }
            },
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
            self.document_store[uri] = (
                "\n".join(c.get("text", "") for c in changes)
                if changes
                else self.document_store.get(uri, "")
            )
        self._analyze_document(uri)

    def _handle_did_close(self, msg: LSPMessage):
        """Handle document close."""
        params = msg.params or {}
        uri = params.get("textDocument", {}).get("uri", "")
        self.document_store.pop(uri, None)

    def _handle_code_action(self, msg: LSPMessage):
        """Return the optimization code actions advertised in `codeActionProvider`."""
        params = msg.params or {}
        uri = params.get("textDocument", {}).get("uri", "")
        actions: List[Dict[str, Any]] = []
        if uri in self.document_store:
            actions = [
                asdict(CodeAction(title="MutaLambda: Optimize this function", kind="quickfix")),
                asdict(CodeAction(title="MutaLambda: Explain optimization", kind="refactor")),
            ]
        self._send(LSPMessage(id=msg.id, result=actions))

    def _handle_inlay_hint(self, msg: LSPMessage):
        """Inlay hints are advertised but currently produce no annotations."""
        self._send(LSPMessage(id=msg.id, result=[]))

    def _handle_hover(self, msg: LSPMessage):
        """Hover summary for the analysed document."""
        params = msg.params or {}
        uri = params.get("textDocument", {}).get("uri", "")
        if uri not in self.document_store:
            self._send(LSPMessage(id=msg.id, result=None))
            return
        diagnostics = self._run_fast_analysis(
            self.document_store[uri],
            self._ext_to_language(Path(uri).suffix) or "python",
        )
        value = (
            "\n".join(f"- `{d.code}` {d.message}" for d in diagnostics)
            if diagnostics
            else "No MutaLambda optimization hints for this document."
        )
        self._send(
            LSPMessage(
                id=msg.id,
                result={"contents": {"kind": "markdown", "value": value}},
            )
        )

    def _handle_completion(self, msg: LSPMessage):
        """Completion is advertised but intentionally returns no items yet."""
        self._send(LSPMessage(id=msg.id, result={"isIncomplete": False, "items": []}))

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
            params={"uri": uri, "diagnostics": [asdict(d) for d in diagnostics]},
        )
        self._send(response)

    def _run_fast_analysis(self, source: str, language: str) -> List[Diagnostic]:
        """Run fast analysis on source code."""
        diagnostics = []

        try:
            from muta_ext.uast.adapters import get_adapter

            adapter = get_adapter(language)

            if not adapter.can_parse(source):
                diagnostics.append(
                    Diagnostic(
                        range=Range(Position(0, 0), Position(0, len(source))),
                        severity=1,
                        code="SYNTAX_ERROR",
                        message="Source code has syntax errors",
                    )
                )
                return diagnostics

            uast = adapter.parse_to_uast(source)

            # Check for optimization opportunities
            for node in uast.body:
                if hasattr(node, "name"):
                    func_name = node.name.name if hasattr(node.name, "name") else str(node.name)
                    # Check for potential optimizations
                    if hasattr(node, "body") and len(node.body) > 10:
                        diagnostics.append(
                            Diagnostic(
                                range=Range(Position(0, 0), Position(0, 0)),
                                severity=4,
                                code="OPT_SUGGESTION",
                                message=f"Function '{func_name}' may benefit from optimization",
                                source="mutalambda/fast",
                            )
                        )
        except Exception as e:
            diagnostics.append(
                Diagnostic(
                    range=Range(Position(0, 0), Position(0, 0)),
                    severity=3,
                    code="ANALYSIS_ERROR",
                    message=f"Analysis error: {str(e)}",
                )
            )

        return diagnostics

    def _ext_to_language(self, ext: str) -> Optional[str]:
        """Map file extension to language."""
        mapping = {
            ".go": "go",
            ".py": "python",
            ".rs": "rust",
            ".cpp": "cpp",
            ".c": "cpp",
        }
        return mapping.get(ext)

    def _send(self, message: LSPMessage):
        """Send an LSP message on stdout using base-protocol framing.

        ``framing="lsp"`` (the default) emits the ``Content-Length`` header
        required by every LSP client. ``framing="line"`` keeps the historic
        newline-delimited output for scripted use.
        """
        msg_dict = {k: v for k, v in asdict(message).items() if v is not None}
        body = json.dumps(msg_dict)
        if self.framing == "line":
            sys.stdout.write(body + "\n")
        else:
            sys.stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
        sys.stdout.flush()


def main():
    """Entry point for LSP server."""
    parser = argparse.ArgumentParser(description="MutaLambda LSP Server")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument(
        "--framing",
        choices=["lsp", "line"],
        default="lsp",
        help="Wire format: 'lsp' = Content-Length frames (editors), 'line' = one JSON per line",
    )
    args = parser.parse_args()

    config = {}
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    server = MutaLambdaLSPServer(config, framing=args.framing)
    server.start()

    # Keep the main thread alive while the stdin worker runs. This used to call
    # ``asyncio.sleep(0.1)`` outside an event loop, which only built a coroutine
    # object (never awaited) and spun the CPU at 100%.
    try:
        while server._running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
