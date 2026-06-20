"""
HFC tiered evolution for MutaLambda.

Implements Hierarchical Fair Competition (HFC) / tiered speciation:

- Tier 1 / Laboratory: chaotic exploration with LLM crossover and AST mutation.
- Tier 2 / Factory: bacterial reproduction (1 -> lambda clones) with focused
  micro-mutators for refinement.
- Tier 3 / Elite: static Pareto frontier with vertical migration only.

The engine is intentionally opt-in from ``MutaLambdaAgent`` so the existing
flat island workflow remains backward compatible.
"""

from __future__ import annotations

import ast
import copy
import logging
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from evolution_engine import ASTMutator, CoreEvolutionEngine
from fitness_vector import FitnessVector
from models import EvalResult, Individual

logger = logging.getLogger("MutaLambda")

TIER_LABORATORY = "laboratory"
TIER_FACTORY = "factory"
TIER_ELITE = "elite"
_TIER_IDS = {
    TIER_LABORATORY: 0,
    TIER_FACTORY: 1,
    TIER_ELITE: 2,
}


@dataclass
class HFCTierConfig:
    """Configuration for the HFC tier engine."""

    max_tier1_size: int = 100
    max_tier2_size: int = 50
    max_tier3_size: int = 10
    lambda_clones: int = 8
    promotion_correctness: float = 1.0
    tier1_crossover_prob: float = 0.35
    tier1_llm_mutate_prob: float = 0.65
    tier1_llm_crossover_prob: float = 0.50
    tier2_llm_micro_mutation: bool = False
    top_down_distillation: bool = True
    top_down_interval: int = 5

    def __post_init__(self) -> None:
        if self.max_tier1_size <= 0:
            raise ValueError("hfc.max_tier1_size must be positive")
        if self.max_tier2_size <= 0:
            raise ValueError("hfc.max_tier2_size must be positive")
        if self.max_tier3_size <= 0:
            raise ValueError("hfc.max_tier3_size must be positive")
        if self.lambda_clones < 0:
            raise ValueError("hfc.lambda_clones must be >= 0")
        if not 0.0 <= self.promotion_correctness <= 1.0:
            raise ValueError("hfc.promotion_correctness must be between 0.0 and 1.0")
        if self.top_down_interval <= 0:
            raise ValueError("hfc.top_down_interval must be positive")


@dataclass
class HFCLeagueSnapshot:
    """Telemetry snapshot for one HFC generation."""

    generation: int
    tier_counts: Dict[str, int]
    best_score: float
    diversity: float
    promoted: int
    demoted: int
    distilled_concept: str = ""


@dataclass
class MicroMutator:
    """Named micro-mutator used by Tier 2 bacterial reproduction."""

    name: str
    fn: Callable[[str, Optional[Callable[[str], str]]], str]

    def apply(self, code: str, llm_fn: Optional[Callable[[str], str]] = None) -> str:
        return self.fn(code, llm_fn)


class HFCLeagueEngine:
    """
    Tiered HFC orchestrator.

    Migration rules are hard constraints:
      * non-functional code remains in Tier 1,
      * functional code moves to Tier 2,
      * code that dominates an elite moves to Tier 3 and demotes the weakest elite.
    """

    def __init__(
        self,
        config: Optional[HFCTierConfig] = None,
        rng: Optional[random.Random] = None,
        core_engine: Optional[CoreEvolutionEngine] = None,
    ):
        self.config = config or HFCTierConfig()
        self.rng = rng or random.Random()
        self.core_engine = core_engine or CoreEvolutionEngine()
        self.tier1: List[Individual] = []
        self.tier2: List[Individual] = []
        self.tier3: List[Individual] = []
        self._last_snapshot: Optional[HFCLeagueSnapshot] = None
        self._distilled_concept = ""
        self._micro_mutators = self._build_micro_mutators()

    def seed(self, codes: List[str]) -> None:
        """Seed the experimental laboratory with initial candidates."""
        self.tier1 = [
            Individual(code=code, tier=TIER_LABORATORY)
            for code in codes[: self.config.max_tier1_size]
        ]
        self.tier2 = []
        self.tier3 = []
        self._distilled_concept = ""

    def restore(
        self,
        populations: Dict[str, List[Dict]],
        generation: int = 0,
        distilled_concept: str = "",
    ) -> None:
        """Restore HFC populations from checkpoint data."""
        self.tier1 = [self._individual_from_dict(data, TIER_LABORATORY)
                      for data in populations.get(TIER_LABORATORY, [])]
        self.tier2 = [self._individual_from_dict(data, TIER_FACTORY)
                      for data in populations.get(TIER_FACTORY, [])]
        self.tier3 = [self._individual_from_dict(data, TIER_ELITE)
                      for data in populations.get(TIER_ELITE, [])]
        self._dedupe_restored_populations()
        self._distilled_concept = distilled_concept

    def step(
        self,
        llm_fn: Callable[[str], str],
        evaluator,
        generation: int,
        lineage_graph=None,
        task: str = "",
    ) -> HFCLeagueSnapshot:
        """Run one HFC generation: evaluate → reproduce by tier → migrate."""
        current = self._current_population()
        self._evaluate(current, evaluator)

        self._distilled_concept = self._maybe_distill(llm_fn, generation, task)
        offspring = (
            self._reproduce_laboratory(llm_fn)
            + self._reproduce_factory(llm_fn)
        )
        self._evaluate(offspring, evaluator)

        next_tier1, next_tier2, next_tier3, migration_stats = self._process_migrations(
            current + offspring
        )

        self.tier1 = self._truncate(
            self._dedupe_by_id(next_tier1),
            self.config.max_tier1_size,
        )
        self.tier2 = self._truncate(
            self._dedupe_by_id(next_tier2),
            self.config.max_tier2_size,
        )
        self.tier3 = self._truncate(
            self._dedupe_by_id(next_tier3),
            self.config.max_tier3_size,
        )
        self._assign_tiers()

        survivors = self.tier1 + self.tier2 + self.tier3
        self._record_lineage(survivors, lineage_graph, generation)

        snapshot = HFCLeagueSnapshot(
            generation=generation,
            tier_counts=self._tier_counts(),
            best_score=self.best_score,
            diversity=self.diversity,
            promoted=migration_stats["promoted"],
            demoted=migration_stats["demoted"],
            distilled_concept=self._distilled_concept,
        )
        self._last_snapshot = snapshot
        return snapshot

    @property
    def best_score(self) -> float:
        population = self._current_population()
        if not population:
            return float("-inf")
        return max(ind.score for ind in population)

    @property
    def best_individual(self) -> Optional[Individual]:
        population = self._current_population()
        if not population:
            return None
        return max(population, key=lambda ind: ind.score)

    @property
    def diversity(self) -> float:
        population = self._current_population()
        if not population:
            return 0.0
        unique = len({ind.code for ind in population})
        return unique / len(population)

    @property
    def last_snapshot(self) -> Optional[HFCLeagueSnapshot]:
        return self._last_snapshot

    def stats(self) -> Dict[str, object]:
        """Return compact telemetry for metrics/checkpoints."""
        snapshot = self.last_snapshot
        if snapshot is None:
            return {
                "tier_counts": self._tier_counts(),
                "best_score": self.best_score,
                "diversity": self.diversity,
                "distilled_concept": self._distilled_concept,
            }
        return {
            "tier_counts": snapshot.tier_counts,
            "best_score": snapshot.best_score,
            "diversity": snapshot.diversity,
            "promoted": snapshot.promoted,
            "demoted": snapshot.demoted,
            "distilled_concept": snapshot.distilled_concept,
        }

    def to_checkpoint_dict(self) -> Dict[str, object]:
        return {
            "populations": self._populations_to_dict(),
            "generation": self.last_snapshot.generation if self.last_snapshot else 0,
            "distilled_concept": self._distilled_concept,
        }

    def _build_micro_mutators(self) -> List[MicroMutator]:
        return [
            MicroMutator("llm_loop_rewrite", self._llm_loop_rewrite),
            MicroMutator("ast_micro_mutation", self._ast_micro_mutation),
            MicroMutator("parsimony_prune", self._parsimony_prune),
            MicroMutator("memory_optimization", self._memory_optimization),
            MicroMutator("loop_unrolling", self._loop_unrolling),
            MicroMutator("type_hint_inference", self._type_hint_inference),
        ]

    def _current_population(self) -> List[Individual]:
        return self.tier1 + self.tier2 + self.tier3

    def _evaluate(self, individuals: List[Individual], evaluator) -> None:
        if not individuals:
            return
        results: List[EvalResult] = evaluator.evaluate_batch([ind.code for ind in individuals])
        for ind, result in zip(individuals, results):
            ind.score = result.score
            ind.fitness = result.fitness
            correctness = self._correctness(ind.fitness)
            ind.passed = bool(result.passed and correctness >= self.config.promotion_correctness)

    def _reproduce_laboratory(self, llm_fn: Callable[[str], str]) -> List[Individual]:
        if not self.tier1:
            return []

        parents = list(self.tier1)
        self.rng.shuffle(parents)
        offspring: List[Individual] = []

        for idx in range(0, len(parents) - 1, 2):
            parent_a = parents[idx]
            parent_b = parents[idx + 1]
            if self.rng.random() < self.config.tier1_crossover_prob:
                code = self._crossover(parent_a, parent_b, llm_fn)
                child_parents = [parent_a, parent_b]
            else:
                code = self._mutate_laboratory(parent_a, llm_fn)
                child_parents = [parent_a]

            child = Individual(
                code=code,
                parent_ids=[parent.id for parent in child_parents],
                tier=TIER_LABORATORY,
                record_lineage=True,
            )
            offspring.append(child)

        if len(parents) % 2:
            parent = parents[-1]
            child = Individual(
                code=self._mutate_laboratory(parent, llm_fn),
                parent_ids=[parent.id],
                tier=TIER_LABORATORY,
                record_lineage=True,
            )
            offspring.append(child)

        return offspring

    def _reproduce_factory(self, llm_fn: Callable[[str], str]) -> List[Individual]:
        if not self.tier2 or self.config.lambda_clones == 0:
            return []

        offspring: List[Individual] = []
        for parent in self.tier2:
            for clone_idx, mutator in enumerate(self._micro_mutators):
                if clone_idx >= self.config.lambda_clones:
                    break
                mutated_code = mutator.apply(
                    parent.code,
                    llm_fn if self.config.tier2_llm_micro_mutation else None,
                )
                clone = Individual(
                    code=mutated_code,
                    score=parent.score,
                    fitness=copy.deepcopy(parent.fitness),
                    parent_ids=[parent.id],
                    tier=TIER_FACTORY,
                    passed=parent.passed,
                    record_lineage=False,
                )
                offspring.append(clone)
        return offspring

    def _mutate_laboratory(
        self,
        parent: Individual,
        llm_fn: Callable[[str], str],
    ) -> str:
        if parent.score < 0 and self.rng.random() < 0.20:
            redesigned = self.core_engine.redesign_with_llm(
                code=parent.code,
                score=parent.score,
                task="Repair correctness first, then explore a different algorithm.",
                llm_fn=llm_fn,
            )
            if redesigned is not None:
                return redesigned

        if self.rng.random() < self.config.tier1_llm_mutate_prob:
            prompt = self._build_laboratory_prompt(parent)
            generated = self.core_engine.extract_valid_code(llm_fn(prompt))
            if generated is not None:
                return generated

        return ASTMutator.apply_random_mutation(parent.code)

    def _build_laboratory_prompt(self, parent: Individual) -> str:
        concept = ""
        if self._distilled_concept:
            concept = (
                "\nELITE DISTILLED CONCEPT TO EXPLORE FROM SCRATCH:\n"
                f"{self._distilled_concept}\n"
            )
        return f"""SYSTEM: You are MutaLambda Tier 1 Laboratory.
MODE: EXPLORATORY_MUTATION
OBJECTIVE: Generate a novel Python module while preserving the public API when known.
{concept}
PARENT SCORE: {parent.score:.4f}
SOURCE MODULE:
{parent.code}
RULES:
- Prefer a new algorithmic idea over a cosmetic edit.
- It is acceptable to be inefficient; Tier 1 protects exploration.
- Return exactly one complete Python module.
- Return raw Python code only, no Markdown fences, no explanations.
"""

    def _crossover(
        self,
        parent_a: Individual,
        parent_b: Individual,
        llm_fn: Callable[[str], str],
    ) -> str:
        if self.rng.random() < self.config.tier1_llm_crossover_prob:
            generated = self.core_engine.crossover_with_llm(
                parent_a.code,
                parent_b.code,
                llm_fn,
            )
            if generated is not None:
                return generated
        return self._ast_crossover(parent_a.code, parent_b.code)

    def _ast_crossover(self, parent_a: str, parent_b: str) -> str:
        try:
            tree_a = ast.parse(parent_a)
            tree_b = ast.parse(parent_b)
            funcs_a = {
                node.name: node
                for node in ast.walk(tree_a)
                if isinstance(node, ast.FunctionDef)
            }
            funcs_b = {
                node.name: node
                for node in ast.walk(tree_b)
                if isinstance(node, ast.FunctionDef)
            }
            common = set(funcs_a) & set(funcs_b)
            if not common:
                return parent_a
            for node in ast.walk(tree_a):
                if isinstance(node, ast.FunctionDef) and node.name in common:
                    if self.rng.random() < 0.5:
                        replacement = copy.deepcopy(funcs_b[node.name])
                        node.body = replacement.body
                        node.args = replacement.args
            ast.fix_missing_locations(tree_a)
            result = ast.unparse(tree_a)
            ast.parse(result)
            return result
        except Exception:
            return ASTMutator.apply_random_mutation(parent_a)

    def _process_migrations(
        self,
        evaluated: List[Individual],
    ) -> tuple[List[Individual], List[Individual], List[Individual], Dict[str, int]]:
        next_tier1: List[Individual] = []
        next_tier2: List[Individual] = []
        next_tier3: List[Individual] = []
        demoted_ids = set()
        had_existing_elite = bool(self.tier3)
        stats = {"promoted": 0, "demoted": 0}

        for ind in evaluated:
            if ind.id in demoted_ids:
                next_tier2.append(ind)
                continue
            if not self._is_functional(ind):
                next_tier1.append(ind)
                continue

            if self._should_enter_elite(ind, next_tier3):
                next_tier3.append(ind)
                stats["promoted"] += 1
                existing_elites = [
                    elite for elite in self.tier3
                    if elite.id != ind.id
                ]
                if had_existing_elite:
                    demoted = self._remove_weakest(existing_elites)
                    if demoted is not None:
                        demoted_ids.add(demoted.id)
                        next_tier2.append(demoted)
                        stats["demoted"] += 1
            else:
                next_tier2.append(ind)

        return next_tier1, next_tier2, next_tier3, stats

    def _should_enter_elite(self, ind: Individual, current_elite: List[Individual]) -> bool:
        if not current_elite and len(self.tier3) < self.config.max_tier3_size:
            return True
        if len(current_elite) < self.config.max_tier3_size:
            return True
        return self._dominates_any_elite(ind, current_elite)

    def _dominates_any_elite(self, ind: Individual, current_elite: List[Individual]) -> bool:
        if not current_elite:
            return True
        ind_fitness = ind.fitness or FitnessVector()
        return any(
            ind_fitness.dominates(elite.fitness or FitnessVector())
            for elite in current_elite
        )

    @staticmethod
    def _remove_weakest(population: List[Individual]) -> Optional[Individual]:
        if not population:
            return None
        weakest_idx = min(range(len(population)), key=lambda i: population[i].score)
        return population.pop(weakest_idx)

    @staticmethod
    def _dedupe_by_id(population: List[Individual]) -> List[Individual]:
        """Return one representative per ID, keeping the highest score."""
        best: Dict[str, Individual] = {}
        for ind in population:
            previous = best.get(ind.id)
            if previous is None or ind.score > previous.score:
                best[ind.id] = ind
        return list(best.values())

    def _truncate(self, population: List[Individual], max_size: int) -> List[Individual]:
        if len(population) <= max_size:
            return population
        try:
            from nsga2 import nsga2_select

            return nsga2_select(population, max_size)
        except Exception:
            return sorted(population, key=lambda ind: ind.score, reverse=True)[:max_size]

    def _assign_tiers(self) -> None:
        for ind in self.tier1:
            ind.tier = TIER_LABORATORY
        for ind in self.tier2:
            ind.tier = TIER_FACTORY
        for ind in self.tier3:
            ind.tier = TIER_ELITE

    def _record_lineage(
        self,
        individuals: List[Individual],
        lineage_graph,
        generation: int,
    ) -> None:
        if lineage_graph is None:
            return
        for ind in individuals:
            if not ind.record_lineage:
                continue
            parents = self._lineage_parents(ind, lineage_graph)
            try:
                lineage_graph.record(
                    ind,
                    parents,
                    generation,
                    _TIER_IDS.get(ind.tier, 0),
                    reason="hfc",
                )
            except Exception as exc:
                logger.debug("Failed to record HFC lineage for %s: %s", ind.id, exc)

    @staticmethod
    def _lineage_parents(ind: Individual, lineage_graph) -> List[Individual]:
        parents: List[Individual] = []
        for parent_id in ind.parent_ids or []:
            node = lineage_graph.nodes.get(parent_id)
            if node is None:
                parents.append(Individual(id=parent_id, code=""))
                continue
            parents.append(
                Individual(
                    id=node.id,
                    code=node.code,
                    score=node.score,
                    fitness=FitnessVector(**node.fitness) if node.fitness else None,
                    parent_ids=node.parent_ids,
                )
            )
        return parents

    def _maybe_distill(
        self,
        llm_fn: Callable[[str], str],
        generation: int,
        task: str,
    ) -> str:
        if not self.config.top_down_distillation:
            return ""
        if generation % self.config.top_down_interval != 0:
            return ""
        if not self.tier3:
            return ""

        elite = max(self.tier3, key=lambda ind: ind.score)
        task_block = f"\nTASK CONTEXT:\n{task}\n" if task else ""
        prompt = f"""SYSTEM: You are MutaLambda Tier 3 Distiller.
MODE: TOP_DOWN_DISTILLATION
OBJECTIVE: Extract one concise implementation concept from the elite code.
Do not rewrite the whole module. Do not return code. Return one short sentence
that a Tier 1 candidate can try to implement from scratch.

{task_block}
ELITE CODE:
{elite.code}
"""
        try:
            concept = llm_fn(prompt).strip()
            concept = concept.strip("`").splitlines()[0][:500]
            return concept
        except Exception as exc:
            logger.debug("HFC distillation failed: %s", exc)
            return ""

    def _is_functional(self, ind: Individual) -> bool:
        correctness = self._correctness(ind.fitness)
        return bool(ind.passed and correctness >= self.config.promotion_correctness)

    @staticmethod
    def _correctness(fitness: Optional[FitnessVector]) -> float:
        if fitness is None:
            return 0.0
        return float(getattr(fitness, "correctness", 0.0))

    def _tier_counts(self) -> Dict[str, int]:
        return {
            TIER_LABORATORY: len(self.tier1),
            TIER_FACTORY: len(self.tier2),
            TIER_ELITE: len(self.tier3),
        }

    def _populations_to_dict(self) -> Dict[str, List[Dict]]:
        return {
            TIER_LABORATORY: [self._individual_to_dict(ind) for ind in self.tier1],
            TIER_FACTORY: [self._individual_to_dict(ind) for ind in self.tier2],
            TIER_ELITE: [self._individual_to_dict(ind) for ind in self.tier3],
        }

    @staticmethod
    def _individual_to_dict(ind: Individual) -> Dict[str, object]:
        return {
            "id": ind.id,
            "code": ind.code,
            "score": ind.score,
            "parent_ids": ind.parent_ids or [],
            "tier": ind.tier,
            "passed": ind.passed,
            "record_lineage": ind.record_lineage,
        }

    @staticmethod
    def _individual_from_dict(data: Dict, default_tier: str) -> Individual:
        return Individual(
            code=data.get("code", ""),
            score=data.get("score", float("-inf")),
            id=data.get("id", ""),
            parent_ids=data.get("parent_ids", []),
            tier=data.get("tier", default_tier),
            passed=bool(data.get("passed", False)),
            record_lineage=bool(data.get("record_lineage", True)),
        )

    def _dedupe_restored_populations(self) -> None:
        """Deduplicate checkpoint-restored HFC populations by ID."""
        self.tier1 = self._dedupe_by_id(self.tier1)
        self.tier2 = self._dedupe_by_id(self.tier2)
        self.tier3 = self._dedupe_by_id(self.tier3)

    def _llm_loop_rewrite(
        self,
        code: str,
        llm_fn: Optional[Callable[[str], str]],
    ) -> str:
        if llm_fn is not None:
            prompt = f"""SYSTEM: You are MutaLambda Tier 2 micro-optimizer.
MODE: LOOP_REWRITE
OBJECTIVE: Rewrite exactly one `for` loop as an equivalent `while` loop.
Preserve public function names, parameters, imports, and behavior.
Return exactly one complete valid Python module and no explanations.

MODULE:
{code}
"""
            generated = self.core_engine.extract_valid_code(llm_fn(prompt))
            if generated is not None and generated.strip() != code.strip():
                return generated
        return self._for_to_while(code)

    @staticmethod
    def _ast_micro_mutation(code: str, _llm_fn: Optional[Callable[[str], str]]) -> str:
        return ASTMutator.apply_random_mutation(code)

    @staticmethod
    def _parsimony_prune(code: str, _llm_fn: Optional[Callable[[str], str]]) -> str:
        try:
            tree = ast.parse(code)

            class Pruner(ast.NodeTransformer):
                @staticmethod
                def _dedupe(body: List[ast.stmt]) -> List[ast.stmt]:
                    if not body:
                        return body
                    pruned = [body[0]]
                    for stmt in body[1:]:
                        if ast.dump(stmt) != ast.dump(pruned[-1]):
                            pruned.append(stmt)
                    return pruned

                def visit_If(self, node: ast.If) -> ast.AST:  # noqa: N802
                    node = self.generic_visit(node)
                    if isinstance(node.test, ast.Constant) and node.test.value is True:
                        return node.body
                    node.body = self._dedupe(node.body)
                    node.orelse = self._dedupe(node.orelse)
                    return node

            tree = Pruner().visit(tree)
            ast.fix_missing_locations(tree)
            result = ast.unparse(tree)
            ast.parse(result)
            return result
        except Exception:
            return code

    @staticmethod
    def _memory_optimization(code: str, _llm_fn: Optional[Callable[[str], str]]) -> str:
        try:
            tree = ast.parse(code)

            class MemoryOptimizer(ast.NodeTransformer):
                def visit_Call(self, node: ast.Call) -> ast.AST:  # noqa: N802
                    node = self.generic_visit(node)
                    if not node.args or not isinstance(node.args[0], ast.ListComp):
                        return node
                    if isinstance(node.func, ast.Name) and node.func.id in {
                        "sum",
                        "min",
                        "max",
                        "all",
                        "any",
                    }:
                        node.args[0] = node.args[0].elt
                    return node

            tree = MemoryOptimizer().visit(tree)
            ast.fix_missing_locations(tree)
            result = ast.unparse(tree)
            ast.parse(result)
            return result
        except Exception:
            return code

    @staticmethod
    def _loop_unrolling(code: str, _llm_fn: Optional[Callable[[str], str]]) -> str:
        try:
            tree = ast.parse(code)

            class LoopUnroller(ast.NodeTransformer):
                def visit_For(self, node: ast.For) -> ast.AST:  # noqa: N802
                    if (
                        isinstance(node.iter, ast.Call)
                        and isinstance(node.iter.func, ast.Name)
                        and node.iter.func.id == "range"
                        and len(node.iter.args) == 1
                        and isinstance(node.iter.args[0], ast.Constant)
                        and node.iter.args[0].value == 1
                    ):
                        return [self.visit(stmt) for stmt in node.body]
                    return node

            tree = LoopUnroller().visit(tree)
            ast.fix_missing_locations(tree)
            result = ast.unparse(tree)
            ast.parse(result)
            return result
        except Exception:
            return code

    @staticmethod
    def _type_hint_inference(code: str, _llm_fn: Optional[Callable[[str], str]]) -> str:
        try:
            tree = ast.parse(code)

            class TypeHintInferer(ast.NodeTransformer):
                def visit_Assign(self, node: ast.Assign) -> ast.AST:  # noqa: N802
                    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                        return node
                    annotation_name = None
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                        annotation_name = "int"
                    elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, float):
                        annotation_name = "float"
                    elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
                        annotation_name = "bool"
                    if annotation_name is not None:
                        target = node.targets[0]
                        target.annotation = ast.Name(id=annotation_name, ctx=ast.Load())
                    return node

            tree = TypeHintInferer().visit(tree)
            ast.fix_missing_locations(tree)
            result = ast.unparse(tree)
            ast.parse(result)
            return result
        except Exception:
            return code

    @staticmethod
    def _for_to_while(code: str) -> str:
        try:
            tree = ast.parse(code)

            class ForToWhile(ast.NodeTransformer):
                def visit_For(self, node: ast.For) -> ast.AST:  # noqa: N802
                    if not (
                        isinstance(node.iter, ast.Call)
                        and isinstance(node.iter.func, ast.Name)
                        and node.iter.func.id == "range"
                        and len(node.iter.args) in {1, 2}
                    ):
                        return node

                    if len(node.iter.args) == 1:
                        start = ast.Constant(value=0)
                        stop = copy.deepcopy(node.iter.args[0])
                    else:
                        start = copy.deepcopy(node.iter.args[0])
                        stop = copy.deepcopy(node.iter.args[1])

                    target = copy.deepcopy(node.target)
                    init = ast.Assign(targets=[target], value=start)
                    condition = ast.Compare(
                        left=copy.deepcopy(target),
                        ops=[ast.Lt()],
                        comparators=[stop],
                    )
                    increment = ast.AugAssign(
                        target=copy.deepcopy(target),
                        op=ast.Add(),
                        value=ast.Constant(value=1),
                    )
                    while_node = ast.While(
                        test=condition,
                        body=node.body + [increment],
                        orelse=node.orelse,
                    )
                    return [init, while_node]

            tree = ForToWhile().visit(tree)
            ast.fix_missing_locations(tree)
            result = ast.unparse(tree)
            ast.parse(result)
            return result
        except Exception:
            return code
