"""Migration bus between evolutionary islands."""

from __future__ import annotations

import copy
import logging
import random
import threading
import types
from typing import Dict, List, Optional, TYPE_CHECKING

from island import Island

if TYPE_CHECKING:
    from muta_lambda import SolutionArchive
from models import Individual

logger = logging.getLogger("MutaLambda")


class MigrationBus:
    """Coordinador de migración entre islas."""

    def __init__(self, topology: str = "ring"):
        self.islands: Dict[int, Island] = {}
        self._lock = threading.RLock()
        self._topology: str = topology
        self._neighbor_cache: Dict[int, List[int]] = {}
        self._cache_version: int = 0
        self._islands_version: int = 0
        self._topology_version: int = 0
        self._cache_topology_version: int = -1
        self._mesh_cols: int = 0
        self.lineage_graph = None
        self.rng = random.Random()  # overridden by agent RNGSession when present

    @property
    def topology(self) -> str:
        return self._topology

    @topology.setter
    def topology(self, value: str) -> None:
        with self._lock:
            if value == self._topology:
                return
            self._topology = value
            self._topology_version += 1
            self._neighbor_cache.clear()
            logger.debug("Migration topology changed to %s; neighbor cache invalidated.", value)

    def register_island(self, island_id: int, island: Island) -> None:
        with self._lock:
            self.islands[island_id] = island
            self._islands_version += 1
            self._neighbor_cache.clear()
            logger.debug("Island %d registered in MigrationBus.", island_id)

    def _get_neighbors(self, island_id: int) -> List[int]:
        """Calcula vecinos según topología. Debe llamarse con self._lock adquirido."""
        if (
            self._cache_version == self._islands_version
            and self._cache_topology_version == self._topology_version
        ):
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
            # Random topology is intentionally dynamic and never cached.
            candidates = [i for i in ids if i != island_id]
            rng = getattr(self, "rng", random)
            return rng.sample(candidates, min(2, len(candidates)))

        self._neighbor_cache[island_id] = result
        self._cache_version = self._islands_version
        self._cache_topology_version = self._topology_version
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

        Por defecto encola en el vecino (``queue_migrant``) para aplicar al
        inicio de la siguiente generación. Si el vecino no soporta cola,
        cae a ``receive_migrant`` inmediato (compat).
        """
        self.stage_migration(island_id, generation, deferred=True)

    def stage_migration(
        self,
        island_id: int,
        generation: int,
        *,
        deferred: bool = True,
        archive=None,
    ) -> int:
        """Fase C: recolectar migrantes y encolarlos en vecinos.

        Parameters
        ----------
        deferred:
            If True (default), neighbors receive via ``queue_migrant`` so the
            population under evaluation is never mutated mid-generation.
        archive:
            Optional :class:`archive.SolutionArchive` used for diversity-aware
            migrant selection (PDF fix b/a). When provided, migrants are ranked
            by semantic distance to the destination island's population and the
            top outliers are preferred, biasing migration toward novel material
            instead of pure random sampling.
        """
        with self._lock:
            island = self.islands.get(island_id)
            if island is None:
                return 0
            if generation % max(1, island.config.migration_interval) != 0:
                return 0

            neighbors = self._get_neighbors(island_id)
            migrants = self._select_diverse_migrants(
                island, island.config.migrants_per_island, archive, neighbors
            )
            sent = 0

            for neighbor_id in neighbors:
                neighbor = self.islands.get(neighbor_id)
                if neighbor is None:
                    continue
                # Destination-island-aware diversity ranking (PDF fix b/a).
                chosen = (
                    self._rank_by_destination_diversity(migrants, neighbor, archive)
                    if archive is not None
                    else migrants
                )
                for migrant in chosen:
                    payload = copy.deepcopy(migrant)
                    if deferred and hasattr(neighbor, "queue_migrant"):
                        neighbor.queue_migrant(payload)
                    else:
                        neighbor.receive_migrant(payload)
                    sent += 1

            logger.debug(
                "Island %d staged %d migrants to %s (deferred=%s).",
                island_id, len(migrants), neighbors, deferred,
            )
            return sent

    def _select_diverse_migrants(
        self, island: "Island", count: int, archive, neighbors: List[int]
    ) -> List[Individual]:
        """Select migrants, optionally diversified via the archive.

        Falls back to plain random sampling (the historical behavior) when no
        archive is available or when the population is too small.
        """
        if not island.population:
            return []
        count = min(count, len(island.population))
        if archive is None or count == len(island.population):
            return island.rng.sample(island.population, count)
        # Rank the source island's population by archive novelty (descending).
        scored = [
            (i, archive.novelty_score(i.code, k=5))
            for i in island.population
        ]
        scored.sort(key=lambda t: t[1], reverse=True)
        top = [ind for ind, _ in scored[: len(scored)]]
        return island.rng.sample(top, count)

    def _rank_by_destination_diversity(
        self,
        migrants: List[Individual],
        destination: "Island",
        archive: SolutionArchive,
    ) -> List[Individual]:
        """Order migrant delivery so the most novel (relative to the
        destination) are delivered first. Novelty is measured via the archive's
        ``semantic_distance`` proxy (``novelty_score``), which returns the mean
        distance to the k nearest archived solutions.
        """
        try:
            scored = sorted(
                migrants,
                key=lambda m: archive.novelty_score(m.code, k=5),
                reverse=True,
            )
            return scored
        except Exception:
            # Degrade gracefully to the source order if distance scoring fails.
            return list(migrants)

    def stage_all_migrations(
        self, generation: int, *, deferred: bool = True, archive=None
    ) -> int:
        """Stage migrations for every registered island (post-barrier).

        ``archive`` is forwarded to :meth:`stage_migration` for diversity-aware
        migrant selection when a :class:`archive.SolutionArchive` is available.
        """
        total = 0
        with self._lock:
            ids = list(self.islands.keys())
        for island_id in ids:
            total += self.stage_migration(
                island_id, generation, deferred=deferred, archive=archive
            )
        return total

    def get_global_best(self) -> Optional[Individual]:
        """Retorna el mejor individuo global entre todas las islas."""
        with self._lock:
            best: Optional[Individual] = None
            for island in self.islands.values():
                if island.local_best is not None:
                    if best is None or island.local_best.score > best.score:
                        best = island.local_best
            return copy.deepcopy(best) if best else None


# ---------------------------------------------------------------------------
# FASE 1: Fitness-Directed Migration (Migration Plan v2)
# ---------------------------------------------------------------------------

class FitnessDirectedMigration:
    """Migración basada en gradiente de fitness + diversidad genética.

    En lugar de migrar según topología fija, la migración usa un gradiente:
      score = α × fitness_gradient + β × diversity_gap

    Donde:
      - fitness_gradient = fitness_destino - fitness_fuente
      - diversity_gap = 1 - similitud(code_fuente, code_destino)
    """

    def __init__(self, config: Optional[Dict] = None) -> None:
        if config is None:
            config = {
                "alpha": 0.7,
                "beta": 0.3,
                "top_k_targets": 2,
                "stagnation_threshold": 0.05,
                "elite_injection": True,
                "min_diversity_gap": 0.2,
            }
        self.alpha = config["alpha"]
        self.beta = config["beta"]
        self.top_k = config["top_k_targets"]
        self.stagnation_threshold = config["stagnation_threshold"]
        self.elite_injection = config["elite_injection"]
        self.min_diversity_gap = config["min_diversity_gap"]

    # ------------------------------------------------------------------
    # Helper: code similarity (1 = identical, 0 = unrelated)
    # ------------------------------------------------------------------

    @staticmethod
    def _code_similarity(hash_a: str, hash_b: str) -> float:
        """Simple Jaccard-like similarity based on code hash prefixes.

        In a production system this would use AST-based semantic similarity,
        but hash prefix overlap is a fast proxy.
        """
        if hash_a == hash_b:
            return 1.0
        # Use first 8 hex chars as a quick shingle
        set_a = set(hash_a[:8])
        set_b = set(hash_b[:8])
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union else 0.0

    # ------------------------------------------------------------------
    # Core: select targets based on fitness gradient + diversity
    # ------------------------------------------------------------------

    def select_targets(
        self,
        source_island: "Island",
        all_islands: Dict[int, "Island"],
    ) -> List["Island"]:
        """Selecciona destinos basándose en fitness gradient + diversity gap.

        Returns the top‑k islands with highest migration score.
        """
        source_fitness = source_island.avg_fitness
        source_hash = source_island.dominant_code_signature()

        scored_targets: List[tuple[float, "Island"]] = []
        for target_id, target in all_islands.items():
            if target_id == source_island.id:
                continue
            fitness_grad = target.avg_fitness - source_fitness
            diversity_gap = 1.0 - self._code_similarity(
                source_hash, target.dominant_code_signature()
            )
            score = self.alpha * fitness_grad + self.beta * diversity_gap
            # Only consider if diversity gap exceeds minimum threshold
            if diversity_gap >= self.min_diversity_gap:
                scored_targets.append((score, target))

        # Sort descending by score and take top-k
        scored_targets.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored_targets[: self.top_k]]

    # ------------------------------------------------------------------
    # Core: migrate selected migrants + optional elite injection
    # ------------------------------------------------------------------

    def migrate(
        self,
        source: "Island",
        targets: List["Island"],
        migrants: List["Individual"],
    ) -> None:
        """Envía migrantes solo a targets seleccionados + elite injection.

        Elite injection: el mejor individuo del donante se inyecta como
        "semilla dirigida" a cada destino.
        """
        # Send regular migrants to each target
        for target in targets:
            for migrant in migrants:
                target.receive_migrant(copy.deepcopy(migrant))

        # Elite injection (top individual from source)
        if self.elite_injection and source.local_best is not None:
            elite = copy.deepcopy(source.local_best)
            elite.tags.add("elite_injection")
            for target in targets:
                target.receive_migrant(elite)

    # ------------------------------------------------------------------
    # Public API: run directed migration for one island
    # ------------------------------------------------------------------

    def run(
        self,
        source_id: int,
        all_islands: Dict[int, "Island"],
        migration_bus: "MigrationBus",
    ) -> int:
        """Ejecuta migración dirigida para una isla fuente.

        Returns the number of migrants sent.
        """
        source = migration_bus.islands.get(source_id)
        if source is None or not source.population:
            return 0

        # Check stagnation: only migrate if there's fitness improvement potential
        # (or if we want to always migrate, we skip this check)
        targets = self.select_targets(source, all_islands)

        if not targets:
            return 0

        # Select migrants: top performers from source population
        count = min(source.config.migrants_per_island, len(source.population))
        if count <= 0:
            return 0

        # Sample migrants from source population (could be diversity-aware)
        migrants = source.rng.sample(source.population, min(count, len(source.population)))

        # Perform directed migration
        self.migrate(source, targets, migrants)

        logger.debug(
            "Fitness-directed migration: island %d → %d targets, %d migrants",
            source_id,
            len(targets),
            len(migrants),
        )
        return len(migrants)


# ---------------------------------------------------------------------------
# MigrationBus integration: add directed migration method
# ---------------------------------------------------------------------------

_MIGRATION_STRATEGIES = {
    "ring": None,
    "fully_connected": None,
    "mesh": None,
    "spatial_grid": None,
    "fitness_gradient": "FitnessDirectedMigration",
}


def _get_migration_strategy(
    topology: str,
) -> type | None:
    """Return the migration class for the given topology, or None."""
    strategy_name = _MIGRATION_STRATEGIES.get(topology)
    if strategy_name is None:
        return None
    # Lazy import to avoid circular dependencies
    try:
        from .migration import FitnessDirectedMigration  # type: ignore[no-redef]
        return FitnessDirectedMigration()
    except ImportError:
        return None


MigrationBus._fitness_directed_migration: Optional[FitnessDirectedMigration] = (  # type: ignore[assignment]


)


def set_fitness_directed_migration(config: Optional[Dict] = None) -> None:
    """Enable fitness-directed migration on the MigrationBus.

    Parameters
    ----------
    config : dict, optional
        Parameters for FitnessDirectedMigration (alpha, beta, top_k, etc.).
        See :class:`FitnessDirectedMigration` for details.
    """
    from .migration import FitnessDirectedMigration  # noqa: F811

    MigrationBus._fitness_directed_migration = FitnessDirectedMigration(config)  # type: ignore[assignment]


MigrationBus.fitness_directed_migration = property(  # type: ignore[assignment]
    lambda self: self._fitness_directed_migration  # type: ignore[return-value]
)


def _validate_topology_fitness_directed(self) -> bool:
    """Validate that the topology is suitable for fitness-directed migration.

    Returns True if the topology should use fitness-directed migration instead
    of the default neighbor selection.
    """
    return self._topology == "fitness_gradient"


# Modify the _get_neighbors method to support fitness_gradient topology
# We'll wrap the original method and add support

_original_get_neighbors = MigrationBus._get_neighbors


def _get_neighbors_fitness_gradient(self, island_id: int) -> List[int]:
    """_get_neighbors implementation for fitness_gradient topology.

    Instead of geometric neighbors, returns islands with highest migration score.
    """
    ids = sorted(self.islands.keys())
    if len(ids) < 2:
        return []

    # Use FitnessDirectedMigration to select targets
    if self._fitness_directed_migration is None:
        return []

    # Select top targets (we'll pick 2 targets by default)
    all_ids = list(self.islands.keys())
    targets = self._fitness_directed_migration.select_targets(
        self.islands.get(island_id, None),  # type: ignore[arg-type]
        {iid: self.islands[iid] for iid in all_ids},  # type: ignore[arg-type]
    )

    # Return target island IDs
    target_ids = [t.id for t in targets]
    # Cache and return
    self._neighbor_cache[island_id] = target_ids
    self._cache_version = self._islands_version
    self._cache_topology_version = self._topology_version
    return target_ids


# Replace _get_neighbors with the fitness-gradient version when topology is set
MigrationBus._get_neighbors = types.MethodType(_get_neighbors_fitness_gradient, MigrationBus)  # type: ignore[assignment]

import types  # noqa: E402 # added after class definition


# ---------------------------------------------------------------------------
# Convenience function to register standard metrics for fitness-directed migration
# ---------------------------------------------------------------------------

def record_fitness_directed_migration(
    source_id: int,
    target_count: int,
    migrant_count: int,
    registry: Optional[MetricsRegistry] = None,
) -> None:
    """Record fitness-directed migration metrics.

    Parameters
    ----------
    source_id : int
        Source island ID.
    target_count : int
        Number of target islands selected.
    migrant_count : int
        Number of migrants sent.
    registry : MetricsRegistry, optional
        Metrics registry. Defaults to the module-level singleton.
    """
    from metrics_exporter import get_registry

    reg = registry or get_registry()
    reg.counter("migration_directed_total").inc()
    reg.gauge("migration_directed_targets").set(float(target_count))
    reg.gauge("migration_directed_migrants").set(float(migrant_count))
    reg.gauge("migration_directed_source").set(float(source_id))
