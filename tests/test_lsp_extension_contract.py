"""Contract tests between the LSP server, the VS Code manifest and extension.js.

The v5 scrutiny pass found this triangle completely disconnected:
  * package.json `main` pointed at `./dist/extension.js`, which no build step
    produced (the `tsc` script had no TypeScript sources);
  * extension.js exported a bare function instead of `activate`/`deactivate`;
  * it started the server from a non-existent `server.js` (the server is
    Python);
  * the server advertised capabilities it had no handler for, so the client
    blocked forever;
  * the server spoke newline-delimited JSON, not LSP `Content-Length` frames.

These tests are plain file/AST assertions so they run without node or vscode.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VSCODE = REPO / "lsp" / "extensions" / "vscode"
PACKAGE_JSON = VSCODE / "package.json"
EXTENSION_JS = VSCODE / "extension.js"
SERVER_PY = REPO / "lsp" / "server.py"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(PACKAGE_JSON.read_text())


@pytest.fixture(scope="module")
def extension_source() -> str:
    return EXTENSION_JS.read_text()


# ---------------------------------------------------------------------------
# Manifest <-> files on disk
# ---------------------------------------------------------------------------


def test_manifest_main_entry_exists(manifest):
    main = manifest["main"]
    resolved = (VSCODE / main).resolve()
    assert resolved.exists(), f"package.json main={main!r} does not exist"


def test_manifest_version_matches_project_version():
    pyproject = (REPO / "pyproject.toml").read_text()
    project_version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    manifest_version = json.loads(PACKAGE_JSON.read_text())["version"]
    assert manifest_version == project_version


def test_no_orphan_js_entry_points():
    """index.js re-exported extension.js but nothing resolved it."""
    js_files = {p.name for p in VSCODE.glob("*.js")}
    assert js_files == {"extension.js"}, f"unexpected JS entry points: {js_files}"


def test_build_script_does_not_reference_missing_typescript(manifest):
    scripts = manifest.get("scripts", {})
    assert "compile" not in scripts or list(VSCODE.glob("*.ts")), (
        "a `compile` script implies TypeScript sources, but none exist"
    )


# ---------------------------------------------------------------------------
# Manifest <-> extension.js
# ---------------------------------------------------------------------------


def test_extension_exports_activate_and_deactivate(extension_source):
    assert "module.exports = { activate, deactivate }" in extension_source


def test_every_contributed_command_is_registered(manifest, extension_source):
    declared = {c["command"] for c in manifest["contributes"]["commands"]}
    registered = set(re.findall(r"'(mutalambda\.[A-Za-z]+)':", extension_source))
    assert declared <= registered, (
        f"commands declared in package.json but never registered: {declared - registered}"
    )


def test_extension_launches_the_python_server(extension_source):
    assert "server.py" in extension_source
    code = "\n".join(
        line for line in extension_source.splitlines() if not line.strip().startswith("//")
    )
    assert "server.js" not in code, "the language server is Python, not JS"


def test_configuration_keys_used_by_extension_are_declared(manifest, extension_source):
    declared = set(manifest["contributes"]["configuration"]["properties"])
    used = {
        f"mutalambda.{key}"
        for key in re.findall(r"getConfiguration\('mutalambda'\)\.get\('([^']+)'\)", extension_source)
    }
    assert used <= declared, f"undeclared configuration keys: {sorted(used - declared)}"


# ---------------------------------------------------------------------------
# Server capabilities <-> server handlers
# ---------------------------------------------------------------------------


def test_every_advertised_capability_has_a_handler():
    from lsp.server import MutaLambdaLSPServer

    server = MutaLambdaLSPServer()
    captured = []
    server._send = captured.append  # type: ignore[method-assign]

    from lsp.server import LSPMessage, LSPMethod

    server._handle_initialize(LSPMessage(id=1, method=LSPMethod.INITIALIZE, params={}))
    capabilities = captured[0].result["capabilities"]

    handler_for = {
        "codeActionProvider": "_handle_code_action",
        "inlayHintProvider": "_handle_inlay_hint",
        "hoverProvider": "_handle_hover",
        "completionProvider": "_handle_completion",
        "diagnosticProvider": "_analyze_document",
        "textDocumentSync": "_handle_did_open",
    }
    for capability in capabilities:
        assert capability in handler_for, f"capability {capability} has no known handler"
        assert hasattr(server, handler_for[capability]), (
            f"{capability} advertised but {handler_for[capability]} is missing"
        )


def test_requests_always_get_a_reply():
    """An unhandled *request* must still be answered or the client hangs."""
    from lsp.server import LSPMessage, MutaLambdaLSPServer

    server = MutaLambdaLSPServer()
    sent: list[LSPMessage] = []
    server._send = sent.append  # type: ignore[method-assign]

    server._handle_message(
        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "textDocument/neverImplemented"})
    )
    assert sent and sent[0].id == 99


def test_notifications_do_not_get_a_reply():
    from lsp.server import LSPMessage, MutaLambdaLSPServer

    server = MutaLambdaLSPServer()
    sent: list[LSPMessage] = []
    server._send = sent.append  # type: ignore[method-assign]

    server._handle_message(json.dumps({"jsonrpc": "2.0", "method": "$/someNotification"}))
    assert sent == []


# ---------------------------------------------------------------------------
# Wire protocol
# ---------------------------------------------------------------------------


def _read_framed(stdout) -> dict:
    length = None
    while True:
        line = stdout.readline()
        if not line:
            raise EOFError("server closed the stream")
        text = line.decode().strip()
        if text.lower().startswith("content-length:"):
            length = int(text.split(":", 1)[1])
        elif text == "" and length is not None:
            return json.loads(stdout.read(length))


def test_server_speaks_lsp_content_length_framing():
    """End-to-end: a real client handshake over the base protocol."""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PY)],
        cwd=str(REPO),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        bufsize=0,
    )
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
        proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        proc.stdin.flush()

        response = _read_framed(proc.stdout)
        assert response["id"] == 1
        assert "capabilities" in response["result"]
    finally:
        proc.kill()
        proc.wait(timeout=10)
