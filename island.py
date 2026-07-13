"""Island evolution unit."""

from __future__ import annotations

import ast
import copy
import heapq
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional

from evolution_engine import ASTMutator, CoreEvolutionEngine, ast_crossover
from models import EvalResult, Individual, IslandConfig
from sandbox import SandboxEvaluator
from workflow_protocol import (
    PASS,
    RETRYABLE_FAIL,
    ProtocolStage,
    ProtocolTrace,
    ProtocolWorkflow,
    artifact_ref,
    make_stage_result,
    security_findings,
)

logger = logging.getLogger("MutaLambda")


class Island:
    """Unidad de evolución independiente."""

    def __init__(
        self,
        island_id: int,
        config: IslandConfig,
        llm_fn: Callable[[str], str],
        evaluator: SandboxEvaluator,
        migration_bus: Any,
    ):
        self.id = island_id
        self.config = config
        self.llm_fn = llm_fn
        self.evaluator = evaluator
        self.migration_bus = migration_bus
        self.core_engine = CoreEvolutionEngine()

        self.population: List[Individual] = []
        self.generation: int = 0
        self.local_best: Optional[Individual] = None
        self._history: List[float] = []
        self._protocol_run_id: str = "unbound"
        self._protocol_trace_sink: Optional[Callable[[ProtocolTrace], None]] = None
        self._protocol_agent: Any = None
        self._workflow_enabled: bool = True
        self._workflow_max_retries: int = 1
        self._workflow_correctness_threshold: float = 1.0
        self._workflow_require_score_improvement: bool = False
        self._workflow_enforce_security: bool = True

        self.migration_bus.register_island(island_id, self)

    def configure_protocol(
        self,
        *,
        run_id: str,
        trace_sink: Optional[Callable[[ProtocolTrace], None]],
        agent: Any,
        config: Any,
    ) -> None:
        """Attach run-scoped workflow state for traceability and gates."""
        self._protocol_run_id = run_id
        self._protocol_trace_sink = trace_sink
        self._protocol_agent = agent
        self._workflow_enabled = getattr(config, "workflow_enabled", True)
        self._workflow_max_retries = max(0, int(getattr(config, "workflow_max_retries", 1)))
        self._workflow_correctness_threshold = float(
            getattr(config, "workflow_correctness_threshold", 1.0)
        )
        self._workflow_require_score_improvement = bool(
            getattr(config, "workflow_require_score_improvement", False)
        )
        self._workflow_enforce_security = bool(
            getattr(config, "workflow_enforce_security", True)
        )

    def seed_population(self, codes: List[str]) -> None:
        """Inicializa la población con semillas de código."""
        self.population = [
            Individual(code=c) for c in codes[: self.config.population_size]
        ]

    def step(self) -> None:
        """Un paso: evolución local + migración."""
        self._evolve_local()
        self.migration_bus.migrate(self.id, self.generation)
        self.generation += 1

    def _evolve_local(self) -> None:
        """Evaluación → selección elitista → mutación."""
        if not self.population:
            return

        codes = [ind.code for ind in self.population]
        results = self.evaluator.evaluate_batch(codes)

        for ind, res in zip(self.population, results):
            ind.score = res.score
            ind.fitness = res.fitness
            ind.passed = bool(res.passed and res.fitness.correctness >= 1.0)

        pattern_memory = getattr(self.migration_bus, "pattern_memory", None)
        if pattern_memory is not None:
            for ind in self.population:
                if ind.passed:
                    pattern_memory.observe(
                        "code_shape",
                        self._pattern_signature(ind.code),
                        True,
                        f"island:{self.id}",
                        ind.id,
                    )

        thc_engine = getattr(self.migration_bus, "thc_engine", None)
        if thc_engine is not None:
            self.population = thc_engine.apply(
                self.population,
                self.evaluator,
                self.generation,
            )

        if (self.migration_bus is not None
                and getattr(self.migration_bus, "lineage_graph", None) is not None
                and self.generation > 0):
            for ind in self.population:
                if ind.parent_ids:
                    try:
                        parents = [
                            Individual(id=pid, code="")
                            for pid in ind.parent_ids
                        ]
                        reason = getattr(ind, "creation_reason", "mutation")
                        self.migration_bus.lineage_graph.record(
                            ind, parents, self.generation, self.id, reason=reason,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to record lineage for individual %s: %s",
                            ind.id,
                            exc,
                        )

        top = max(self.population, key=lambda x: x.score)
        self._history.append(top.score)

        if self.local_best is None or top.score > self.local_best.score:
            self.local_best = copy.deepcopy(top)
            logger.info(
                "Island %d — gen %d — nuevo mejor local: score=%.4f",
                self.id, self.generation, top.score,
            )

        advanced_selection = getattr(self.migration_bus, "advanced_selection", None)
        if advanced_selection is not None:
            advanced_selection.score_population(self.population)

        try:
            from nsga2 import nsga2_select, nsga2_tournament_select
            elites = nsga2_select(self.population, self.config.top_k)
            use_nsga2 = True
        except ImportError:
            elites = heapq.nlargest(
                self.config.top_k, self.population, key=lambda x: x.score
            )
            use_nsga2 = False

        error_map: Dict[str, str] = {}
        for ind, res in zip(self.population, results):
            if res.stderr and not res.passed:
                error_map[ind.id] = "\n".join(res.stderr.splitlines()[:3])

        new_pop: List[Individual] = list(elites)
        while len(new_pop) < self.config.population_size:
            strategy = "mutation"
            if use_nsga2 and len(elites) >= 2 and random.random() < 0.7:
                parents = nsga2_tournament_select(elites, 1)
                parent = parents[0] if parents else random.choice(elites)
            else:
                parent = random.choice(elites)

            child_parents: List[Individual] = [parent]
            if parent.score < 0 and random.random() < 0.10:
                strategy = "redesign"
                mutated_code = self._redesign(parent.code, parent.score)
            elif random.random() < 0.15 and len(elites) >= 2:
                mate_candidates = [e for e in elites if e.id != parent.id]
                if mate_candidates:
                    strategy = "crossover"
                    other = random.choice(mate_candidates)
                    mutated_code = self._crossover(parent.code, other.code)
                    child_parents.append(other)
                else:
                    error_info = error_map.get(parent.id, "")
                    mutated_code = self._mutate_with_context(
                        parent.code, parent.score, error_info
                    )
            else:
                error_info = error_map.get(parent.id, "")
                mutated_code = self._mutate_with_context(
                    parent.code, parent.score, error_info
                )

            child = self._build_child_candidate(
                parent=parent,
                child_parents=child_parents,
                mutated_code=mutated_code,
                strategy=strategy,
                candidate_index=len(new_pop),
            )
            new_pop.append(child)

        self.population = new_pop

    def _mutate(self, code: str) -> str:
        """Mutación híbrida: AST o LLM."""
        if random.random() < 0.4:
            return ASTMutator.apply_random_mutation(code)

        prompt = (
            "Improve this Python function for correctness and efficiency. "
            "Return only valid Python code, no explanations:\n\n"
            + code
        )
        result = self.llm_fn(prompt)

        try:
            ast.parse(result)
            return result
        except SyntaxError:
            return code

    def _mutate_with_context(self, code: str, score: float, error_info: str = "") -> str:
        """Mutación informada: selector AST + prompt estricto + fallback AST."""
        candidate = self.core_engine.mutate_with_llm(
            code=code,
            score=score,
            error_info=error_info,
            llm_fn=self.llm_fn,
        )
        if candidate.strip() == code.strip():
            candidate = self._mutate(code)
        return self._dialectic_refine(code, candidate)

    def _redesign(self, code: str, score: float) -> str:
        """Rediseño radical dirigido por LLM para individuos fallidos."""
        redesigned = self.core_engine.redesign_with_llm(
            code=code,
            score=score,
            task="Repair correctness first, then improve algorithmic efficiency.",
            llm_fn=self.llm_fn,
        )
        candidate = redesigned if redesigned is not None else ASTMutator.apply_random_mutation(code)
        return self._dialectic_refine(code, candidate)

    def _crossover(self, parent_a: str, parent_b: str) -> str:
        """Recombina dos soluciones con LLM y fallback AST local."""
        generated = self.core_engine.crossover_with_llm(parent_a, parent_b, self.llm_fn)
        if generated is not None:
            return self._dialectic_refine(parent_a, generated)
        return ast_crossover(parent_a, parent_b)

    def _dialectic_refine(self, base_code: str, candidate_code: str) -> str:
        """Run optional dialectic synthesis before a candidate reaches sandbox."""
        engine = getattr(self.migration_bus, "dialectic_engine", None)
        if engine is None:
            return candidate_code
        return engine.refine(base_code, candidate_code, self.llm_fn)

    def _pattern_signature(self, code: str) -> str:
        """Compact AST shape signature for PatternMemory."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return "syntax:error"
        names = [type(node).__name__ for node in ast.walk(tree)]
        return ",".join(names[:16])

    def recompute_local_best(self) -> None:
        """Recalcula local_best tras cambios externos al score."""
        if not self.population:
            return
        top = max(self.population, key=lambda ind: ind.score)
        if self.local_best is None or top.score > self.local_best.score:
            self.local_best = copy.deepcopy(top)

    def get_migrants(self, count: int) -> List[Individual]:
        """Devuelve una muestra aleatoria de la población actual."""
        if not self.population:
            return []
        return random.sample(self.population, min(count, len(self.population)))

    def receive_migrant(self, individual: Individual) -> None:
        """Acepta un inmigrante sin reutilizar su score externo."""
        migrant = copy.deepcopy(individual)
        migrant.score = float("-inf")
        migrant.fitness = None
        migrant.passed = False

        if len(self.population) < self.config.population_size:
            self.population.append(migrant)
            return

        worst_idx = min(
            range(len(self.population)),
            key=lambda i: self.population[i].score,
        )
        self.population[worst_idx] = migrant

    def _build_child_candidate(
        self,
        *,
        parent: Individual,
        child_parents: List[Individual],
        mutated_code: str,
        strategy: str,
        candidate_index: int,
    ) -> Individual:
        if not self._workflow_enabled:
            child = Individual(code=mutated_code, tier="laboratory", record_lineage=True)
            if self.migration_bus is not None and getattr(self.migration_bus, "lineage_graph", None) is not None:
                child.parent_ids = [p.id for p in child_parents]
            child.creation_reason = strategy
            return child

        trace = ProtocolTrace(
            run_id=self._protocol_run_id,
            subject_id=(
                f"island-{self.id}-gen-{self.generation}-candidate-{candidate_index}"
            ),
            metadata={
                "island_id": self.id,
                "generation": self.generation,
                "parent_ids": [p.id for p in child_parents],
                "strategy": strategy,
            },
        )
        base_code = parent.code
        attempts = self._workflow_max_retries + 1
        candidate_code = mutated_code

        for attempt in range(1, attempts + 1):
            trace.attempts = attempt
            attempt_strategy = strategy if attempt == 1 else f"{strategy}_retry"
            context: Dict[str, Any] = {
                "attempt": attempt,
                "strategy": attempt_strategy,
                "parent": parent,
                "candidate_code": candidate_code,
                "candidate_result": None,
            }
            workflow = ProtocolWorkflow(
                [
                    ProtocolStage("generate_candidate", self._stage_generate_candidate),
                    ProtocolStage("build_gate", self._stage_build_gate),
                    ProtocolStage("security_gate", self._stage_security_gate),
                    ProtocolStage("evaluate_candidate", self._stage_evaluate_candidate),
                    ProtocolStage("tests_gate", self._stage_tests_gate),
                    ProtocolStage("performance_gate", self._stage_performance_gate),
                    ProtocolStage("decision_gate", self._stage_decision_gate),
                ]
            )
            if workflow.execute(context, trace):
                result = context["candidate_result"]
                child = Individual(
                    code=context["candidate_code"],
                    tier="laboratory",
                    record_lineage=True,
                )
                child.score = result.score
                child.fitness = result.fitness
                child.passed = bool(
                    result.passed
                    and result.fitness.correctness >= self._workflow_correctness_threshold
                )
                child.creation_reason = attempt_strategy
                if self.migration_bus is not None and getattr(self.migration_bus, "lineage_graph", None) is not None:
                    child.parent_ids = [p.id for p in child_parents]
                child.workflow_trace = trace.to_dict()
                self._emit_protocol_trace(trace)
                return child

            candidate_code = ASTMutator.apply_random_mutation(base_code)
            logger.debug(
                "[run=%s] island=%d gen=%d candidate retry=%d decision=%s",
                self._protocol_run_id,
                self.id,
                self.generation,
                attempt,
                trace.decision,
            )

        trace.decision = "reject"
        self._emit_protocol_trace(trace)
        child = Individual(code=base_code, tier=parent.tier, record_lineage=True)
        child.score = parent.score
        child.fitness = copy.deepcopy(parent.fitness)
        child.passed = parent.passed
        child.creation_reason = f"{strategy}_rejected"
        if self.migration_bus is not None and getattr(self.migration_bus, "lineage_graph", None) is not None:
            child.parent_ids = [p.id for p in child_parents]
        child.workflow_trace = trace.to_dict()
        return child

    def _stage_generate_candidate(self, context: Dict[str, Any]):
        code = context["candidate_code"]
        attempt = context["attempt"]
        strategy = context["strategy"]
        return make_stage_result(
            "generate_candidate",
            PASS,
            f"{strategy} generated candidate",
            metadata={"attempt": attempt, "strategy": strategy},
            artifacts={"candidate_ref": artifact_ref(code)},
        )

    def _stage_build_gate(self, context: Dict[str, Any]):
        attempt = context["attempt"]
        code = context["candidate_code"]
        stage_start = time.perf_counter()
        try:
            ast.parse(code)
            compile(code, "<candidate>", "exec")
            return make_stage_result(
                "build_gate",
                PASS,
                "candidate parses and compiles",
                metadata={"attempt": attempt},
                artifacts={"candidate_ref": artifact_ref(code)},
                started_at=stage_start,
            )
        except SyntaxError as exc:
            return make_stage_result(
                "build_gate",
                RETRYABLE_FAIL,
                f"syntax error: {exc.msg}",
                metadata={"attempt": attempt},
                artifacts={"candidate_ref": artifact_ref(code)},
                started_at=stage_start,
            )

    def _stage_security_gate(self, context: Dict[str, Any]):
        code = context["candidate_code"]
        attempt = context["attempt"]
        findings = security_findings(code)
        if findings and self._workflow_enforce_security:
            return make_stage_result(
                "security_gate",
                RETRYABLE_FAIL,
                ", ".join(findings),
                metadata={"attempt": attempt, "findings": findings},
                artifacts={"candidate_ref": artifact_ref(code)},
            )
        return make_stage_result(
            "security_gate",
            PASS,
            "no high-confidence security findings",
            metadata={"attempt": attempt, "findings": findings},
            artifacts={"candidate_ref": artifact_ref(code)},
        )

    def _stage_evaluate_candidate(self, context: Dict[str, Any]):
        code = context["candidate_code"]
        attempt = context["attempt"]
        stage_start = time.perf_counter()
        result = self.evaluator.evaluate_batch([code])[0]
        context["candidate_result"] = result
        return make_stage_result(
            "evaluate_candidate",
            PASS,
            "sandbox evaluation complete",
            metadata={
                "attempt": attempt,
                "score": round(result.score, 6),
                "correctness": round(result.fitness.correctness, 6),
                "timed_out": result.timed_out,
            },
            artifacts={"candidate_ref": artifact_ref(code)},
            started_at=stage_start,
        )

    def _stage_tests_gate(self, context: Dict[str, Any]):
        result = context["candidate_result"]
        attempt = context["attempt"]
        status = PASS
        message = "candidate passed correctness gate"
        if not result.passed or result.fitness.correctness < self._workflow_correctness_threshold:
            status = RETRYABLE_FAIL
            message = "sandbox/tests gate failed"
        return make_stage_result(
            "tests_gate",
            status,
            message,
            metadata={
                "attempt": attempt,
                "passed": result.passed,
                "correctness": round(result.fitness.correctness, 6),
            },
            artifacts={"stderr_preview": result.stderr[:120]},
        )

    def _stage_performance_gate(self, context: Dict[str, Any]):
        result = context["candidate_result"]
        parent = context["parent"]
        attempt = context["attempt"]
        score_delta = result.score - parent.score
        status = PASS
        message = "candidate accepted by performance gate"
        if self._workflow_require_score_improvement and score_delta < 0:
            status = RETRYABLE_FAIL
            message = "candidate regressed versus parent"
        return make_stage_result(
            "performance_gate",
            status,
            message,
            metadata={
                "attempt": attempt,
                "score_delta": round(score_delta, 6),
                "parent_score": round(parent.score, 6),
                "candidate_score": round(result.score, 6),
            },
            artifacts={"candidate_ref": artifact_ref(context["candidate_code"])},
        )

    def _stage_decision_gate(self, context: Dict[str, Any]):
        result = context["candidate_result"]
        return make_stage_result(
            "decision_gate",
            PASS,
            "promote candidate",
            metadata={
                "candidate_score": round(result.score, 6),
                "correctness": round(result.fitness.correctness, 6),
            },
            artifacts={"candidate_ref": artifact_ref(context["candidate_code"])},
        )

    def _emit_protocol_trace(self, trace: ProtocolTrace) -> None:
        if self._protocol_trace_sink is not None:
            self._protocol_trace_sink(trace)
