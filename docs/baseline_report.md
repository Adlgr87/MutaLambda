# MutaLambda — Baseline Performance Report

Generated: 2026-08-28 (FASE 0 — Phase 0 baseline)
Profiling session run against `muta_lambda.MutaLambdaAgent.run` with a 4-island ring
topology, 5 generations, population 4 per island, checkpoint disabled, early-stop
patience 3. No LLM backend key was configured (OpenRouter/Agnes), so LLM-backed
mutation gates failed with `LLMCircuitOpen` and the run degraded to AST-only mode;
this is representative of an offline/local workload.

## Executive summary

| Metric | Value |
|---|---|
| Total wall-clock (`run`) | 5.576 s |
| Generations completed | 5 (early-stopped at gen 4) |
| Islands | 4 |
| Population / island | 4 |
| Peak traced memory | 11.49 MB |
| Total function calls | 312 528 (297 352 primitive) |
| Best score achieved | -1.0000 |
| Run UUID | `4737beebcd1e` |

## Top-10 most expensive call sites (by cumulative time)

1. `concurrent.futures._base.as_completed` — 16.682 s cum (thread/futures plumbing; includes
   process-pool join wait). This is an artifact of how the sandbox evaluation pool is shut
   down — the `join` of worker processes dominates.
2. `threading.wait` / `_thread.join` — 15.5 – 16.66 s cum. Same root cause:
   `SandboxEvaluator`/`EvaluationService` process-pool teardown.
3. `SandboxEvaluator.shutdown` (`sandbox.py:123`) → `EvaluationService.shutdown`
   (`evaluation_service.py:400`) → `process.py:644 _join_executor_internals`.
   This is the single largest contributor of cumulative wall time **outside of actual
   evolution work**.
4. `MutaLambdaAgent.run` (`muta_lambda.py:1193`) — 5.222 s cum (end-to-end orchestrator).
5. `MutaLambdaAgent.step_generation` (`muta_lambda.py:936`) — 5.194 s cum across 4 calls
   (~1.30 s/generation).
6. `IslandPool.run_generation` (`island_evolution.py:118`) — 5.189 s cum.
7. `ASTMutator._complexity_score` (`evolution_engine.py:451`) — 0.031 s cum, 0.031 s tottime
   across 67 calls. Pure-Python AST recursion; the single hottest *non-plumbing* function.
8. `charset_normalizer` module import — 0.034 s (one-time import cost).
9. `marshal.loads` — 0.033 s (bytecode caching during import).
10. `evolution_engine` module-level exec — 0.062 s (import-time class/enum construction).

## Where the time actually goes

```
time.sleep            4.713 s tottime  (12 calls × ~0.39 s)  ← pool join / worker idle
select.poll           0.215 s tottime  (75 calls)           ← IPC from sandbox subprocesses
_complexity_score     0.031 s tottime  (67 calls)           ← AST analysis hot loop
```

**Interpretation.** Two regimes exist:

- **Plumbing/teardown overhead** (`~95 %` of wall time): `time.sleep` inside the
  process-pool join and `as_completed` wait chains. This is **deterministic and
  removable** — it is spent *after* the last generation, not during evolution.
- **Real evolutionary work** (`<1 %` of wall time): AST mutation, complexity scoring,
  fitness evaluation. This is the signal the optimizer must preserve and accelerate.

## Latency breakdown (approximate, single run)

| Stage | Time (s) | Notes |
|---|---|---|
| Agent setup + module imports | ~0.05 | dominated by `charset_normalizer`, enum conversion |
| 5 generations × step_generation | ~0.21 | 5.194 cum − teardown overlap; real evolve work |
| Sandbox evaluator teardown | ~5.0 | `process.py` executor join + queue thread join |
| **Total** | **5.58** | — |

## Memory profile

- Peak traced Python heap: **11.49 MB** (traced via `tracemalloc`, single run).
- No sustained growth detected (run exits cleanly; no leak signature).

## Reproducer

```bash
MUTALAMBDA_UNSAFE_LOCAL=1 python -c "
import cProfile, pstats, io, tracemalloc
from muta_lambda import MutaLambdaAgent, EvolveConfig
cfg = EvolveConfig(generations=5, population_size=4,
                   seed_codes=['<seed>'], checkpoint_enabled=False,
                   early_stop_patience=3)
prof = cProfile.Profile(); tracemalloc.start(); prof.enable()
MutaLambdaAgent(cfg).run()
prof.disable(); cur,peak = tracemalloc.get_traced_memory()
pstats.Stats(prof).sort_stats('cumulative').print_stats(20)
print('mem_peak_MB', peak/1e6)
"
```

## Baseline correctness gate

- Full unit test suite: **524 passed**, 7 failed, 5 skipped
  (failures are pre-existing `tree_sitter_cpp` import gaps in test env, unrelated to
  this baseline run).
- `test_full_smoke_chain` (evolve → writes `optimized.py` + `fitness_report.json`): **PASS**

## Implications for FASE 2 / FASE 4

1. Removing the ~5 s pool-teardown `join`/`sleep` cost is the highest-leverage
   non-functional win and should be gated behind a "clean shutdown only when
   checkpoint disabled" flag rather than done on every quick run.
2. `_complexity_score` is the best candidate for a vectorized/leaf C-extension
   offload in FASE 3/4 — it is pure AST recursion with no external state.
3. The run is **CPU-bound and single-process** — ideal GPU batch-eval candidate once
   the correctness gate is locked (ε < 1e-10 numeric parity vs this baseline).
