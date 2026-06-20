"""
IslandPool — Coordinador de evolución paralela multi‑isla para MutaLambda.

Proporciona evolución verdaderamente paralela de islas semi‑aisladas
con métricas de diversidad por isla y entre islas.  Diseñado para
evitar la convergencia prematura mediante:
  • Thread‑parallel island steps
  • Differentiated seeding (cada isla recibe variantes mutadas)
  • Diversity tracking (varianza de longitud de código, distancia semántica)
  • Mesh topology support
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


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


@dataclass
class IslandDiversity:
    """Métricas de diversidad para una isla."""
    code_length_variance: float   # varianza en longitud de código
    unique_ratio: float           # fracción de individuos únicos
    score_variance: float         # varianza en scores
    mean_code_length: float
    mean_score: float


class IslandPool:
    """
    Coordinador de evolución paralela para múltiples islas.

    Usa ThreadPoolExecutor (default) o ProcessPoolExecutor para ejecutar
    island.step() concurrentemente. Cada isla comparte el mismo MigrationBus
    (thread‑safe vía RLock).

    Parameters
    ----------
    max_workers : int, optional
        Número máximo de workers. Default: min(32, num_islands + 4).
    backend : str
        "thread" (default) para ThreadPoolExecutor (I/O-bound, LLM calls).
        "process" para ProcessPoolExecutor (CPU-bound, sandbox pesada).
        NOTA: "process" requiere que Island sea pickleable — actualmente
        limitado a islas sin LLM callables complejos.

    Warning
    -------
    ``backend="process"`` está en fase experimental. Las islas con LLM
    callables (funciones lambda/closures) no son pickleables y causarán
    errores. Se recomienda usar "thread" a menos que el sandbox sea el
    cuello de botella principal.
    """

    def __init__(self, max_workers: Optional[int] = None,
                 backend: str = "thread"):
        self._max_workers = max_workers
        self.backend = backend
        self._lock = threading.Lock()
        self._generation_snapshots: List[List[IslandSnapshot]] = []

    def run_generation(
        self,
        islands: List,
        generation: int,
    ) -> List[IslandSnapshot]:
        """
        Ejecuta un paso evolutivo en paralelo para todas las islas.

        Cada isla evoluciona independientemente en su propio thread;
        el MigrationBus (compartido) maneja la sincronización de
        migración internamente.

        Returns
        -------
        List[IslandSnapshot]
            Snapshot del estado de cada isla tras el paso.
        """
        num_islands = len(islands)
        max_workers = self._max_workers or min(32, num_islands + 4)

        snapshots: Dict[int, IslandSnapshot] = {}

        ExecutorClass = (
            ProcessPoolExecutor if self.backend == "process"
            else ThreadPoolExecutor
        )
        with ExecutorClass(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._step_island, island): island.id
                for island in islands
            }

            for future in as_completed(futures):
                island_id = futures[future]
                try:
                    snapshot = future.result()
                    snapshots[island_id] = snapshot
                except Exception as exc:
                    # Nunca crashear el motor por fallo en una isla
                    snapshots[island_id] = IslandSnapshot(
                        island_id=island_id,
                        generation=generation,
                        pop_size=0,
                        best_score=float("-inf"),
                        diversity=0.0,
                        mean_code_len=0.0,
                    )

        # Ordenar por island_id para consistencia
        result = [snapshots[i] for i in sorted(snapshots)]
        with self._lock:
            self._generation_snapshots.append(result)
        return result

    @staticmethod
    def _step_island(island) -> IslandSnapshot:
        """Wrapper thread‑safe para island.step()."""
        island.step()

        diversity = IslandPool._compute_diversity(island)
        best = island.local_best

        return IslandSnapshot(
            island_id=island.id,
            generation=island.generation,
            pop_size=len(island.population),
            best_score=best.score if best else float("-inf"),
            diversity=diversity.unique_ratio,
            mean_code_len=diversity.mean_code_length,
        )

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

        # Unique ratio: fracción de código único
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
