"""
Scientific Validation Layer — Stage runner para ProtocolWorkflow.

Provides StageResult integration for scientific invariants validation.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from muta_ext.scientific.invariants import ScientificInvariant, BASE_INVARIANTS

logger = logging.getLogger("MutaLambda.Scientific")

# Import workflow protocol - will be available in the environment
try:
    from workflow_protocol import StageResult, make_stage_result, PASS, FAIL
except ImportError:
    # Fallback for testing
    PASS = "PASS"
    FAIL = "FAIL"
    @dataclass
    class StageResult:
        name: str
        status: str
        message: str = ""
        started_at: float = 0.0
        finished_at: float = 0.0
        metadata: Dict[str, Any] = field(default_factory=dict)
        artifacts: Dict[str, Any] = field(default_factory=dict)
    def make_stage_result(name, status, message="", started_at=0.0, **kwargs):
        return StageResult(name=name, status=status, message=message,
                        started_at=started_at, finished_at=time.perf_counter(), **kwargs)


@dataclass
class InvariantResult:
    """Result of checking a single invariant."""
    name: str
    passed: bool
    severity: str
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScientificValidationResult:
    """Aggregated validation result across all invariants."""
    passed: bool
    scientific_score: float
    hard_passed: int
    hard_failed: int
    soft_passed: int
    soft_failed: int
    total_invariants: int
    details: List[InvariantResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """Human-readable summary of validation result."""
        if self.hard_failed:
            return (f"FAIL: {self.hard_failed} hard failure(s), "
                    f"{self.soft_failed} soft (score={self.scientific_score:.3f})")
        if self.soft_failed:
            return (f"PASS with penalties: {self.soft_failed} soft failure(s) "
                    f"(score={self.scientific_score:.3f})")
        return f"All {self.total_invariants} invariants passed (score={self.scientific_score:.3f})"


SOFT_PENALTY_FACTOR: float = 0.85


def evaluate_invariants(
    result_dict: Dict[str, Any],
    context: Dict[str, Any],
    invariants: Optional[List[ScientificInvariant]] = None,
    soft_penalty: float = SOFT_PENALTY_FACTOR,
) -> ScientificValidationResult:
    """
    Evaluate a set of scientific invariants against evaluation results.

    Args:
        result_dict: Dictionary of evaluation metrics (e.g., energy, mass_delta)
        context: Full context dictionary for additional information
        invariants: List of invariants to check; defaults to BASE_INVARIANTS
        soft_penalty: Multiplicative penalty per soft failure

    Returns:
        ScientificValidationResult with pass/fail status and score
    """
    if invariants is None:
        invariants = BASE_INVARIANTS

    details: List[InvariantResult] = []
    hard_failed, hard_passed, soft_failed, soft_passed = 0, 0, 0, 0

    for inv in invariants:
        try:
            holds = inv.check(result_dict, context)
        except Exception as exc:
            logger.debug("Invariant '%s' raised: %s", inv.name, exc)
            holds = False

        details.append(InvariantResult(
            name=inv.name, passed=holds, severity=inv.severity,
            message="" if holds else f"'{inv.name}' violated",
        ))

        if holds:
            if inv.severity == "hard":
                hard_passed += 1
            else:
                soft_passed += 1
        else:
            if inv.severity == "hard":
                hard_failed += 1
            else:
                soft_failed += 1

    # Calculate score: hard failures reduce by 50% each, soft failures multiply penalty
    hard_ratio = 1.0 - (hard_failed / max(len(invariants), 1)) * 0.5
    soft_ratio = soft_penalty ** soft_failed
    scientific_score = round(max(0.0, hard_ratio * soft_ratio), 4)
    passed = hard_failed == 0

    return ScientificValidationResult(
        passed=passed, scientific_score=scientific_score,
        hard_passed=hard_passed, hard_failed=hard_failed,
        soft_passed=soft_passed, soft_failed=soft_failed,
        total_invariants=len(invariants), details=details,
    )


def run_scientific_validation_stage(context: Dict[str, Any]) -> StageResult:
    """
    ProtocolWorkflow stage runner.

    Se inserta entre 'tests' y 'perf'. Si scientific.enabled=False,
    devuelve PASS inmediatamente sin validar.
    """
    started_at = time.perf_counter()
    eval_result = context.get("eval_result")
    sci_config = context.get("scientific_config", {})
    enabled = sci_config.get("enabled", False)

    if not enabled:
        return make_stage_result(
            name="scientific_validation", status=PASS,
            message="Scientific validation disabled",
            started_at=started_at,
            metadata={"scientific_score": 1.0, "enabled": False},
        )

    # Extraer dict de resultado
    result_dict: Dict[str, Any] = {}
    if eval_result:
        result_dict["passed"] = getattr(eval_result, "passed", False)
        metrics = getattr(eval_result, "metrics", {}) or {}
        if isinstance(metrics, dict):
            result_dict.update(metrics)
        fitness = getattr(eval_result, "fitness", None)
        if fitness:
            for dim in ("correctness", "latency_p50", "latency_p99", "throughput", "memory"):
                v = getattr(fitness, dim, None)
                if v is not None:
                    result_dict[dim] = v

    # Seleccionar invariantes según config
    vc = sci_config.get("validation", {})
    active = list(BASE_INVARIANTS)
    if not vc.get("invariants", True):
        active = []
    if not vc.get("numerical_stability", True):
        active = [i for i in active if i.name != "numerical_stability"]
    if not vc.get("conservation_checks", True):
        active = [i for i in active if i.name not in ("mass_conservation", "energy_non_negative")]
    if not vc.get("property_based", True):
        active = [i for i in active if i.name not in ("monotonicity_trend", "physical_bounds")]

    custom = context.get("custom_invariants", [])
    if custom:
        active.extend(custom)

    if not active:
        return make_stage_result(
            name="scientific_validation", status=PASS,
            message="No active invariants", started_at=started_at,
            metadata={"scientific_score": 1.0, "invariants_run": 0},
        )

    result = evaluate_invariants(result_dict, context, invariants=active)
    status = PASS if result.passed else FAIL

    return make_stage_result(
        name="scientific_validation", status=status,
        message=result.summary, started_at=started_at,
        metadata={
            "scientific_score": result.scientific_score,
            "passed": result.passed,
            "hard_failed": result.hard_failed,
            "soft_failed": result.soft_failed,
            "total_invariants": result.total_invariants,
            "enabled": True,
        },
        artifacts={d.name: "PASS" if d.passed else f"FAIL({d.severity})"
                   for d in result.details},
    )