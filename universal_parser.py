#!/usr/bin/env python3
"""Universal source-to-CoreUAST parser CLI.

Thin wrapper around the UAST adapter layer (`muta_ext.uast.adapters.get_adapter`).
Parses a source file using the language-appropriate adapter and emits a
JSON document describing the CoreUAST nodes (type, name, line ranges, etc.).

Usage:
    python universal_parser.py <file> [--lang python/rust/cpp] [-o uast.json]

Exit codes:
    0  success
    2  argument / parse error
    3  unsupported language / missing dependency
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["parse_file", "emit_uast_dict", "SUPPORTED_LANGUAGES"]

SUPPORTED_LANGUAGES = ("python", "rust", "cpp")

# Extension → language hint when --lang is not given.
_EXTENSION_MAP = {
    ".py": "python",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".h": "cpp",
    ".hxx": "cpp",
}


def _infer_language(path: Path, override: Optional[str]) -> str:
    if override:
        lang = override.lower()
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language '{override}'. Supported: {SUPPORTED_LANGUAGES}")
        return lang
    ext = path.suffix.lower()
    lang = _EXTENSION_MAP.get(ext)
    if lang is None:
        raise ValueError(
            f"Cannot infer language for '{path.suffix}'. "
            f"Pass --lang explicitly. Supported: {SUPPORTED_LANGUAGES}"
        )
    return lang


def parse_file(path: Path, language: Optional[str] = None) -> Dict[str, Any]:
    """Parse a source file into a JSON-serialisable CoreUAST dict."""
    from muta_ext.uast.adapters import get_adapter

    lang = _infer_language(path, language)
    source = path.read_text(encoding="utf-8")
    if not source.strip():
        raise ValueError(f"Source file is empty: {path}")
    try:
        adapter = get_adapter(lang)
    except ValueError as exc:
        raise ValueError(str(exc))
    uast = adapter.parse_to_uast(source)
    return emit_uast_dict(uast, path=path, source=source)


def emit_uast_dict(uast: Any, *, path: Optional[Path] = None, source: str = "") -> Dict[str, Any]:
    """Render a CoreUAST object as a JSON-serialisable dict.

    The CoreUAST ``to_dict`` already recursively serialises every node into
    plain dicts (with ``__type__`` markers). We walk that structure to produce a
    flat, consumer-friendly node list with ``type``, ``name``, ``line``/
    ``end_line`` and nested ``children``.
    """
    from muta_ext.uast.core_uast import CoreUAST  # for typing only

    if isinstance(uast, CoreUAST):
        raw = uast.to_dict()
    elif isinstance(uast, dict) and "body" in uast:
        raw = uast
    else:
        raw = {"body": [], "language": "", "metadata": {}}

    flat_nodes: List[Dict[str, Any]] = []
    _flatten(raw.get("body", []), flat_nodes, depth=0)

    payload: Dict[str, Any] = {
        "language": raw.get("language", ""),
        "metadata": raw.get("metadata", {}),
        "node_count": len(flat_nodes),
        "nodes": flat_nodes,
    }

    if path is not None:
        payload["file"] = str(path)
    if source:
        payload["source_text"] = source

    return payload


def _flatten(nodes: List[Any], out: List[Dict[str, Any]], depth: int) -> None:
    """Recursively flatten a list of serialised CoreUAST nodes into ``out``."""
    for node in nodes:
        out.append(_descriptor(node, depth))


def _descriptor(node: Any, depth: int) -> Dict[str, Any]:
    """Build a flat descriptor for one serialised CoreUAST node."""
    if isinstance(node, dict):
        node_type = node.get("__type__", "dict")
        name = _pick_name(node)
        location = node.get("location")
    else:
        node_type = type(node).__name__
        name = getattr(node, "name", None)
        location = getattr(node, "location", None)

    descriptor: Dict[str, Any] = {
        "type": node_type,
        "name": _coerce_name(name),
        "depth": depth,
        "line": _line(location, "start_line", "line"),
        "end_line": _line(location, "end_line"),
    }

    if isinstance(node, dict):
        children: List[Dict[str, Any]] = []
        for value in node.values():
            _collect_node_children(value, children, depth + 1)
        if children:
            descriptor["children"] = children

    return descriptor


def _collect_node_children(value: Any, out: List[Dict[str, Any]], depth: int) -> None:
    """Append any nested CoreUAST node(s) found inside *value* to *out*."""
    if value is None:
        return
    if isinstance(value, dict) and "__type__" in value:
        out.append(_descriptor(value, depth))
        return
    if isinstance(value, list):
        _flatten(value, out, depth)


def _pick_name(node: Dict[str, Any]) -> Any:
    for key in ("name", "id", "func", "var", "exception_type"):
        if key in node and node[key] is not None:
            return node[key]
    return None


def _coerce_name(name: Any) -> Optional[str]:
    if name is None:
        return None
    if isinstance(name, str):
        return name
    if isinstance(name, dict) and "name" in name:
        return _coerce_name(name["name"])
    if hasattr(name, "name"):
        return name.name
    return str(name)


def _line(location: Any, *keys: str) -> Optional[int]:
    if not isinstance(location, dict):
        return None
    for key in keys:
        if key in location and location[key] is not None:
            return location[key]
    return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="universal_parser",
        description="Parse a source file into a JSON CoreUAST document.",
    )
    parser.add_argument("file", type=Path, help="Path to the source file to parse.")
    parser.add_argument(
        "--lang",
        choices=list(SUPPORTED_LANGUAGES),
        default=None,
        help="Override the language. If omitted, inferred from the file extension.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("uast.json"),
        help="Output JSON path (default: uast.json).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.file.exists():
        parser.error(f"File not found: {args.file}")
        return 2

    try:
        result = parse_file(args.file, args.lang)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Unexpected error parsing {args.file}: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(
        f"Parsed {args.file} ({result.get('language', '?')}) → "
        f"{len(result.get('nodes', []))} nodes → {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
