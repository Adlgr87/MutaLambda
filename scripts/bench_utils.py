#!/usr/bin/env python
"""Shared helpers for the benchmark scripts under ``scripts/``."""
import os
import random
import sys
from typing import Callable, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Individual
from fitness_vector import FitnessVector


def random_population(
    n: int,
    code_for: Callable[[int], str],
    score_for: Callable[[int], float],
    seed: int = 42,
) -> List[Individual]:
    """Build ``n`` individuals with reproducible pseudo-random fitness vectors."""
    rng = random.Random(seed)
    population = []
    for i in range(n):
        population.append(
            Individual(
                code=code_for(i),
                score=score_for(i),
                fitness=FitnessVector(
                    correctness=0.5 + rng.random() * 0.5,
                    latency_p50=rng.uniform(0.1, 10.0),
                    latency_p99=rng.uniform(1.0, 50.0),
                    throughput=rng.uniform(100, 1000),
                    memory_peak_mb=rng.uniform(10, 100),
                    parsimony=rng.uniform(0.1, 0.9),
                ),
            )
        )
    return population
