# Fitness metrics — what exists vs what does not

**Audience:** contributors reading `FitnessVector` / NSGA-II.  
**Related:** `fitness_vector.py`, `fitness_normalize.py`, `benchmarking.py`, `runners.py`.

## Active dimensions (6)

| Field | Direction | Source | Used by |
|-------|-----------|--------|---------|
| `correctness` | higher | tests passed / total | hard gate, protocol tests_gate |
| `latency_p50` | lower | wall time or multi-sample p50 | NSGA, weighted_sum |
| `latency_p99` | lower | same sample or true p99 | NSGA, weighted_sum |
| `throughput` | higher | tests/sec or ops/sec | NSGA, weighted_sum |
| `memory_peak_mb` | lower | rusage / runner | NSGA, weighted_sum |
| `parsimony` | higher | AST complexity vs size | NSGA, weighted_sum |

Default scalarisation weights: see `DEFAULT_WEIGHTS` in `fitness_vector.py`.

## Baseline-relative gains (optional)

`fitness_normalize.normalize_against_baseline` computes:

- `latency_gain = baseline_p50 / candidate_p50`
- `throughput_gain = candidate_tp / baseline_tp`
- `memory_gain = baseline_mem / candidate_mem`

Enable via evolution config `fitness_normalize: true` (default).

## Metrics **not** implemented on FitnessVector

These appear in some older planning notes; they are **not** fields or methods today:

- hypervolume
- IGD / epsilon indicator
- spread / spacing of Pareto front (beyond NSGA crowding distance)

NSGA-II crowding distance is computed in `nsga2.py`, not stored on `FitnessVector`.

## Tests

- Unit: `tests/test_fitness_vector.py`
- Multi-objective selection: `tests/test_nsga2.py` (uses shared `tests/conftest.make_individual`)
- Archive novelty is **orthogonal** (embedding similarity), not a FitnessVector field
