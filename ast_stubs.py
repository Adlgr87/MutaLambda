"""O3 (Fase 1) — AST stubs + on-demand body retrieval.

Sending full function bodies is the single biggest token sink in mutation
prompts.  ``stubify`` replaces the bodies of large functions/classes with a
skeleton marker and registers the full body in a ``StubStore``.  The prompt
then instructs the LLM: *if you need a full body, emit
``headroom_retrieve("<stub_id>")`` on its own line* — the pipeline answers
with the body and asks the model to continue (bounded round trip, works with
any ``llm_fn`` — no provider-specific function calling required).

Everything here is deterministic and dependency-free; the flag
``headroom.ast_stubs.enabled`` gates the behaviour (off → prompts unchanged).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "StubRef",
    "StubStore",
    "stubify",
    "parse_retrieve_calls",
    "render_retrievals",
    "RETRIEVE_PROTOCOL_NOTE",
]

#: Bodies smaller than this are kept inline (stubs do not pay for themself).
MIN_BODY_LINES = 8
MIN_BODY_CHARS = 250

RETRIEVE_CALL_RE = re.compile(
    r"^\s*headroom_retrieve\(\s*['\"]?(stub_\d{3,})['\"]?\s*\)\s*$",
    re.MULTILINE,
)

RETRIEVE_PROTOCOL_NOTE = (
    "STUB PROTOCOL: large function bodies below are abbreviated with "
    'headroom_retrieve markers. If you need the full body of a stubbed '
    'function, reply with EXACTLY one line: headroom_retrieve("<stub_id>") '
    "(you may repeat the line for several ids). The system will answer with "
    "the full body; then continue and produce your final answer. Do not "
    "guess the content of a stubbed body without retrieving it."
)


@dataclass
class StubRef:
    stub_id: str
    name: str
    start_line: int
    end_line: int
    body_chars: int

    def marker(self) -> str:
        # The `...` is a real statement (a comment-only block would be an
        # IndentationError); the comments carry the retrieval protocol.
        return (
            "    ...\n"
            f"    # [headroom:stub:{self.stub_id}] {self.name} — "
            f"lines {self.start_line}-{self.end_line}, {self.body_chars} chars omitted\n"
            f'    # full body: headroom_retrieve("{self.stub_id}")'
        )


class StubStore:
    """stub_id -> full body source (per prompt, per run)."""

    def __init__(self) -> None:
        self._bodies: Dict[str, str] = {}
        self._order: List[str] = []

    def add(self, name: str, body: str) -> StubRef:
        stub_id = f"stub_{len(self._bodies):03d}"
        self._bodies[stub_id] = body
        self._order.append(stub_id)
        return StubRef(stub_id=stub_id, name=name, start_line=0, end_line=0, body_chars=len(body))

    def retrieve(self, stub_id: str) -> Optional[str]:
        return self._bodies.get(stub_id)

    def __len__(self) -> int:
        return len(self._bodies)

    def stats(self) -> Dict[str, int]:
        return {
            "stubs": len(self._bodies),
            "stubbed_chars": sum(len(b) for b in self._bodies.values()),
        }


def _function_nodes(tree: ast.AST) -> List[Tuple[ast.AST, str]]:
    out: List[Tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node, f"def {node.name}"))
        elif isinstance(node, ast.ClassDef):
            out.append((node, f"class {node.name}"))
    return out


def _body_text(lines: List[str], node: ast.AST) -> Tuple[str, int, int]:
    """Return (body_source, first_body_line, end_line) using 1-based lines."""
    # The def line is node.lineno; the body starts on the line after it.
    first = getattr(node.body[0], "lineno", node.lineno + 1) if node.body else node.lineno + 1
    last = node.end_lineno or first
    # Strip the def/class header line so the stored body is the block only.
    body_lines = lines[first - 1 : last]
    return "\n".join(body_lines), first, last


def stubify(
    code: str,
    store: Optional[StubStore] = None,
    *,
    min_body_lines: int = MIN_BODY_LINES,
    min_body_chars: int = MIN_BODY_CHARS,
) -> Tuple[str, StubStore, List[StubRef]]:
    """Replace large bodies with stub markers; register bodies in *store*.

    Returns ``(stubbed_code, store, refs)``.  Unparseable input is returned
    unchanged with an empty store (never break the prompt path).
    """
    store = store or StubStore()
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return code, store, []

    lines = code.splitlines()
    # Candidate big bodies, top-down.  Overlapping candidates (nested
    # function inside a stubbed outer body) are resolved by keeping the
    # OUTER node only — the outer body already contains the inner one.
    selected: List[Tuple[ast.AST, str]] = []
    for node, name in sorted(_function_nodes(tree), key=lambda nr: nr[0].lineno):
        if not node.body or node.end_lineno is None:
            continue
        body_src, first, last = _body_text(lines, node)
        n_lines = last - first + 1
        if n_lines < min_body_lines or len(body_src) < min_body_chars:
            continue
        node_a, end_a = node.lineno, node.end_lineno
        # Drop previously selected inner nodes this one contains.
        selected = [
            (o, n)
            for (o, n) in selected
            if not (o.lineno >= node_a and (o.end_lineno or 0) <= (end_a or 0) and o is not node)
        ]
        # Skip if this node is inside an already selected outer node.
        if any(o is not node and o.lineno <= node_a and (o.end_lineno or 0) >= (end_a or 0) for (o, _) in selected):
            continue
        selected.append((node, name))

    if not selected:
        return code, store, []

    edits: List[Tuple[int, int, StubRef]] = []
    refs: List[StubRef] = []
    for node, name in selected:
        body_src, first, last = _body_text(lines, node)
        ref = store.add(name, body_src)
        ref.start_line = first
        ref.end_line = last
        edits.append((first, last, ref))
        refs.append(ref)

    # Splice bottom-up so earlier line numbers stay valid.
    for first, last, ref in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[first - 1 : last] = ref.marker().splitlines()

    stubbed = "\n".join(lines)
    if code.endswith("\n"):
        stubbed += "\n"
    return stubbed, store, refs


def parse_retrieve_calls(text: str) -> List[str]:
    """Extract ``headroom_retrieve("<stub_id>")`` calls (in order, deduped)."""
    seen: Dict[str, None] = {}
    for m in RETRIEVE_CALL_RE.finditer(text or ""):
        seen.setdefault(m.group(1))
    return list(seen.keys())


def render_retrievals(store: StubStore, stub_ids: List[str]) -> str:
    """Render retrieved bodies as a continuation block for the LLM."""
    parts: List[str] = []
    for sid in stub_ids:
        body = store.retrieve(sid)
        if body is None:
            continue
        parts.append(f'=== FULL BODY for {sid} ===\n{body.rstrip()}\n=== END {sid} ===')
    if not parts:
        return ""
    return (
        "\n\nRETRIEVED BODIES (continue now; produce your final answer in the "
        "requested format):\n\n" + "\n\n".join(parts)
    )
