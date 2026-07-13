"""
MutaLambda Agent — slim orchestrator after module extraction.

The large implementation has been split into focused modules:
- [`llm_backend.py`](llm_backend.py:1) for LLM adapters
- [`models.py`](models.py:1) for core dataclasses and LineageGraph
- [`evolution_engine.py`](evolution_engine.py:1) for AST mutation and prompt contracts
- [`island.py`](island.py:1) for Island evolution
- [`migration.py`](migration.py:1) for MigrationBus
- [`sandbox.py`](sandbox.py:1) for hard-limited subprocess evaluation
- [`archive.py`](archive.py:1) for SolutionArchive
- [`prompt_evolver.py`](prompt_evolver.py:1) for basic prompt evolution
"""

from __future__ import annotations

import ast
import copy
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import numpy as np

from fitness_vector import FitnessVector
from hfc_tiers import HFCTierConfig, HFCLeagueEngine
from island_evolution import IslandPool, IslandDiversity, IslandSnapshot

# Keep these globals for backward-compatible tests and optional archive mocking.
try:
    import faiss
except ImportError:  # pragma: no cover - optional dependency
    faiss = None  # type: ignore[assignment]

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore[assignment,misc]

# ─── Logging global ───────────────────────────────────────────────────────────
_LOG_LEVEL = os.environ.get("MUTALAMBDA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MutaLambda")

PROJECT_NAME = "MutaLambda"

# ─── Re-exported modules/classes for backward-compatible imports ─────────────
from archive import SolutionArchive
from evolution_engine import ASTMutator, CodeRegion, CoreEvolutionEngine
from island import Island
from llm_backend import LLMBackend, _resolve_llm_backend
from migration import MigrationBus
from models import (
    ArchivedSolution,
    EvalResult,
    Individual,
    IslandConfig,
    LineageGraph,
    LineageNode,
    PromptGenome,
)
from prompt_evolver import PromptEvolver
from sandbox import SandboxEvaluator
from workflow_protocol import ProtocolTrace


@dataclass
class EvolveConfig:
    """Configuración global del agente."""

    num_islands: int = 4
    generations: int = 50
    seed_codes: List[str] = field(default_factory=list)
    topology: str = "ring"
    population_size: int = 8
    top_k: int = 3
    migration_interval: int = 10
    migrants_per_island: int = 2
    archive_solutions: bool = True
    prompt_evolution: bool = True
    checkpoint_enabled: bool = True
    checkpoint_interval: int = 10
    checkpoint_dir: str = "checkpoints"
    early_stop_patience: int = 15
    early_stop_delta: float = 0.001
    novelty_alpha: float = 0.15
    workflow_enabled: bool = True
    workflow_max_retries: int = 1
    workflow_correctness_threshold: float = 1.0
    workflow_require_score_improvement: bool = False
    workflow_enforce_security: bool = True
    workflow_trace_limit: int = 200
    convergent_boost_enabled: bool = True
    convergent_boost_threshold: float = 0.85
    convergent_boost_factor: float = 0.15
    resurrection_enabled: bool = True
    resurrection_threshold: int = 8
    resurrection_max_attempts: int = 3
    resurrection_min_score_ratio: float = 0.3
    cross_branch_crossover_enabled: bool = True
    cross_branch_crossover_prob: float = 0.05
    cross_branch_min_distance: int = 3
    use_process_pool: bool = False
    llm_backend: str = "ollama"
    llm_model: str = "llama3.2:3b"
    llm_timeout_sec: float = 60.0
    llm_temperature: float = 0.2
    prompt_pop_size: int = 6
    prompt_elite_frac: float = 0.5
    hfc_enabled: bool = False
    hfc_tier1_size: int = 100
    hfc_tier2_size: int = 50
    hfc_tier3_size: int = 10
    hfc_lambda_clones: int = 8
    hfc_top_down_distillation: bool = True
    hfc_top_down_interval: int = 5
    hfc_promotion_correctness: float = 1.0
    thc_enabled: bool = False
    thc_max_transfers_per_generation: int = 1
    thc_min_donor_score: float = 0.0
    thc_validate_in_sandbox: bool = True
    advanced_selection_enabled: bool = False
    advanced_fitness_weight: float = 1.0
    advanced_novelty_weight: float = 0.15
    advanced_entropy_weight: float = 0.20
    advanced_discovery_weight: float = 0.35
    dialectic_enabled: bool = False
    dialectic_critique_intensity: str = "medium"
    spatial_enabled: bool = False
    spatial_neighborhood: str = "moore"
    pattern_memory_enabled: bool = False

    @classmethod
    def from_yaml(cls, path: str) -> "EvolveConfig":
        """Load EvolveConfig from a validated YAML file."""
        from config_loader import load_yaml

        cfg = load_yaml(path)

        evo = cfg.get("evolution", {})
        pop = cfg.get("population", {})
        sand = cfg.get("sandbox", {})
        arch = cfg.get("archive", {})
        prompt = cfg.get("prompt_evolution", {})
        chk = cfg.get("checkpoint", {})
        log = cfg.get("logging", {})
        llm = cfg.get("llm", {})
        repro = cfg.get("reproducibility", {})
        hfc = cfg.get("hfc", {})
        thc = cfg.get("thc", {})
        advanced = cfg.get("advanced_selection", {})
        dialectic = cfg.get("dialectic", {})
        spatial = cfg.get("spatial", {})
        patterns = cfg.get("pattern_memory", {})

        config = cls(
            num_islands=evo.get("num_islands", 4),
            generations=evo.get("generations", 50),
            topology=evo.get("topology", "ring"),
            population_size=pop.get("size", 8),
            top_k=pop.get("top_k", 3),
            migration_interval=pop.get("migration_interval", 10),
            migrants_per_island=pop.get("migrants_per_island", 2),
            archive_solutions=arch.get("enabled", True),
            prompt_evolution=prompt.get("enabled", True),
            checkpoint_enabled=chk.get("enabled", True),
            checkpoint_interval=chk.get("interval", 10),
            checkpoint_dir=chk.get("dir", "checkpoints"),
            early_stop_patience=evo.get("early_stop_patience", 15),
            early_stop_delta=evo.get("early_stop_delta", 0.001),
            novelty_alpha=evo.get("novelty_alpha", 0.15),
            workflow_enabled=cfg.get("workflow", {}).get("enabled", True),
            workflow_max_retries=cfg.get("workflow", {}).get("max_retries", 1),
            workflow_correctness_threshold=cfg.get("workflow", {}).get("correctness_threshold", 1.0),
            workflow_require_score_improvement=cfg.get("workflow", {}).get("require_score_improvement", False),
            workflow_enforce_security=cfg.get("workflow", {}).get("enforce_security", True),
            workflow_trace_limit=cfg.get("workflow", {}).get("trace_limit", 200),
            convergent_boost_enabled=evo.get("convergent_boost", {}).get("enabled", True),
            convergent_boost_threshold=evo.get("convergent_boost", {}).get("threshold", 0.85),
            convergent_boost_factor=evo.get("convergent_boost", {}).get("factor", 0.15),
            resurrection_enabled=evo.get("resurrection", {}).get("enabled", True),
            resurrection_threshold=evo.get("resurrection", {}).get("threshold", 8),
            resurrection_max_attempts=evo.get("resurrection", {}).get("max_attempts", 3),
            resurrection_min_score_ratio=evo.get("resurrection", {}).get("min_score_ratio", 0.3),
            cross_branch_crossover_enabled=evo.get("cross_branch_crossover", {}).get("enabled", True),
            cross_branch_crossover_prob=evo.get("cross_branch_crossover", {}).get("prob", 0.05),
            cross_branch_min_distance=evo.get("cross_branch_crossover", {}).get("min_distance", 3),
            use_process_pool=evo.get("use_process_pool", False),
            llm_backend=llm.get("backend", "ollama"),
            llm_model=llm.get("model", "llama3.2:3b"),
            llm_timeout_sec=llm.get("timeout_sec", 60.0),
            llm_temperature=llm.get("temperature", 0.2),
            prompt_pop_size=prompt.get("pop_size", 6),
            prompt_elite_frac=prompt.get("elite_frac", 0.5),
            hfc_enabled=hfc.get("enabled", False),
            hfc_tier1_size=hfc.get("tier1_size", 100),
            hfc_tier2_size=hfc.get("tier2_size", 50),
            hfc_tier3_size=hfc.get("tier3_size", 10),
            hfc_lambda_clones=hfc.get("lambda_clones", 8),
            hfc_top_down_distillation=hfc.get("top_down_distillation", True),
            hfc_top_down_interval=hfc.get("top_down_interval", 5),
            hfc_promotion_correctness=hfc.get("promotion_correctness", 1.0),
            thc_enabled=thc.get("enabled", False),
            thc_max_transfers_per_generation=thc.get("max_transfers_per_generation", 1),
            thc_min_donor_score=thc.get("min_donor_score", 0.0),
            thc_validate_in_sandbox=thc.get("validate_in_sandbox", True),
            advanced_selection_enabled=advanced.get("enabled", False),
            advanced_fitness_weight=advanced.get("fitness_weight", 1.0),
            advanced_novelty_weight=advanced.get("novelty_weight", 0.15),
            advanced_entropy_weight=advanced.get("entropy_weight", 0.20),
            advanced_discovery_weight=advanced.get("discovery_weight", 0.35),
            dialectic_enabled=dialectic.get("enabled", False),
            dialectic_critique_intensity=dialectic.get("critique_intensity", "medium"),
            spatial_enabled=spatial.get("enabled", False),
            spatial_neighborhood=spatial.get("neighborhood", "moore"),
            pattern_memory_enabled=patterns.get("enabled", False),
        )

        config.sandbox_timeout = sand.get("timeout_sec", 10.0)
        config.sandbox_workers = sand.get("max_workers", 4)

        log_level = log.get("level", "INFO")
        logging.getLogger("MutaLambda").setLevel(log_level)

        seed = repro.get("seed")
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        return config


class EarlyStopMonitor:
    """Detector de convergencia por ventana de mejora relativa."""

    def __init__(self, patience: int = 15, delta: float = 0.001):
        self.patience = patience
        self.delta = delta
        self._best: float = float("-inf")
        self._no_improve: int = 0

    def update(self, score: float) -> bool:
        """Retorna True si se detecta convergencia."""
        if self._best == float("-inf"):
            self._best = score
            self._no_improve = 0
            return False

        improvement = score - self._best
        rel_improvement = improvement / (abs(self._best) + 1e-9)

        if rel_improvement > self.delta:
            self._best = score
            self._no_improve = 0
        else:
            self._no_improve += 1

        return self._no_improve >= self.patience

    @property
    def stagnant_generations(self) -> int:
        return self._no_improve


class MutaLambdaAgent:
    """Orquestador principal del ciclo evolutivo MutaLambda."""

    def __init__(
        self,
        config: EvolveConfig,
        test_cases: Optional[List[Dict]] = None,
        llm_fn: Optional[Callable[[str], str]] = None,
        timeout_sec: float = 10.0,
        task: str = "",
    ):
        self.config = config
        self.task = task
        self.run_id = uuid4().hex[:12]
        self._protocol_traces: List[Dict[str, Any]] = []
        self._protocol_metrics: Dict[str, Any] = {
            "promoted": 0,
            "rejected": 0,
            "retried": 0,
            "gate_failures": {},
        }
        self.llm_fn = (
            _resolve_llm_backend(
                backend=config.llm_backend,
                model=config.llm_model,
                timeout_sec=config.llm_timeout_sec,
                temperature=config.llm_temperature,
            )
            if llm_fn is None
            else llm_fn
        )
        self._base_llm_fn = self.llm_fn
        self._active_prompt_genome: Optional[PromptGenome] = None

        self.evaluator = SandboxEvaluator(
            test_cases=test_cases or [],
            timeout_sec=timeout_sec,
        )
        topology = "spatial_grid" if config.spatial_enabled else config.topology
        self.migration_bus = MigrationBus(topology=topology)
        if config.spatial_enabled:
            from muta_ext.spatial_topology import SpatialConfig, SpatialTopology

            self.migration_bus.spatial_topology = SpatialTopology(
                SpatialConfig(enabled=True, neighborhood=config.spatial_neighborhood)
            )

        island_cfg = IslandConfig(
            migration_interval=config.migration_interval,
            migrants_per_island=config.migrants_per_island,
            topology=config.topology,
            population_size=config.population_size,
            top_k=config.top_k,
        )
        self.islands: List[Island] = [
            Island(
                island_id=i,
                config=island_cfg,
                llm_fn=self._island_llm_fn,
                evaluator=self.evaluator,
                migration_bus=self.migration_bus,
            )
            for i in range(config.num_islands)
        ]
        for island in self.islands:
            island.configure_protocol(
                run_id=self.run_id,
                trace_sink=self._record_protocol_trace,
                agent=self,
                config=config,
            )
        self._hfc: Optional[HFCLeagueEngine] = None
        if config.hfc_enabled:
            self._hfc = HFCLeagueEngine(
                HFCTierConfig(
                    max_tier1_size=config.hfc_tier1_size,
                    max_tier2_size=config.hfc_tier2_size,
                    max_tier3_size=config.hfc_tier3_size,
                    lambda_clones=config.hfc_lambda_clones,
                    promotion_correctness=config.hfc_promotion_correctness,
                    top_down_distillation=config.hfc_top_down_distillation,
                    top_down_interval=config.hfc_top_down_interval,
                ),
                rng=random.Random(),
            )
            if config.seed_codes:
                self._hfc.seed(config.seed_codes)

        if config.seed_codes:
            self._seed_islands_differentiated(config.seed_codes)

        self.archive: Optional[SolutionArchive] = None
        self._embed_cache: Dict = {}
        if config.archive_solutions:
            try:
                self.archive = SolutionArchive()
            except ImportError:
                logger.warning("FAISS/sentence-transformers not available; archive disabled.")

        self._advanced_selection = None
        if config.advanced_selection_enabled:
            from muta_ext.advanced_selection import (
                AdvancedSelectionConfig,
                AdvancedSelectionEngine,
            )

            self._advanced_selection = AdvancedSelectionEngine(
                AdvancedSelectionConfig(
                    enabled=True,
                    fitness_weight=config.advanced_fitness_weight,
                    novelty_weight=config.advanced_novelty_weight,
                    entropy_weight=config.advanced_entropy_weight,
                    discovery_weight=config.advanced_discovery_weight,
                ),
                archive=self.archive,
                lineage_graph=None,
            )
            self.migration_bus.advanced_selection = self._advanced_selection

        self._thc_engine = None
        if config.thc_enabled:
            from muta_ext.thc_engine import HorizontalTransferEngine, THCConfig

            self._thc_engine = HorizontalTransferEngine(
                THCConfig(
                    enabled=True,
                    max_transfers_per_generation=config.thc_max_transfers_per_generation,
                    min_donor_score=config.thc_min_donor_score,
                    validate_in_sandbox=config.thc_validate_in_sandbox,
                ),
                rng=random.Random(),
            )
            self.migration_bus.thc_engine = self._thc_engine

        self._dialectic_engine = None
        if config.dialectic_enabled:
            from muta_ext.dialectic_engine import DialecticConfig, DialecticEngine

            self._dialectic_engine = DialecticEngine(
                DialecticConfig(
                    enabled=True,
                    critique_intensity=config.dialectic_critique_intensity,
                )
            )
            self.migration_bus.dialectic_engine = self._dialectic_engine

        self._pattern_memory = None
        if config.pattern_memory_enabled:
            from muta_ext.pattern_memory import PatternMemory

            self._pattern_memory = PatternMemory()
            self.migration_bus.pattern_memory = self._pattern_memory

        self.prompt_evolver: Optional[Any] = None
        if config.prompt_evolution:
            from prompt_evolution import RichPromptEvolver

            self.prompt_evolver = RichPromptEvolver(
                self._base_llm_fn,
                self.evaluator,
                archive=self.archive,
                pop_size=config.prompt_pop_size,
                elite_frac=config.prompt_elite_frac,
            )
            initial_prompt = self.prompt_evolver.get_best_prompt()
            if initial_prompt is not None:
                self._active_prompt_genome = copy.deepcopy(initial_prompt)

        self._start_time: float = 0.0
        self._generation_times: List[float] = []
        self._global_best_history: List[float] = []
        self._island_pool = IslandPool()
        self._early_stop = EarlyStopMonitor(
            patience=config.early_stop_patience,
            delta=config.early_stop_delta,
        )
        self._lineage = LineageGraph()
        self.migration_bus.lineage_graph = self._lineage
        if self._advanced_selection is not None:
            self._advanced_selection.lineage_graph = self._lineage

    def _island_llm_fn(self, prompt: str) -> str:
        """LLM callable used by islands; steered by best evolved prompt if available."""
        if self._active_prompt_genome is None:
            return self._base_llm_fn(prompt)
        steering_task = self.task or "Improve Python code for correctness and efficiency."
        evolved_prompt = self._active_prompt_genome.render(steering_task, prompt)
        return self._base_llm_fn(evolved_prompt)

    def _record_protocol_trace(self, trace: ProtocolTrace) -> None:
        trace_dict = trace.to_dict()
        self._protocol_traces.append(trace_dict)
        if len(self._protocol_traces) > self.config.workflow_trace_limit:
            self._protocol_traces = self._protocol_traces[-self.config.workflow_trace_limit:]

        decision = trace_dict.get("decision", "pending")
        if decision == "promote":
            self._protocol_metrics["promoted"] += 1
        elif decision == "reject":
            self._protocol_metrics["rejected"] += 1

        for stage in trace_dict.get("stages", []):
            if stage["status"] == "RETRYABLE_FAIL":
                self._protocol_metrics["retried"] += 1
                failures = self._protocol_metrics["gate_failures"]
                failures[stage["name"]] = failures.get(stage["name"], 0) + 1

        logger.debug(
            "[run=%s] protocol candidate=%s decision=%s stages=%s",
            self.run_id,
            trace_dict.get("subject_id"),
            decision,
            " -> ".join(
                f"{stage['name']}:{stage['status']}"
                for stage in trace_dict.get("stages", [])
            ),
        )

    def _seed_islands_differentiated(self, seed_codes: List[str]) -> None:
        for i, island in enumerate(self.islands):
            if i == 0:
                island.seed_population(seed_codes)
            else:
                mutated = []
                for code in seed_codes:
                    variant = code
                    for _ in range(i):
                        variant = ASTMutator.apply_random_mutation(variant)
                    mutated.append(variant)
                island.seed_population(mutated)
        logger.info(
            "Seeded %d islands with differentiated populations "
            "(island 0 = original, islands 1..%d = mutated variants)",
            len(self.islands), len(self.islands) - 1,
        )

    def _process_hitl_hints(self) -> None:
        hints = getattr(self, '_pending_hints', [])
        if not hints:
            return
        for code in hints:
            island = random.choice(self.islands)
            new_ind = Individual(code=code, score=0.0)
            island.population.append(new_ind)
            logger.info("HITL: hint injected into island %d", island.id)
        self._pending_hints = []

    def inject_hint(self, code: str) -> None:
        pending = getattr(self, '_pending_hints', [])
        pending.append(code)
        self._pending_hints = pending

    def _compute_cross_island_diversity(self) -> float:
        if self._hfc is not None:
            return self._hfc.diversity
        return self._island_pool.get_cross_island_diversity(self.islands)

    def _get_global_best(self) -> Optional[Individual]:
        if self._hfc is not None:
            best = self._hfc.best_individual
            return copy.deepcopy(best) if best else None
        return self.migration_bus.get_global_best()

    def _code_similarity(self, code_a: str, code_b: str) -> float:
        if code_a == code_b:
            return 1.0
        if not code_a or not code_b:
            return 0.0

        if self.archive is not None:
            try:
                code_key = (code_a, code_b)
                if code_key in self._embed_cache:
                    return self._embed_cache[code_key]
                emb_a = self.archive._encode_normalized([code_a])[0]
                emb_b = self.archive._encode_normalized([code_b])[0]
                score = max(0.0, float(np.dot(emb_a, emb_b)))
                self._embed_cache[code_key] = score
                return score
            except Exception as e:
                logger.warning("Embed cache similarity failed: %s", e)

        tokens_a = set(code_a.split())
        tokens_b = set(code_b.split())
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

    def _apply_convergent_boost(self) -> Dict[str, int]:
        if not self.config.convergent_boost_enabled:
            return {"boosted": 0, "pairs": 0}

        active = [(i, isl) for i, isl in enumerate(self.islands) if isl.local_best is not None]
        if len(active) < 2:
            return {"boosted": 0, "pairs": 0}

        threshold = self.config.convergent_boost_threshold
        factor = self.config.convergent_boost_factor

        convergent_pairs: List[Tuple[int, int, float]] = []
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                idx_a, isl_a = active[i]
                idx_b, isl_b = active[j]
                sim = self._code_similarity(isl_a.local_best.code, isl_b.local_best.code)
                if sim > threshold:
                    convergent_pairs.append((idx_a, idx_b, sim))

        if not convergent_pairs:
            return {"boosted": 0, "pairs": 0}

        island_boosts: Dict[int, float] = {}
        for ia, ib, sim in convergent_pairs:
            boost = factor * sim
            island_boosts[ia] = island_boosts.get(ia, 0.0) + boost
            island_boosts[ib] = island_boosts.get(ib, 0.0) + boost

        boosted_count = 0
        for isl_idx, total_boost in island_boosts.items():
            island = self.islands[isl_idx]
            for ind in island.population:
                ind.score *= (1.0 + total_boost)
                boosted_count += 1
            island.recompute_local_best()

        logger.debug(
            "ConvergentBoost: %d inds boosted (%.0f%% x%d pairs, threshold=%.2f)",
            boosted_count, factor * 100, len(convergent_pairs), threshold,
        )
        return {"boosted": boosted_count, "pairs": len(convergent_pairs)}

    def _find_stagnant_island(self) -> Optional[Island]:
        active = [isl for isl in self.islands if isl.local_best is not None]
        if not active:
            return None
        return min(active, key=lambda isl: isl.local_best.score)

    def _resurrect_branch(self, node: LineageNode) -> Individual:
        self._lineage._resurrection_count += 1
        node.resurrected = True

        base_code: Optional[str] = None
        should_mutate = False
        if getattr(node, "code", ""):
            base_code = node.code

        if base_code is None:
            try:
                from muta_ext.lineage.compression import LineageCompressor

                compressor = getattr(self, "_lineage_compressor", None)
                if compressor is None:
                    compressor = LineageCompressor(self._lineage)
                    setattr(self, "_lineage_compressor", compressor)

                reconstructed = compressor.decompress_node(node.id)
                if reconstructed:
                    base_code = reconstructed
            except Exception:
                base_code = None

        if base_code is None:
            stagnant = self._find_stagnant_island()
            base_code = (
                stagnant.local_best.code
                if stagnant and stagnant.local_best
                else "def solution():\n    pass"
            )
            should_mutate = True

        code = base_code
        if should_mutate:
            for _ in range(3):
                mutated = ASTMutator.apply_random_mutation(code)
                if mutated.strip() != code.strip():
                    code = mutated
                    break

        resurrected = Individual(
            code=code,
            parent_ids=[node.id],
        )
        logger.info(
            "♜ Branch resurrected: node=%s gen=%d score=%.4f",
            node.id[:8], node.generation, node.score,
        )
        return resurrected

    def _cross_branch_crossover(self, island: Island) -> Optional[Individual]:
        if not self.config.cross_branch_crossover_enabled:
            return None
        if len(self._lineage.nodes) < 10:
            return None
        if random.random() > self.config.cross_branch_crossover_prob:
            return None

        min_dist = self.config.cross_branch_min_distance
        correctness_nodes = []
        throughput_nodes = []
        for nid, node in self._lineage.nodes.items():
            if not node.fitness:
                continue
            corr = node.fitness.get("correctness", 0.0)
            tp = node.fitness.get("throughput", 0.0)
            if corr > 0.5:
                correctness_nodes.append(node)
            if tp > 0.5:
                throughput_nodes.append(node)

        if len(correctness_nodes) < 1 or len(throughput_nodes) < 1:
            return None

        for _ in range(10):
            node_a = random.choice(correctness_nodes)
            node_b = random.choice(throughput_nodes)
            if node_a.id == node_b.id:
                continue
            dist = self._lineage.get_genealogical_distance(node_a.id, node_b.id)
            if dist is not None and dist >= min_dist:
                candidates_a = [isl for isl in self.islands
                                if isl.id != island.id and isl.local_best]
                if not candidates_a:
                    return None
                parent_a = random.choice(candidates_a).local_best
                parent_b = island.local_best or random.choice(island.population)

                child_code = island._crossover(parent_a.code, parent_b.code)
                child = Individual(
                    code=child_code,
                    parent_ids=[parent_a.id, parent_b.id],
                )
                logger.debug(
                    "Cross-branch crossover: nodes %s × %s (dist=%d)",
                    node_a.id[:8], node_b.id[:8], dist,
                )
                return child

        return None

    def _score_with_novelty(self, individual: Individual) -> float:
        if self.archive is None or self.config.novelty_alpha == 0.0:
            return individual.score
        novelty = self.archive.novelty_score(individual.code, k=10)
        alpha = self.config.novelty_alpha
        return (1.0 - alpha) * individual.score + alpha * novelty * 100.0

    def run(self, task: str = "") -> Individual:
        if not task:
            task = self.task
        elif task != self.task:
            self.task = task
        self._start_time = time.perf_counter()
        logger.info(
            "MutaLambda starting: run=%s %d islands × %d generations",
            self.run_id,
            self.config.num_islands,
            self.config.generations,
        )

        global_best: Optional[Individual] = None

        for gen in range(self.config.generations):
            gen_start = time.perf_counter()

            if self._hfc is not None:
                hfc_snapshot = self._hfc.step(
                    self.llm_fn,
                    self.evaluator,
                    gen,
                    lineage_graph=self._lineage,
                    task=task,
                )
                island_snapshots = []
                logger.debug(
                    "HFC gen %d — tiers=%s | best=%.4f | diversity=%.3f",
                    gen + 1,
                    hfc_snapshot.tier_counts,
                    hfc_snapshot.best_score,
                    hfc_snapshot.diversity,
                )
            else:
                island_snapshots = self._island_pool.run_generation(
                    self.islands, gen
                )

            self._process_hitl_hints()

            cross_diversity = self._compute_cross_island_diversity()
            spatial_topology = getattr(self.migration_bus, "spatial_topology", None)
            if spatial_topology is not None:
                spatial_topology.update_metrics(self.migration_bus.islands)
            if gen % 5 == 0 and self._hfc is None:
                diversities = [s.diversity for s in island_snapshots]
                logger.debug(
                    "Gen %d diversity — intra: [%s] | cross: %.3f",
                    gen + 1,
                    ", ".join(f"{d:.3f}" for d in diversities),
                    cross_diversity,
                )

            if (
                self._hfc is None
                and gen % max(1, self.config.migration_interval) == 0
            ):
                boost_stats = self._apply_convergent_boost()
                if boost_stats.get("boosted", 0) > 0:
                    logger.info(
                        "Gen %d — convergent boost: %d inds × %d pairs",
                        gen + 1, boost_stats["boosted"], boost_stats.get("pairs", 0),
                    )

            if (
                os.getenv("MUTALAMBDA_ENABLE_LINEAGE_COMPRESSION", "0") == "1"
                and len(self._lineage.nodes) > 1000
                and global_best is not None
            ):
                try:
                    from muta_ext.lineage.compression import LineageCompressor

                    compressor = getattr(self, "_lineage_compressor", None)
                    if compressor is None:
                        compressor = LineageCompressor(self._lineage)
                        setattr(self, "_lineage_compressor", compressor)

                    active_branch_ids = set(self._lineage.get_ancestors(global_best.id))
                    active_branch_ids.add(global_best.id)
                    compressor.compress_inactive(active_branch_ids)
                except Exception as e:
                    logger.warning("Lineage compression failed: %s", e)

            if (self.config.resurrection_enabled
                    and self._early_stop.stagnant_generations
                    >= self.config.resurrection_threshold
                    and self._lineage._resurrection_count
                    < self.config.resurrection_max_attempts
                    and global_best is not None):
                threshold = (self.config.resurrection_min_score_ratio
                             * global_best.score)
                candidates = self._lineage.find_abandoned_branches(
                    global_best.id, threshold,
                )
                if candidates:
                    resurrected = self._resurrect_branch(candidates[0])
                    stagnant_island = self._find_stagnant_island()
                    if stagnant_island:
                        stagnant_island.population[0] = resurrected
                        logger.info(
                            "Gen %d — ♜ resurrected branch → island %d",
                            gen + 1, stagnant_island.id,
                        )

            if gen % 5 == 0:
                try:
                    from nsga2 import get_nsga2_stats
                    all_inds = [
                        ind for isl in self.islands
                        for ind in isl.population
                    ]
                    nsga_stats = get_nsga2_stats(all_inds)
                    logger.debug(
                        "NSGA-II fronts=%d pareto=%d crowding=%.3f",
                        nsga_stats["num_fronts"],
                        nsga_stats["pareto_frontier_size"],
                        nsga_stats["mean_crowding"],
                    )
                except ImportError:
                    pass

            if self.prompt_evolver and task:
                best_so_far = self._get_global_best()
                base_code = best_so_far.code if best_so_far else ""
                self.prompt_evolver.step(task, base_code)
                best_prompt = self.prompt_evolver.get_best_prompt()
                if best_prompt is not None:
                    self._active_prompt_genome = copy.deepcopy(best_prompt)

            current_best = self._get_global_best()
            if current_best:
                combined = self._score_with_novelty(current_best)
                if global_best is None or combined > self._score_with_novelty(global_best):
                    global_best = copy.deepcopy(current_best)

            if self.archive and global_best:
                self.archive.add(
                    global_best.code,
                    {"score": global_best.score, "generation": float(gen)},
                )

            gen_elapsed = time.perf_counter() - gen_start
            self._generation_times.append(gen_elapsed)
            current_score = global_best.score if global_best else float("-inf")
            current_combined_score = (
                self._score_with_novelty(global_best)
                if global_best is not None
                else float("-inf")
            )
            self._global_best_history.append(current_score)

            if gen % 5 == 0 or gen == self.config.generations - 1:
                avg_time = (
                    sum(self._generation_times[-5:]) /
                    min(5, len(self._generation_times[-5:]))
                )
                logger.info(
                    "Gen %d/%d | best=%.4f | avg_time=%.2fs | "
                    "archive=%d | stagnant=%d | protocol(promote=%d reject=%d)",
                    gen + 1, self.config.generations, current_score,
                    avg_time,
                    self.archive.size if self.archive else 0,
                    self._early_stop.stagnant_generations,
                    self._protocol_metrics["promoted"],
                    self._protocol_metrics["rejected"],
                )

            if (
                self.config.checkpoint_enabled
                and
                self.config.checkpoint_interval > 0
                and (gen + 1) % self.config.checkpoint_interval == 0
            ):
                self._save_checkpoint(gen + 1)

            if self._early_stop.update(current_combined_score):
                logger.info(
                    "Early stop en gen %d: sin mejora ≥%.4f en %d generaciones.",
                    gen + 1, self.config.early_stop_delta,
                    self.config.early_stop_patience,
                )
                break

        total_time = time.perf_counter() - self._start_time
        logger.info(
            "Evolution complete: run=%s in %.1fs. Best score: %.4f",
            self.run_id,
            total_time,
            global_best.score if global_best else float("-inf"),
        )

        self.shutdown()

        if global_best is None:
            raise RuntimeError("Evolution produced no valid individuals.")
        return global_best

    def _save_checkpoint(self, generation: int) -> None:
        try:
            from checkpoint_manager import save_full_checkpoint

            raw_config = getattr(self, '_raw_config', None)
            save_full_checkpoint(
                self, generation, self.config,
                raw_config=raw_config,
            )
        except ImportError:
            os.makedirs(self.config.checkpoint_dir, exist_ok=True)
            path = os.path.join(
                self.config.checkpoint_dir, f"checkpoint_gen{generation:04d}.json"
            )
            best = self._get_global_best()
            data = {
                "generation": generation,
                "best_score": best.score if best else None,
                "best_code": best.code if best else None,
                "island_generations": [isl.generation for isl in self.islands],
                "avg_gen_time": (
                    sum(self._generation_times) / len(self._generation_times)
                    if self._generation_times else 0
                ),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug("Checkpoint saved: %s", path)

    def shutdown(self) -> None:
        self.evaluator.shutdown()
        logger.info("MutaLambda agent shut down cleanly.")

    def get_metrics(self) -> Dict[str, Any]:
        advanced_metrics = {}
        if self._advanced_selection is not None:
            advanced_metrics = self._advanced_selection.metrics.__dict__
        thc_metrics = {}
        if self._thc_engine is not None:
            thc_metrics = self._thc_engine.metrics.__dict__
        dialectic_metrics = {}
        if self._dialectic_engine is not None:
            dialectic_metrics = self._dialectic_engine.metrics.__dict__
        spatial = getattr(self.migration_bus, "spatial_topology", None)
        spatial_metrics = spatial.metrics.__dict__ if spatial is not None else {}
        pattern_count = (
            len(self._pattern_memory.records)
            if self._pattern_memory is not None else 0
        )
        return {
            "run_id": self.run_id,
            "total_generations": len(self._generation_times),
            "total_time_sec": round(sum(self._generation_times), 4),
            "avg_generation_time_sec": round(
                sum(self._generation_times) / len(self._generation_times)
                if self._generation_times else 0, 4
            ),
            "best_score_history": self._global_best_history,
            "archive_size": self.archive.size if self.archive else 0,
            "num_islands": len(self.islands),
            "hfc_enabled": self._hfc is not None,
            "hfc_stats": self._hfc.stats() if self._hfc is not None else {},
            "stagnant_generations": self._early_stop.stagnant_generations,
            "novelty_alpha": self.config.novelty_alpha,
            "cross_island_diversity": self._compute_cross_island_diversity(),
            "parallel_generations": self._island_pool.generation_count,
            "advanced_selection": advanced_metrics,
            "thc": thc_metrics,
            "dialectic": dialectic_metrics,
            "spatial": spatial_metrics,
            "pattern_memory_size": pattern_count,
            "protocol": {
                **self._protocol_metrics,
                "enabled": self.config.workflow_enabled,
                "recent_traces": list(self._protocol_traces),
            },
        }


def run_full_test_suite() -> bool:
    """Suite integrada mínima para el CLI --test."""
    import traceback

    passed: List[str] = []
    failed: List[Tuple[str, str]] = []

    def test(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            passed.append(name)
            print(f"  [PASS] {name}")
        except Exception as exc:
            tb = traceback.format_exc().splitlines()[-1]
            failed.append((name, tb))
            print(f"  [FAIL] {name} — {tb}")

    def t_ast_mutations_valid():
        code = "def f(x):\n    total = 0\n    for i in range(x):\n        total += i\n    return total\n"
        for _ in range(200):
            ast.parse(ASTMutator.apply_random_mutation(code))

    def t_llm_mutation_accepts_valid_code():
        engine = CoreEvolutionEngine()
        result = engine.mutate_with_llm(
            code="def f(x):\n    return x + 1\n",
            score=1.0,
            error_info="",
            llm_fn=lambda _prompt: "def f(x):\n    return x * 2\n",
        )
        ast.parse(result)

    def t_diversity_not_placeholder():
        from island_evolution import IslandPool

        pool = IslandPool()
        fake_islands = []
        for idx in range(2):
            fake = type("FakeIsland", (), {"population": []})()
            fake.population = [Individual(code=f"def f{idx}(): return {idx}")]
            fake_islands.append(fake)
        # Two islands with different code should have diversity > 0.0
        # (old placeholder returned 1.0, new implementation returns 1.0 - jaccard)
        diversity = pool.get_cross_island_diversity(fake_islands)
        assert 0.0 < diversity < 1.0, f"Expected diversity in (0,1), got {diversity}"

    print("\n" + "=" * 60)
    print("SUITE DE TESTS — MutaLambda Agent (modular)")
    print("=" * 60)
    test("ast_mutations_valid", t_ast_mutations_valid)
    test("llm_mutation_accepts_valid_code", t_llm_mutation_accepts_valid_code)
    test("cross_island_diversity_not_placeholder", t_diversity_not_placeholder)

    print("\n" + "-" * 60)
    total = len(passed) + len(failed)
    print(f"Resultado: {len(passed)}/{total} tests pasaron")
    if failed:
        print("\nFallidos:")
        for name, err in failed:
            print(f"  ✗ {name}: {err}")
    print("=" * 60 + "\n")
    return len(failed) == 0


def _demo_llm_fn(prompt: str) -> str:
    """LLM simulado para demostración: aplica micro-mutaciones al código."""
    lines = prompt.split("\n")
    code_lines = [
        l for l in lines
        if l.strip() and not l.startswith(("You are", "Task:", "Improve", "Return", "Instructions:"))
    ]
    code = "\n".join(code_lines).strip()
    if not code:
        return "def solution():\n    return 42"
    mutated = ASTMutator.apply_random_mutation(code)
    return mutated


def main() -> None:
    """Demo/CLI: ejecuta MutaLambda con un LLM simulado o corre los tests."""
    import argparse

    parser = argparse.ArgumentParser(description="MutaLambda Agent modular")
    parser.add_argument("--islands", type=int, default=3)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--pop-size", type=int, default=6)
    parser.add_argument("--topology", default="ring",
                        choices=["ring", "fully_connected", "random", "mesh"])
    parser.add_argument("--novelty-alpha", type=float, default=0.15,
                        help="Peso del bonus de novedad en el score (0.0–1.0)")
    parser.add_argument("--early-stop-patience", type=int, default=15)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--test", action="store_true",
                        help="Ejecutar suite de tests integrada y salir")
    parser.add_argument("--config", type=str, default=None,
                        help="Ruta a archivo YAML de configuración")
    parser.add_argument("--resume", type=str, default=None,
                        help="Ruta a checkpoint para reanudar evolución")
    parser.add_argument("--dashboard", action="store_true",
                        help="Activar dashboard de consola HITL")
    parser.add_argument("--hint", type=str, default=None,
                        help="Inyectar código como hint experto en una isla")
    parser.add_argument("--hfc-enabled", action="store_true",
                        help="Activar evolución por ligas HFC")
    parser.add_argument("--hfc-lambda-clones", type=int, default=8,
                        help="Clones bacterianos por individuo Tier2")
    args = parser.parse_args()

    logging.getLogger("MutaLambda").setLevel(args.log_level)

    if args.test:
        ok = run_full_test_suite()
        sys.exit(0 if ok else 1)

    if args.config:
        config = EvolveConfig.from_yaml(args.config)
        from config_loader import load_yaml
        agent_kwargs = {"config": config}
    else:
        seed = (
            "def compute_sum(n):\n"
            "    total = 0\n"
            "    for i in range(n):\n"
            "        total += i\n"
            "    return total\n"
        )

        config = EvolveConfig(
            num_islands=args.islands,
            generations=args.generations,
            seed_codes=[seed],
            topology=args.topology,
            population_size=args.pop_size,
            top_k=max(2, args.pop_size // 3),
            archive_solutions=False,
            prompt_evolution=False,
            novelty_alpha=args.novelty_alpha,
            early_stop_patience=args.early_stop_patience,
            hfc_enabled=args.hfc_enabled,
            hfc_lambda_clones=args.hfc_lambda_clones,
        )
        config.sandbox_timeout = 5.0
        config.sandbox_workers = 4
        agent_kwargs = {"config": config}

    if args.resume:
        from checkpoint_manager import resume_agent

        agent = resume_agent(
            args.resume, config,
            test_cases=[],
            llm_fn=_demo_llm_fn,
        )
        best = agent.run(task="Continue evolution from checkpoint")
    else:
        agent = MutaLambdaAgent(
            config=config,
            llm_fn=_demo_llm_fn,
            test_cases=[],
            timeout_sec=getattr(config, 'sandbox_timeout', 5.0),
        )
        best = agent.run(task="Optimize a sum function for correctness and speed")

    print("\n" + "=" * 60)
    print("BEST SOLUTION FOUND:")
    print("=" * 60)
    print(best.code)
    print(f"\nScore: {best.score:.4f}")
    print("\nMetrics:", json.dumps(agent.get_metrics(), indent=2, default=str))


if __name__ == "__main__":
    main()
