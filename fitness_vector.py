"""
FitnessVector — Multi-objective fitness for MutaLambda evolution engine.

Simplified 3-objective design (2.0):
- Correctness (0.0 - 1.0): MUST pass all tests
- Latency_P50 (ms): median execution time
- Memory_Peak (MB): peak memory usage

Advanced metrics (P99, Throughput, Parsimony) moved to diagnostics.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


# Default weights for weighted-sum scalarisation.
# With 3 objectives, selective pressure remains strong.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "correctness":    1.00,
    "latency_p50":   -0.15,
    "memory_peak_mb":-0.10,
}

# Reference costs for normalizing absolute units (milliseconds / MiB) into
# dimensionless penalties in FitnessVector.to_scalar(). A candidate costing
# exactly these references pays RESOURCE_PENALTY_WEIGHT points; the total
# penalty is capped so resource terms can never outweigh correctness ordering.
REF_LATENCY_MS: float = 500.0
REF_MEMORY_MB: float = 64.0
RESOURCE_PENALTY_WEIGHT: float = 0.05
MAX_RESOURCE_PENALTY: float = 0.25


@dataclass
class FitnessVector:
    """Three-dimensional multi-objective fitness for Pareto optimization.

    Objectives follow "higher is better" convention for Pareto operations.
    Latency and memory are negated internally in dominates()/weighted_sum().

    Attributes
    ----------
    correctness : float
        0.0 – 1.0 fraction of test-cases passed. **Hard gate**: < 1.0 ranks
        below every fully-correct candidate.
    latency_p50 : float
        Median wall-clock milliseconds per evaluation. Lower → better.
    memory_peak_mb : float
        Peak RSS in MiB. Lower → better.
    """

    correctness: float = 0.0
    latency_p50: float = 0.0
    memory_peak_mb: float = 0.0

    # Legacy fields (deprecated, kept for backward compatibility)
    latency_p99: float = 0.0
    throughput: float = 0.0
    parsimony: float = 0.0


    def is_worst(self) -> bool:
        """Check if this is worst possible fitness."""
        return (self.correctness == 0.0 and 
                self.latency_p50 == float('inf') and
                self.memory_peak_mb == float('inf'))

    def is_best(self) -> bool:
        """Check if this is best possible fitness."""
        return (self.correctness == 1.0 and 
                self.latency_p50 == 0.0 and
                self.memory_peak_mb == 0.0)

    def is_perfect(self) -> bool:
        """Check if correctness is perfect."""
        return self.correctness >= 1.0

    # ── Pareto dominance ─────────────────────────────────────────────────

    def dominates(self, other: "FitnessVector") -> bool:
        """Return True if *self* Pareto-dominates *other*.

        Latency and memory are negated so "greater is better" holds.
        """
        self_vals = (self.correctness, -self.latency_p50, -self.memory_peak_mb)
        other_vals = (other.correctness, -other.latency_p50, -other.memory_peak_mb)

        at_least_one_better = False
        for s, o in zip(self_vals, other_vals):
            if s < o:
                return False
            if s > o:
                at_least_one_better = True
        return at_least_one_better

    # ── Scalarization ───────────────────────────────────────────────────

    def to_scalar(self) -> float:
        """Convert to scalar score. Correctness is a hard gate."""
        if self.correctness < 1.0:
            return self.correctness - 1.0  # All imperfect solutions rank below perfect

        # Weighted sum over *normalized* objectives. Raw absolute units
        # (milliseconds / MiB) previously dominated correctness units and sank
        # fully-correct candidates below the -1.0 floor reserved for broken
        # ones, inverting selection pressure (evolution preferred crashing code).
        latency_norm = max(0.0, self.latency_p50) / REF_LATENCY_MS
        memory_norm = max(0.0, self.memory_peak_mb) / REF_MEMORY_MB
        penalty = min(
            MAX_RESOURCE_PENALTY,
            RESOURCE_PENALTY_WEIGHT * (latency_norm + memory_norm),
        )
        return DEFAULT_WEIGHTS["correctness"] * self.correctness - penalty

    def weighted_sum(self) -> float:
        """Alias for to_scalar()."""
        return self.to_scalar()

    # ── Comparison ──────────────────────────────────────────────────────

    def __lt__(self, other: "FitnessVector") -> bool:
        return self.to_scalar() < other.to_scalar()

    def __gt__(self, other: "FitnessVector") -> bool:
        return self.to_scalar() > other.to_scalar()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FitnessVector):
            return NotImplemented
        return (self.correctness == other.correctness and 
                self.latency_p50 == other.latency_p50 and
                self.memory_peak_mb == other.memory_peak_mb)

    def __repr__(self) -> str:
        return (f"FitnessVector(correct={self.correctness:.2f}, "
                f"latency={self.latency_p50:.2f}ms, "
                f"memory={self.memory_peak_mb:.2f}MB)")

    # ── Serialization ───────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, float]:
        return {
            "correctness": self.correctness,
            "latency_p50": self.latency_p50,
            "memory_peak_mb": self.memory_peak_mb,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "FitnessVector":
        return cls(
            correctness=data.get("correctness", 0.0),
            latency_p50=data.get("latency_p50", 0.0),
            memory_peak_mb=data.get("memory_peak_mb", 0.0),
        )




    @classmethod
    def worst(cls) -> "FitnessVector":
        """Return worst possible fitness (for initialization)."""
        return cls(correctness=0.0, latency_p50=float('inf'), memory_peak_mb=float('inf'))

    @classmethod
    def best(cls) -> "FitnessVector":
        """Return best possible fitness (for initialization)."""
        return cls(correctness=1.0, latency_p50=0.0, memory_peak_mb=0.0)

    @classmethod
    def from_metrics(cls, correctness: float, latency_ms: float, 
                     memory_mb: float, **kwargs) -> "FitnessVector":
        """Create from raw metrics."""
        return cls(correctness=correctness, latency_p50=latency_ms,
                  memory_peak_mb=memory_mb, **kwargs)

# ── NSGA-II Helpers ─────────────────────────────────────────────────────────

def non_dominated_sort(population: list) -> list:
    """Fast non-dominated sort (NSGA-II). Returns list of fronts."""
    if not population:
        return []

    fronts = [[]]
    dom_count = {}  # number of solutions dominating this one
    dom_set = {}   # solutions this one dominates

    for i, p in enumerate(population):
        dom_count[i] = 0
        dom_set[i] = []

        for j, q in enumerate(population):
            if i == j:
                continue
            if p.fitness and q.fitness:
                if p.fitness.dominates(q.fitness):
                    dom_set[i].append(j)
                elif q.fitness.dominates(p.fitness):
                    dom_count[i] += 1

        if dom_count[i] == 0:
            fronts[0].append(i)

    current_front = 0
    while fronts[current_front]:
        next_front = []
        for i in fronts[current_front]:
            for j in dom_set[i]:
                dom_count[j] -= 1
                if dom_count[j] == 0:
                    next_front.append(j)
        current_front += 1
        fronts.append(next_front)

    # Remove empty last front
    if not fronts[-1]:
        fronts.pop()

    return fronts


def crowding_distance(population: list, front: list) -> dict:
    """Compute crowding distance for a front."""
    if len(front) <= 2:
        return {i: float('inf') for i in front}

    distance = {i: 0.0 for i in front}

    objectives = ['correctness', 'latency_p50', 'memory_peak_mb']

    for obj in objectives:
        # Sort by objective
        sorted_front = sorted(front, key=lambda i: getattr(population[i].fitness, obj))

        # Boundary points get infinite distance
        distance[sorted_front[0]] = float('inf')
        distance[sorted_front[-1]] = float('inf')

        # Compute for intermediate points
        obj_min = getattr(population[sorted_front[0]].fitness, obj)
        obj_max = getattr(population[sorted_front[-1]].fitness, obj)
        obj_range = obj_max - obj_min

        if obj_range == 0:
            continue

        for i in range(1, len(sorted_front) - 1):
            prev_val = getattr(population[sorted_front[i-1]].fitness, obj)
            next_val = getattr(population[sorted_front[i+1]].fitness, obj)
            distance[sorted_front[i]] += (next_val - prev_val) / obj_range

    return distance
