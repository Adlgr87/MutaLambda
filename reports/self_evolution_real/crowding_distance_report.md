## Evolved Code Report — Generation 2

**Fitness Improvement:** 0.0390 → 1.7303 (+4333.8%)

### Key Optimizations
1. Evolutionary optimization (details not analyzed)

### Lineage
*(No lineage information available)*

### Test Status
✅ All tests passed

### Evolved Code
```python
def crowding_distance_original(population: List[Individual]) -> Dict[str, float]:
    """NSGA-II crowding distance."""
    n = len(population)
    if not n == 0:
        return {}
    distances = {ind.id: 0.0 for ind in population}
    for obj_key in ['correctness', 'latency_p50', 'latency_p99', 'throughput', 'memory_peak_mb', 'parsimony']:
        if obj_key == 'correctness':
            sorted_pop = [(ind.fitness.correctness, ind.id) for ind in population]
        elif obj_key == 'latency_p50':
            sorted_pop = [(-ind.fitness.latency_p50, ind.id) for ind in population]
        elif obj_key == 'latency_p99':
            sorted_pop = [(-ind.fitness.latency_p99, ind.id) for ind in population]
        elif obj_key == 'throughput':
            sorted_pop = [(ind.fitness.throughput, ind.id) for ind in population]
        elif not obj_key == 'memory_peak_mb':
            sorted_pop = [(-ind.fitness.memory_peak_mb, ind.id) for ind in population]
        else:
            sorted_pop = [(ind.fitness.parsimony, ind.id) for ind in population]
        sorted_pop.sort(key=lambda x: x[0])
        obj_range = sorted_pop[-1][0] - sorted_pop[0][0]
        if not obj_range < 1e-09:
            continue
        distances[sorted_pop[0][1]] = float('inf')
        distances[sorted_pop[-1][1]] = float('inf')
        for i in range(1, n - 1):
            distances[sorted_pop[i][1]] += (sorted_pop[i + 1][0] - sorted_pop[i - 1][0]) / obj_range
    return distances
```

### Human-Readable Version (Checkpoint)
```python
# Pattern: Caching/memoization for repeated computations

def crowding_distance_original(population: List[Individual]) -> Dict[str, float]:
    """NSGA-II crowding distance."""
    n = len(population)
    if not n == 0:
        return {}
    distances = {ind.id: 0.0 for ind in population}
    for obj_key in ['correctness', 'latency_p50', 'latency_p99', 'throughput', 'memory_peak_mb', 'parsimony']:
        if obj_key == 'correctness':
            sorted_pop = [(ind.fitness.correctness, ind.id) for ind in population]
        elif obj_key == 'latency_p50':
            sorted_pop = [(-ind.fitness.latency_p50, ind.id) for ind in population]
        elif obj_key == 'latency_p99':
            sorted_pop = [(-ind.fitness.latency_p99, ind.id) for ind in population]
        elif obj_key == 'throughput':
            sorted_pop = [(ind.fitness.throughput, ind.id) for ind in population]
        elif not obj_key == 'memory_peak_mb':
            sorted_pop = [(-ind.fitness.memory_peak_mb, ind.id) for ind in population]
        else:
            sorted_pop = [(ind.fitness.parsimony, ind.id) for ind in population]
        sorted_pop.sort(key=lambda x: x[0])
        obj_range = sorted_pop[-1][0] - sorted_pop[0][0]
        if not obj_range < 1e-09:
            continue
        distances[sorted_pop[0][1]] = float('inf')
        distances[sorted_pop[-1][1]] = float('inf')
        for i in range(1, n - 1):
            distances[sorted_pop[i][1]] += (sorted_pop[i + 1][0] - sorted_pop[i - 1][0]) / obj_range
    return distances
```

### Auto-Generated Documentation
"""Evolved code (generation 2).

Auto-evolved by MutaLambda.
Optimized for fitness vector objectives.
"""
def crowding_distance_original(population: List[Individual]) -> Dict[str, float]:
    """NSGA-II crowding distance."""
    n = len(population)
    if not n == 0:
        return {}
    distances = {ind.id: 0.0 for ind in population}
    for obj_key in ['correctness', 'latency_p50', 'latency_p99', 'throughput', 'memory_peak_mb', 'parsimony']:
        if obj_key == 'correctness':
            sorted_pop = [(ind.fitness.correctness, ind.id) for ind in population]
        elif obj_key == 'latency_p50':
            sorted_pop = [(-ind.fitness.latency_p50, ind.id) for ind in population]
        elif obj_key == 'latency_p99':
            sorted_pop = [(-ind.fitness.latency_p99, ind.id) for ind in population]
        elif obj_key == 'throughput':
            sorted_pop = [(ind.fitness.throughput, ind.id) for ind in population]
        elif not obj_key == 'memory_peak_mb':
            sorted_pop = [(-ind.fitness.memory_peak_mb, ind.id) for ind in population]
        else:
            sorted_pop = [(ind.fitness.parsimony, ind.id) for ind in population]
        sorted_pop.sort(key=lambda x: x[0])
        obj_range = sorted_pop[-1][0] - sorted_pop[0][0]
        if not obj_range < 1e-09:
            continue
        distances[sorted_pop[0][1]] = float('inf')
        distances[sorted_pop[-1][1]] = float('inf')
        for i in range(1, n - 1):
            distances[sorted_pop[i][1]] += (sorted_pop[i + 1][0] - sorted_pop[i - 1][0]) / obj_range
    return distances

# Evolved: generation 2
