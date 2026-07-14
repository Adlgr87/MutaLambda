"""Local pure-function stand-in for MASSIVE utility_logic.calculate_group_cohesion.

Used when the MASSIVE repo is not on PYTHONPATH; the adapter can also point at
the real MASSIVE file via MassiveTargetAdapter.from_massive_utility_logic().
"""

from __future__ import annotations

from typing import Iterable, Sequence


def calculate_group_cohesion(opinions: Sequence[float]) -> float:
    """Return cohesion in [0, 1] from bipolar opinions in [-1, 1].

    Cohesion is 1 - normalized mean absolute pairwise difference.
    Empty input returns 0.0.
    """
    vals = [float(x) for x in opinions]
    n = len(vals)
    if n <= 1:
        return 0.0 if n == 0 else 1.0
    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += abs(vals[i] - vals[j])
            pairs += 1
    # max pairwise |diff| on [-1,1] is 2
    mean_diff = total / pairs
    cohesion = 1.0 - (mean_diff / 2.0)
    if cohesion < 0.0:
        return 0.0
    if cohesion > 1.0:
        return 1.0
    return cohesion
