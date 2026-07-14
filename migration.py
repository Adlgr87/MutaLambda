"""Migration bus between evolutionary islands."""

from __future__ import annotations

import copy
import logging
import random
import threading
from typing import Dict, List, Optional

from island import Island
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
            return random.sample(candidates, min(2, len(candidates)))

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
    ) -> int:
        """Fase C: recolectar migrantes y encolarlos en vecinos.

        Parameters
        ----------
        deferred:
            If True (default), neighbors receive via ``queue_migrant`` so the
            population under evaluation is never mutated mid-generation.
        """
        with self._lock:
            island = self.islands.get(island_id)
            if island is None:
                return 0
            if generation % max(1, island.config.migration_interval) != 0:
                return 0

            neighbors = self._get_neighbors(island_id)
            migrants = island.get_migrants(island.config.migrants_per_island)
            sent = 0

            for neighbor_id in neighbors:
                neighbor = self.islands.get(neighbor_id)
                if neighbor is None:
                    continue
                for migrant in migrants:
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

    def stage_all_migrations(self, generation: int, *, deferred: bool = True) -> int:
        """Stage migrations for every registered island (post-barrier)."""
        total = 0
        with self._lock:
            ids = list(self.islands.keys())
        for island_id in ids:
            total += self.stage_migration(island_id, generation, deferred=deferred)
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
