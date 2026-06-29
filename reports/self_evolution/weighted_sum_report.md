## Evolved Code Report — Generation 5

**Fitness Improvement:** 3.5930 → 3.6036 (+0.3%)

### Key Optimizations
1. Evolutionary optimization (details not analyzed)

### Lineage
*(No lineage information available)*

### Test Status
✅ All tests passed

### Evolved Code
```python

def weighted_sum(correctness, latency_p50, latency_p99, throughput,
                 memory_peak_mb, parsimony, weights=None):
    """Scalarise fitness vector with weighted sum.
    
    Default weights emphasize correctness; latency/memory/parsimony
    act as tie-breakers.
    """
    if weights is None:
        weights = {
            "correctness": 1.00,
            "latency_p50": -0.10,
            "latency_p99": -0.05,
            "throughput": 0.15,
            "memory_peak_mb": -0.05,
            "parsimony": 0.05,
        }
    
    return (
        weights.get("correctness", 1.0) * correctness
        + weights.get("latency_p50", -0.1) * latency_p50
        + weights.get("latency_p99", -0.05) * latency_p99
        + weights.get("throughput", 0.15) * throughput
        + weights.get("memory_peak_mb", -0.05) * memory_peak_mb
        + weights.get("parsimony", 0.05) * parsimony
    )

```

### Human-Readable Version (Checkpoint)
```python
# Pattern: Caching/memoization for repeated computations
# Pattern: Functional programming constructs for efficiency


def weighted_sum(correctness, latency_p50, latency_p99, throughput,
                memory_peak_mb, parsimony, weights=None):
    """Scalarise fitness vector with weighted sum.

    Default weights emphasize correctness; latency/memory/parsimony
    act as tie-breakers.
    """
    if weights is None:
        weights = {
            "correctness": 1.00,
            "latency_p50": -0.10,
            "latency_p99": -0.05,
            "throughput": 0.15,
            "memory_peak_mb": -0.05,
            "parsimony": 0.05,
        }

    return (
        weights.get("correctness", 1.0) * correctness
        + weights.get("latency_p50", -0.1) * latency_p50
        + weights.get("latency_p99", -0.05) * latency_p99
        + weights.get("throughput", 0.15) * throughput
        + weights.get("memory_peak_mb", -0.05) * memory_peak_mb
        + weights.get("parsimony", 0.05) * parsimony
    )

```

### Auto-Generated Documentation
"""Evolved code (generation 5).

Auto-evolved by MutaLambda.
Optimized for fitness vector objectives.
"""

def weighted_sum(correctness, latency_p50, latency_p99, throughput,
                 memory_peak_mb, parsimony, weights=None):
    """Scalarise fitness vector with weighted sum.
    
    Default weights emphasize correctness; latency/memory/parsimony
    act as tie-breakers.
    """
    if weights is None:
        weights = {
            "correctness": 1.00,
            "latency_p50": -0.10,
            "latency_p99": -0.05,
            "throughput": 0.15,
            "memory_peak_mb": -0.05,
            "parsimony": 0.05,
        }
    
    return (
        weights.get("correctness", 1.0) * correctness
        + weights.get("latency_p50", -0.1) * latency_p50
        + weights.get("latency_p99", -0.05) * latency_p99
        + weights.get("throughput", 0.15) * throughput
        + weights.get("memory_peak_mb", -0.05) * memory_peak_mb
        + weights.get("parsimony", 0.05) * parsimony
    )


# Evolved: generation 5
