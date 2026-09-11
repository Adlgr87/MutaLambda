"""Canonical (semantic-structural) hashing for UAST documents.

Lever A2 (Fase 0).  ``canonical_hash`` produces a stable 64-char SHA-256
digest for a UAST that is independent of:

* source formatting (whitespace, indentation),
* parser location data (``location`` line/col spans),
* cosmetic ``tag`` annotations,
* run metadata (``metadata`` is excluded — it carries file paths, tool
  versions, etc. that must not perturb the semantic identity).

Accepts a ``CoreUAST`` instance, a serialized UAST ``dict`` (e.g. the
``uast.json`` document or its ``body``), or a plain list of nodes.  This is
the key used by the fitness cache and by the Fase 3 pareto archive signature
index.

Note: ``CoreUAST.canonical_hash()`` (legacy, 16-hex over the full dict) is
intentionally left untouched for backward compatibility; use this module
function for new call sites.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any, List, Union

__all__ = ["canonical_hash", "canonical_payload", "canonical_body"]


def _node_to_canonical(node: Any) -> Any:
    """Recursively convert a UAST node into its canonical dict form."""
    if node is None or isinstance(node, (bool, int, float, str)):
        return node
    if isinstance(node, (list, tuple)):
        return [_node_to_canonical(n) for n in node]
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in ("location", "tag", "__type__"):
                # positional / cosmetic / serializer marker — not semantic.
                continue
            out[key] = _node_to_canonical(value)
        return out
    if is_dataclass(node) and not isinstance(node, type):
        return _node_to_canonical(asdict(node))
    if hasattr(node, "to_dict"):
        return _node_to_canonical(node.to_dict())
    return str(node)


def _normalize_body(body: Any) -> Any:
    """Normalize a body that may be a list of nodes or a list of dicts."""
    return _node_to_canonical(body)


def canonical_body(body: Any) -> List[Any]:
    """Canonical, location-free form of a UAST body."""
    normalized = _normalize_body(body)
    return normalized if isinstance(normalized, list) else [normalized]


def canonical_payload(body: Any, language: str = "python") -> Any:
    """Full canonical payload: sorted, deterministic, JSON-serializable."""
    payload = {"body": canonical_body(body), "language": str(language).lower()}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def canonical_hash(uast: Any) -> str:
    """Stable SHA-256 hex digest (64 chars) of a UAST's semantic structure.

    Args:
        uast: a ``CoreUAST`` instance, a UAST document dict (with ``body`` /
            ``language``), a dict with a ``body`` list, or a raw list of
            nodes.

    Returns:
        64-character lowercase hex string.  Same semantic program ⇒ same
        digest, regardless of formatting, locations or metadata.
    """
    if uast is None:
        raise ValueError("canonical_hash requires a UAST, dict or node list")

    body: Any
    language: str = "python"

    if hasattr(uast, "body") and hasattr(uast, "language"):
        # CoreUAST-like object.
        body = list(uast.body)
        language = str(getattr(uast, "language", "python"))
    elif isinstance(uast, dict):
        if "body" not in uast:
            raise ValueError("UAST dict must contain a 'body' key")
        body = uast.get("body")
        language = str(uast.get("language", "python"))
    elif isinstance(uast, (list, tuple)):
        body = list(uast)
    else:
        # Single node.
        body = [uast]

    digest = hashlib.sha256(canonical_payload(body, language).encode("utf-8"))
    return digest.hexdigest()
