"""
NSGA-II — Non-dominated Sorting Genetic Algorithm II for MutaLambda.

Replaces elitist scalar selection with Pareto-based multi-objective
optimisation.  Works directly with FitnessVector from Phase 1.

Algorithm
---------
1. Non-dominated sorting: assign fronts (rank 0 = Pareto frontier)
2. Crowding distance: diversity preservation within each front
3. Tournament selection: prefer lower rank, then higher crowding
4. Elitism: preserve best fronts for next generation

Reference
---------
Deb, K., et al. "A Fast and Elitist Multiobjective Genetic Algorithm:
NSGA-II." IEEE Trans. Evol. Comput., 2002.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from fitness_vector import FitnessVector
from muta_lambda import Individual, logger


@dataclass
class ParetoFront:
    """A non-dominated front with rank and crowding distances."""
    rank: int
    individuals: List[Individual]
    crowding: List[float] = field(default_factory=list)


def non_dominated_sort(population: List[Individual]) -> List[ParetoFront]:
    """
    Fast non-dominated sorting (Deb 2002).

    Returns fronts sorted by rank (0 = Pareto frontier).
    Each individual must have a FitnessVector accessible via ind.score
    or ind.fitness attribute.
    """
    n = len(population)
    if n == 0:
        return []

    # Dominance counts
    dominated_by: List[int] = [0] * n         # how many dominate this ind
    dominates: List[List[int]] = [[] for _ in range(n)]  # which inds this dominates

    for i in range(n):
        fi = _get_fitness(population[i])
        for j in range(i + 1, n):
            fj = _get_fitness(population[j])
            if fi.dominates(fj):
                dominates[i].append(j)
                dominated_by[j] += 1
            elif fj.dominates(fi):
                dominates[j].append(i)
                dominated_by[i] += 1

    # Fronts
    fronts: List[ParetoFront] = []
    front_indices: List[int] = [i for i, d in enumerate(dominated_by) if d == 0]

    while front_indices:
        front_inds = [
            population[i] for i in front_indices
        ]
        crowding = _crowding_distance(front_inds)
        fronts.append(ParetoFront(
            rank=len(fronts),
            individuals=front_inds,
            crowding=crowding,
        ))

        next_front: List[int] = []
        for i in front_indices:
            for j in dominates[i]:
                dominated_by[j] -= 1
                if dominated_by[j] == 0:
                    next_front.append(j)
        front_indices = next_front

    return fronts


def nsga2_select(
    population: List[Individual],
    top_k: int,
) -> List[Individual]:
    """
    NSGA-II selection: preserve diversity while optimising all objectives.

    Returns top_k individuals selected via:
      1. Non-dominated sort
      2. Crowding distance within each front
      3. Fill slots front-by-front until top_k reached
    """
    if len(population) <= top_k:
        return list(population)

    fronts = non_dominated_sort(population)
    selected: List[Individual] = []

    for front in fronts:
        remaining = top_k - len(selected)
        if len(front.individuals) <= remaining:
            selected.extend(front.individuals)
        else:
            # Sort by crowding distance (descending) within this front
            paired = list(zip(front.crowding, front.individuals))
            paired.sort(key=lambda x: x[0], reverse=True)
            selected.extend(ind for _, ind in paired[:remaining])
            break

    return selected


def nsga2_tournament_select(
    elites: List[Individual],
    num_parents: int,
    tournament_size: int = 2,
) -> List[Individual]:
    """
    Tournament selection for breeding: prefer lower NSGA-II rank
    and higher crowding distance.

    Parameters
    ----------
    elites : list
        Pre-sorted by NSGA-II (already fronts).
    num_parents : int
        Number of parents to select.
    tournament_size : int
        Tournament size (default 2).
    """
    import random
    selected: List[Individual] = []

    if not elites:
        return selected

    fronts = non_dominated_sort(elites)
    # Build rank map
    rank_map: Dict[str, int] = {}
    crowd_map: Dict[str, float] = {}
    for front in fronts:
        for ind, cd in zip(front.individuals, front.crowding):
            rank_map[ind.id] = front.rank
            crowd_map[ind.id] = cd

    for _ in range(num_parents):
        tournament = random.sample(
            elites, min(tournament_size, len(elites))
        )
        # Winner: lower rank, break ties with higher crowding
        winner = min(
            tournament,
            key=lambda ind: (rank_map.get(ind.id, 999), -crowd_map.get(ind.id, 0.0)),
        )
        selected.append(winner)

    return selected


# ── Helpers ────────────────────────────────────────────────────────────

def _get_fitness(ind: Individual) -> FitnessVector:
    """Extract FitnessVector from Individual, falling back to constructing one."""
    if hasattr(ind, 'fitness') and ind.fitness is not None:
        return ind.fitness  # type: ignore[return-value]
    # Fallback: treat scalar score as correctness, rest unknown
    return FitnessVector(
        correctness=max(0.0, min(1.0, ind.score / 100.0)),
        parsimony=0.5,
    )


def _crowding_distance(individuals: List[Individual]) -> List[float]:
    """
    Crowding distance for diversity preservation (Deb 2002).

    Measures how isolated each individual is in objective space.
    Higher = more isolated = better for diversity.
    """
    n = len(individuals)
    if n <= 2:
        return [float("inf")] * n

    distances = [0.0] * n

    # For each objective dimension
    dims = ["correctness", "latency_p50", "latency_p99",
            "throughput", "memory_peak_mb", "parsimony"]

    for dim in dims:
        # Sort by this dimension
        values = [(i, getattr(_get_fitness(ind), dim, 0.0))
                   for i, ind in enumerate(individuals)]
        values.sort(key=lambda x: x[1])

        min_val = values[0][1]
        max_val = values[-1][1]
        obj_range = max_val - min_val

        if obj_range < 1e-9:
            continue  # no diversity in this dimension

        # Boundary points get infinite distance
        distances[values[0][0]] = float("inf")
        distances[values[-1][0]] = float("inf")

        # Interior points
        for k in range(1, n - 1):
            distances[values[k][0]] += (
                (values[k + 1][1] - values[k - 1][1]) / obj_range
            )

    return distances


def get_pareto_frontier(population: List[Individual]) -> List[Individual]:
    """Return the Pareto frontier (rank 0 individuals)."""
    fronts = non_dominated_sort(population)
    if not fronts:
        return []
    return fronts[0].individuals


def get_nsga2_stats(population: List[Individual]) -> Dict:
    """NSGA-II telemetry for logging and dashboard."""
    fronts = non_dominated_sort(population)
    frontier_size = len(fronts[0].individuals) if fronts else 0
    return {
        "num_fronts": len(fronts),
        "pareto_frontier_size": frontier_size,
        "mean_crowding": (
            sum(fronts[0].crowding) / max(1, len(fronts[0].crowding))
            if fronts and fronts[0].crowding else 0.0
        ),
    }
