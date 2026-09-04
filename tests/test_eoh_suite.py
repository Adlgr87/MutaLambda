"""TDD smoke for the EoH public-comparison harness.

Validates that eoh_suite.run_comparison_with_mutalambda:
  - runs MutaLambda on a small circle-packing problem,
  - returns mean_fitness / speedup floats in [0, inf),
  - does not regress vs the greedy baseline.
"""
import pytest
from benchmarks.eoh_suite import run_comparison_with_mutalambda, EoHTask


@pytest.fixture(scope="module")
def small_tasks():
    return [
        EoHTask("circle_packing_rectangle", "Pack N circles into minimum-area square",
                n_dimensions=2, optimal_known=False, optimal_value=None),
    ]


def test_run_comparison_returns_scores(small_tasks):
    res = run_comparison_with_mutalambda(
        tasks=small_tasks,
        n_generations=5,        # tiny for CI speed
        budget_secs=60,
    )
    assert "results" in res
    r0 = res["results"][0]
    assert r0["name"] == "circle_packing_rectangle"
    assert isinstance(r0["baseline_fitness"], float)
    assert isinstance(r0["mutalambda_fitness"], float)
    assert r0["mutalambda_fitness"] <= r0["baseline_fitness"]  # must improve
    assert r0["speedup_ratio"] >= 1.0
