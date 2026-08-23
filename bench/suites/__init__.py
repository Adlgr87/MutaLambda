"""Benchmark suite registry.

A suite is a module exposing ``load_tasks(limit=None, **kwargs) -> list[BenchTask]``
and the module-level constants ``SUITE``, ``TIER`` and ``DATASET`` (the
``bench.datasets`` key it needs, or ``""`` when self-contained).

Suites raise :class:`bench.datasets.DatasetUnavailable` when their data is not
cached; the runner turns that into an actionable message instead of a stack
trace.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

from bench.spec import BenchTask

# name -> (module, tier, dataset key, status)
REGISTRY: Dict[str, Dict[str, str]] = {
    # Tier 1 — table stakes
    "smoke": {
        "module": "bench.suites.smoke", "tier": "tier1", "dataset": "",
        "status": "ready",
        "summary": "Self-contained sanity suite; validates the harness itself.",
    },
    "effibench": {
        "module": "bench.suites.effibench", "tier": "tier1", "dataset": "effibench",
        "status": "ready",
        "summary": "EffiBench: efficiency vs human canonical solutions (ratio-to-human).",
    },
    "pie": {
        "module": "bench.suites.pie", "tier": "tier1", "dataset": "pie",
        "status": "ready",
        "summary": "PIE C++ slow→fast pairs; %Opt and speedup over -O3.",
    },
    "polybench": {
        "module": "bench.suites.polybench", "tier": "tier1", "dataset": "polybench-python",
        "status": "ready",
        "summary": "PolyBench numerical kernels; NumPy vectorisation target.",
    },
    "pyperformance": {
        "module": "bench.suites.pyperformance", "tier": "tier1", "dataset": "pyperformance",
        "status": "planned",
        "summary": "CPython's official suite; whole-program workloads.",
    },
    # Tier 2 — differentiators
    "effibench-plus": {
        "module": "bench.suites.effibench_plus", "tier": "tier2", "dataset": "effibench",
        "status": "ready",
        "summary": "EffiBench tasks + scientific invariants that optimizers must not break.",
    },
    "rosetta": {
        "module": "bench.suites.rosetta", "tier": "tier2", "dataset": "rosetta",
        "status": "experimental",
        "summary": "Cross-language: does a Python-side optimization carry to Rust/C++?",
    },
    # Tier 3 — moonshot
    "eoh": {
        "module": "bench.suites.eoh", "tier": "tier3", "dataset": "",
        "status": "ready",
        "summary": "Heuristic discovery (bin packing, circle packing); quality, not speed.",
    },
}


def list_suites() -> List[Dict[str, str]]:
    return [{"name": name, **meta} for name, meta in sorted(REGISTRY.items())]


def load_suite(name: str) -> Any:
    if name not in REGISTRY:
        raise KeyError(f"unknown suite '{name}'; available: {sorted(REGISTRY)}")
    return importlib.import_module(REGISTRY[name]["module"])


def load_tasks(name: str, limit: int = 0, **kwargs: Any) -> List[BenchTask]:
    module = load_suite(name)
    tasks = module.load_tasks(limit=limit or None, **kwargs)
    return list(tasks)
