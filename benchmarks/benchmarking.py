"""
Callable benchmarking utilities for benchmark harness (D2/D6).
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Callable, List, Tuple


@dataclass
class BenchmarkStat:
    median_s: float
    iqr: float
    p95: float
    mean_s: float
    min_s: float
    max_s: float
    n: int


def run_callable_benchmark(fn: Callable, args: tuple, *, reps: int = 30, warmups: int = 5) -> BenchmarkStat:
    """Benchmark a callable with fixed args; return timing statistics."""
    latencies: List[float] = []

    for _ in range(warmups):
        try:
            fn(*args)
        except Exception:
            pass

    for _ in range(reps):
        start = time.perf_counter()
        fn(*args)
        latencies.append(time.perf_counter() - start)

    return _stats(latencies)


def run_code_benchmark(code: str, function_name: str, arg_factory: Callable, *,
                       reps: int = 30, warmups: int = 5) -> BenchmarkStat:
    """Exec code, build fn, time it. arg_factory() returns fresh args each rep."""
    ns: dict = {"__name__": "__bench__"}
    exec(compile(code, "<bench>", "exec"), ns, ns)  # noqa: S102
    fn = ns[function_name]

    latencies: List[float] = []
    for _ in range(warmups):
        try:
            fn(*arg_factory())
        except Exception:
            pass

    for _ in range(reps):
        args = arg_factory()
        start = time.perf_counter()
        fn(*args)
        latencies.append(time.perf_counter() - start)

    return _stats(latencies)


def _stats(latencies: List[float]) -> BenchmarkStat:
    if not latencies:
        return BenchmarkStat(median_s=float("inf"), iqr=0.0, p95=float("inf"),
                             mean_s=float("inf"), min_s=float("inf"),
                             max_s=float("inf"), n=0)
    s = sorted(latencies)
    n = len(s)
    md = statistics.median(s)
    q1 = s[int(0.25 * (n - 1))]
    q3 = s[int(0.75 * (n - 1))]
    p95 = s[int(0.95 * (n - 1))] if n > 1 else s[0]
    return BenchmarkStat(
        median_s=md, iqr=q3 - q1, p95=p95,
        mean_s=statistics.mean(s), min_s=s[0], max_s=s[-1], n=n)


# Alias for the harness's time_callable wrapper
def time_callable(fn: Callable[[], None], reps: int = 30, warmups: int = 5) -> List[float]:
    """Measure wall-clock latency of a zero-arg callable; return per-rep seconds."""
    latencies: List[float] = []
    for _ in range(warmups):
        try:
            fn()
        except Exception:
            pass
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        latencies.append(time.perf_counter() - start)
    return latencies