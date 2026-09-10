#!/usr/bin/env python3
"""Emitters for UAST v2 — the frozen legacy emitters, reused unchanged.

``v2_to_legacy()`` feeds the existing per-language emitters, so v2 gets code
generation for free (including the ``Opaque`` passthrough) with zero duplicated
logic.  The small wrapper mirrors the legacy emitter API (``.emit()``,
``.can_emit()``, ``.language``) so call sites can swap engines transparently.
"""

from __future__ import annotations

import typing as T
from typing import Any, Optional

from muta_ext.uast2 import core as v2
from muta_ext.uast2.convert import v2_to_legacy

__all__ = ["EmitterWrapperV2", "get_emitter_v2", "emit", "emit_from_uast"]


class EmitterWrapperV2:
    """Thin adapter exposing the legacy emitter API over a v2 document."""

    def __init__(self, language: Optional[str] = None) -> None:
        self._language = language
        self._emitter = None

    # ── helpers ─────────────────────────────────────────────────────────────
    def _resolve(self, uast: Any) -> Any:
        language = self._language or getattr(uast, "language", "python")
        if self._emitter is not None and getattr(self._emitter, "language", None) == language:
            return self._emitter
        from muta_ext.uast.emitters import get_emitter

        self._emitter = get_emitter(language)
        return self._emitter

    @staticmethod
    def _as_legacy(uast: Any) -> Any:
        if isinstance(uast, v2.CoreUAST):
            return v2_to_legacy(uast)
        if isinstance(uast, v2.UASTNode):
            return v2_to_legacy(uast)
        return uast

    # ── public API (legacy-compatible) ──────────────────────────────────────
    def emit(self, uast: Any) -> str:
        """Emit a v2 document/subtree (or a legacy one) as source code."""
        legacy_uast = self._as_legacy(uast)
        return self._resolve(legacy_uast).emit(legacy_uast)

    def can_emit(self, uast: Any) -> bool:
        """Whether an emitter exists for this language/document."""
        try:
            return bool(self._resolve(self._as_legacy(uast)).can_emit(self._as_legacy(uast)))
        except Exception:
            return False

    @property
    def language(self) -> Optional[str]:
        """Language this wrapper emits (``None`` → taken from the document)."""
        if self._language is not None:
            return self._language
        return getattr(self._emitter, "language", None)


def get_emitter_v2(language: Optional[str] = None) -> EmitterWrapperV2:
    """Return an emitter wrapper for *language* (``None`` → from the document)."""
    return EmitterWrapperV2(language)


def emit(uast: Any, language: Optional[str] = None) -> str:
    """Emit *uast* (v2 or legacy) back to source code."""
    return EmitterWrapperV2(language).emit(uast)


#: Legacy-compatible alias (``emit_from_uast``).
def emit_from_uast(uast: Any, language: Optional[str] = None) -> str:
    """Alias of :func:`emit` (matches ``muta_ext.uast.emitters`` naming)."""
    return emit(uast, language)
