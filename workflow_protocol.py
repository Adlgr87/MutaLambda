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
