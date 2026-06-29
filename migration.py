"""Migration bus between evolutionary islands.

Supports topological migration (ring, mesh, fully_connected, spatial_grid)
and fitness-directed gradient migration for asertive, quality-aware transfers.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import random
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from island import Island
from models import Individual

logger = logging.getLogger("MutaLambda")


# ---------------------------------------------------------------------------
# Fitness-Directed Gradient Migration
# ---------------------------------------------------------------------------

@dataclass
class GradientConfig:
    """Configuration for fitness-directed gradient migration."""

    alpha: float = 0.7            # Weight for fitness gradient (higher = prefer fitter islands)
    beta: float = 0.3             # Weight for diversity gap (higher = prefer diverse islands)
    top_k_targets: int = 2        # Max destination islands per migration event
    stagnation_threshold: float = 0.05  # Min fitness improvement ratio to not be "stagnant"
    elite_injection: bool = True  # Inject top 5% of donor as directed seeds
    min_diversity_gap: float = 0.15  # Minimum diversity gap to allow migration
    max_diversity_gap: float = 0.85  # Maximum diversity gap (avoid incompatible code)
    fitness_window: int = 5       # Number of recent generations for fitness averaging


@dataclass
class MigrationMetrics:
    """Tracks migration efficiency for benchmark evidence."""

    total_migrations: int = 0
    successful_migrations: int = 0  # Migrants that improved destination fitness
    elite_injections: int = 0
    skipped_low_diversity: int = 0
    skipped_low_gradient: int = 0
    fitness_improvements: List[float] = field(default_factory=list)
    migration_history: List[Dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_migration(
        self, source_id: int, target_id: int, migrant_score: float,
        target_avg_before: float, target_avg_after: float,
        is_elite: bool = False, reason: str = "gradient",
    ) -> None:
        with self._lock:
            self.total_migrations += 1
            improvement = target_avg_after - target_avg_before
            if improvement > 0:
                self.successful_migrations += 1
                self.fitness_improvements.append(improvement)
            if is_elite:
                self.elite_injections += 1
            self.migration_history.append({
                "timestamp": time.time(),
                "source": source_id,
                "target": target_id,
                "migrant_score": migrant_score,
                "target_before": target_avg_before,
                "target_after": target_avg_after,
                "improvement": improvement,
                "is_elite": is_elite,
                "reason": reason,
            })

    @property
    def success_rate(self) -> float:
        with self._lock:
            if self.total_migrations == 0:
                return 0.0
            return self.successful_migrations / self.total_migrations

    @property
    def mean_improvement(self) -> float:
        with self._lock:
            if not self.fitness_improvements:
                return 0.0
            return sum(self.fitness_improvements) / len(self.fitness_improvements)

    def get_report(self) -> Dict:
        with self._lock:
            return {
                "total_migrations": self.total_migrations,
                "successful_migrations": self.successful_migrations,
                "success_rate": round(self.success_rate, 4),
                "mean_improvement": round(self.mean_improvement, 6),
                "elite_injections": self.elite_injections,
                "skipped_low_diversity": self.skipped_low_diversity,
                "skipped_low_gradient": self.skipped_low_gradient,
            }


class FitnessDirectedMigration:
    """Migración basada en gradiente de fitness + diversidad genética.

    Instead of sending migrants to topological neighbors, selects destinations
    where the migrant will have the highest positive impact based on:
      1. Fitness gradient: islands with higher fitness benefit from diverse genetic material
      2. Diversity gap: ensures migrants bring genuinely novel genetic material
      3. Elite injection: top individuals are seeded directly into promising islands

    This replaces blind topological migration with quality-aware directed transfer.
    """

    def __init__(self, config: GradientConfig | None = None):
        self.config = config or GradientConfig()
        self._code_cache: Dict[str, str] = {}  # code -> signature cache
        self._island_fitness_history: Dict[int, List[float]] = defaultdict(list)
        self.metrics = MigrationMetrics()

    def _code_signature(self, code: str) -> str:
        """Compute a compact structural signature of code for diversity comparison.

        Uses normalized AST-like hashing: strips whitespace, sorts tokens,
        and hashes the result for O(1) comparison.
        """
        if code in self._code_cache:
            return self._code_cache[code]

        # Normalize: strip whitespace, lowercase keywords, sort tokens
        tokens = code.split()
        normalized = " ".join(sorted(t.lower() for t in tokens if len(t) > 1))
        sig = hashlib.md5(normalized.encode()).hexdigest()[:16]
        self._code_cache[code] = sig
        return sig

    def _code_similarity(self, code_a: str, code_b: str) -> float:
        """Estimate structural similarity between two code fragments.

        Uses token overlap (Jaccard-like) as a fast proxy for AST similarity.
        Returns 0.0 (completely different) to 1.0 (identical).
        """
        if not code_a or not code_b:
            return 0.0
        tokens_a = set(code_a.split())
        tokens_b = set(code_b.split())
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    def _island_avg_fitness(self, island: Island) -> float:
        """Compute average fitness score of an island's population."""
        if not island.population:
            return float("-inf")
        scores = [ind.score for ind in island.population if ind.score > float("-inf")]
        if not scores:
            return float("-inf")
        return sum(scores) / len(scores)

    def _island_fitness_trend(self, island_id: int, current_fitness: float) -> float:
        """Track fitness trend: positive = improving, negative = stagnating."""
        history = self._island_fitness_history[island_id]
        history.append(current_fitness)
        window = self.config.fitness_window
        if len(history) < 2:
            return 0.0
        recent = history[-window:]
        if len(recent) < 2:
            return 0.0
        # Simple linear trend: (last - first) / len
        return (recent[-1] - recent[0]) / len(recent)

    def _dominant_signature(self, island: Island) -> str:
        """Get the code signature of the best individual in the island."""
        if island.local_best and island.local_best.code:
            return self._code_signature(island.local_best.code)
        if island.population:
            best = max(island.population, key=lambda ind: ind.score)
            if best.code:
                return self._code_signature(best.code)
        return ""

    def select_targets(
        self,
        source: Island,
        all_islands: Dict[int, Island],
    ) -> List[Tuple[float, Island]]:
        """Select the best destination islands for migration.

        Scores each potential target based on:
          score = α × fitness_gradient + β × diversity_gap

        Where:
          - fitness_gradient: how much fitter the target is (positive = target is better)
          - diversity_gap: how genetically different source and target are

        Returns list of (score, island) tuples sorted by score descending.
        """
        source_fitness = self._island_avg_fitness(source)
        source_sig = self._dominant_signature(source)
        source_trend = self._island_fitness_trend(source.id, source_fitness)

        scored_targets: List[Tuple[float, Island]] = []

        for target_id, target in all_islands.items():
            if target_id == source.id:
                continue

            target_fitness = self._island_avg_fitness(target)
            if target_fitness == float("-inf"):
                continue

            target_sig = self._dominant_signature(target)

            # Fitness gradient: normalized difference
            # Positive = target is fitter (good place to send diverse genes)
            # We also consider sending TO stagnant islands from improving ones
            fitness_range = max(abs(target_fitness), abs(source_fitness), 1.0)
            fitness_gradient = (target_fitness - source_fitness) / fitness_range

            # Diversity gap: how different are the populations
            if source_sig and target_sig:
                diversity_gap = 1.0 - self._code_similarity(
                    source.local_best.code if source.local_best else "",
                    target.local_best.code if target.local_best else "",
                )
            else:
                diversity_gap = 0.5  # Unknown, assume moderate diversity

            # Filter: skip if diversity gap is too small (clones) or too large (incompatible)
            if diversity_gap < self.config.min_diversity_gap:
                with self.metrics._lock:
                    self.metrics.skipped_low_diversity += 1
                continue
            if diversity_gap > self.config.max_diversity_gap:
                with self.metrics._lock:
                    self.metrics.skipped_low_diversity += 1
                continue

            # Combined score
            score = (
                self.config.alpha * fitness_gradient
                + self.config.beta * diversity_gap
            )

            # Bonus: if source is improving and target is stagnant, boost score
            target_trend = self._island_fitness_trend(target_id, target_fitness)
            if source_trend > 0 and target_trend <= 0:
                score *= 1.3  # 30% boost for rescuing stagnant islands

            # Bonus: if target is improving and source is stagnant, still useful
            # (target might pull source out of stagnation via bidirectional flow)
            elif target_trend > 0 and source_trend <= 0:
                score *= 1.1  # 10% boost

            scored_targets.append((score, target))

        # Sort by score descending, take top K
        scored_targets.sort(key=lambda x: x[0], reverse=True)
        return scored_targets[: self.config.top_k_targets]

    def get_elite_migrants(
        self, island: Island, fraction: float = 0.05, max_elite: int = 2,
    ) -> List[Individual]:
        """Extract elite individuals (top fraction) from an island.

        These are the highest-quality migrants for directed injection.
        """
        if not island.population:
            return []
        sorted_pop = sorted(island.population, key=lambda ind: ind.score, reverse=True)
        n_elite = max(1, min(max_elite, int(len(sorted_pop) * fraction)))
        elites = []
        for ind in sorted_pop[:n_elite]:
            if ind.score > float("-inf"):
                elite = copy.deepcopy(ind)
                elites.append(elite)
        return elites

    def migrate(
        self,
        source: Island,
        all_islands: Dict[int, Island],
        generation: int,
    ) -> Dict[str, int]:
        """Execute fitness-directed migration from source island.

        Returns stats dict with counts of migrations, skips, elite injections.
        """
        stats: Dict[str, int] = {
            "migrated": 0, "skipped": 0, "elite_injected": 0,
        }

        targets = self.select_targets(source, all_islands)
        if not targets:
            with self.metrics._lock:
                self.metrics.skipped_low_gradient += 1
            stats["skipped"] = 1
            return stats

        # Regular migrants: best individuals from source
        n_migrants = source.config.migrants_per_island
        migrants = source.get_migrants(n_migrants)

        # Elite migrants: top fraction for directed injection
        elites = []
        if self.config.elite_injection and source.local_best:
            elites = self.get_elite_migrants(source)

        for score, target in targets:
            # Measure target fitness before migration
            target_avg_before = self._island_avg_fitness(target)

            # Send regular migrants
            for migrant in migrants:
                migrant_copy = copy.deepcopy(migrant)
                target.receive_migrant(migrant_copy)
                stats["migrated"] += 1

            # Elite injection: send best individuals as directed seeds
            for elite in elites:
                elite_copy = copy.deepcopy(elite)
                target.receive_migrant(elite_copy)
                stats["elite_injected"] += 1

            # Measure target fitness after migration
            target_avg_after = self._island_avg_fitness(target)

            # Record metrics
            best_migrant_score = max(
                (m.score for m in migrants), default=float("-inf")
            )
            self.metrics.record_migration(
                source_id=source.id,
                target_id=target.id,
                migrant_score=best_migrant_score,
                target_avg_before=target_avg_before,
                target_avg_after=target_avg_after,
                is_elite=bool(elites),
                reason="fitness_gradient",
            )

            logger.debug(
                "Gradient migration: island %d → island %d "
                "(score=%.3f, migrants=%d, elites=%d, Δfitness=%.4f)",
                source.id, target.id, score, len(migrants), len(elites),
                target_avg_after - target_avg_before,
            )

        return stats


class MigrationBus:
    """Coordinador de migración entre islas.

    Supports topological migration (ring, mesh, fully_connected, spatial_grid)
    and fitness-directed gradient migration (fitness_gradient) that selects
    destinations based on fitness improvement potential + diversity gap.
    """

    def __init__(self, topology: str = "ring"):
        self.islands: Dict[int, Island] = {}
        self.topology = topology
        self._lock = threading.RLock()
        self._neighbor_cache: Dict[int, List[int]] = {}
        self._cache_version: int = 0
        self._islands_version: int = 0
        self._mesh_cols: int = 0
        self.lineage_graph = None
        # Fitness-directed migration engine (lazy init)
        self._gradient_engine: Optional[FitnessDirectedMigration] = None
        self._gradient_config: Optional[GradientConfig] = None

    @property
    def gradient_engine(self) -> FitnessDirectedMigration:
        """Lazy-initialize the fitness-directed migration engine."""
        if self._gradient_engine is None:
            self._gradient_engine = FitnessDirectedMigration(self._gradient_config)
        return self._gradient_engine

    def configure_gradient(self, config: GradientConfig) -> None:
        """Configure fitness-directed gradient migration parameters."""
        self._gradient_config = config
        self._gradient_engine = None  # Force re-init with new config

    def get_migration_metrics(self) -> Dict:
        """Return migration efficiency metrics (for benchmarks)."""
        if self._gradient_engine is not None:
            return self._gradient_engine.metrics.get_report()
        return {"total_migrations": 0, "success_rate": 0.0}

    def register_island(self, island_id: int, island: Island) -> None:
        with self._lock:
            self.islands[island_id] = island
            self._islands_version += 1
            self._neighbor_cache.clear()
            logger.debug("Island %d registered in MigrationBus.", island_id)

    def _get_neighbors(self, island_id: int) -> List[int]:
        """Calcula vecinos según topología. Debe llamarse con self._lock adquirido.

        For 'fitness_gradient' topology, returns all other islands (the gradient
        engine handles target selection in migrate()).
        """
        if self.topology == "fitness_gradient":
            # For gradient topology, return all islands as potential targets
            # (actual selection happens in migrate() via FitnessDirectedMigration)
            ids = sorted(self.islands.keys())
            return [i for i in ids if i != island_id]

        if self._cache_version == self._islands_version:
            cached = self._neighbor_cache.get(island_id)
            if cached is not None:
                return cached

        ids = sorted(self.islands.keys())
        if len(ids) < 2:
            result: List[int] = []
        elif self.topology == "ring":
            idx = ids.index(island_id)
            result = [ids[(idx - 1) % len(ids)], ids[(idx + 1) % len(ids)]]
        elif self.topology == "fully_connected":
            result = [i for i in ids if i != island_id]
        elif self.topology == "mesh":
            n = len(ids)
            cols = max(1, int(n ** 0.5))
            result = self._mesh_neighbors(island_id, ids, cols)
        elif self.topology == "spatial_grid":
            try:
                spatial = getattr(self, "spatial_topology", None)
                if spatial is None:
                    from muta_ext.spatial_topology import SpatialConfig, SpatialTopology

                    spatial = SpatialTopology(SpatialConfig(enabled=True))
                    self.spatial_topology = spatial
                result = spatial.neighbors(island_id, ids)
            except Exception:
                n = len(ids)
                cols = max(1, int(n ** 0.5))
                result = self._mesh_neighbors(island_id, ids, cols)
        else:
            candidates = [i for i in ids if i != island_id]
            return random.sample(candidates, min(2, len(candidates)))

        self._neighbor_cache[island_id] = result
        self._cache_version = self._islands_version
        return result

    def _mesh_neighbors(
        self, island_id: int, ids: List[int], cols: int
    ) -> List[int]:
        """Calcula vecinos en grid 2D para topología mesh."""
        idx = ids.index(island_id)
        row, col = divmod(idx, cols)
        neighbors: List[int] = []
        for dr, dc in [(-1, 0), (1, 0), (0, 1), (0, -1)]:
            nr, nc = row + dr, col + dc
            if 0 <= nr and 0 <= nc < cols:
                nidx = nr * cols + nc
                if nidx < len(ids):
                    neighbors.append(ids[nidx])
        return neighbors

    def migrate(self, island_id: int, generation: int) -> None:
        """Envía migrantes si el intervalo de migración se cumple.

        When topology is 'fitness_gradient', delegates to FitnessDirectedMigration
        for quality-aware target selection with fitness gradient + diversity gap.
        Otherwise uses standard topological migration.
        """
        with self._lock:
            island = self.islands.get(island_id)
            if island is None:
                return
            if generation % island.config.migration_interval != 0:
                return

            # ─── Fitness-Directed Gradient Migration ───
            if self.topology == "fitness_gradient":
                stats = self.gradient_engine.migrate(
                    island, self.islands, generation,
                )
                logger.debug(
                    "Island %d gradient migration: migrated=%d, elite=%d, skipped=%d",
                    island_id,
                    stats.get("migrated", 0),
                    stats.get("elite_injected", 0),
                    stats.get("skipped", 0),
                )
                return

            # ─── Standard Topological Migration ───
            neighbors = self._get_neighbors(island_id)
            migrants = island.get_migrants(island.config.migrants_per_island)

            for neighbor_id in neighbors:
                neighbor = self.islands.get(neighbor_id)
                if neighbor is None:
                    continue
                for migrant in migrants:
                    neighbor.receive_migrant(copy.deepcopy(migrant))

            logger.debug(
                "Island %d migrated %d individuals to %s.",
                island_id, len(migrants), neighbors,
            )

    def get_global_best(self) -> Optional[Individual]:
        """Retorna el mejor individuo global entre todas las islas."""
        with self._lock:
            best: Optional[Individual] = None
            for island in self.islands.values():
                if island.local_best is not None:
                    if best is None or island.local_best.score > best.score:
                        best = island.local_best
            return copy.deepcopy(best) if best else None
