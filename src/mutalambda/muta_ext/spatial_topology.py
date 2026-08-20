"""Spatial coevolution helpers for island neighborhoods."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class SpatialConfig:
    """Configuration for grid-based island interactions."""

    enabled: bool = False
    neighborhood: str = "moore"


@dataclass
class SpatialMetrics:
    """Spatial telemetry."""

    cluster_count: int = 0
    local_diversity_index: float = 0.0
    spatial_migration_success: float = 0.0


class SpatialTopology:
    """Computes 2D grid neighbors for structured coevolution."""

    def __init__(self, config: SpatialConfig | None = None) -> None:
        self.config = config or SpatialConfig()
        self.metrics = SpatialMetrics()

    def neighbors(self, island_id: int, ids: List[int]) -> List[int]:
        """Return direct grid neighbors using Moore or Von Neumann topology."""
        if island_id not in ids:
            return []
        n = len(ids)
        if n < 2:
            return []
        cols = max(1, math.ceil(math.sqrt(n)))
        idx = ids.index(island_id)
        row, col = divmod(idx, cols)
        offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        if self.config.neighborhood == "moore":
            offsets += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        result: List[int] = []
        for dr, dc in offsets:
            nr, nc = row + dr, col + dc
            if nr < 0 or nc < 0 or nc >= cols:
                continue
            nidx = nr * cols + nc
            if 0 <= nidx < n:
                result.append(ids[nidx])
        return result

    def update_metrics(self, islands: Dict[int, object]) -> SpatialMetrics:
        """Estimate local diversity from neighboring populations."""
        if not islands:
            self.metrics = SpatialMetrics()
            return self.metrics
        ids = sorted(islands)
        diversities: List[float] = []
        for iid in ids:
            neighbors = self.neighbors(iid, ids)
            own_codes = {getattr(ind, "code", "") for ind in getattr(islands[iid], "population", [])}
            for nid in neighbors:
                other_codes = {getattr(ind, "code", "") for ind in getattr(islands[nid], "population", [])}
                union = own_codes | other_codes
                if union:
                    diversities.append(1.0 - (len(own_codes & other_codes) / len(union)))
        self.metrics = SpatialMetrics(
            cluster_count=max(1, round(math.sqrt(len(ids)))),
            local_diversity_index=sum(diversities) / max(1, len(diversities)),
            spatial_migration_success=0.0,
        )
        return self.metrics
