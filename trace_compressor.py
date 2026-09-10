"""O1 (Fase 1) — compress tracebacks/logs before they reach the LLM.

Tracebacks, sandbox stderr and regression-gate logs are token-hungry and
mostly redundant (dozens of passing lines around one error).  This module
compresses them with Headroom's ``LogCompressor`` / ``SmartCrusher`` when the
``headroom`` package is available, and with a deterministic built-in
fallback when it is not (keep error/exception lines + tail + a summary), so
the lever keeps working in minimal environments.

Contract:
* ``compress_for_llm(text) -> str`` — the single call site for anything that
  will be embedded in an LLM prompt.  Flag-gated:
  ``headroom.smart_crusher.enabled`` (off → passthrough, byte-identical).
* Short inputs below ``min_chars`` pass through untouched (compression only
  pays off above it; also avoids churning one-line errors).
* Every real compression is recorded in the cost ledger as an event
  (``trace_compressed``) with before/after sizes — Rule 4 (sin medición =
  no implementada).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "CompressedTrace",
    "TraceCompressor",
    "get_trace_compressor",
    "compress_for_llm",
    "reset_trace_compressor",
]

MIN_CHARS_DEFAULT = 200  # below this, compression cannot pay for itself
TAIL_LINES_DEFAULT = 5

# Lines worth keeping in the built-in fallback (case-insensitive).
_KEEP_RE = re.compile(
    r"(traceback|error|exception|failed|failure|fatal|panic|segmentation|assert|raise "
    r"|^\s*File \"|^\s{2,}\S+.*\d+[:$]|warning|critic)",
    re.IGNORECASE,
)


@dataclass
class CompressedTrace:
    text: str
    method: str  # headroom_log | headroom_json | builtin | passthrough
    original_chars: int
    compressed_chars: int
    original_lines: int = 0
    compressed_lines: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        if self.original_chars == 0:
            return 1.0
        return self.compressed_chars / self.original_chars

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "ratio": round(self.ratio, 4),
            "meta": self.meta,
        }


class TraceCompressor:
    """Stateless compressor facade (cached lazily on first use)."""

    def __init__(self, min_chars: int = MIN_CHARS_DEFAULT, tail_lines: int = TAIL_LINES_DEFAULT) -> None:
        self.min_chars = int(min_chars)
        self.tail_lines = int(tail_lines)
        self._hr_log = None
        self._hr_json = None
        self._hr_checked = False

    # ── Headroom availability (lazy, import failures are non-fatal) ─────
    def _headroom(self) -> None:
        if self._hr_checked:
            return
        self._hr_checked = True
        try:
            from headroom import SmartCrusher
            from headroom.transforms import LogCompressor

            self._hr_log = LogCompressor()
            self._hr_json = SmartCrusher()
        except Exception:  # headroom not installed — builtin fallback
            self._hr_log = None
            self._hr_json = None

    # ── Public API ───────────────────────────────────────────────────────
    def compress(self, text: str, *, min_chars: Optional[int] = None) -> CompressedTrace:
        """Compress *text* for LLM ingestion (O1). Never raises."""
        if text is None:
            return CompressedTrace("", "passthrough", 0, 0)
        original_chars = len(text)
        original_lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        threshold = self.min_chars if min_chars is None else int(min_chars)
        if original_chars < threshold:
            return CompressedTrace(text, "passthrough", original_chars, original_chars, original_lines, original_lines)
        try:
            out = self._compress_inner(text, original_chars, original_lines)
        except Exception:
            # Compression must never break the prompt path.
            out = CompressedTrace(text, "passthrough", original_chars, original_chars, original_lines, original_lines)
        return out

    def _compress_inner(self, text: str, original_chars: int, original_lines: int) -> CompressedTrace:
        self._headroom()
        stripped = text.strip()

        # 1) JSON-ish content (tool outputs, structured logs) → SmartCrusher.
        if self._hr_json is not None and stripped.startswith(("{", "[")):
            try:
                json.loads(stripped)  # only crush real JSON
            except (json.JSONDecodeError, ValueError):
                pass
            else:
                result = self._hr_json.crush(stripped)
                compressed = getattr(result, "compressed", None)
                if compressed and len(compressed) < original_chars:
                    return CompressedTrace(
                        compressed,
                        "headroom_json",
                        original_chars,
                        len(compressed),
                        original_lines,
                        compressed.count("\n") + 1,
                        meta={"strategy": str(getattr(result, "strategy", ""))},
                    )

        # 2) Line-oriented logs / tracebacks → LogCompressor.
        if self._hr_log is not None and original_lines > 8:
            try:
                result = self._hr_log.compress(text)
                compressed = getattr(result, "compressed", None)
                if compressed and len(compressed) < original_chars:
                    return CompressedTrace(
                        compressed,
                        "headroom_log",
                        original_chars,
                        len(compressed),
                        original_lines,
                        getattr(result, "compressed_line_count", 0),
                        meta={
                            "stats": dict(getattr(result, "stats", {}) or {}),
                            "ratio": round(float(getattr(result, "compression_ratio", 0.0) or 0.0), 4),
                        },
                    )
            except Exception:
                pass  # fall through to builtin

        # 3) Deterministic built-in fallback (no dependency required).
        return self._builtin_compress(text, original_chars, original_lines)

    def _builtin_compress(self, text: str, original_chars: int, original_lines: int) -> CompressedTrace:
        lines = text.splitlines()
        tail = lines[-self.tail_lines:]
        kept: list[str] = []
        dropped = 0
        for line in lines:
            if line in tail:
                continue
            if _KEEP_RE.search(line):
                kept.append(line)
            else:
                dropped += 1
        out_lines: list[str] = []
        if kept:
            out_lines.extend(kept[: 4 * self.tail_lines])
            if tail and kept[-1] != tail[0]:
                out_lines.append("...")
        out_lines.extend(tail)
        if dropped:
            out_lines.append(f"[headroom-builtin: dropped {dropped} non-error lines]")
        compressed = "\n".join(out_lines)
        if len(compressed) >= original_chars:
            # Not worth it — keep the original.
            return CompressedTrace(text, "passthrough", original_chars, original_chars, original_lines, original_lines)
        return CompressedTrace(
            compressed,
            "builtin",
            original_chars,
            len(compressed),
            original_lines,
            len(out_lines),
            meta={"dropped": dropped},
        )


_compressor_singleton: Optional[TraceCompressor] = None
_compressor_lock = threading.Lock()


def get_trace_compressor() -> TraceCompressor:
    global _compressor_singleton
    if _compressor_singleton is None:
        with _compressor_lock:
            if _compressor_singleton is None:
                _compressor_singleton = TraceCompressor()
    return _compressor_singleton


def reset_trace_compressor() -> None:
    global _compressor_singleton
    with _compressor_lock:
        _compressor_singleton = None


def compress_for_llm(text: str, *, min_chars: Optional[int] = None) -> str:
    """Flag-gated one-call helper for prompt builders (O1).

    Returns the text unchanged when the lever is disabled (regla 6) or when
    compression is not beneficial.
    """
    if not text:
        return text or ""
    try:
        from optimization_flags import get_optimization_flags

        enabled = get_optimization_flags().enabled("headroom.smart_crusher.enabled", False)
    except Exception:
        enabled = False
    if not enabled:
        return text
    record = get_trace_compressor().compress(text, min_chars=min_chars)
    if record.method != "passthrough":
        try:
            from cost_ledger import record_event

            record_event(
                "trace_compressed",
                {
                    "method": record.method,
                    "original_chars": record.original_chars,
                    "compressed_chars": record.compressed_chars,
                    "ratio": round(record.ratio, 4),
                },
            )
        except Exception:  # pragma: no cover - observability only
            pass
        return record.text
    return text
