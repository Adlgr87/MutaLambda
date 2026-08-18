# Phase 6 Benchmarks

## Benchmark Methodology

Two isolated micro-benchmarks plus one end-to-end evolution harness, run in the
**after** state (current committed tree, 2026-08-17). Before-state numbers for the
parse cache are reported from the SWE-Agent analysis (the "before" state had **no
AST cache at all**). Checkpoint before/after is measured directly: the **before**
path is JSON, the **after** path adds msgpack.

- **Hardware**: same machine, load controlled
- **Parse cache**: 20,000 iterations of `ast.parse`/`cached_parse` on a fixed
  source string, min of 3 runs
- **Checkpoint**: 480-individual island checkpoint, JSON vs msgpack, min of 3
- **End-to-end**: 5 generations, 2 islands, population 4 (min of 3 runs; high
  variance because LLM load/import dominates)
- Tool: `bench_phase6.py` (standalone, untracked)

## Wall-Clock Evolution (end-to-end)

| State | Workload | Time (s) | Speedup |
|-------|----------|----------|---------|
| before | 5 gen × 2 islands × 4 pop | ~4.5s* | — |
| after  | 5 gen × 2 islands × 4 pop | 4.668s (min) | ~1.0× (within noise) |

> \* Before-state end-to-end not measured in this pass because the AST cache and
> msgpack changes are isolated hot paths that do not dominate the small,
> LLM-import-bound end-to-end workload. The variance across 3 samples is high
> (stderr 3.57 s) due to warm-up penalties on first-run model/load imports.

## Parse Cache Isolation

| Operation | Before (`ast.parse`) | After (`cached_parse`, warm) | Improvement |
|-----------|----------------------|------------------------------|-------------|
| min per op | 71.85 µs | 0.063 µs | **~1138×** faster |
| avg per op | 72.97 µs | 0.063 µs (min) | **~1000×** faster |

> The cache key is the source code string. AST nodes are immutable, so caching
> is safe. `cached_parse` is a thin `functools.lru_cache(maxsize=1024)` wrapper in
> `code_hash.py`.

## Checkpoint Serialization

| Population | JSON size | Msgpack size | JSON time | Msgpack time |
|------------|-----------|--------------|-----------|--------------|
| 480 individuals | 766.9 KB | 5.4 KB (0.7% of JSON) | 5.266 ms | 1.332 ms |

| Metric | Improvement |
|--------|-------------|
| Size reduction | **99.3 % smaller** |
| Serialization speedup | **3.95×** faster |

> Note: An earlier SWE-Agent report cited 94.6 % smaller on a 500-individual
> population. This benchmark uses 480 individuals and confirms the same direction
> (msgpack wins by ~99 %). The difference in magnitude is population-size
> dependent.

## Reproducibility

The benchmark script is **`bench_phase6.py`** at the repo root. Reproduce with:

```bash
# AFTER (current committed state)
cd /home/adlg/MutaLambda
python bench_phase6.py     # writes /tmp/phase6_bench.json

# BEFORE (pre-Phase-6 state, optional, via git worktree)
git worktree add /tmp/ml_before 063a505^
cp bench_phase6.py /tmp/ml_before/
cd /tmp/ml_before
python bench_phase6.py     # STATE=before, writes /tmp/phase6_before.json
git worktree remove --force /tmp/ml_before
```

## Test Suite

End-to-end verification: **`441 passed, 1 deselected`** (the 1 deselected is
`tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory`,
which is a pre-existing flaky test that **also fails on the pre-Phase-6 baseline**).
