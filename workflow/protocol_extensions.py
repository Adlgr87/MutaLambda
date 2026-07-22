"""Extensiones al ProtocolWorkflow para integrar SVL y Hot-path."""

from __future__ import annotations
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("MutaLambda.Workflow.Scientific")

# Import workflow protocol - will be available in the environment
try:
    from workflow_protocol import (
        ProtocolWorkflow, ProtocolStage, StageResult, PASS,
        make_stage_result,
    )
except ImportError:
    # Fallback for testing
    PASS = "PASS"
    FAIL = "FAIL"
    @dataclass
    class ProtocolStage:
        name: str
        runner: Callable[[Dict[str, Any]], StageResult]
        requires: Optional[List[str]] = None
    @dataclass
    class StageResult:
        name: str
        status: str
        message: str = ""
        started_at: float = 0.0
        finished_at: float = 0.0
        metadata: Dict[str, Any] = field(default_factory=dict)
        artifacts: Dict[str, Any] = field(default_factory=dict)
    @dataclass
    class ProtocolWorkflow:
        stages: List[ProtocolStage]

    def make_stage_result(name, status, message="", started_at=0.0, **kwargs):
        return StageResult(name=name, status=status, message=message,
                        started_at=started_at, finished_at=time.perf_counter(), **kwargs)

from muta_ext.scientific.validation import run_scientific_validation_stage
from muta_ext.scientific.hotpath import profile_workload
from muta_ext.scientific.hotpath_types import ProfileConfig, HotPathResult
from muta_ext.uast.call_graph import (
    CallGraph, extract_call_graph_from_source, extract_call_graph_multi_file,
)


def build_scientific_workflow(
    base_stages: List[ProtocolStage],
    scientific_config: Optional[Dict[str, Any]] = None,
) -> ProtocolWorkflow:
    """Construye ProtocolWorkflow con scientific_validation insertado.

    Inserta el stage 'scientific_validation' entre 'tests' y 'perf'.
    Si scientific.enabled=False, devuelve el workflow original sin cambios.
    """
    if scientific_config is None:
        scientific_config = {"enabled": False}

    if not scientific_config.get("enabled", False):
        return ProtocolWorkflow(stages=list(base_stages))

    new_stages: List[ProtocolStage] = []
    inserted = False

    for stage in base_stages:
        new_stages.append(stage)
        if stage.name == "tests" and not inserted:
            new_stages.append(ProtocolStage(
                name="scientific_validation",
                runner=_make_svl_runner(scientific_config),
            ))
            inserted = True

    if not inserted:
        new_stages.append(ProtocolStage(
            name="scientific_validation",
            runner=_make_svl_runner(scientific_config),
        ))

    return ProtocolWorkflow(stages=new_stages)


def _make_svl_runner(sci_config: Dict[str, Any]) -> Callable[[Dict[str, Any]], StageResult]:
    """Crea el runner para el stage de validación científica."""
    def runner(context: Dict[str, Any]) -> StageResult:
        context["scientific_config"] = sci_config
        return run_scientific_validation_stage(context)
    return runner


# ── Context enrichment para Hot-path ─────────────────────────

def enrich_context_with_hotpath(
    context: Dict[str, Any],
    hotpath_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Profilea el workload y enriquece el context con HotPath y CallGraph."""
    if hotpath_config is None:
        hotpath_config = {}

    enabled = hotpath_config.get("enabled", True)
    if not enabled:
        context["hotpath_result"] = HotPathResult()
        return context

    candidate_code = context.get("candidate", {}).get("source", "")
    workload = context.get("workload")

    if not workload:
        context["hotpath_result"] = HotPathResult()
        return context

    config = ProfileConfig(
        enabled=enabled,
        profiler=hotpath_config.get("profiler", "cprofile"),
        min_cumulative_pct=float(hotpath_config.get("min_cumulative_pct", 5.0)),
        max_hot_functions=int(hotpath_config.get("max_hot_functions", 15)),
        interprocedural_prob=float(hotpath_config.get("interprocedural_prob", 0.25)),
        max_functions_per_mutation=int(hotpath_config.get("max_functions_per_mutation", 3)),
        depth=int(hotpath_config.get("depth", 1)),
    )

    result = profile_workload(
        entry_point=context.get("entry_point", "main"),
        workload=workload,
        config=config,
    )
    context["hotpath_result"] = result

    file_paths = context.get("file_paths", [])
    if file_paths:
        call_graph = extract_call_graph_multi_file(file_paths)
    else:
        call_graph = extract_call_graph_from_source(candidate_code)

    if call_graph is not None:
        context["call_graph"] = call_graph
        if result.has_hot_paths:
            hot_names = {hp.function_name for hp in result.hot_paths}
            context["hot_subgraph"] = call_graph.hot_subgraph(hot_names, depth=config.depth)
    else:
        context["call_graph"] = CallGraph()
        context["hot_subgraph"] = CallGraph()

    return context


# ── Helpers de rollback ─────────────────────────────────────

def is_scientific_enabled(config: Dict[str, Any]) -> bool:
    """Verifica si la extensión científica está habilitada."""
    return config.get("scientific", {}).get("enabled", False)


def disable_scientific(config: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve config con scientific completamente desactivado (para regresión)."""
    modified = dict(config)
    sci = dict(modified.get("scientific", {}))
    sci["enabled"] = False
    sci["validation"] = {k: False for k in ("invariants", "numerical_stability",
                                              "conservation_checks", "property_based")}
    if "hotpath" in sci:
        sci["hotpath"]["enabled"] = False
    if "domain_operators" in sci:
        sci["domain_operators"]["enabled"] = False
    modified["scientific"] = sci
    return modified