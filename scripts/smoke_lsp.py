"""Smoke: a real LSP session over a subprocess, using Content-Length framing.

This exists because the unit tests called the handlers directly and so could
not catch the defect that mattered: the server spoke newline-delimited JSON
while every real editor speaks Content-Length-framed JSON-RPC, so no client
ever got past `initialize`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def read_frame(stream) -> dict:
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            raise AssertionError("server closed the stream before replying")
        line = line.decode("ascii").strip()
        if not line:
            break
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers["content-length"])
    return json.loads(stream.read(length).decode("utf-8"))


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "lsp" / "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
    )
    try:
        proc.stdin.write(
            frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"processId": None, "rootUri": None, "capabilities": {}},
                }
            )
        )
        proc.stdin.flush()
        reply = read_frame(proc.stdout)

        assert reply.get("id") == 1, reply
        caps = reply["result"]["capabilities"]
        print("  initialize OK; capabilities:", ", ".join(sorted(caps)))

        # Every advertised capability must have a handler: an advertised
        # capability with no responder hangs the client forever.
        for method, cap in [
            ("textDocument/hover", "hoverProvider"),
            ("textDocument/codeAction", "codeActionProvider"),
        ]:
            if cap not in caps:
                continue
            proc.stdin.write(
                frame(
                    {
                        "jsonrpc": "2.0",
                        "id": 99,
                        "method": method,
                        "params": {
                            "textDocument": {"uri": "file:///tmp/x.py"},
                            "position": {"line": 0, "character": 0},
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0},
                            },
                            "context": {"diagnostics": []},
                        },
                    }
                )
            )
            proc.stdin.flush()
            resp = read_frame(proc.stdout)
            assert resp.get("id") == 99, (method, resp)
            print(f"  {method} answered OK")

        print("LSP HANDSHAKE OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
