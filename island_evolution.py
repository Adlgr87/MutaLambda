"""
IslandPool — Coordinador de evolución paralela multi‑isla para MutaLambda.

Proporciona evolución verdaderamente paralela de islas semi‑aisladas
con métricas de diversidad por isla y entre islas.  Diseñado para
evitar la convergencia prematura mediante:
  • Thread‑parallel island steps
  • Differentiated seeding (cada isla recibe variantes mutadas)
  • Diversity tracking (varianza de longitud de código, distancia semántica)
  • Mesh topology support
  • Generation barriers for safe migration (ML-CON01)
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger("MutaLambda")


@dataclass
class IslandSnapshot:
    """Fotografía del estado de una isla tras un paso evolutivo."""
    island_id: int
    generation: int
    pop_size: int
    best_score: float
    diversity: float          # 0..1, mayor = más diversa
    mean_code_len: float
    num_migrants_sent: int = 0
    num_migrants_received: int = 0
    failed: bool = False
    failure: Optional["IslandFailure"] = None


@dataclass
class IslandFailure:
    """Structured failure from an island step (ML-E03 / ML-CON03)."""

    island_id: int
    generation: int
    error_type: str
    message: str
    policy: str = "continue_with_warning"  # retry | replace_island | abort_run | continue_with_warning

    def to_dict(self) -> dict:
        return {
            "island_id": self.island_id,
            "generation": self.generation,
            "error_type": self.error_type,
            "message": self.message,
            "policy": self.policy,
        }


@dataclass
class IslandDiversity:
    """Métricas de diversidad para una isla."""
    code_length_variance: float   # varianza en longitud de código
    unique_ratio: float           # fracción de individuos únicos
    score_variance: float         # varianza en scores
    mean_code_length: float
    mean_score: float


@dataclass
class GenerationBarriersResult:
    """Result of a full barrier-synchronized generation."""

    snapshots: List[IslandSnapshot] = field(default_factory=list)
    failures: List[IslandFailure] = field(default_factory=list)
    migrants_staged: int = 0
    should_abort: bool = False


class IslandPool:
    """
    Coordinador de evolución paralela para múltiples islas.

    Generation pipeline (ML-CON01):
      Phase A/B: local evolution (evaluate + select + mutate) in parallel
      Barrier
      Phase C: stage migrants into neighbor queues
      Barrier
      Phase D: applied at the start of the next generation via
               ``Island.apply_pending_migrants()``

    Parameters
    ----------
    max_workers : int, optional
        Número máximo de workers. Default: min(32, num_islands + 4).
    backend : str
        "thread" (default) para ThreadPoolExecutor (I/O-bound, LLM calls).
        "process" para ProcessPoolExecutor (CPU-bound, sandbox pesada).
        NOTA: "process" requiere que Island sea pickleable — actualmente
        limitado a islas sin LLM callables complejos.
    failure_policy : str
        Default policy when an island raises: continue_with_warning | abort_run.
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        backend: str = "thread",
        failure_policy: str = "continue_with_warning",
    ):
        self._max_workers = max_workers
        self.backend = backend
        self.failure_policy = failure_policy
        self._lock = threading.Lock()
        self._generation_snapshots: List[List[IslandSnapshot]] = []
        self._failures: List[IslandFailure] = []

    def run_generation(
        self,
        islands: List,
        generation: int,
    ) -> List[IslandSnapshot]:
        """
        Ejecuta un paso evolutivo en paralelo para todas las islas con
        barreras de migración.

        Returns
        -------
        List[IslandSnapshot]
            Snapshot del estado de cada isla tras el paso.
        """
        result = self.run_generation_barriers(islands, generation)
        return result.snapshots

    def run_generation_barriers(
        self,
        islands: List,
        generation: int,
    ) -> GenerationBarriersResult:
        """Full barrier pipeline with structured failures."""
        num_islands = len(islands)
        max_workers = self._max_workers or min(32, num_islands + 4)
        out = GenerationBarriersResult()

        snapshots: Dict[int, IslandSnapshot] = {}
        ExecutorClass = (
            ProcessPoolExecutor if self.backend == "process"
            else ThreadPoolExecutor
        )

        # ── Phase A/B: local evolution only ─────────────────────────────
        with ExecutorClass(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._step_island_local, island): island.id
                for island in islands
            }

            for future in as_completed(futures):
                island_id = futures[future]
                try:
                    snapshot = future.result()
                    snapshots[island_id] = snapshot
                except Exception as exc:
                    failure = IslandFailure(
                        island_id=island_id,
                        generation=generation,
                        error_type=type(exc).__name__,
                        message=str(exc)[:500],
                        policy=self.failure_policy,
                    )
                    out.failures.append(failure)
                    with self._lock:
                        self._failures.append(failure)
                    logger.warning(
                        "Island %d failed at gen %d (%s): %s",
                        island_id, generation, failure.error_type, failure.message,
                    )
                    snapshots[island_id] = IslandSnapshot(
                        island_id=island_id,
                        generation=generation,
                        pop_size=0,
                        best_score=float("-inf"),
                        diversity=0.0,
                        mean_code_len=0.0,
                        failed=True,
                        failure=failure,
                    )
                    if self.failure_policy == "abort_run":
                        out.should_abort = True

        # Barrier: all local steps finished before migration staging.

        # ── Phase C: stage migrants into queues ─────────────────────────
        if islands and not out.should_abort:
            bus = getattr(islands[0], "migration_bus", None)
            if bus is not None and hasattr(bus, "stage_all_migrations"):
                # Use pre-increment generation index for interval checks.
                # Islands already bumped generation in step_local, so pass generation.
                out.migrants_staged = bus.stage_all_migrations(generation, deferred=True)
            else:
                # Fallback: legacy per-island migrate
                for island in islands:
                    try:
                        island.migration_bus.migrate(island.id, generation)
                    except Exception as exc:
                        logger.warning("Legacy migrate failed island %s: %s", island.id, exc)

        # Phase D happens at the start of the next generation (apply_pending_migrants).

        result_list = [snapshots[i] for i in sorted(snapshots)]
        out.snapshots = result_list
        with self._lock:
            self._generation_snapshots.append(result_list)
        return out

    @staticmethod
    def _step_island_local(island) -> IslandSnapshot:
        """Wrapper thread‑safe para evolución local sin migración inmediata."""
        if hasattr(island, "step_local"):
            island.step_local()
        else:
            # Backward-compatible path for mocks without step_local.
            island.step()

        diversity = IslandPool._compute_diversity(island)
        best = island.local_best
        pending = len(getattr(island, "_pending_migrants", []) or [])

        return IslandSnapshot(
            island_id=island.id,
            generation=island.generation,
            pop_size=len(island.population),
            best_score=best.score if best else float("-inf"),
            diversity=diversity.unique_ratio,
            mean_code_len=diversity.mean_code_length,
            num_migrants_received=pending,
        )

    @staticmethod
    def _step_island(island) -> IslandSnapshot:
        """Legacy wrapper retained for external callers."""
        return IslandPool._step_island_local(island)

    @staticmethod
    def _compute_diversity(island) -> IslandDiversity:
        """Calcula métricas de diversidad intra‑isla."""
        pop = island.population
        if not pop:
            return IslandDiversity(0.0, 0.0, 0.0, 0.0, 0.0)

        lengths = [len(ind.code) for ind in pop]
        scores = [ind.score for ind in pop]
        n = len(pop)

        mean_len = sum(lengths) / n
        mean_score = sum(scores) / n
        len_var = sum((l - mean_len) ** 2 for l in lengths) / n
        score_var = sum((s - mean_score) ** 2 for s in scores) / n

        unique_codes = len({ind.code for ind in pop})
        unique_ratio = unique_codes / n

        return IslandDiversity(
            code_length_variance=len_var,
            unique_ratio=unique_ratio,
            score_variance=score_var,
            mean_code_length=mean_len,
            mean_score=mean_score,
        )

    def get_cross_island_diversity(self, islands: Optional[List] = None) -> float:
        """
        Diversidad entre islas usando Jaccard sobre tokens de código.

        ``1.0`` significa conjuntos de tokens completamente disjuntos;
        ``0.0`` significa poblaciones idénticas o no comparables.
        """
        if not islands:
            return 0.0

        island_tokens: List[Set[str]] = []
        for island in islands:
            tokens: Set[str] = set()
            for ind in island.population:
                tokens.update(ind.code.split())
            island_tokens.append(tokens)

        total_jaccard = 0.0
        pairs = 0
        for i in range(len(island_tokens)):
            for j in range(i + 1, len(island_tokens)):
                a, b = island_tokens[i], island_tokens[j]
                if not a and not b:
                    continue
                union = len(a | b)
                if union == 0:
                    continue
                total_jaccard += len(a & b) / union
                pairs += 1

        if pairs == 0:
            return 0.0
        return 1.0 - (total_jaccard / pairs)

    @property
    def generation_count(self) -> int:
        return len(self._generation_snapshots)

    @property
    def failures(self) -> List[IslandFailure]:
        with self._lock:
            return list(self._failures)
