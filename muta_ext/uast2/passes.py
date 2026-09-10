#!/usr/bin/env python3
"""Nanopass infrastructure for UAST v2 — atomic, verifiable transformations.

Every mutation is a :class:`Pass`: a small atomic rewrite (``run``) paired with a
non-mutating verifier (``verify``).  The :class:`Pipeline` runs passes in order,
verifies after each one and — crucially for reliability — can **roll back** a pass
whose verification fails, so a pipeline can never leave an invalid tree behind.

Modes (matching the playbook):

* ``strict=False`` (shadow/default): an invalid IR is logged and the pass is
  rolled back; the pipeline keeps going.
* ``strict=True``: the first invalid IR raises :class:`InvalidIR`, which callers
  such as the sandbox/evaluator treat as a rejected candidate.
"""

from __future__ import annotations

import logging
import time
import typing as T
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from muta_ext.uast2.core import UASTNode, CoreUAST, walk

__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
    "Diagnostic",
    "InvalidIR",
    "Pass",
    "MutationPass",
    "Pipeline",
    "PipelineResult",
]

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

logger = logging.getLogger("MutaLambda.uast2")


@dataclass(frozen=True)
class Diagnostic:
    """A single verification finding (never mutates the tree)."""

    severity: str
    message: str
    pass_name: str = ""
    node: Optional[UASTNode] = field(default=None, compare=False, repr=False)
    code: str = ""

    @property
    def is_error(self) -> bool:
        """True when this diagnostic invalidates the IR."""
        return self.severity == SEVERITY_ERROR

    @property
    def node_id(self) -> Optional[int]:
        """Arena id of the offending node (useful for flat checkpoints/logs)."""
        return getattr(self.node, "_id", None)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable form."""
        return {
            "severity": self.severity,
            "pass": self.pass_name,
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "node_type": type(self.node).__name__ if self.node is not None else None,
        }

    def __str__(self) -> str:  # pragma: no cover - formatting helper
        location = ""
        if self.node is not None and self.node.lineno is not None:
            location = f" (line {self.node.lineno})"
        return f"[{self.severity}] {self.pass_name}: {self.message}{location}"


class InvalidIR(RuntimeError):
    """Raised by a strict :class:`Pipeline` when a pass leaves an invalid IR."""

    def __init__(self, pass_name: str, diagnostics: Sequence[Diagnostic]) -> None:
        self.pass_name = pass_name
        self.diagnostics = list(diagnostics)
        detail = "; ".join(str(diag) for diag in self.diagnostics)
        super().__init__(f"{pass_name} produced an invalid IR: {detail}")


class Pass(ABC):
    """Atomic rewrite plus its verifier.

    Subclasses implement :meth:`run` (mutates) and, optionally, :meth:`verify`
    (read-only).  ``verify`` must never modify the tree — the pipeline relies on
    that to decide about rollbacks.
    """

    name: str = "pass"
    description: str = ""
    #: Verifiers set this to ``False`` so the pipeline knows no snapshot is needed.
    mutating: bool = True
    #: ``False`` for expensive gates (legacy bridge, security scan, math fidelity):
    #: they run once per document/pipeline instead of after every nanopass, which
    #: keeps "verify after each mutation" proportional to the mutation.
    per_pass_guard: bool = True
    #: Mutation passes declare whether they *intend* to keep arithmetic semantics.
    #: The math-fidelity gate is only engaged when every executed mutation claims
    #: preservation (constant folding and bound tweaking change numbers on
    #: purpose, so requiring equivalence there would veto the whole pipeline).
    preserves_math: bool = True

    def __init__(self) -> None:
        self.mutations: int = 0
        self.last_diagnostics: List[Diagnostic] = []

    # ── API ─────────────────────────────────────────────────────────────────
    @abstractmethod
    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:
        """Apply the transformation *in place* (verifiers have a no-op body)."""
        raise NotImplementedError

    def verify(
        self, root: CoreUAST, scope: Optional[Sequence[Any]] = None
    ) -> List[Diagnostic]:
        """Return diagnostics for *root*; must not mutate anything.

        ``scope`` limits the check to the subtrees a nanopass may have touched
        (``None`` verifies the whole document).  Verifiers that need global
        context simply ignore it.
        """
        return []

    # ── helpers for subclasses ──────────────────────────────────────────────
    def _record(self, count: int = 1) -> None:
        """Track how many mutations this pass applied (reported by the pipeline)."""
        self.mutations += count

    def nodes(self, root: CoreUAST) -> T.Iterator[UASTNode]:
        """Iterate the document's nodes (convenience for subclasses)."""
        return root.walk()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{type(self).__name__} name={self.name!r} mutations={self.mutations}>"


class MutationPass(Pass):
    """A mutating pass that self-verifies with structural invariants.

    Passing ``verify_with`` (a callable ``root -> List[Diagnostic]``) lets the
    pass reuse existing verifiers instead of duplicating rules.
    """

    def __init__(self, verify_with: T.Optional[T.Callable[[CoreUAST], List[Diagnostic]]] = None):
        super().__init__()
        self._verify_with = verify_with

    def verify(
        self, root: CoreUAST, scope: Optional[Sequence[Any]] = None
    ) -> List[Diagnostic]:
        if self._verify_with is None:
            return []
        try:
            return self._verify_with(root, scope)
        except TypeError:
            return self._verify_with(root)


@dataclass
class PipelineResult:
    """Outcome of a :class:`Pipeline` run."""

    diagnostics: Dict[str, List[Diagnostic]] = field(default_factory=dict)
    passes_run: List[str] = field(default_factory=list)
    rolled_back: List[str] = field(default_factory=list)
    aborted_at: Optional[str] = None
    duration_sec: float = 0.0
    mutations: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when the run left a valid IR (passes rolled back don't count)."""
        return not self.errors and self.aborted_at is None

    @property
    def errors(self) -> List[Diagnostic]:
        """Every *surviving* error, in pass order.

        Diagnostics of passes that were rolled back stay in ``diagnostics`` as a
        historical record (audit trail) but no longer make the run fail.
        """
        rolled = set(self.rolled_back) - ({self.aborted_at} if self.aborted_at else set())
        return [
            diag
            for name, diags in self.diagnostics.items()
            if name not in rolled
            for diag in diags
            if diag.severity == SEVERITY_ERROR
        ]

    @property
    def warnings(self) -> List[Diagnostic]:
        """Every warning-severity diagnostic, in pass order."""
        return [
            diag
            for diags in self.diagnostics.values()
            for diag in diags
            if diag.severity == SEVERITY_WARNING
        ]

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable summary (used by CLI/CI reporting)."""
        return {
            "ok": self.ok,
            "passes_run": self.passes_run,
            "rolled_back": self.rolled_back,
            "aborted_at": self.aborted_at,
            "duration_sec": self.duration_sec,
            "mutations": self.mutations,
            "errors": [diag.to_dict() for diag in self.errors],
            "warnings": [diag.to_dict() for diag in self.warnings],
        }


class Pipeline:
    """Ordered pass pipeline with per-pass verification and rollback."""

    def __init__(
        self,
        passes: Optional[Sequence[Pass]] = None,
        strict: bool = False,
        rollback: bool = True,
        logger_: Optional[logging.Logger] = None,
        guards: Optional[Sequence[Pass]] = None,
    ) -> None:
        self.passes: List[Pass] = list(passes or [])
        self.strict = strict
        self.rollback = rollback
        self.logger = logger_ or logger
        self.last_result: Optional[PipelineResult] = None
        # ``guards`` are read-only verifiers executed after *every* mutating pass
        # (the playbook's "nanopasses with verify"): a mutation that leaves an
        # invalid IR is rolled back (or raises, in strict mode) even when the
        # mutating pass itself declares no verifier.  ``None`` means "auto":
        # every non-mutating pass already registered in this pipeline.
        self._guards_explicit = guards is not None
        self._guards: List[Pass] = list(guards or [])

    # ── Construction ────────────────────────────────────────────────────────
    @property
    def guards(self) -> List[Pass]:
        """Verifier passes executed after every mutating pass."""
        if self._guards_explicit:
            return list(self._guards)
        return [
            pass_
            for pass_ in self.passes
            if not pass_.mutating and getattr(pass_, "per_pass_guard", True)
        ]

    def set_guards(self, guards: Sequence[Pass]) -> "Pipeline":
        """Replace the guard set explicitly (``[]`` disables post-pass checks)."""
        self._guards_explicit = True
        self._guards = list(guards)
        return self


    def add(self, pass_: Pass, index: Optional[int] = None) -> "Pipeline":
        """Append (or insert) a pass and return ``self`` for chaining."""
        if index is None:
            self.passes.append(pass_)
        else:
            self.passes.insert(index, pass_)
        return self

    def extend(self, passes: Sequence[Pass]) -> "Pipeline":
        """Append several passes."""
        self.passes.extend(passes)
        return self

    def __iter__(self) -> T.Iterator[Pass]:
        return iter(self.passes)

    def __len__(self) -> int:
        return len(self.passes)

    def names(self) -> List[str]:
        """Names of the registered passes, in execution order."""
        return [pass_.name for pass_ in self.passes]

    # ── Execution ───────────────────────────────────────────────────────────
    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> PipelineResult:
        """Run every pass, verifying after each one and rolling back on failure.

        ``rollback=True`` (default) is *atomic per run*: one snapshot is taken
        before the first mutating pass and a failure restores the whole run (all
        mutating passes executed so far are reverted).  ``rollback="pass"`` takes
        a snapshot per pass (finer granularity, more copies); ``rollback=False``
        disables the safety net entirely (fastest, used by hot loops that verify
        out-of-band).  Snapshots are only taken when a mutating pass exists.
        """
        from muta_ext.uast2 import metrics

        started = time.perf_counter()
        result = PipelineResult()
        per_pass_snapshots = self.rollback == "pass"
        snapshot: Optional[CoreUAST] = None
        snapshot_taken_for: Optional[str] = None
        mutating_executed: List[str] = []
        for pass_ in self.passes:
            mutations_before = pass_.mutations
            if self.rollback and pass_.mutating and (per_pass_snapshots or snapshot is None):
                snapshot = root.clone()
                snapshot_taken_for = pass_.name
            from muta_ext.uast2.merkle import begin_touch, end_touch

            begin_touch()
            try:
                pass_.run(root, arena)
            except Exception as exc:  # pragma: no cover - defensive
                result.diagnostics[pass_.name] = [
                    Diagnostic(
                        SEVERITY_ERROR,
                        f"pass crashed: {type(exc).__name__}: {exc}",
                        pass_name=pass_.name,
                        code="pass_exception",
                    )
                ]
                result.aborted_at = pass_.name
                metrics.incr("uast2.pipeline.pass_errors")
                if self.strict:
                    if snapshot is not None:
                        _restore(root, snapshot, arena)
                        result.rolled_back.extend(
                            [pass_.name]
                            if per_pass_snapshots
                            else _merge_names(mutating_executed, pass_.name)
                        )
                    self._finish(result, started)
                    raise InvalidIR(pass_.name, result.diagnostics[pass_.name]) from exc
                if snapshot is not None:
                    _restore(root, snapshot, arena)
                    result.rolled_back.extend(
                        [pass_.name]
                        if per_pass_snapshots
                        else _merge_names(mutating_executed, pass_.name)
                    )
                self._finish(result, started)
                return result

            touched = end_touch() if pass_.mutating else []
            scope = self._scope_for(touched, pass_) if pass_.mutating else None
            diagnostics = list(pass_.verify(root, scope))
            if pass_.mutating:
                for guard in self.guards:
                    if guard is pass_:
                        continue
                    diagnostics.extend(guard.verify(root, scope))
            pass_.last_diagnostics = list(diagnostics)
            result.diagnostics[pass_.name] = list(diagnostics)
            result.passes_run.append(pass_.name)
            result.mutations[pass_.name] = pass_.mutations - mutations_before

            if pass_.mutating:
                mutating_executed.append(pass_.name)
            errors = [diag for diag in diagnostics if diag.severity == SEVERITY_ERROR]
            if errors:
                metrics.incr("uast2.pipeline.invalid_ir")
                if self.strict:
                    if snapshot is not None:
                        _restore(root, snapshot, arena)
                        result.rolled_back.extend(
                            [pass_.name]
                            if per_pass_snapshots
                            else _merge_names(mutating_executed, snapshot_taken_for)
                        )
                    self._finish(result, started)
                    raise InvalidIR(pass_.name, errors)
                self.logger.warning(
                    "UAST v2: '%s' left an invalid IR (%d error(s)); rolling back%s",
                    pass_.name,
                    len(errors),
                    " (whole run)" if not per_pass_snapshots else "",
                )
                if snapshot is not None:
                    _restore(root, snapshot, arena)
                    result.rolled_back.extend(
                        [pass_.name]
                        if per_pass_snapshots
                        else _merge_names(mutating_executed, snapshot_taken_for)
                    )
                    if not per_pass_snapshots:
                        break  # the run is atomic: nothing left to apply

        self._finish(result, started)
        return result

    def verify_only(self, root: CoreUAST) -> List[Diagnostic]:
        """Run only the ``verify`` half of every registered pass (and guard)."""
        collected: List[Diagnostic] = []
        seen_guards: T.Set[int] = set()
        candidates: List[Pass] = list(self.passes)
        for guard in self.guards:
            if id(guard) not in seen_guards and guard not in candidates:
                seen_guards.add(id(guard))
                candidates.append(guard)
        for pass_ in candidates:
            for diag in pass_.verify(root):
                collected.append(
                    diag
                    if diag.pass_name
                    else Diagnostic(diag.severity, diag.message, pass_name=pass_.name, node=diag.node)
                )
        return collected

    # ── Internals ───────────────────────────────────────────────────────────
    def _scope_for(self, touched: Sequence[Any], pass_: Pass) -> Optional[List[Any]]:
        """Turn a touch log into the scope handed to the guards.

        ``None`` means "verify the whole document": that happens when the pass
        declared mutations but the log is empty (passes that rebuild the tree
        wholesale, e.g. the legacy bridge), so the safety net never silently
        shrinks.
        """
        if pass_.mutations and not touched:
            return None
        if not touched:
            return None
        scope_ids = {id(node) for node in touched}
        scopes: List[Any] = []
        seen: T.Set[int] = set()
        for node in touched:
            identity = id(node)
            if identity in seen:
                continue
            # Drop nodes covered by an ancestor already in the scope, otherwise
            # overlapping roots would look like shared subtrees to the guards.
            parent = getattr(node, "_parent", None)
            covered = False
            while parent is not None:
                if id(parent) in scope_ids:
                    covered = True
                    break
                parent = getattr(parent, "_parent", None)
            if covered:
                continue
            seen.add(identity)
            scopes.append(node)
        return scopes


    def _finish(self, result: PipelineResult, started: float) -> None:
        result.duration_sec = time.perf_counter() - started
        self.last_result = result


def _merge_names(names: Sequence[str], fallback: Optional[str]) -> List[str]:
    """Unique pass names in order (``fallback`` added when the list is empty)."""
    merged: List[str] = []
    for name in names:
        if name not in merged:
            merged.append(name)
    if not merged and fallback:
        merged.append(fallback)
    return merged


def _restore(root: CoreUAST, snapshot: CoreUAST, arena: Optional[Any] = None) -> None:
    """Copy *snapshot* back into *root* (same object, so callers keep their handle)."""
    root.body[:] = snapshot.body
    root.metadata = dict(snapshot.metadata)
    root.language = snapshot.language
    root.prepare(arena)
