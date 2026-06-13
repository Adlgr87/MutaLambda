"""
Tests for Convergent Evolution Boost (cross-island consensus).
"""

import pytest
from unittest.mock import MagicMock
from muta_lambda import (
    Individual,
    Island,
    IslandConfig,
    MutaLambdaAgent,
    EvolveConfig,
    FitnessVector,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_individual(code: str, score: float = 10.0) -> Individual:
    """Create a minimal individual for boost tests."""
    return Individual(
        code=code,
        score=score,
        fitness=FitnessVector(correctness=score / 10.0),
    )


def _make_island(island_id: int, pop_size: int = 4,
                 best_code: str = "x + 1") -> Island:
    """Create an island with mocked dependencies and a known population."""
    config = IslandConfig(population_size=pop_size, top_k=2)
    llm_fn = MagicMock(return_value=best_code)
    evaluator = MagicMock()
    mig_bus = MagicMock()

    isl = Island(
        island_id=island_id,
        config=config,
        llm_fn=llm_fn,
        evaluator=evaluator,
        migration_bus=mig_bus,
    )
    isl.population = [_make_individual(f"{best_code} # var{i}", 10.0 + i * 0.1)
                      for i in range(pop_size)]
    isl.local_best = max(isl.population, key=lambda x: x.score)
    return isl


def _make_agent(config: EvolveConfig, similarity: float = 0.95) -> MutaLambdaAgent:
    """Create an agent with _code_similarity patched to a fixed value."""
    agent = MutaLambdaAgent(config, lambda: "test_spec()")
    agent._code_similarity = MagicMock(return_value=similarity)
    return agent


# ── Tests ──────────────────────────────────────────────────────────────────


def test_boost_applied_when_similar():
    """When 2+ islands have highly similar local_bests, scores get boosted."""
    config = EvolveConfig(
        num_islands=2,
        convergent_boost_enabled=True,
        convergent_boost_threshold=0.85,
        convergent_boost_factor=0.15,
    )
    agent = _make_agent(config, similarity=0.95)  # sim > threshold

    isl_a = _make_island(island_id=0, pop_size=3, best_code="def f(x): return x + 1")
    isl_b = _make_island(island_id=1, pop_size=3, best_code="def f(x): return x + 2")
    agent.islands = [isl_a, isl_b]

    orig_scores_a = [ind.score for ind in isl_a.population]
    orig_scores_b = [ind.score for ind in isl_b.population]

    stats = agent._apply_convergent_boost()

    assert stats["boosted"] == 6   # 3 per island
    assert stats["pairs"] == 1     # one pair of islands

    for orig, ind in zip(orig_scores_a, isl_a.population):
        assert ind.score > orig
    for orig, ind in zip(orig_scores_b, isl_b.population):
        assert ind.score > orig

    assert isl_a.local_best is not None
    assert isl_b.local_best is not None


def test_boost_skipped_when_different():
    """When code similarity is below threshold, no boost is applied."""
    config = EvolveConfig(
        num_islands=2,
        convergent_boost_enabled=True,
        convergent_boost_threshold=0.85,
        convergent_boost_factor=0.15,
    )
    agent = _make_agent(config, similarity=0.30)  # sim < threshold

    isl_a = _make_island(island_id=0, pop_size=3, best_code="def f(x): return x + 1")
    isl_b = _make_island(island_id=1, pop_size=3, best_code="import os; os.system('ls')")
    agent.islands = [isl_a, isl_b]

    orig_scores_a = [ind.score for ind in isl_a.population]
    orig_scores_b = [ind.score for ind in isl_b.population]

    stats = agent._apply_convergent_boost()

    assert stats["boosted"] == 0
    assert stats["pairs"] == 0

    for orig, ind in zip(orig_scores_a, isl_a.population):
        assert ind.score == orig
    for orig, ind in zip(orig_scores_b, isl_b.population):
        assert ind.score == orig


def test_boost_disabled():
    """When convergent_boost_enabled=False, no boost even if identical code."""
    config = EvolveConfig(
        num_islands=2,
        convergent_boost_enabled=False,
        convergent_boost_threshold=0.85,
        convergent_boost_factor=0.15,
    )
    agent = _make_agent(config, similarity=0.99)

    isl_a = _make_island(island_id=0, pop_size=2, best_code="def f(x): return x")
    isl_b = _make_island(island_id=1, pop_size=2, best_code="def f(x): return x")
    agent.islands = [isl_a, isl_b]

    orig_scores_a = [ind.score for ind in isl_a.population]
    stats = agent._apply_convergent_boost()

    assert stats["boosted"] == 0
    for orig, ind in zip(orig_scores_a, isl_a.population):
        assert ind.score == orig


def test_single_island_no_boost():
    """With only 1 island, no boost (minimum 2 for convergence check)."""
    config = EvolveConfig(
        num_islands=2,
        convergent_boost_enabled=True,
    )
    agent = _make_agent(config, similarity=0.99)

    isl_a = _make_island(island_id=0, pop_size=2, best_code="def f(x): return x")
    agent.islands = [isl_a]

    stats = agent._apply_convergent_boost()
    assert stats["boosted"] == 0
    assert stats["pairs"] == 0


def test_code_similarity_fallback_no_archive():
    """_code_similarity works with Jaccard fallback when no archive."""
    config = EvolveConfig()
    agent = MutaLambdaAgent(config, lambda: "test_spec()")
    agent.archive = None

    sim = agent._code_similarity("def f(x): return x + 1", "def f(x): return x + 1")
    assert sim == 1.0

    sim = agent._code_similarity("abcdef", "xyz  123  456")
    assert sim < 0.3

    assert agent._code_similarity("", "something") == 0.0
    assert agent._code_similarity("", "") == 1.0


def test_recompute_local_best():
    """Island.recompute_local_best picks the highest score after external change."""
    isl = _make_island(island_id=0, pop_size=3, best_code="code_a")
    orig_best = isl.local_best

    non_best = isl.population[0]
    if non_best is orig_best:
        non_best = isl.population[1]
    non_best.score *= 100.0

    isl.recompute_local_best()
    assert isl.local_best is not orig_best
    assert isl.local_best.score == non_best.score


def test_large_population_boost():
    """Boost scales correctly with larger populations across islands."""
    config = EvolveConfig(
        num_islands=4,
        convergent_boost_enabled=True,
        convergent_boost_threshold=0.80,
        convergent_boost_factor=0.20,
    )
    agent = _make_agent(config, similarity=0.90)  # > threshold

    agent.islands = []
    for i in range(4):
        isl = _make_island(island_id=i, pop_size=8,
                           best_code=f"def f(x): return x + {i}")
        agent.islands.append(isl)

    orig_scores = [
        [ind.score for ind in isl.population]
        for isl in agent.islands
    ]

    stats = agent._apply_convergent_boost()

    # 4 islands → C(4,2) = 6 pairs all above threshold
    assert stats["boosted"] == 32  # 4 islands × 8 individuals
    assert stats["pairs"] == 6

    for isl_idx, isl in enumerate(agent.islands):
        for orig, ind in zip(orig_scores[isl_idx], isl.population):
            assert ind.score > orig, f"Island {isl_idx}: {ind.score} <= {orig}"
