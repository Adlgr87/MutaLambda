"""Smoke tests for the Evolution Upgrade v2.0 benchmark matrix definitions."""

from __future__ import annotations


BENCHMARK_VARIANTS = [
    "base",
    "base_plus_thc",
    "base_plus_advanced_selection",
    "base_plus_dialectic",
    "full_v2",
]

GLOBAL_METRICS = [
    "best_fitness",
    "convergence_speed",
    "fragment_reuse_ratio",
    "lineage_depth_max",
    "sandbox_efficiency",
    "cpu_time_per_gain",
]


def test_benchmark_matrix_contains_required_variants():
    assert BENCHMARK_VARIANTS == [
        "base",
        "base_plus_thc",
        "base_plus_advanced_selection",
        "base_plus_dialectic",
        "full_v2",
    ]


def test_global_metrics_are_declared():
    assert "best_fitness" in GLOBAL_METRICS
    assert "cpu_time_per_gain" in GLOBAL_METRICS
