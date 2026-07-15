"""Shared test helpers (importable from test modules; FIX 4.1)."""

from __future__ import annotations

from fitness_vector import FitnessVector
from models import Individual


def make_individual(
    code: str = "def f():\n    return 1\n",
    *,
    correctness: float = 1.0,
    latency: float = 0.01,
    throughput: float = 50.0,
    memory: float = 10.0,
    parsimony: float = 0.5,
    score: float | None = None,
) -> Individual:
    """Build an Individual with a populated FitnessVector."""
    ind = Individual(code=code)
    ind.fitness = FitnessVector(
        correctness=correctness,
        latency_p50=latency,
        latency_p99=latency,
        throughput=throughput,
        memory_peak_mb=memory,
        parsimony=parsimony,
    )
    ind.score = score if score is not None else ind.fitness.to_scalar()
    ind.passed = correctness >= 1.0
    return ind
