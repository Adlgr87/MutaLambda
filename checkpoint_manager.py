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
class Checkpoint:
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

    # RNG state
    random_state: Any = None
    numpy_state: Any = None

    # Config metadata
    config_dir: str = field(default_factory=lambda: os.getcwd())

    # Fase 7: Lineage DAG
    lineage: Optional[Dict[str, Any]] = None


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

    checkpoint = Checkpoint(generation=generation)

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
    except Exception:
        pass

    # ── Best solution ────────────────────────────────────────────────
    best = agent.migration_bus.get_global_best()
    if best:
        checkpoint.best_score = best.score
        checkpoint.best_code = best.code

    # ── Island populations (ALL individuals) ─────────────────────────
    for island in agent.islands:
        pop_data = [
            {"id": ind.id, "code": ind.code, "score": ind.score,
             "parent_ids": ind.parent_ids or []}
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

    # ── RNG state (critical for reproducibility) ─────────────────────
    checkpoint.random_state = random.getstate()
    checkpoint.numpy_state = np.random.get_state()

    # ── Metrics history ──────────────────────────────────────────────
    checkpoint.global_best_history = agent._global_best_history
    checkpoint.generation_times = agent._generation_times

    # ── Lineage graph (Fase 7) ────────────────────────────────────────
    if hasattr(agent, '_lineage') and agent._lineage.nodes:
        checkpoint.lineage = agent._lineage.to_dict()

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


def _serialise_checkpoint(cp: Checkpoint) -> Dict[str, Any]:
    """Convert Checkpoint to JSON-serialisable dict."""
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
        "random_state": random_serialised,
        "numpy_state": numpy_serialised,
        "lineage": cp.lineage,
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

def load_checkpoint(path: str | Path) -> Checkpoint:
    """Load a checkpoint from disk."""
    path = Path(path)
    if path.is_dir():
        path = path / "checkpoint.json"
    if not path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cp = Checkpoint(
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
        lineage=data.get("lineage"),
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
                Individual(code=ind["code"], score=ind["score"], id=ind.get("id", ""),
                               parent_ids=ind.get("parent_ids", []))
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

    # Restore metrics
    agent._global_best_history = cp.global_best_history
    agent._generation_times = cp.generation_times

    # Restore lineage graph (Fase 7)
    if cp.lineage and hasattr(agent, '_lineage'):
        agent._lineage = LineageGraph.from_dict(cp.lineage)
        agent.migration_bus.lineage_graph = agent._lineage

    logger.info(
        "Agent resumed from checkpoint: gen %d, %d islands restored, "
        "archive=%d, config_hash=%s",
        cp.generation, len(cp.island_populations),
        agent.archive.size if agent.archive else 0,
        cp.config_hash,
    )

    return agent