"""Pytest fixtures re-exporting shared helpers (FIX 4.1)."""

from __future__ import annotations

import pytest

from fitness_vector import FitnessVector
from tests.helpers import make_individual


@pytest.fixture
def perfect_fitness() -> FitnessVector:
    return FitnessVector(
        correctness=1.0,
        latency_p50=0.001,
        latency_p99=0.002,
        throughput=1000.0,
        memory_peak_mb=1.0,
        parsimony=0.9,
    )


@pytest.fixture
def worst_fitness() -> FitnessVector:
    return FitnessVector.worst()


@pytest.fixture
def sample_individual():
    return make_individual("def f():\n    return 1\n")
