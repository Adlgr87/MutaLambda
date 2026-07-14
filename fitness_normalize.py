"""Baseline-relative fitness gains (ML-F08).

Avoid summing incompatible units (MB, seconds, ops/s) by normalizing
against a baseline FitnessVector:
  latency_gain    = baseline_latency / candidate_latency
  throughput_gain = candidate_throughput / baseline_throughput
  memory_gain     = baseline_memory / candidate_memory
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from fitness_vector import FitnessVector


def _safe_ratio(numer: float, denom: float, default: float = 1.0) -> float:
    if denom is None or denom == 0 or denom == float("inf"):
        return default
    if numer is None or numer == float("inf"):
        return 0.0
    return float(numer) / float(denom)


@dataclass
class NormalizedGains:
    correctness: float
    latency_gain: float
    throughput_gain: float
    memory_gain: float
    parsimony: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "correctness": self.correctness,
            "latency_gain": self.latency_gain,
            "throughput_gain": self.throughput_gain,
            "memory_gain": self.memory_gain,
            "parsimony": self.parsimony,
        }

    def scalar(
        self,
        *,
        w_correctness: float = 1.0,
        w_latency: float = 0.25,
        w_throughput: float = 0.25,
        w_memory: float = 0.15,
        w_parsimony: float = 0.10,
    ) -> float:
        """Correctness-gated aggregate of gains (higher is better)."""
        if self.correctness < 1.0:
            return self.correctness - 1.0
        return (
            w_correctness * self.correctness
            + w_latency * self.latency_gain
            + w_throughput * self.throughput_gain
            + w_memory * self.memory_gain
            + w_parsimony * self.parsimony
        )


def normalize_against_baseline(
    candidate: FitnessVector,
    baseline: Optional[FitnessVector],
) -> NormalizedGains:
    """Compute multi-objective gains relative to a baseline measurement."""
    if baseline is None:
        return NormalizedGains(
            correctness=candidate.correctness,
            latency_gain=1.0,
            throughput_gain=1.0,
            memory_gain=1.0,
            parsimony=candidate.parsimony,
        )
    return NormalizedGains(
        correctness=candidate.correctness,
        latency_gain=_safe_ratio(baseline.latency_p50, candidate.latency_p50, 1.0),
        throughput_gain=_safe_ratio(candidate.throughput, baseline.throughput, 1.0),
        memory_gain=_safe_ratio(baseline.memory_peak_mb, candidate.memory_peak_mb, 1.0),
        parsimony=candidate.parsimony,
    )
