"""
FitnessVector — Multi-objective fitness for MutaLambda evolution engine.

Provides a 6-dimensional fitness vector that replaces the scalar score,
enabling Pareto dominance, weighted-sum aggregation, and backward-
compatible scalar access for existing Island/Agent code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


# Default weights for weighted-sum scalarisation.
#   correctness   — dominates: must-pass tests above all else
#   latency       — penalised mildly
#   throughput    — rewarded moderately
#   memory        — penalised lightly (avoid OOM, don't obsess)
#   parsimony     — rewarded lightly (shorter code preferred)
DEFAULT_WEIGHTS: Dict[str, float] = {
    "correctness":    1.00,
    "latency_p50":   -0.10,
    "latency_p99":   -0.05,
    "throughput":     0.15,
    "memory_peak_mb":-0.05,
    "parsimony":      0.05,
}


@dataclass
class FitnessVector:
    """Six-dimensional multi-objective fitness.

    All objectives follow the convention *higher is better*.  Objectives that
    naturally prefer lower values (latency, memory) are stored as-is and
    *negated* inside ``dominates()`` and ``weighted_sum()``.

    Attributes
    ----------
    correctness : float
        0.0 – 1.0  fraction of test-cases passed.  Hard constraint.
    latency_p50 : float
        Median wall-clock seconds per evaluation.  Lower → better.
    latency_p99 : float
        P99 wall-clock seconds.  Lower → better.
    throughput : float
        Operations per second (estimated from runtime).  Higher → better.
    memory_peak_mb : float
        Peak resident-set size in MiB.  Lower → better.
    parsimony : float
        1.0 / (1.0 + cyclomatic_complexity / max(1, code_kb)).
        Higher → shorter & simpler code.
    """

    correctness: float = 0.0
    latency_p50: float = 0.0
    latency_p99: float = 0.0
    throughput: float = 0.0
    memory_peak_mb: float = 0.0
    parsimony: float = 0.0

    # ── Pareto dominance ─────────────────────────────────────────────────

    def dominates(self, other: FitnessVector) -> bool:
        """Return True if *self* Pareto-dominates *other*.

        Pareto dominance: self is at least as good in every objective AND
        strictly better in at least one.  Objectives where *lower is better*
        are negated internally so that "greater is better" always holds.
        """
        # self_dim  = (correctness, -p50, -p99, throughput, -mem, parsimony)
        # other_dim = same

        self_dim = (
            self.correctness,
            -self.latency_p50,
            -self.latency_p99,
            self.throughput,
            -self.memory_peak_mb,
            self.parsimony,
        )
        other_dim = (
            other.correctness,
            -other.latency_p50,
            -other.latency_p99,
            other.throughput,
            -other.memory_peak_mb,
            other.parsimony,
        )

        at_least_as_good = all(s >= o for s, o in zip(self_dim, other_dim))
        strictly_better = any(s > o for s, o in zip(self_dim, other_dim))
        return at_least_as_good and strictly_better

    # ── Aggregation ──────────────────────────────────────────────────────

    def weighted_sum(self, weights: Dict[str, float] | None = None) -> float:
        """Scalarise the vector with a weighted sum.

        Default weights emphasise correctness above all else; latency,
        memory and parsimony act as tie-breakers.
        """
        w = weights if weights is not None else DEFAULT_WEIGHTS
        return (
            w.get("correctness", 1.0)      * self.correctness
            + w.get("latency_p50", -0.1)    * self.latency_p50
            + w.get("latency_p99", -0.05)   * self.latency_p99
            + w.get("throughput", 0.15)     * self.throughput
            + w.get("memory_peak_mb", -0.05)* self.memory_peak_mb
            + w.get("parsimony", 0.05)      * self.parsimony
        )

    def to_scalar(self) -> float:
        """Return a correctness-gated scalar score.

        Correctness is the hard constraint for code synthesis. Candidates
        below full correctness are ranked below every fully correct candidate,
        even if they are extremely fast or compact.
        """
        if self.correctness < 1.0:
            return self.correctness - 1.0
        return self.weighted_sum()

    def to_dict(self) -> Dict[str, float]:
        """Exporta los 6 objetivos como diccionario (para serialización)."""
        return {
            "correctness": self.correctness,
            "latency_p50": self.latency_p50,
            "latency_p99": self.latency_p99,
            "throughput": self.throughput,
            "memory_peak_mb": self.memory_peak_mb,
            "parsimony": self.parsimony,
        }

    # ── Helpers ──────────────────────────────────────────────────────────

    @classmethod
    def worst(cls) -> FitnessVector:
        """Return the worst-possible fitness vector (used as sentinel)."""
        return cls(
            correctness=0.0,
            latency_p50=float("inf"),
            latency_p99=float("inf"),
            throughput=0.0,
            memory_peak_mb=float("inf"),
            parsimony=0.0,
        )

    def is_worst(self) -> bool:
        """Return True if this vector exactly matches the worst sentinel."""
        sentinel = FitnessVector.worst()
        return (
            self.correctness == sentinel.correctness
            and self.latency_p50 == sentinel.latency_p50
            and self.latency_p99 == sentinel.latency_p99
            and self.throughput == sentinel.throughput
            and self.memory_peak_mb == sentinel.memory_peak_mb
            and self.parsimony == sentinel.parsimony
        )

    def __repr__(self) -> str:
        return (
            f"FitnessVector(correct={self.correctness:.2f}, "
            f"p50={self.latency_p50:.4f}s, "
            f"p99={self.latency_p99:.4f}s, "
            f"thru={self.throughput:.1f}op/s, "
            f"mem={self.memory_peak_mb:.1f}MB, "
            f"pars={self.parsimony:.4f})"
        )
