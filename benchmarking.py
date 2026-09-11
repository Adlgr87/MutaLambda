"""Statistical benchmarking for candidate evaluation (ML-F04 / ML-F05).

Produces real percentiles from multiple samples instead of reusing a single
timing measurement for p50/p99.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class BenchmarkConfig:
    """Workload definition for performance measurement."""

    warmups: int = 5
    samples: int = 30
    operations_per_case: int = 1
    repetitions: int = 1  # outer loop around the full sample set

    def __post_init__(self) -> None:
        self.warmups = max(0, int(self.warmups))
        self.samples = max(1, int(self.samples))
        self.operations_per_case = max(1, int(self.operations_per_case))
        self.repetitions = max(1, int(self.repetitions))


@dataclass
class BenchmarkResult:
    """Result of a multi-sample micro-benchmark."""

    samples_sec: List[float] = field(default_factory=list)
    warmups: int = 0
    operations_per_case: int = 1
    error: str = ""

    @property
    def n(self) -> int:
        return len(self.samples_sec)

    def percentile(self, p: float) -> float:
        """Inclusive percentile via nearest-rank on sorted samples."""
        if not self.samples_sec:
            return float("inf")
        data = sorted(self.samples_sec)
        if len(data) == 1:
            return data[0]
        # Clamp p to [0, 100]
        p = max(0.0, min(100.0, float(p)))
        k = (len(data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return data[int(k)]
        return data[f] * (c - k) + data[c] * (k - f)

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def p99(self) -> float:
        return self.percentile(99)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples_sec) if self.samples_sec else float("inf")

    @property
    def stdev(self) -> float:
        if len(self.samples_sec) < 2:
            return 0.0
        return statistics.stdev(self.samples_sec)

    def confidence_interval_95(self) -> tuple[float, float]:
        """Approximate 95% CI for the mean (normal approx)."""
        if not self.samples_sec:
            return (float("inf"), float("inf"))
        if len(self.samples_sec) == 1:
            v = self.samples_sec[0]
            return (v, v)
        mean = self.mean
        se = self.stdev / math.sqrt(len(self.samples_sec))
        # z≈1.96
        half = 1.96 * se
        return (mean - half, mean + half)

    @property
    def throughput_ops_per_sec(self) -> float:
        """Throughput from p50 latency and operations_per_case."""
        if self.p50 <= 0 or self.p50 == float("inf"):
            return 0.0
        return self.operations_per_case / self.p50

    def to_dict(self) -> Dict[str, Any]:
        lo, hi = self.confidence_interval_95()
        return {
            "n": self.n,
            "warmups": self.warmups,
            "operations_per_case": self.operations_per_case,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "mean": self.mean,
            "stdev": self.stdev,
            "ci95_low": lo,
            "ci95_high": hi,
            "throughput": self.throughput_ops_per_sec,
            "error": self.error,
            "samples_sec": list(self.samples_sec),
        }


def run_callable_benchmark(
    fn: Callable[[], Any],
    config: Optional[BenchmarkConfig] = None,
) -> BenchmarkResult:
    """Benchmark a zero-arg callable with warmups and samples."""
    cfg = config or BenchmarkConfig()
    result = BenchmarkResult(
        warmups=cfg.warmups,
        operations_per_case=cfg.operations_per_case,
    )
    try:
        for _ in range(cfg.warmups):
            for _ in range(cfg.operations_per_case):
                fn()
        samples: List[float] = []
        for _rep in range(cfg.repetitions):
            for _ in range(cfg.samples):
                start = time.perf_counter()
                for _ in range(cfg.operations_per_case):
                    fn()
                samples.append(time.perf_counter() - start)
        result.samples_sec = samples
    except Exception as exc:
        result.error = str(exc)[:500]
    return result


def percentiles_from_samples(samples: Sequence[float]) -> Dict[str, float]:
    """Convenience helper for pre-collected samples."""
    br = BenchmarkResult(samples_sec=list(samples))
    return {"p50": br.p50, "p95": br.p95, "p99": br.p99, "mean": br.mean, "n": float(br.n)}


# ── Ablation Testing (FASE 1 framework) ───────────────────────────────────────


@dataclass
class AblationVariant:
    """A single variant of the ablation (e.g. a component toggled off)."""

    name: str
    enabled_components: Dict[str, bool]
    config_overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AblationResult:
    """Result of running the full benchmark for one variant."""

    variant: AblationVariant
    benchmark: BenchmarkResult
    metadata: Dict[str, Any] = field(default_factory=dict)


class AblationTester:
    """Run a baseline benchmark and an ablation sweep, comparing p50 latency.

    Mirrors the PDF FASE 1 "ablation_testing.py" contract while reusing the
    existing :func:`run_callable_benchmark` percentile infra. Usage::

        def workload(**cfg):
            return MutaLambdaAgent(EvolveConfig(**cfg)).run()
        tester = AblationTester(workload, baseline_cfg)
        results = tester.run_ablation(
            [AblationVariant("no_migration", enabled_components={"migration": False})]
        )
    """

    def __init__(
        self,
        workload_fn: Callable[..., Any],
        baseline_config: Dict[str, Any],
        benchmark_config: BenchmarkConfig | None = None,
    ) -> None:
        self._workload = workload_fn
        self._baseline = baseline_config
        self._bench = benchmark_config or BenchmarkConfig(warmups=2, samples=15)

    def run_baseline(self) -> BenchmarkResult:
        return run_callable_benchmark(
            lambda: self._workload(**self._baseline), self._bench
        )

    def run_ablation(self, variants: List[AblationVariant]) -> Dict[str, AblationResult]:
        baseline = self.run_baseline()
        out: Dict[str, AblationResult] = {
            "baseline": AblationResult(
                variant=AblationVariant(
                    name="baseline",
                    enabled_components={},
                ),
                benchmark=baseline,
                metadata={"p50": baseline.p50},
            )
        }
        base_p50 = baseline.p50
        for v in variants:
            cfg = {**self._baseline, **v.config_overrides}
            # component flags that are disabled get zeroed
            for comp, en in v.enabled_components.items():
                if not en:
                    cfg[comp] = False if isinstance(cfg.get(comp), bool) else cfg.get(comp)
            br = run_callable_benchmark(lambda: self._workload(**cfg), self._bench)
            delta_pct = ((br.p50 - base_p50) / base_p50) if base_p50 else 0.0
            out[v.name] = AblationResult(
                variant=v,
                benchmark=br,
                metadata={
                    "p50": br.p50,
                    "delta_pct_vs_baseline": round(delta_pct * 100, 3),
                    "baseline_p50": base_p50,
                },
            )
        return out


def summarize_ablation(
    results: Dict[str, AblationResult],
    min_impact_pct: float = 5.0,
) -> Dict[str, Any]:
    """Summarize which ablated components have >= ``min_impact_pct`` effect.

    Output::

        {"baseline_p50": float, "impactful_components": [{"variant": str, "delta_pct": float}]}
    """
    base_p50 = results["baseline"].metadata["p50"]
    impactful = [
        {
            "variant": name,
            "delta_pct": res.metadata["delta_pct_vs_baseline"],
        }
        for name, res in results.items()
        if name != "baseline"
        and abs(res.metadata["delta_pct_vs_baseline"]) >= min_impact_pct
    ]
    return {"baseline_p50": base_p50, "impactful_components": sorted(impactful, key=lambda x: x["delta_pct"])}
