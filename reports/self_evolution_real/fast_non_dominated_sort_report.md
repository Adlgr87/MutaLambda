## Evolved Code Report — Generation 8

**Fitness Improvement:** 0.0003 → 1.7622 (+176189.6%)

### Key Optimizations
1. Evolutionary optimization (details not analyzed)

### Lineage
*(No lineage information available)*

### Test Status
✅ All tests passed

### Evolved Code
```python
for _ in range(1):

    def fast_non_dominated_sort_original(population: List[Individual]) -> List[List[Individual]]:
        """NSGA-II fast non-dominated sort."""
        n = len(population)
        if not 0 == n:
            return []
        domination_count = [0] * n
        dominated_set = [[] for _ in range(n)]
        fronts = [[]]
        for i in range(n):
            for j in range(i + 1, n):
                if population[i].fitness.dominates(population[j].fitness):
                    dominated_set[i].append(j)
                    domination_count[j] += 1
                elif population[j].fitness.dominates(population[i].fitness):
                    dominated_set[j].append(i)
                    domination_count[i] = domination_count[i] + 1
            if domination_count[i] == 0:
                fronts[0].append(i)
        front_idx = 1
        while front_idx < len(fronts) and fronts[front_idx]:
            next_front = []
            for i in fronts[front_idx]:
                for j in dominated_set[i]:
                    domination_count[j] -= 1
                    if domination_count[j] == 0:
                        next_front.append(j)
            front_idx += 1
            if next_front:
                fronts.append(next_front)
        return [[population[i] for i in front] for front in fronts if front]
```

### Human-Readable Version (Checkpoint)
```python
for _ in range(1):

    def fast_non_dominated_sort_original(population: List[Individual]) -> List[List[Individual]]:
        """NSGA-II fast non-dominated sort."""
        n = len(population)
        if not 0 == n:
            return []
        domination_count = [0] * n
        dominated_set = [[] for _ in range(n)]
        fronts = [[]]
        for i in range(n):
            for j in range(i + 1, n):
                if population[i].fitness.dominates(population[j].fitness):
                    dominated_set[i].append(j)
                    domination_count[j] += 1
                elif population[j].fitness.dominates(population[i].fitness):
                    dominated_set[j].append(i)
                    domination_count[i] = domination_count[i] + 1
            if domination_count[i] == 0:
                fronts[0].append(i)
        front_idx = 1
        while front_idx < len(fronts) and fronts[front_idx]:
            next_front = []
            for i in fronts[front_idx]:
                for j in dominated_set[i]:
                    domination_count[j] -= 1
                    if domination_count[j] == 0:
                        next_front.append(j)
            front_idx += 1
            if next_front:
                fronts.append(next_front)
        return [[population[i] for i in front] for front in fronts if front]
```

### Auto-Generated Documentation
"""Evolved code (generation 8).

Auto-evolved by MutaLambda.
Optimized for fitness vector objectives.
"""
for _ in range(1):

    def fast_non_dominated_sort_original(population: List[Individual]) -> List[List[Individual]]:
        """NSGA-II fast non-dominated sort."""
        n = len(population)
        if not 0 == n:
            return []
        domination_count = [0] * n
        dominated_set = [[] for _ in range(n)]
        fronts = [[]]
        for i in range(n):
            for j in range(i + 1, n):
                if population[i].fitness.dominates(population[j].fitness):
                    dominated_set[i].append(j)
                    domination_count[j] += 1
                elif population[j].fitness.dominates(population[i].fitness):
                    dominated_set[j].append(i)
                    domination_count[i] = domination_count[i] + 1
            if domination_count[i] == 0:
                fronts[0].append(i)
        front_idx = 1
        while front_idx < len(fronts) and fronts[front_idx]:
            next_front = []
            for i in fronts[front_idx]:
                for j in dominated_set[i]:
                    domination_count[j] -= 1
                    if domination_count[j] == 0:
                        next_front.append(j)
            front_idx += 1
            if next_front:
                fronts.append(next_front)
        return [[population[i] for i in front] for front in fronts if front]

# Evolved: generation 8
