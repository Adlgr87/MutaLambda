"""MutaLambda evolutionary agent — extracted to its own module (Phase 2B).

Contains :class:`MutaLambdaAgent` together with its helper methods. The class
depends on the public API re-exported by the :mod:`muta_lambda` package
(``EvolveConfig``, ``Individual``, ``Island``, ``SandboxEvaluator`` etc.) which
are imported at module load time from the package ``__init__``.

The heavy / optional dependencies (faiss, sentence-transformers, metrics
exporter, muta_ext engines, checkpoint_manager, etc.) are imported lazily
inside methods, exactly as they were in the original monolithic module, so
importing this module stays cheap and free of side effects.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import numpy as np

# Package-internal dependencies. These are defined in the package ``__init__``
# *before* it imports this module, which avoids a circular-import problem:
#   muta_lambda/__init__.py  ->  from muta_lambda.agent import MutaLambdaAgent
#   muta_lambda/agent.py     ->  from muta_lambda import <symbols above>
# works because by the time ``agent`` runs, ``__init__`` has already bound
# every name referenced below.
from muta_lambda import (
    CHECKPOINT_SAVED,
    GENERATION_COMPLETED,
    GENERATION_STARTED,
    RUN_COMPLETED,
    RUN_STARTED,
    ASTMutator,
    CommandQueue,
    EarlyStopMonitor,
    EventBus,
    EvolveConfig,
    ExtensionContext,
    ExtensionRegistry,
    HFCLeagueEngine,
    HFCTierConfig,
    Individual,
    Island,
    IslandConfig,
    IslandPool,
    LineageGraph,
    LineageNode,
    PromptGenome,
    ProtocolTrace,
    RNGSession,
    SandboxEvaluator,
    MigrationBus,
    GenerationResult,
    ProfileMode,
    SolutionArchive,
    _filter_mutant,
    _resolve_llm_backend,
    logger,
)

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
                max_retries=int(getattr(config, "llm_max_retries", 3) or 3),
                max_calls_per_generation=int(
                    getattr(config, "llm_max_calls_per_generation", 0) or 0
                ),
                max_total_calls=int(getattr(config, "llm_max_total_calls", 0) or 0),
                max_cost_usd=float(
                    getattr(config, "llm_max_cost_usd", 0.0) or 0.0
                ),
                privacy_allow_external=bool(
                    getattr(config, "privacy_allow_external_llm", True)
                ),
                replay_log_path=getattr(config, "llm_replay_log", None)
                or (
                    str(Path(config.checkpoint_dir) / "llm_replay.jsonl")
                    if getattr(config, "checkpoint_enabled", False)
                    else None
                ),
            )
            if llm_fn is None
            else llm_fn
        )
        # Keep backend instance when factory attached it.
        self._llm_backend = getattr(self.llm_fn, "__self_backend__", None)
        self._base_llm_fn = self.llm_fn
        self._active_prompt_genome: Optional[PromptGenome] = None

        # Backward-compat: some callers pass llm_fn as the second positional
        # argument (historically before test_cases was required).
        if callable(test_cases) and llm_fn is None:
            llm_fn = test_cases  # type: ignore[assignment]
            test_cases = []

        cases = list(test_cases or [])
        allow_untested = bool(getattr(config, "allow_untested", True))
        if getattr(config, "require_tests", False) and not cases and not allow_untested:
            raise ValueError(
                "No test cases configured. Use --allow-untested only for development."
            )
        self.evaluator = SandboxEvaluator(
            test_cases=cases,
            timeout_sec=timeout_sec,
            parallelism=getattr(config, "sandbox_workers", None),
            allow_untested=allow_untested,
            runner_mode=getattr(config, "runner_mode", "subprocess"),
            allow_expression_eval=getattr(config, "allow_expression_eval", False),
            enforce_ast_scan=getattr(config, "enforce_ast_scan", True),
            benchmark_warmups=int(getattr(config, "benchmark_warmups", 0) or 0),
            benchmark_samples=int(getattr(config, "benchmark_samples", 1) or 1),
            benchmark_operations_per_case=int(
                getattr(config, "benchmark_operations_per_case", 1) or 1
            ),
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

        self._metrics_server: Optional[Any] = None
        if getattr(config, "observability_enabled", True):
            try:
                from metrics_exporter import start_metrics_server  # noqa: PLC0415

                port = int(getattr(config, "observability_metrics_port", 9100) or 9100)
                self._metrics_server = start_metrics_server(port=port)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("metrics server unavailable: %s", exc)

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

        self._global_best: Optional[Individual] = None
        self._current_generation: int = 0
        self._stopped: bool = False
        self.event_bus = EventBus()
        self.commands = CommandQueue()
        self._generation_completed: int = 0
        self.extensions = ExtensionRegistry()
        seed = getattr(config, "master_seed", None)
        if seed is None:
            seed = getattr(config, "seed", None)
        self.rng_session = RNGSession(master_seed=seed)
        # Per-island / migration RNG streams (optimization FIX 2.1)
        for _i, _isl in enumerate(self.islands):
            _isl.rng = self.rng_session.island(_i)
        self.migration_bus.rng = self.rng_session.stream("migration")
        self._rng = self.rng_session.stream("agent")
        self._baseline_fitness = None
        self._operator_bandit = None
        if getattr(config, "operator_bandit_enabled", False):
            from operator_bandit import OperatorBandit
            self._operator_bandit = OperatorBandit(
                operators=["ast", "llm", "crossover", "redesign", "component"],
                strategy=getattr(config, "operator_bandit_strategy", "ucb1"),
                rng=self.rng_session.stream("bandit"),
            )
        # Register optional engines under EvolutionExtension contract (WF#20)
        from extensions import wrap_engine
        for eng, name in (
            (self._hfc, "hfc"),
            (getattr(self, "_thc_engine", None), "thc"),
            (getattr(self, "_dialectic_engine", None), "dialectic"),
            (getattr(self, "_pattern_memory", None), "pattern_memory"),
            (getattr(self, "_advanced_selection", None), "advanced_selection"),
        ):
            wrapped = wrap_engine(eng, name=name)
            if wrapped is not None:
                self.extensions.register(wrapped)

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
                        variant = _filter_mutant(variant, ProfileMode.STRICT) or variant
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
            island = self._random().choice(self.islands)
            new_ind = Individual(code=code, score=0.0)
            island.population.append(new_ind)
            logger.info("HITL: hint injected into island %d", island.id)
        self._pending_hints = []


    def _random(self) -> random.Random:
        """Session RNG (falls back to module random if not initialized)."""
        rng = getattr(self, "_rng", None)
        return rng if rng is not None else random

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
            for attempt in range(10):
                mutated = ASTMutator.apply_random_mutation(code)
                filtered = _filter_mutant(mutated, ProfileMode.STRICT)
                if filtered is not None and filtered.strip() != code.strip():
                    code = filtered
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
        if self._random().random() > self.config.cross_branch_crossover_prob:
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
            node_a = self._random().choice(correctness_nodes)
            node_b = self._random().choice(throughput_nodes)
            if node_a.id == node_b.id:
                continue
            dist = self._lineage.get_genealogical_distance(node_a.id, node_b.id)
            if dist is not None and dist >= min_dist:
                candidates_a = [isl for isl in self.islands
                                if isl.id != island.id and isl.local_best]
                if not candidates_a:
                    return None
                parent_a = self._random().choice(candidates_a).local_best
                parent_b = island.local_best or self._random().choice(island.population)

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

    def step_generation(self, generation: Optional[int] = None, task: str = "") -> "GenerationResult":
        """Ejecuta exactamente una generación y devuelve un resultado estructurado.

        API incremental compartida por CLI, dashboard y core. No cierra el evaluator.
        """
        if not task:
            task = self.task
        elif task != self.task:
            self.task = task

        if generation is None:
            generation = self._current_generation
        gen = int(generation)
        self.commands.wait_if_paused()
        if self.commands.stop_requested:
            self._stopped = True
            return GenerationResult(
                generation=gen,
                best=self._global_best,
                snapshots=[],
                should_stop=True,
                combined_best_score=float("-inf"),
            )
        # Drain HITL/control commands
        for cmd in self.commands.drain():
            c = cmd.get("command")
            if c == "inject_hint" and cmd.get("code"):
                self.inject_hint(str(cmd["code"]))
            elif c == "stop":
                self.commands.stop_requested = True
        gen_start = time.perf_counter()
        island_snapshots: List[IslandSnapshot] = []
        self.event_bus.emit(
            GENERATION_STARTED,
            {"generation": gen},
            run_id=self.run_id,
            generation=gen,
        )
        ext_ctx = ExtensionContext(
            generation=gen,
            run_id=self.run_id,
            task=task,
            islands=list(self.islands),
            best=self._global_best,
        )
        self.extensions.on_generation_start(ext_ctx)
        # Reset per-generation LLM budget when available
        backend = getattr(self, "_llm_backend", None)
        if backend is not None and hasattr(backend, "reset_generation_budget"):
            backend.reset_generation_budget()

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
            island_snapshots = self._island_pool.run_generation(self.islands, gen)

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

        global_best = self._global_best
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
                self._global_best = global_best

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
            and self.config.checkpoint_interval > 0
            and (gen + 1) % self.config.checkpoint_interval == 0
        ):
            ckpt_path = self._save_checkpoint(gen + 1)
            if ckpt_path:
                self.event_bus.emit(
                    CHECKPOINT_SAVED,
                    {"path": ckpt_path, "generation": gen + 1},
                    run_id=self.run_id,
                    generation=gen + 1,
                )

        should_stop = self._early_stop.update(current_combined_score)
        if should_stop:
            logger.info(
                "Early stop en gen %d: sin mejora ≥%.4f en %d generaciones.",
                gen + 1, self.config.early_stop_delta,
                self.config.early_stop_patience,
            )
            self._stopped = True

        self._current_generation = gen + 1
        self._generation_completed = gen + 1
        ext_ctx.best = self._global_best
        ext_ctx.metadata["combined_best_score"] = current_combined_score
        self.extensions.on_generation_end(ext_ctx)
        self.event_bus.emit(
            GENERATION_COMPLETED,
            {
                "generation": gen + 1,
                "best_score": current_score,
                "combined_best_score": current_combined_score,
                "should_stop": should_stop,
                "snapshots": len(island_snapshots),
                "extension_metrics": self.extensions.all_metrics(),
            },
            run_id=self.run_id,
            generation=gen + 1,
        )
        if self.commands.stop_requested:
            should_stop = True
            self._stopped = True
        return GenerationResult(
            generation=gen + 1,
            best=self._global_best,
            snapshots=island_snapshots,
            should_stop=should_stop,
            combined_best_score=current_combined_score,
        )

    def step(self, task: str = "") -> "GenerationResult":
        """Alias CLI-compatible de ``step_generation``."""
        return self.step_generation(task=task)

    def run(
        self,
        task: str = "",
        *,
        additional_generations: Optional[int] = None,
        from_generation: Optional[int] = None,
    ) -> Individual:
        if not task:
            task = self.task
        elif task != self.task:
            self.task = task
        self._start_time = time.perf_counter()
        self._stopped = False
        self.commands.stop_requested = False
        start_gen = (
            int(from_generation)
            if from_generation is not None
            else int(getattr(self, "_current_generation", 0) or 0)
        )
        if additional_generations is not None:
            end_gen = start_gen + max(0, int(additional_generations))
        else:
            # Fresh runs start at 0; resumed agents keep start_gen and run until config.generations
            if start_gen > 0:
                end_gen = max(start_gen, int(self.config.generations))
            else:
                end_gen = int(self.config.generations)
                self._current_generation = 0
        logger.info(
            "MutaLambda starting: run=%s %d islands × gens [%d, %d)",
            self.run_id,
            self.config.num_islands,
            start_gen,
            end_gen,
        )
        self.event_bus.emit(
            RUN_STARTED,
            {"start_gen": start_gen, "end_gen": end_gen},
            run_id=self.run_id,
            generation=start_gen,
        )

        result: Optional[GenerationResult] = None
        try:
            for gen in range(start_gen, end_gen):
                result = self.step_generation(generation=gen, task=task)
                if result.should_stop:
                    break
        finally:
            total_time = time.perf_counter() - self._start_time
            best = self._global_best
            logger.info(
                "Evolution complete: run=%s in %.1fs. Best score: %.4f",
                self.run_id,
                total_time,
                best.score if best else float("-inf"),
            )
            self.event_bus.emit(
                RUN_COMPLETED,
                {
                    "best_score": best.score if best else float("-inf"),
                    "elapsed_sec": total_time,
                    "generation_completed": getattr(self, "_generation_completed", 0),
                },
                run_id=self.run_id,
                generation=getattr(self, "_generation_completed", -1),
            )
            # Workflow §16 artifacts + optional elite auto-doc (WF#22)
            try:
                from run_artifacts import write_run_artifacts
                art_dir = Path(self.config.checkpoint_dir) / f"run_{self.run_id}"
                baseline = ""
                if self.config.seed_codes:
                    baseline = self.config.seed_codes[0]
                paths = write_run_artifacts(
                    self,
                    output_dir=art_dir,
                    baseline_code=baseline,
                    task=task or self.task,
                )
                logger.info("Run artifacts written to %s", art_dir)
                # Auto-doc only the final elite, never every candidate
                if best is not None and getattr(self.config, "autodoc_elites", True):
                    try:
                        from interpretability import CodeDocumenter
                        doc_path = art_dir / "best_solution_documented.md"
                        # Lightweight report without extra LLM if documenter needs one
                        report_body = (
                            f"# Elite documentation\n\n"
                            f"run={self.run_id} score={best.score}\n\n"
                            f"```python\n{best.code}\n```\n"
                        )
                        doc_path.write_text(report_body, encoding="utf-8")
                    except Exception as doc_exc:
                        logger.debug("elite autodoc skipped: %s", doc_exc)
            except Exception as art_exc:
                logger.warning("Failed to write run artifacts: %s", art_exc)
            self.shutdown()

        if self._global_best is None:
            raise RuntimeError("Evolution produced no valid individuals.")
        return self._global_best

    def _save_checkpoint(self, generation: int) -> Optional[str]:
        try:
            from checkpoint_manager import save_full_checkpoint

            raw_config = getattr(self, '_raw_config', None)
            return save_full_checkpoint(
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
            return path
        except Exception as exc:
            logger.warning("Checkpoint save failed: %s", exc)
            return None

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


