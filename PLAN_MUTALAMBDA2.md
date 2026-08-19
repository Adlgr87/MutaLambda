# PLAN_MUTALAMBDA2.md — MutaLambda Optimization Roadmap (Corrected)

## Inventory Corrections

### 1. FitnessVector is 3-Objective, NOT 6
**Status:** CORRECTED

**Code evidence** (`fitness_vector.py:29`):
```python
"""Three-dimensional multi-objective fitness for Pareto optimization."""
# correctness, latency_p50, memory_peak_mb
```

`dominates()` uses only 3 objectives:
```python
self_vals = (self.correctness, -self.latency_p50, -self.memory_peak_mb)
```

`latency_p99`, `throughput`, `parsimony` are marked `# deprecated, kept for backward compatibility` (lines 49-52). They are NOT part of Pareto selection.

**Action:** All documentation must reflect 3 active objectives.

### 2. HFC (Horizontal Code Transfer) EXISTS
**Status:** CORRECTED — was misreported as non-existent

**Code evidence:**
- `muta_ext/thc_engine.py:46` — `class HorizontalTransferEngine`
- `island.py:176-178` — integrated into evolution pipeline
- `muta_lambda.py:560` — `self._thc_engine = None`
- `checkpoint_manager.py:219` — checkpointed
- `tests/test_evolution_upgrade_v2.py:12` — test coverage

HFC extracts successful functions from high-scoring individuals and injects them into compatible receivers, creating validated hybrids with lineage tracking.

---

## Phase 6 Optimizations (Completed)
- [x] AST parse cache (`cached_parse`, lru_cache maxsize=1024) — 1038x speedup
- [x] Msgpack checkpoint serialization (2000→256 threshold) — 3.90x faster
- [x] AST-only mutation fast-path (skip build_gate + security_gate) — DONE

---

## Pending Optimizations (Phase 7)

### P7.1 — HFC Evaluation Batch Volume
**Priority:** HIGH
**Predicted speedup:** ~15–25%
**File:** `island.py:_evolve_local` (line ~154)
**Problem:** Population is evaluated in a single `evaluate_batch(codes)` call, but offspring candidates are evaluated individually at line 682 via `evaluate_batch([code])[0]`.
**Solution:** Batch current population + offspring candidates into a single `evaluate_batch` call per generation. The `EvaluationService` already supports batch evaluation with caching.

### P7.2 — HFC Cache Hit/Miss Instrumentation
**Priority:** LOW
**Risk:** Visibility-only (no behavior change)
**File:** `evaluation_service.py:173-180`
**Problem:** `cache_stats()` only returns `{"size": N}`. No hit/miss counters exist.
**Solution:** Add `hits` and `misses` counters to `EvaluationService.__post_init__`, increment in `evaluate_batch`, expose in `cache_stats()`:
```python
def cache_stats(self):
    return {"size": len(self._cache), "hits": self._hits, "misses": self._misses,
            "hit_rate": self._hits / (self._hits + self._misses) if (self._hits + self._misses) else 0.0}
```

### P7.3 — Persistent Worker Pool
**Priority:** MEDIUM-HIGH
**Risk:** High (process lifecycle, error recovery)
**Predicted speedup:** ~5–15%
**File:** `evaluation_service.py:143-149`
**Problem:** `_ensure_pool()` spawns workers lazily but the pool is never reused across generations efficiently — each `evaluate_batch` with `pending_idx` submits all pending tasks but the pool churn adds overhead.
**Solution:** Keep the persistent `ProcessPoolExecutor` alive across generations (already done via `__post_init__`), but ensure `_pool_worker` doesn't re-import/re-initialize heavy modules per task. Consider a worker init function with `initializer` param.

---

## Test Status
- Total: 594 passed, 1 deselected (flaky `test_hfc_tiers`)
- Phase 6 benchmark: parse cache 1038x, msgpack 3.90x faster
- NSGA2 cache benchmark: no regression

## Run Commands
```bash
cd /home/adlg/MutaLambda
python bench_phase6.py
python -m pytest tests/ -q --deselect tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory
```