# ADR-0039 — Rewrite `_non_dominated_sort_numpy` with `processed` mask

## Status: accepted (Fase 4A)

## Context
The numpy fast-path in `nsga2.py` used a confusing `front_indices` reassignment
followed by a defensive `break`, producing an off-by-one on multi-level fronts
(F2 individuals could remain un-assigned to any front when fronts spilled past a
single iteration).

## Decision
Replace the loop with a clean `processed = np.zeros(n, dtype=bool)` mask:
repeat until all individuals are processed, each pass collecting the next
non-dominated front among `unprocessed` indices. Add
`test_numpy_pure_python_equivalence()` comparing both implementations on 3-level
hierarchies (sizes 10/30/50/100).

## Consequences
- Removes the defensive `break`; correctness now guarded by unit test.
- `_NUMPY_FASTPATH_THRESHOLD` unchanged; fast-path only engages at pop >= 20.
