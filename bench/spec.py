"""Core data model for the MutaLambda benchmark harness.

Everything a suite adapter must produce is a :class:`BenchTask`; everything the
runner produces is a :class:`TaskRecord`. Both are plain dataclasses that
serialise to JSON so results can be diffed and audited.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "muta-bench/1"

# Tier taxonomy from the benchmark plan.
TIER_1 = "tier1"  # table stakes: EffiBench, PIE, pyperformance/PolyBench
TIER_2 = "tier2"  # differentiators: scientific invariants, cross-language
TIER_3 = "tier3"  # moonshot: EoH / AlphaEvolve-style discovery


@dataclass
class Workload:
    """How to *time* a task.

    ``calls`` is a list of ``[args, kwargs]`` pairs applied to ``entrypoint``.
    One "sample" executes every call in ``calls`` once, so the reported latency
    is the cost of the whole workload, not of a single call.

    ``rotate_calls`` makes each sample use a different slice of ``calls`` when
    available. That is the cheapest defence against a candidate that memoises
    the benchmark inputs and reports a fake 100x.
    """

    calls: List[List[Any]] = field(default_factory=list)
    warmups: int = 3
    samples: int = 15
    rotate_calls: bool = True
    timeout_sec: float = 60.0
    setup: str = ""  # optional python executed once before timing

    def normalised_calls(self) -> List[List[Any]]:
        out: List[List[Any]] = []
        for c in self.calls:
            if isinstance(c, dict):
                out.append([list(c.get("args", [])), dict(c.get("kwargs", {}))])
            elif isinstance(c, (list, tuple)):
                if len(c) == 2 and isinstance(c[0], (list, tuple)) and isinstance(c[1], dict):
                    out.append([list(c[0]), dict(c[1])])
                else:
                    out.append([list(c), {}])
            else:
                out.append([[c], {}])
        return out

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["calls"] = self.normalised_calls()
        return d


@dataclass
class BenchTask:
    """A single optimizable unit of work.

    ``visible_tests`` are handed to the optimizer (it may read them, and
    MutaLambda uses them as its correctness gate). ``holdout_tests`` are
    **never** shown to the optimizer and decide whether an optimization counts.
    That split is the anti-overfitting core of the methodology.
    """

    task_id: str
    suite: str
    tier: str
    source_code: str
    entrypoint: str
    workload: Workload
    visible_tests: List[Dict[str, Any]] = field(default_factory=list)
    holdout_tests: List[Dict[str, Any]] = field(default_factory=list)
    language: str = "python"
    # Human/canonical reference (EffiBench canonical solution, PIE fast pair,
    # PolyBench vectorised kernel...). Used to compute ratio-to-human.
    reference_code: str = ""
    reference_label: str = ""
    # Tier-2 scientific invariants, by name (see bench.invariants).
    invariants: List[str] = field(default_factory=list)
    # Free-form provenance: dataset row id, problem url, license, difficulty.
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def all_tests(self) -> List[Dict[str, Any]]:
        return list(self.visible_tests) + list(self.holdout_tests)

    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "task_id": self.task_id,
                "suite": self.suite,
                "source": self.source_code,
                "entrypoint": self.entrypoint,
                "visible": self.visible_tests,
                "holdout": self.holdout_tests,
                "workload": self.workload.to_dict(),
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["workload"] = self.workload.to_dict()
        d["fingerprint"] = self.fingerprint()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchTask":
        payload = dict(data)
        payload.pop("fingerprint", None)
        wl = payload.pop("workload", {}) or {}
        return cls(workload=Workload(**wl), **payload)


@dataclass
class Measurement:
    """Result of one measurement pass over one code variant."""

    ok: bool = False
    tests_passed: int = 0
    tests_total: int = 0
    latency_ms_p50: float = float("inf")
    latency_ms_p95: float = float("inf")
    latency_ms_min: float = float("inf")
    latency_ms_stdev: float = 0.0
    mem_peak_mb: float = float("inf")
    samples: List[float] = field(default_factory=list)
    error: str = ""
    timed_out: bool = False
    failures: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return (self.tests_passed / self.tests_total) if self.tests_total else 0.0

    @property
    def all_pass(self) -> bool:
        return self.tests_total > 0 and self.tests_passed == self.tests_total

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["pass_rate"] = self.pass_rate
        return d


@dataclass
class OptimizationOutcome:
    """What an optimizer backend returns for one task."""

    code: str
    optimizer: str
    wall_sec: float = 0.0
    llm_calls: int = 0
    tokens: int = 0
    generations: int = 0
    cost_usd: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskRecord:
    """Per-task audit row — this is the unit that gets published."""

    task_id: str
    suite: str
    tier: str
    optimizer: str
    fingerprint: str
    baseline: Dict[str, Any] = field(default_factory=dict)
    optimized: Dict[str, Any] = field(default_factory=dict)
    reference: Dict[str, Any] = field(default_factory=dict)
    integrity: Dict[str, Any] = field(default_factory=dict)
    budget: Dict[str, Any] = field(default_factory=dict)
    diff: str = ""
    repeats: int = 1
    counted: bool = False  # True only if integrity clean AND holdout passes
    speedup: float = 1.0
    memory_ratio: float = 1.0
    ratio_to_reference: float = float("nan")
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SuiteReport:
    """Aggregate over a suite for one optimizer configuration."""

    suite: str
    tier: str
    optimizer: str
    schema: str = SCHEMA_VERSION
    env: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    records: List[TaskRecord] = field(default_factory=list)
    aggregates: Dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "suite": self.suite,
            "tier": self.tier,
            "optimizer": self.optimizer,
            "env": self.env,
            "config": self.config,
            "aggregates": self.aggregates,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "records": [r.to_dict() for r in self.records],
        }
