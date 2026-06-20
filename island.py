"""Island evolution unit."""

from __future__ import annotations

import ast
import copy
import heapq
import logging
import random
from typing import Any, Callable, Dict, List, Optional

from evolution_engine import ASTMutator, CoreEvolutionEngine
from models import EvalResult, Individual, IslandConfig
from sandbox import SandboxEvaluator

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

        self.migration_bus.register_island(island_id, self)

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

        error_map: Dict[int, str] = {}
        for ind, res in zip(self.population, results):
            if res.stderr and not res.passed:
                error_map[ind.id] = "\n".join(res.stderr.splitlines()[:3])

        new_pop: List[Individual] = list(elites)
        while len(new_pop) < self.config.population_size:
            if use_nsga2 and len(elites) >= 2 and random.random() < 0.7:
                parents = nsga2_tournament_select(elites, 1)
                parent = parents[0] if parents else random.choice(elites)
            else:
                parent = random.choice(elites)

            child_parents: List[Individual] = [parent]
            if parent.score < 0 and random.random() < 0.10:
                mutated_code = self._redesign(parent.code, parent.score)
            elif random.random() < 0.15 and len(elites) >= 2:
                other = random.choice([e for e in elites if e != parent])
                mutated_code = self._crossover(parent.code, other.code)
                child_parents.append(other)
            else:
                error_info = error_map.get(parent.id, "")
                mutated_code = self._mutate_with_context(
                    parent.code, parent.score, error_info
                )

            child = Individual(code=mutated_code, tier="laboratory", record_lineage=True)
            if self.migration_bus is not None and getattr(self.migration_bus, "lineage_graph", None) is not None:
                child.parent_ids = [p.id for p in child_parents]
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

        try:
            tree_a = ast.parse(parent_a)
            tree_b = ast.parse(parent_b)
            funcs_a = {n.name: n for n in ast.walk(tree_a) if isinstance(n, ast.FunctionDef)}
            funcs_b = {n.name: n for n in ast.walk(tree_b) if isinstance(n, ast.FunctionDef)}
            common = set(funcs_a.keys()) & set(funcs_b.keys())
            if not common:
                return parent_a
            for node in ast.walk(tree_a):
                if isinstance(node, ast.FunctionDef) and node.name in common:
                    if random.random() < 0.5:
                        b_func = copy.deepcopy(funcs_b[node.name])
                        node.body = b_func.body
                        node.args = b_func.args
            ast.fix_missing_locations(tree_a)
            result = ast.unparse(tree_a)
            ast.parse(result)
            return result
        except Exception:
            return parent_a

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
        """Acepta un inmigrante: añade o reemplaza al peor si mejora."""
        if len(self.population) < self.config.population_size:
            self.population.append(individual)
        else:
            worst_idx = min(
                range(len(self.population)),
                key=lambda i: self.population[i].score,
            )
            if individual.score > self.population[worst_idx].score:
                self.population[worst_idx] = individual
