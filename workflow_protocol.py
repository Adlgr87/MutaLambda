"""Protocol-driven workflow helpers for ordered candidate evolution."""

from __future__ import annotations

import ast
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

PASS = "PASS"
FAIL = "FAIL"
RETRYABLE_FAIL = "RETRYABLE_FAIL"


@dataclass
class StageResult:
    """Result for a single workflow stage."""

    name: str
    status: str
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)
    finished_at: float = field(default_factory=time.perf_counter)

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


@dataclass
class ProtocolTrace:
    """Trace for an ordered workflow execution."""

    run_id: str
    subject_id: str
    decision: str = "pending"
    attempts: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    stages: List[StageResult] = field(default_factory=list)

    def add_stage(self, result: StageResult) -> None:
        self.stages.append(result)

    def stage_names(self) -> List[str]:
        return [stage.name for stage in self.stages]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "subject_id": self.subject_id,
            "decision": self.decision,
            "attempts": self.attempts,
            "metadata": dict(self.metadata),
            "stages": [
                {
                    "name": stage.name,
                    "status": stage.status,
                    "message": stage.message,
                    "metadata": dict(stage.metadata),
                    "artifacts": dict(stage.artifacts),
                    "duration_sec": round(stage.duration_sec, 6),
                }
                for stage in self.stages
            ],
        }


@dataclass
class ProtocolStage:
    """Sequential workflow stage."""

    name: str
    runner: Callable[[Dict[str, Any]], StageResult]


class ProtocolWorkflow:
    """Executes ordered stages until one fails."""

    def __init__(self, stages: List[ProtocolStage]):
        self.stages = stages

    def execute(self, context: Dict[str, Any], trace: ProtocolTrace) -> bool:
        for stage in self.stages:
            result = stage.runner(context)
            trace.add_stage(result)
            if result.status == FAIL:
                trace.decision = "reject"
                return False
            if result.status == RETRYABLE_FAIL:
                trace.decision = "retry"
                return False
        trace.decision = "promote"
        return True


def make_stage_result(
    name: str,
    status: str,
    message: str = "",
    *,
    metadata: Dict[str, Any] | None = None,
    artifacts: Dict[str, str] | None = None,
    started_at: float | None = None,
) -> StageResult:
    finished_at = time.perf_counter()
    return StageResult(
        name=name,
        status=status,
        message=message,
        metadata=metadata or {},
        artifacts=artifacts or {},
        started_at=finished_at if started_at is None else started_at,
        finished_at=finished_at,
    )


def artifact_ref(code: str) -> str:
    """Stable artifact reference without storing the source."""

    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:12]


def security_findings(code: str) -> List[str]:
    """Return high-confidence security findings for generated code."""

    findings: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings

    risky_calls = {"eval", "exec", "compile", "__import__"}
    risky_attributes = {
        ("os", "system"),
        ("os", "popen"),
        ("subprocess", "run"),
        ("subprocess", "Popen"),
        ("subprocess", "call"),
        ("subprocess", "check_output"),
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in risky_calls:
                findings.append(f"dynamic_call:{node.func.id}")
            elif isinstance(node.func, ast.Attribute):
                owner = getattr(node.func.value, "id", None)
                key = (owner, node.func.attr)
                if key in risky_attributes:
                    findings.append(f"risky_call:{owner}.{node.func.attr}")

    return findings


# ── Validation Gates (FASE 1 framework) ─────────────────────────────────────────


@dataclass
class GateConfig:
    """Per-gate enable/weight configuration."""

    run_id: str = ""
    enable_syntax: bool = True
    enable_security: bool = True
    enable_complexity: bool = True
    enable_correctness: bool = True
    enable_performance: bool = False
    enable_resource: bool = False


def _run_syntax_gate(code: str) -> StageResult:
    name = "syntax_check"
    try:
        ast.parse(code)
        return make_stage_result(name, PASS, "valid Python syntax")
    except SyntaxError as exc:
        return make_stage_result(
            name, FAIL, f"SyntaxError: {exc.msg} (line {exc.lineno})"
        )


def _run_security_gate(code: str) -> StageResult:
    findings = security_findings(code)
    if findings:
        return make_stage_result(
            "security_scan", FAIL, "risky calls", metadata={"findings": findings}
        )
    return make_stage_result("security_scan", PASS, "no risky patterns")


def _run_complexity_gate(code: str, max_complexity: int = 10) -> StageResult:
    try:
        tree = ast.parse(code)
        score = sum(
            getattr(node, "complexity", 0)
            for node in ast.walk(tree)
            if isinstance(getattr(node, "complexity", 0), int)
        ) or _complexity_node_count(tree)
    except SyntaxError:
        score = 0
    if score > max_complexity:
        return make_stage_result(
            "complexity_gate",
            RETRYABLE_FAIL,
            f"complexity {score} > {max_complexity}",
            metadata={"complexity": score},
        )
    return make_stage_result("complexity_gate", PASS, f"complexity {score}")


def _complexity_node_count(tree: ast.AST) -> int:
    return sum(1 for _ in ast.walk(tree))


def build_validation_gates(
    cfg: GateConfig, on_correctness: Callable[[str], bool] | None = None
) -> ProtocolWorkflow:
    """Build the ordered gate workflow from a :class:`GateConfig`.

    Mirrors the PDF FASE 1 "ValidationGates" (syntax_check, security_scan,
    complexity_gate, correctness, performance, resource). Each gate is only
    appended when enabled so the cost is paid only for active checks.
    """
    stages: List[ProtocolStage] = []
    if cfg.enable_syntax:
        stages.append(ProtocolStage("syntax", lambda ctx: _run_syntax_gate(ctx["code"])))
    if cfg.enable_security:
        stages.append(
            ProtocolStage("security", lambda ctx: _run_security_gate(ctx["code"]))
        )
    if cfg.enable_complexity:
        stages.append(
            ProtocolStage(
                "complexity",
                lambda ctx: _run_complexity_gate(ctx["code"]),
            )
        )
    if cfg.enable_correctness and on_correctness:
        stages.append(
            ProtocolStage(
                "correctness",
                lambda ctx: make_stage_result(
                    "correctness",
                    PASS if on_correctness(ctx["code"]) else FAIL,
                ),
            )
        )
    if cfg.enable_performance:
        stages.append(
            ProtocolStage(
                "performance",
                lambda ctx: make_stage_result(
                    "performance", PASS, "placeholder perf gate"
                ),
            )
        )
    if cfg.enable_resource:
        stages.append(
            ProtocolStage(
                "resource",
                lambda ctx: make_stage_result("resource", PASS, "placeholder resource gate"),
            )
        )
    return ProtocolWorkflow(stages)


class ValidationGates:
    """Facade around :class:`ProtocolWorkflow` + :class:`GateConfig`.

    Usage::

        gates = ValidationGates(GateConfig(run_id="r1"))
        trace = gates.evaluate({"code": new_code})
        if trace.decision != "promote":
            ...

    This replaces the ad-hoc inline gate checks scattered in
    ``EvolutionEngine.mutate`` and ``CoreEvolutionEngine._apply_mutation`` once
    FASE 2 wires it through.
    """

    def __init__(self, cfg: GateConfig, on_correctness: Callable[[str], bool] | None = None) -> None:
        self.cfg = cfg
        self._correctness_cb = on_correctness
        self._workflow = build_validation_gates(cfg, on_correctness)

    def evaluate(self, context: Dict[str, Any]) -> ProtocolTrace:
        trace = ProtocolTrace(
            run_id=self.cfg.run_id or "",
            subject_id=artifact_ref(context["code"])[:12],
        )
        self._workflow.execute(context, trace)
        return trace


# ── Complexity Gate (legacy, kept) ─────────────────────────────────────────

class ComplexityGate:
    """Pre-evolutive gate: decide if a function is worth deep evolution.

    Trivial functions (small AST, no loops, no I/O) should use --fast mode
    and skip island_evolution entirely.
    """

    def __init__(self, 
                 min_ast_nodes: int = 15,
                 require_loops: bool = True,
                 max_trivial_depth: int = 1):
        self.min_ast_nodes = min_ast_nodes
        self.require_loops = require_loops
        self.max_trivial_depth = max_trivial_depth

    def evaluate(self, code: str) -> dict:
        """Evaluate if function is complex enough for deep evolution."""
        result = {
            "passes_gate": False,
            "recommendation": "fast",
            "reasons": [],
            "metrics": {},
        }

        try:
            tree = ast.parse(code)
        except SyntaxError:
            result["reasons"].append("syntax_error")
            return result

        # Count AST nodes
        node_count = sum(1 for _ in ast.walk(tree))
        result["metrics"]["ast_nodes"] = node_count

        # Check for loops
        has_loops = False
        max_depth = 0

        def _loop_depth(node, depth=0):
            nonlocal max_depth
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.For, ast.While)):
                    max_depth = max(max_depth, depth + 1)
                    _loop_depth(child, depth + 1)
                else:
                    _loop_depth(child, depth)

        _loop_depth(tree)
        has_loops = max_depth > 0
        result["metrics"]["max_loop_depth"] = max_depth
        result["metrics"]["has_loops"] = has_loops

        # Check for I/O
        has_io = False
        io_funcs = {'open', 'read', 'write', 'print', 'input', 'socket'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in io_funcs:
                    has_io = True
                    break
        result["metrics"]["has_io"] = has_io

        # Decision logic
        if node_count < self.min_ast_nodes:
            result["reasons"].append(f"too_few_nodes ({node_count} < {self.min_ast_nodes})")

        if self.require_loops and not has_loops:
            result["reasons"].append("no_loops_found")

        if has_io:
            result["reasons"].append("has_io_calls")
            result["recommendation"] = "skip"  # Don't optimize I/O code

        # Passes gate = complex enough for deep evolution
        if not result["reasons"]:
            result["passes_gate"] = True
            result["recommendation"] = "deep"

        return result

    def get_fast_mode(self, code: str) -> bool:
        """Returns True if function should use fast mode only."""
        result = self.evaluate(code)
        return result["recommendation"] == "fast"
