"""
Checkpoint Manager — Full-state snapshot with RNG reproducibility.

Saves:
  • Island populations (all individuals + scores)
  • MigrationBus state (topology, versions)
  • SolutionArchive state (via archive.save())
  • PromptEvolver state (best prompts, population)
  • RNG state (random, numpy.random)
  • Config hash (SHA256 of config YAML)
  • Git commit hash (reproducibility)
  • Generation metrics & history

Load:
  • Resume evolution from any checkpoint
  • Restore RNG for exact reproducibility
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from muta_lambda import (
    EvolveConfig,
    Individual,
    Island,
    LineageGraph,
    logger,
    MutaLambdaAgent,
    SandboxEvaluator,
    SolutionArchive,
)


@dataclass
class CheckpointData:
    """Full experiment state snapshot."""
    generation: int
    timestamp: float = field(default_factory=time.time)
    config_hash: str = ""
    git_commit: str = ""

    # Core metrics
    best_score: Optional[float] = None
    best_code: Optional[str] = None
    global_best_history: List[float] = field(default_factory=list)
    generation_times: List[float] = field(default_factory=list)

    # Island state
    island_populations: List[List[Dict[str, Any]]] = field(default_factory=list)
    island_generations: List[int] = field(default_factory=list)

    # Archive snapshot path (relative)
    archive_path: Optional[str] = None

    # Prompt evolver state
    prompt_population: Optional[List[Dict[str, Any]]] = None
    prompt_metrics: Optional[Dict[str, Any]] = None

    # HFC tiered evolution state
    hfc_populations: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    hfc_generation: int = 0
    hfc_distilled_concept: str = ""

    # RNG state
    random_state: Any = None
    numpy_state: Any = None

    # Config metadata
    config_dir: str = field(default_factory=lambda: os.getcwd())

    # Fase 7: Lineage DAG
    lineage: Optional[Dict[str, Any]] = None

    # Evolution Upgrade v2.0
    advanced_metrics: Dict[str, Any] = field(default_factory=dict)
    thc_metrics: Dict[str, Any] = field(default_factory=dict)
    dialectic_metrics: Dict[str, Any] = field(default_factory=dict)
    spatial_metrics: Dict[str, Any] = field(default_factory=dict)
    pattern_memory: Optional[Dict[str, Any]] = None

    # Resume metadata (ML-CK03/CK04)
    generation_completed: int = 0
    current_generation: int = 0
    early_stop_best: float = float("-inf")
    early_stop_no_improve: int = 0
    run_id: str = ""
    task: str = ""


# Backward-compatible alias (FIX 1.2)
Checkpoint = CheckpointData

# ── Save ──────────────────────────────────────────────────────────────

def save_full_checkpoint(
    agent: MutaLambdaAgent,
    generation: int,
    config: EvolveConfig,
    raw_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Save complete experiment state for reproducibility.

    Returns the checkpoint directory path.
    """
    chk_dir = Path(config.checkpoint_dir) / f"chk_gen{generation:04d}"
    chk_dir.mkdir(parents=True, exist_ok=True)

    checkpoint = CheckpointData(generation=generation)

    # ── Config hash ──────────────────────────────────────────────────
    if raw_config:
        config_json = json.dumps(raw_config, sort_keys=True, ensure_ascii=False)
        checkpoint.config_hash = hashlib.sha256(config_json.encode()).hexdigest()[:16]

    # ── Git commit ───────────────────────────────────────────────────
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=config.checkpoint_dir,
        )
        if result.returncode == 0:
            checkpoint.git_commit = result.stdout.strip()[:12]
    except (OSError, subprocess.SubprocessError, TimeoutError):
        # Git unavailable or timeout — leave git_commit empty.
        pass

    # ── Best solution ────────────────────────────────────────────────
    best = (
        agent._get_global_best()
        if hasattr(agent, "_get_global_best")
        else agent.migration_bus.get_global_best()
    )
    if best:
        checkpoint.best_score = best.score
        checkpoint.best_code = best.code

    # ── Island populations (ALL individuals) ─────────────────────────
    for island in agent.islands:
        pop_data = [
            {"id": ind.id, "code": ind.code, "score": ind.score,
             "parent_ids": ind.parent_ids or [], "tier": ind.tier,
             "passed": ind.passed, "record_lineage": ind.record_lineage}
            for ind in island.population
        ]
        checkpoint.island_populations.append(pop_data)
        checkpoint.island_generations.append(island.generation)

    # ── Archive ──────────────────────────────────────────────────────
    if agent.archive and agent.archive.size > 0:
        archive_file = chk_dir / "archive"
        agent.archive.save(str(archive_file))
        checkpoint.archive_path = str(archive_file.relative_to(chk_dir))

    # ── Prompt evolver ───────────────────────────────────────────────
    if agent.prompt_evolver:
        checkpoint.prompt_population = [
            {
                "system_prompt": pg.system_prompt,
                "few_shot_examples": pg.few_shot_examples,
                "mutation_instructions": pg.mutation_instructions,
                "temperature": pg.temperature,
                "fitness": pg.fitness,
            }
            for pg in agent.prompt_evolver.population
        ]
        checkpoint.prompt_metrics = agent.prompt_evolver.get_metrics()

    # ── HFC tiered evolution (Fase HFC) ───────────────────────────────
    if hasattr(agent, "_hfc") and agent._hfc is not None:
        hfc_data = agent._hfc.to_checkpoint_dict()
        checkpoint.hfc_populations = hfc_data.get("populations", {})
        checkpoint.hfc_generation = int(hfc_data.get("generation", 0))
        checkpoint.hfc_distilled_concept = str(hfc_data.get("distilled_concept", ""))

    # ── RNG state (critical for reproducibility) ─────────────────────
    checkpoint.random_state = random.getstate()
    checkpoint.numpy_state = np.random.get_state()

    # ── Metrics history ──────────────────────────────────────────────
    checkpoint.global_best_history = agent._global_best_history
    checkpoint.generation_times = agent._generation_times
    checkpoint.generation_completed = int(
        getattr(agent, "_generation_completed", generation) or generation
    )
    checkpoint.current_generation = int(
        getattr(agent, "_current_generation", generation) or generation
    )
    checkpoint.run_id = str(getattr(agent, "run_id", "") or "")
    checkpoint.task = str(getattr(agent, "task", "") or "")
    early = getattr(agent, "_early_stop", None)
    if early is not None:
        checkpoint.early_stop_best = float(getattr(early, "_best", float("-inf")))
        checkpoint.early_stop_no_improve = int(getattr(early, "_no_improve", 0))

    # ── Lineage graph (Fase 7) ────────────────────────────────────────
    if hasattr(agent, '_lineage') and agent._lineage.nodes:
        checkpoint.lineage = agent._lineage.to_dict()

    for attr, target in (
        ("_advanced_selection", "advanced_metrics"),
        ("_thc_engine", "thc_metrics"),
        ("_dialectic_engine", "dialectic_metrics"),
    ):
        engine = getattr(agent, attr, None)
        metrics = getattr(engine, "metrics", None)
        if metrics is not None:
            setattr(checkpoint, target, getattr(metrics, "__dict__", {}))

    spatial = getattr(agent.migration_bus, "spatial_topology", None)
    if spatial is not None and getattr(spatial, "metrics", None) is not None:
        checkpoint.spatial_metrics = getattr(spatial.metrics, "__dict__", {})

    pattern_memory = getattr(agent, "_pattern_memory", None)
    if pattern_memory is not None:
        checkpoint.pattern_memory = pattern_memory.to_dict()

    # ── Serialise ────────────────────────────────────────────────────
    ckpt_path = chk_dir / "checkpoint.json"
    with open(ckpt_path, "w", encoding="utf-8") as f:
        json.dump(_serialise_checkpoint(checkpoint), f, indent=2, ensure_ascii=False)

    logger.info(
        "Full checkpoint saved: %s (gen %d, %d islands, "
        "archive=%d, config_hash=%s, git=%s)",
        ckpt_path, generation, len(checkpoint.island_populations),
        agent.archive.size if agent.archive else 0,
        checkpoint.config_hash,
        checkpoint.git_commit,
    )

    return str(chk_dir)


def _serialise_checkpoint(cp: CheckpointData) -> Dict[str, Any]:
    """Convert CheckpointData to JSON-serialisable dict."""
    # Serialise RNG state — handle different Python versions flexibly
    rs = cp.random_state
    if rs is not None:
        try:
            # Convert all elements to JSON-safe types recursively
            random_serialised = _to_json_safe(rs)
        except Exception:
            random_serialised = None
    else:
        random_serialised = None
    # numpy state: tuple of (algorithm, state_array, pos, has_gauss, gauss)
    np_state_tuple = cp.numpy_state
    if np_state_tuple and len(np_state_tuple) >= 2:
        np_version = np_state_tuple[0]  # 'MT19937'
        np_core = np_state_tuple[1]      # (624,) ndarray
        np_pos = np_state_tuple[2] if len(np_state_tuple) > 2 else 0
        np_has_gauss = np_state_tuple[3] if len(np_state_tuple) > 3 else 0
        np_gauss = np_state_tuple[4] if len(np_state_tuple) > 4 else 0.0
        numpy_serialised = [
            np_version,
            np_core.tolist() if hasattr(np_core, 'tolist') else np_core,
            np_pos,
            np_has_gauss,
            np_gauss,
        ]
    else:
        numpy_serialised = None

    return {
        "generation": cp.generation,
        "timestamp": cp.timestamp,
        "config_hash": cp.config_hash,
        "git_commit": cp.git_commit,
        "best_score": cp.best_score,
        "best_code": cp.best_code,
        "global_best_history": cp.global_best_history,
        "generation_times": cp.generation_times,
        "island_populations": cp.island_populations,
        "island_generations": cp.island_generations,
        "archive_path": cp.archive_path,
        "prompt_population": cp.prompt_population,
        "prompt_metrics": cp.prompt_metrics,
        "hfc_populations": cp.hfc_populations,
        "hfc_generation": cp.hfc_generation,
        "hfc_distilled_concept": cp.hfc_distilled_concept,
        "random_state": random_serialised,
        "numpy_state": numpy_serialised,
        "lineage": cp.lineage,
        "advanced_metrics": cp.advanced_metrics,
        "thc_metrics": cp.thc_metrics,
        "dialectic_metrics": cp.dialectic_metrics,
        "spatial_metrics": cp.spatial_metrics,
        "pattern_memory": cp.pattern_memory,
        "generation_completed": cp.generation_completed,
        "current_generation": cp.current_generation,
        "early_stop_best": (
            None if cp.early_stop_best == float("-inf") else cp.early_stop_best
        ),
        "early_stop_no_improve": cp.early_stop_no_improve,
        "run_id": cp.run_id,
        "task": cp.task,
        "format": "mutalambda-core-json",
        "version": "4.0.0",
    }


# ── Serialisation helpers ──────────────────────────────────────────────

def _to_json_safe(obj):
    """Convert tuples and numpy arrays to JSON-serialisable lists."""
    if isinstance(obj, (tuple, list)):
        return [_to_json_safe(x) for x in obj]
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


def _restore_state(state_data):
    """Restore RNG state from JSON-safe format (reverse of _to_json_safe)."""
    if isinstance(state_data, list):
        return tuple(_restore_state(x) for x in state_data)
    return state_data

def load_checkpoint(path: str | Path) -> CheckpointData:
    """Load a checkpoint from disk."""
    path = Path(path)
    if path.is_dir():
        path = path / "checkpoint.json"
    if not path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cp = CheckpointData(
        generation=data["generation"],
        timestamp=data.get("timestamp", 0.0),
        config_hash=data.get("config_hash", ""),
        git_commit=data.get("git_commit", ""),
        best_score=data.get("best_score"),
        best_code=data.get("best_code"),
        global_best_history=data.get("global_best_history", []),
        generation_times=data.get("generation_times", []),
        island_populations=data.get("island_populations", []),
        island_generations=data.get("island_generations", []),
        archive_path=data.get("archive_path"),
        prompt_population=data.get("prompt_population"),
        prompt_metrics=data.get("prompt_metrics"),
        hfc_populations=data.get("hfc_populations", {}),
        hfc_generation=data.get("hfc_generation", 0),
        hfc_distilled_concept=data.get("hfc_distilled_concept", ""),
        lineage=data.get("lineage"),
        advanced_metrics=data.get("advanced_metrics", {}),
        thc_metrics=data.get("thc_metrics", {}),
        dialectic_metrics=data.get("dialectic_metrics", {}),
        spatial_metrics=data.get("spatial_metrics", {}),
        pattern_memory=data.get("pattern_memory"),
        generation_completed=int(data.get("generation_completed", data.get("generation", 0))),
        current_generation=int(data.get("current_generation", data.get("generation", 0))),
        early_stop_best=(
            float("-inf")
            if data.get("early_stop_best") is None
            else float(data.get("early_stop_best"))
        ),
        early_stop_no_improve=int(data.get("early_stop_no_improve", 0)),
        run_id=str(data.get("run_id", "") or ""),
        task=str(data.get("task", "") or ""),
    )

    # Restore RNG state
    rs = data.get("random_state")
    if rs and isinstance(rs, list):
        try:
            restored = _restore_state(rs)
            if isinstance(restored, tuple) and len(restored) >= 2:
                random.setstate(restored)
                cp.random_state = restored
        except Exception:
            pass

    ns = data.get("numpy_state")
    if ns and isinstance(ns, list) and len(ns) >= 2:
        try:
            np_version = ns[0]
            np_core = np.array(ns[1]) if isinstance(ns[1], list) else ns[1]
            np_pos = ns[2] if len(ns) > 2 else 0
            np_has_gauss = ns[3] if len(ns) > 3 else 0
            np_gauss = ns[4] if len(ns) > 4 else 0.0
            np.random.set_state((np_version, np_core, np_pos, np_has_gauss, np_gauss))
        except Exception:
            pass

    return cp


def resume_agent(
    checkpoint_path: str | Path,
    config: EvolveConfig,
    test_cases: List[Dict],
    llm_fn: Optional[callable] = None,
) -> MutaLambdaAgent:
    """
    Resume MutaLambdaAgent from a full checkpoint.

    Restores island populations, RNG state, archive, and prompt evolver.
    Use to continue an interrupted experiment exactly.
    """
    cp = load_checkpoint(checkpoint_path)
    chk_dir = Path(checkpoint_path).parent if Path(checkpoint_path).is_file() else Path(checkpoint_path)

    # Create fresh agent
    agent = MutaLambdaAgent(
        config=config,
        test_cases=test_cases,
        llm_fn=llm_fn,
        timeout_sec=config._timeout_sec if hasattr(config, '_timeout_sec') else 10.0,
    )

    # Restore island populations
    for i, island in enumerate(agent.islands):
        if i < len(cp.island_populations):
            pop_data = cp.island_populations[i]
            island.population = [
                Individual(
                    code=ind["code"],
                    score=ind["score"],
                    id=ind.get("id", ""),
                    parent_ids=ind.get("parent_ids", []),
                    tier=ind.get("tier", "laboratory"),
                    passed=bool(ind.get("passed", False)),
                    record_lineage=bool(ind.get("record_lineage", True)),
                )
                for ind in pop_data
            ]
            if island.population:
                island.local_best = max(island.population, key=lambda x: x.score)
            if i < len(cp.island_generations):
                island.generation = cp.island_generations[i]
            island._registered = True
            agent.migration_bus.register_island(island.id, island)

    # Restore archive
    if cp.archive_path and agent.archive:
        archive_file = chk_dir / cp.archive_path
        if archive_file.with_suffix(".index").exists():
            try:
                agent.archive = SolutionArchive.load(str(archive_file))
            except Exception:
                logger.warning("Could not restore archive from checkpoint", exc_info=True)

    # Restore prompt evolver
    if cp.prompt_population and agent.prompt_evolver:
        from muta_lambda import PromptGenome
        agent.prompt_evolver.population = [
            PromptGenome(**pd) for pd in cp.prompt_population
        ]

    # Restore HFC tiered evolution
    if cp.hfc_populations and hasattr(agent, "_hfc") and agent._hfc is not None:
        agent._hfc.restore(
            cp.hfc_populations,
            generation=cp.hfc_generation,
            distilled_concept=cp.hfc_distilled_concept,
        )

    # Restore metrics
    agent._global_best_history = cp.global_best_history
    agent._generation_times = cp.generation_times
    agent._current_generation = cp.current_generation or cp.generation
    agent._generation_completed = cp.generation_completed or cp.generation
    if cp.task:
        agent.task = cp.task
    if cp.run_id:
        agent.run_id = cp.run_id

    # Restore global best
    if cp.best_code is not None:
        agent._global_best = Individual(
            code=cp.best_code,
            score=float(cp.best_score) if cp.best_score is not None else float("-inf"),
        )

    # Restore EarlyStopMonitor
    early = getattr(agent, "_early_stop", None)
    if early is not None:
        early._best = cp.early_stop_best
        early._no_improve = cp.early_stop_no_improve

    # Restore lineage graph (Fase 7)
    if cp.lineage and hasattr(agent, '_lineage'):
        agent._lineage = LineageGraph.from_dict(cp.lineage)
        agent.migration_bus.lineage_graph = agent._lineage
        advanced = getattr(agent, "_advanced_selection", None)
        if advanced is not None:
            advanced.lineage_graph = agent._lineage

    if cp.pattern_memory and hasattr(agent, "_pattern_memory") and agent._pattern_memory is not None:
        try:
            from muta_ext.pattern_memory import PatternMemory

            agent._pattern_memory = PatternMemory.from_dict(cp.pattern_memory)
            agent.migration_bus.pattern_memory = agent._pattern_memory
        except Exception:
            logger.warning("Could not restore pattern memory", exc_info=True)

    logger.info(
        "Agent resumed from checkpoint: gen_completed=%d current=%d, %d islands, "
        "archive=%d, config_hash=%s",
        agent._generation_completed,
        agent._current_generation,
        len(cp.island_populations),
        agent.archive.size if agent.archive else 0,
        cp.config_hash,
    )

    return agent
