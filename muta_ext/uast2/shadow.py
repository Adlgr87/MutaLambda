#!/usr/bin/env python3
"""Shadow mode — parse with both engines and compare, never break the run.

The playbook asks for an exact ``canonical_hash`` comparison between engines.
That cannot be done literally: the legacy ``canonical_hash()`` folds ``metadata``
into the digest, and the legacy Python adapter fills it with ``str(hash(tree))``
(a process-local, address-derived value), so the legacy digest changes between
two parses of the *same* source.  Shadow mode therefore compares the thing the
hash was trying to express — the normalised structure of ``body`` + ``language``:

* :func:`canonical_digest` — deterministic digest of *either* representation
  (metadata and locations excluded), so legacy and v2 digests are comparable;
* :func:`compare` — full structural comparison that reports human-readable
  differences (node type sequence and first diverging field);
* :func:`shadow_parse` — runs both engines, records metrics
  (``uast2.shadow.*``), logs warnings, and **never raises on mismatch**;
* :func:`run_shadow_suite` — the CI/CLI gate over a list of files.

With the extended dialect (``extended=True``) the v2 tree is a *superset* of the
legacy tree (comparisons become real nodes), so ``mode="subset"`` accepts an
``Opaque`` legacy node being replaced by a structured v2 node while still
rejecting any other divergence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import typing as T
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from muta_ext.uast2 import metrics
from muta_ext.uast2.convert import legacy_to_v2
from muta_ext.uast2.core import UASTNode, CoreUAST, iter_fields, walk

__all__ = [
    "ShadowResult",
    "compare",
    "canonical_digest",
    "shadow_parse",
    "run_shadow_suite",
    "shadow_stats",
]

logger = logging.getLogger("MutaLambda.uast2.shadow")

_MAX_DETAILS = 5


@dataclass
class ShadowResult:
    """Outcome of comparing the two engines for one source."""

    equal: bool
    mode: str = "exact"
    legacy_digest: str = ""
    v2_digest: str = ""
    legacy_nodes: int = 0
    v2_nodes: int = 0
    differences: List[str] = field(default_factory=list)
    duration_ns: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable summary."""
        return {
            "equal": self.equal,
            "mode": self.mode,
            "legacy_digest": self.legacy_digest,
            "v2_digest": self.v2_digest,
            "legacy_nodes": self.legacy_nodes,
            "v2_nodes": self.v2_nodes,
            "differences": self.differences[: _MAX_DETAILS],
            "duration_ns": self.duration_ns,
            "error": self.error,
        }


def canonical_digest(uast: Any, include_location: bool = False) -> str:
    """Deterministic structure digest for a legacy *or* v2 document.

    Excludes ``metadata`` (volatile in the legacy engine) and, by default,
    locations — i.e. exactly the information the legacy hash *intended* to
    capture.
    """
    if isinstance(uast, CoreUAST):
        return uast.canonical_hash(include_location=include_location)
    body = getattr(uast, "body", None)
    if body is None:
        raise TypeError(f"canonical_digest() expects a CoreUAST, got {type(uast).__name__}")
    serialised = [
        _legacy_dict(node) if hasattr(node, "__dataclass_fields__") else node for node in body
    ]
    payload = json.dumps(
        {"body": serialised, "language": getattr(uast, "language", "python")},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _legacy_dict(node: Any) -> Any:
    """Dict form of a legacy subtree, byte-compatible with ``to_serializable``.

    ``location`` is forced to ``None`` (the same shape v2 emits with
    ``include_location=False``) so both digests are directly comparable.
    """
    fields = getattr(node, "__dataclass_fields__", None)
    if fields is None:
        return node
    payload: Dict[str, Any] = {"__type__": type(node).__name__}
    for name in fields:
        if name in ("location", "tag"):
            continue
        payload[name] = _legacy_value(getattr(node, name))
    payload["tag"] = getattr(node, "tag", None)
    payload["location"] = None
    return payload


def _legacy_value(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _legacy_dict(value)
    if isinstance(value, (list, tuple)):
        return [_legacy_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _legacy_value(item) for key, item in value.items()}
    return value


def compare(
    legacy_uast: Any,
    v2_uast: CoreUAST,
    mode: str = "exact",
    max_details: int = _MAX_DETAILS,
) -> ShadowResult:
    """Compare a legacy document against a v2 document.

    ``mode="exact"`` requires identical trees; ``mode="subset"`` allows v2 to
    refine a legacy ``Opaque`` node into a structured node (extended dialect).
    """
    if mode not in ("exact", "subset"):
        raise ValueError("mode must be 'exact' or 'subset'")
    started = time.perf_counter_ns()
    differences: List[str] = []
    converted = legacy_to_v2(legacy_uast)
    legacy_nodes = sum(1 for _ in walk(legacy_uast))
    v2_nodes = sum(1 for _ in walk(v2_uast))

    if legacy_nodes != v2_nodes and mode == "exact":
        differences.append(f"node count differs: legacy={legacy_nodes} v2={v2_nodes}")

    for index, (left, right) in enumerate(zip(converted.body, v2_uast.body)):
        _compare_nodes(left, right, f"body[{index}]", mode, differences, max_details)
        if len(differences) >= max_details:
            break

    if len(converted.body) != len(v2_uast.body) and mode == "exact":
        differences.append(
            f"body length differs: legacy={len(converted.body)} v2={len(v2_uast.body)}"
        )

    legacy_digest = canonical_digest(legacy_uast)
    v2_digest = v2_uast.canonical_hash()
    equal = not differences and (mode != "exact" or legacy_digest == v2_digest)
    if mode == "exact" and not differences and legacy_digest != v2_digest:
        differences.append(f"digest mismatch: legacy={legacy_digest} v2={v2_digest}")
        equal = False

    return ShadowResult(
        equal=equal,
        mode=mode,
        legacy_digest=legacy_digest,
        v2_digest=v2_digest,
        legacy_nodes=legacy_nodes,
        v2_nodes=v2_nodes,
        differences=differences[:max_details],
        duration_ns=time.perf_counter_ns() - started,
    )


def _compare_nodes(
    left: Any,
    right: Any,
    path: str,
    mode: str,
    differences: List[str],
    max_details: int,
) -> None:
    """Recursive structural comparison (legacy-converted vs native v2)."""
    if len(differences) >= max_details:
        return
    left_type = type(left).__name__
    right_type = type(right).__name__
    if mode == "subset" and left_type == "Opaque":
        return
    if left_type != right_type:
        differences.append(f"{path}: type {left_type} != {right_type}")
        return

    for name, left_value in iter_fields(left):
        if name in ("location",):
            continue
        right_value = getattr(right, name, None)
        child_path = f"{path}.{name}"
        if isinstance(left_value, UASTNode) or hasattr(left_value, "__dataclass_fields__"):
            if not isinstance(right_value, UASTNode):
                differences.append(f"{child_path}: expected node, got {type(right_value).__name__}")
                continue
            _compare_nodes(left_value, right_value, child_path, mode, differences, max_details)
        elif isinstance(left_value, (list, tuple)):
            if not isinstance(right_value, (list, tuple)):
                differences.append(
                    f"{child_path}: expected list, got {type(right_value).__name__}"
                )
                continue
            if len(left_value) != len(right_value):
                differences.append(
                    f"{child_path}: length {len(left_value)} != {len(right_value)}"
                )
                continue
            for index, (left_item, right_item) in enumerate(zip(left_value, right_value)):
                if hasattr(left_item, "__dataclass_fields__") or isinstance(left_item, UASTNode):
                    _compare_nodes(
                        left_item,
                        right_item,
                        f"{child_path}[{index}]",
                        mode,
                        differences,
                        max_details,
                    )
                elif left_item != right_item:
                    differences.append(f"{child_path}[{index}]: {left_item!r} != {right_item!r}")
        elif isinstance(left_value, dict):
            if not isinstance(right_value, dict):
                differences.append(
                    f"{child_path}: expected dict, got {type(right_value).__name__}"
                )
                continue
            for key, left_item in left_value.items():
                right_item = right_value.get(key)
                if hasattr(left_item, "__dataclass_fields__") or isinstance(left_item, UASTNode):
                    _compare_nodes(
                        left_item,
                        right_item,
                        f"{child_path}[{key!r}]",
                        mode,
                        differences,
                        max_details,
                    )
                elif left_item != right_item:
                    differences.append(
                        f"{child_path}[{key!r}]: {left_item!r} != {right_item!r}"
                    )
        elif left_value != right_value:
            differences.append(f"{child_path}: {left_value!r} != {right_value!r}")
        if len(differences) >= max_details:
            return


def _legacy_adapter(language: str) -> Any:
    """Instantiate the frozen adapter for *language* (no v2 involvement)."""
    from muta_ext.uast.adapters import get_adapter

    return get_adapter(language)


def shadow_parse(
    source: str,
    language: str = "python",
    mode: str = "exact",
    extended: Optional[bool] = None,
    raise_on_error: bool = False,
) -> ShadowResult:
    """Parse *source* with both engines, compare, and record metrics.

    Returns the comparison result.  Mismatches are logged at WARNING level and
    counted in the ``uast2.shadow.*`` metrics; the caller decides whether to act.
    """
    from muta_ext.uast2.adapters import parse_to_uast as parse_v2

    started = time.perf_counter_ns()
    try:
        legacy_uast = _legacy_adapter(language).parse_to_uast(source)
    except Exception as exc:
        if raise_on_error:
            raise
        detail = f"legacy engine failed: {type(exc).__name__}: {exc}"
        result = ShadowResult(
            equal=False,
            mode=mode,
            differences=[detail],
            duration_ns=time.perf_counter_ns() - started,
            error=detail,
        )
        metrics.incr("uast2.shadow.legacy_errors")
        logger.warning("UAST shadow: legacy parse failed (%s)", exc)
        return result

    v2_uast = parse_v2(source, language=language, extended=bool(extended))
    result = compare(legacy_uast, v2_uast, mode=mode)
    result.duration_ns = time.perf_counter_ns() - started

    metrics.incr("uast2.shadow.parses")
    metrics.incr("uast2.shadow.nodes", result.v2_nodes)
    if not result.equal:
        metrics.incr("uast2.shadow.mismatches")
        logger.warning(
            "UAST shadow mismatch (%s, %d difference(s)): %s",
            language,
            len(result.differences),
            "; ".join(result.differences[:3]) or "unknown",
        )
        if raise_on_error:
            raise AssertionError(
                f"UAST shadow mismatch for {language}: {result.differences}"
            )
    return result


def run_shadow_suite(
    paths: Sequence[Union[str, Path]],
    language: str = "python",
    mode: str = "exact",
    extended: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run shadow mode over many files (the CI / ``--mode deep`` gate)."""
    results: List[Dict[str, Any]] = []
    mismatches = 0
    failures = 0
    for path in paths:
        path = Path(path)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures += 1
            results.append({"path": str(path), "error": str(exc)})
            continue
        try:
            result = shadow_parse(source, language=language, mode=mode, extended=extended)
        except Exception as exc:  # pragma: no cover - defensive
            failures += 1
            results.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        entry = {"path": str(path), **result.to_dict()}
        results.append(entry)
        if result.error is not None:
            failures += 1  # engine could not parse the file: not a parity issue
        elif not result.equal:
            mismatches += 1
    return {
        "files": len(paths),
        "mismatches": mismatches,
        "errors": failures,
        "ok": mismatches == 0 and failures == 0,
        "results": results,
    }


def shadow_stats() -> Dict[str, float]:
    """Shadow-related counters (from :mod:`muta_ext.uast2.metrics`)."""
    return {key: value for key, value in metrics.snapshot().items() if ".shadow." in key}
