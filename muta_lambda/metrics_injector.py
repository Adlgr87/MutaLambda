"""Metrics injection utilities for evolution_engine.py.

Provides lightweight hooks to collect runtime metrics (latency distribution,
memory peak, throughput) without requiring a full diagnostics pass.
"""
from __future__ import annotations

import time
import tracemalloc
from typing import Callable, Dict, Any


def measure_candidate(func: Callable, iterations: int = 10) -> Dict[str, float]:
    """Measure runtime metrics for a candidate solution."""
    times: list[float] = []
    
    tracemalloc.start()
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            func()
        except Exception:
            pass  # correctness is gated elsewhere
        times.append((time.perf_counter() - start) * 1000)
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    times.sort()
    n = len(times)
    return {
        "latency_p50": times[n // 2],
        "latency_p99": times[int(n * 0.99)] if n >= 100 else times[-1],
        "memory_peak_mb": peak / (1024 * 1024),
        "throughput": iterations / (sum(times) / 1000) if sum(times) > 0 else 0.0,
    }


def inject_metrics(candidate_code: str, test_fn: Callable) -> Dict[str, float]:
    """Compile and measure a candidate string."""
    namespace: Dict[str, Any] = {}
    exec(compile(candidate_code, "<candidate>", "exec"), namespace)  # noqa: S102
    
    # Extract test function from namespace
    test_func = namespace.get(test_fn.__name__, test_fn)
    return measure_candidate(test_func)
