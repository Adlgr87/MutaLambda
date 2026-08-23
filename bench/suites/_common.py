"""Helpers shared by suite adapters."""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional, Sequence

from bench.spec import BenchTask, Workload


def expected_for(code: str, entrypoint: str, arg_sets: Sequence[Sequence[Any]],
                 *, comparison: str = "equal") -> List[Dict[str, Any]]:
    """Derive expected outputs by executing the *reference* implementation.

    Suites use this so a task's ground truth always comes from the task's own
    canonical/original code — never from the optimizer under test.
    """
    ns: Dict[str, Any] = {"__name__": "__muta_bench_reference__"}
    exec(compile(code, "<reference>", "exec"), ns, ns)  # noqa: S102 (trusted suite code)
    fn = ns[entrypoint]
    tests: List[Dict[str, Any]] = []
    for args in arg_sets:
        args = list(args)
        tests.append({
            "function": entrypoint,
            "args": args,
            "expected": fn(*args),
            "comparison": comparison,
        })
    return tests


def split_tests(tests: Sequence[Dict[str, Any]], *, visible: int,
                seed: int = 1234) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Deterministic visible/held-out split.

    The seed is fixed and published so the split is reproducible, but the
    optimizer never sees the held-out half.
    """
    pool = list(tests)
    rng = random.Random(seed)
    rng.shuffle(pool)
    visible = max(1, min(visible, len(pool) - 1)) if len(pool) > 1 else len(pool)
    return pool[:visible], pool[visible:]


def make_task(
    *,
    task_id: str,
    suite: str,
    tier: str,
    source_code: str,
    entrypoint: str,
    visible_args: Sequence[Sequence[Any]],
    holdout_args: Sequence[Sequence[Any]],
    workload_args: Sequence[Sequence[Any]],
    comparison: str = "equal",
    warmups: int = 2,
    samples: int = 9,
    timeout_sec: float = 90.0,
    reference_code: str = "",
    reference_label: str = "",
    invariants: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> BenchTask:
    """Build a task, deriving ground truth from ``source_code``."""
    return BenchTask(
        task_id=task_id,
        suite=suite,
        tier=tier,
        source_code=source_code,
        entrypoint=entrypoint,
        workload=Workload(
            calls=[[list(a), {}] for a in workload_args],
            warmups=warmups,
            samples=samples,
            timeout_sec=timeout_sec,
        ),
        visible_tests=expected_for(source_code, entrypoint, visible_args, comparison=comparison),
        holdout_tests=expected_for(source_code, entrypoint, holdout_args, comparison=comparison),
        reference_code=reference_code,
        reference_label=reference_label,
        invariants=list(invariants or []),
        metadata=dict(metadata or {}),
    )


def limited(items: Iterable[Any], limit: Optional[int]) -> List[Any]:
    out = list(items)
    return out[:limit] if limit else out
