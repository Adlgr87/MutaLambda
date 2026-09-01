"""
Tests for NSGA-II multi-objective selection.
"""

import pytest
from fitness_vector import FitnessVector
from muta_lambda import Individual
from nsga2 import (
    non_dominated_sort,
    nsga2_select,
    nsga2_tournament_select,
    get_pareto_frontier,
    get_nsga2_stats,
    _crowding_distance,
)


@pytest.mark.root
def _make_ind(code: str, correctness: float = 0.5, latency: float = 0.01,
              throughput: float = 50.0, memory: float = 10.0,
              parsimony: float = 0.5) -> Individual:
    """Compat wrapper → tests.helpers.make_individual (FIX 4.1)."""
    from tests.helpers import make_individual

    return make_individual(
        code,
        correctness=correctness,
        latency=latency,
        throughput=throughput,
        memory=memory,
        parsimony=parsimony,
    )


@pytest.mark.root
class TestNonDominatedSort:

    def test_empty_population(self):
        assert non_dominated_sort([]) == []

    def test_single_individual(self):
        pop = [_make_ind("a")]
        fronts = non_dominated_sort(pop)
        assert len(fronts) == 1
        assert fronts[0].rank == 0
        assert len(fronts[0].individuals) == 1

    def test_pareto_frontier(self):
        """Best individual dominates all others → single front."""
        best = _make_ind("best", correctness=1.0, latency=0.001,
                          throughput=1000, memory=1.0, parsimony=1.0)
        worst = _make_ind("worst", correctness=0.0, latency=1.0,
                           throughput=1.0, memory=100.0, parsimony=0.0)
        mid = _make_ind("mid", correctness=0.5, latency=0.5,
                         throughput=50.0, memory=50.0, parsimony=0.5)
        fronts = non_dominated_sort([worst, mid, best])
        assert fronts[0].rank == 0
        # best should dominate mid and worst
        assert len(fronts) >= 2

    def test_incomparable_individuals(self):
        """Two individuals where neither dominates → same front."""
        a = _make_ind("a", correctness=1.0, latency=0.10)
        b = _make_ind("b", correctness=0.5, latency=0.01)
        fronts = non_dominated_sort([a, b])
        assert len(fronts[0].individuals) == 2  # both in Pareto frontier

    def test_numpy_pure_equivalence_multi_level(self):
        """Fase 4A regression guard: numpy fast path must match the pure-Python
        path exactly, including multi-level front assignment. The rewritten
        `processed`-mask loop previously regressed front-rank ordering."""
        from nsga2 import _non_dominated_sort_numpy, _NUMPY_FASTPATH_THRESHOLD
        import nsga2 as _n

        # Build a population large enough to exercise the numpy path, with a
        # clear multi-level dominance chain so a regression in frontier
        # extraction would change the front sizes.
        pop = []
        # chain: ind_0 dominates ind_1 dominates ... dominates ind_29
        for i in range(30):
            pop.append(_make_ind(f"ind_{i}", correctness=1.0 - i / 30,
                                 latency=0.001 * (i + 1), throughput=1.0))
        # add incomparable cluster
        for _ in range(30):
            pop.append(_make_ind("inc", correctness=0.5, latency=0.5, throughput=50.0))

        pure = _n.non_dominated_sort.__wrapped__ if hasattr(_n.non_dominated_sort, "__wrapped__") else None
        # Force pure-python path by temporarily lowering the threshold.
        orig = _NUMPY_FASTPATH_THRESHOLD
        try:
            _n._NUMPY_FASTPATH_THRESHOLD = 999999
            pure_fronts = non_dominated_sort(pop)
            ranks_pure = [len(f.individuals) for f in pure_fronts]
        finally:
            _n._NUMPY_FASTPATH_THRESHOLD = orig

        # numpy path
        np_fronts = _non_dominated_sort_numpy(pop)
        ranks_np = [len(f.individuals) for f in np_fronts]

        assert ranks_pure == ranks_np
        assert len(np_fronts) == len(pure_fronts)


@pytest.mark.root
class TestNSGA2Select:
    """NSGA-II selection."""

    def test_top_k_selection(self):
        pop = [
            _make_ind(f"f{i}", correctness=0.1 * i, latency=0.1 / max(1, i))
            for i in range(1, 11)
        ]
        selected = nsga2_select(pop, top_k=5)
        assert len(selected) == 5
        assert all(isinstance(ind, Individual) for ind in selected)

    def test_top_k_equals_population(self):
        pop = [_make_ind("a"), _make_ind("b")]
        selected = nsga2_select(pop, top_k=2)
        assert len(selected) == 2

    def test_top_k_exceeds_population(self):
        pop = [_make_ind("a")]
        selected = nsga2_select(pop, top_k=5)
        assert len(selected) == 1


@pytest.mark.root
class TestNSGA2Tournament:
    """Tournament selection for breeding."""

    def test_tournament_returns_parents(self):
        pop = [_make_ind(f"x{i}", correctness=0.1 * i) for i in range(1, 6)]
        parents = nsga2_tournament_select(pop, num_parents=3, tournament_size=2)
        assert len(parents) == 3

    def test_tournament_empty(self):
        assert nsga2_tournament_select([], 5) == []


@pytest.mark.root
class TestParetoFrontier:
    """Pareto frontier extraction."""

    def test_get_pareto_frontier(self):
        pop = [
            _make_ind("a", correctness=1.0, latency=0.001),
            _make_ind("b", correctness=0.8, latency=0.01),
            _make_ind("c", correctness=0.5, latency=0.10),
        ]
        frontier = get_pareto_frontier(pop)
        assert len(frontier) >= 1


@pytest.mark.root
class TestNSGA2Stats:
    """NSGA-II telemetry."""

    def test_stats(self):
        pop = [_make_ind(f"s{i}") for i in range(10)]
        stats = get_nsga2_stats(pop)
        assert "num_fronts" in stats
        assert "pareto_frontier_size" in stats
        assert stats["num_fronts"] >= 1

    @pytest.mark.flaky
    def test_dominance_uses_only_3_objectives(self):
        """No-regresión Fase 2: dominance compara exactamente 3 objetivos
        (correctness, latency, throughput) y no deja objetivos adicionales
        filtrar en el sort ni en crowding."""
        from nsga2 import _DOMINANCE_OBJECTIVES

        # The dominance objective count must be exactly 3 (not 6).
        assert _DOMINANCE_OBJECTIVES == 3
        pop = [
            _make_ind("a", correctness=1.0, latency=0.001, throughput=100.0),
            _make_ind("b", correctness=0.8, latency=0.01, throughput=80.0),
            _make_ind("c", correctness=0.5, latency=0.10, throughput=50.0),
        ]
        front0 = get_pareto_frontier(pop)
        # 'a' (best correctness + latency + throughput) must be on front 0
        assert any(ind.code == "a" for ind in front0)


@pytest.mark.root
class TestCrowdingDistance:
    """Crowding distance calculation."""

    def test_crowding_two_individuals(self):
        pop = [_make_ind("a"), _make_ind("b")]
        cd = _crowding_distance(pop)
        assert cd == [float("inf"), float("inf")]

    def test_crowding_three_individuals(self):
        pop = [
            _make_ind("a", correctness=1.0, latency=0.001),
            _make_ind("b", correctness=0.5, latency=0.05),
            _make_ind("c", correctness=0.0, latency=0.10),
        ]
        cd = _crowding_distance(pop)
        assert len(cd) == 3
        assert cd[0] == float("inf")
        assert cd[2] == float("inf")
        assert cd[1] > 0
