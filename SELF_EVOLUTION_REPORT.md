# Self-Evolution Report — MutaLambda optimizing MutaLambda

**Date:** 2026-08-19
**Target:** `nsga2._crowding_distance` (hot path: 110K lambda calls / 3.5K list sorts in a 20-iteration NSGA-II profile)
**Status:** ✅ Validated and merged — 483/483 tests passing
**Reproduce:** `python experiments/self_evolution_crowding.py --mutants 200`

## Executive Summary

MutaLambda was applied to its own hot path using its **real production gates**
(mutation filters, security scan, differential correctness oracle, honest
multi-size benchmark). The experiment produced a validated **1.49x geometric-mean
speedup** on the target function (up to **1.88x** on large fronts) with exact
semantic equivalence, and — more importantly — demonstrated the system's core
value proposition: **25 candidate mutants that were faster but incorrect were
rejected by the correctness oracle**. A naive fitness function would have
shipped any of them.

## Prerequisite: the `self` security profile

Self-evolution was structurally impossible before this experiment: MutaLambda's
own code uses `getattr` extensively (144K calls in one profile), and the
security filter blocked **100/100 mutants** of its own modules with
`ast:getattr_call`. This is evidence the gates work — they are calibrated for
*untrusted numeric kernels* — but it required a new `ProfileMode.SELF`:

- **Waives only** dynamic-introspection findings (`getattr_call`, `chr_call`)
  for trusted first-party code.
- **Still blocks** eval / exec / subprocess / imports / open / alias-of-eval /
  `__builtins__` access (verified by `tests/test_self_profile.py`).
- The sandbox remains the hard execution boundary.

## Pipeline (all gates are production code, not experiment scaffolding)

| Gate | Mechanism | Source |
|---|---|---|
| 1. Static | empty / syntax / max-length | `mutation_filters` |
| 2. Security | regex criticals + AST SecurityVisitor, profile=`self` | `mutation_filters` + `runners` |
| 3. Correctness | differential oracle vs baseline: 74 randomized populations incl. ties, degenerate (zero-range) dims, missing-fitness fallback, sizes 0–80; exact equivalence (tol 1e-9, inf==inf) | experiment harness |
| 4. Benchmark | median-of-7 across N ∈ {10, 50, 200, 1000}; accept only if gmean ≥ 1.10x **and no size regresses below 0.98x** | experiment harness |

Candidates: 200 random AST mutants (`ASTMutator`) + 3 engineered rewrites
playing the role the LLM backend plays in production (no LLM credentials in
this environment).

## Results

| Outcome | Count |
|---|---|
| Total candidates | 203 |
| Rejected by static/security gates | 0 |
| Failed to compile | 0 |
| Rejected by correctness oracle | 32 |
| — of which *faster but incorrect* (false speedups prevented) | **25** |
| Correct but below speedup threshold | 169 |
| **Accepted** | **2** |

### Accepted candidates

| Candidate | gmean | N=10 | N=50 | N=200 | N=1000 | Verdict |
|---|---|---|---|---|---|---|
| `engineered_purepy` (column sort, no lambdas/tuples) | 1.23x | 1.19x | 1.24x | 1.24x | 1.25x | accepted |
| `engineered_numpy` (stable argsort vectorization) | 1.14x | **0.44x** | 1.08x | 1.60x | 2.01x | **rejected — small-front regression** |
| `engineered_hybrid` (purepy < 80 ≤ numpy) | **1.49x** | 1.22x | 1.28x | 1.67x | 1.88x | **merged** |

The benchmark gate's no-regression rule caught the NumPy variant's small-front
penalty (array setup overhead dominates at n<40: 0.28x at n=5). The merged
implementation is a size-gated hybrid.

### End-to-end impact (full NSGA-II cycle: sort + crowding + select)

| Population | Before | After | Δ |
|---|---|---|---|
| 100 | 2.12 ms | 2.01 ms | +5% |
| 400 | 24.38 ms | 22.32 ms | +9% |
| 1000 | 132.87 ms | 131.69 ms | ~1% |

Honest reading: the cycle is dominated by `non_dominated_sort` (already NumPy-
vectorized), so function-level 1.49x translates to single-digit end-to-end
gains — consistent with the lessons in `EMPIRICAL_EVIDENCE.md`.

## Side discovery: dogfooding found a real bug

The first self-application attempt **crashed the mutation engine**: four AST
operators assumed `node.body` is always a list, but for `ast.Lambda` /
`ast.IfExp` it is a single expression node (`TypeError: 'Name' object is not
iterable` while mutating `nsga2.py`, which contains lambdas). Fixed, with
regression tests that permanently mutate MutaLambda's own source
(`tests/test_mutator_robustness.py`).

## Lessons (extending EMPIRICAL_EVIDENCE.md)

1. **The gates are the product.** 12% of random mutants were faster-but-wrong;
   the differential oracle rejected every one of them.
2. **Benchmark gates need small sizes too.** Measuring only large inputs would
   have shipped a variant that is 3.6x *slower* on the most common front sizes.
3. **Self-application is a bug-finding tool**, independent of any speedup: the
   very first run surfaced a latent crash affecting any user code with lambdas.
4. Function-level speedups compress at system level when a different component
   dominates — report both, always.

---

# Chapter 2 — The mutation engine's copy path (2026-08-19)

**Target:** `ASTMutator.apply_random_mutation` — profiling showed
`copy.deepcopy` of the cached AST was **60% of total mutation time**
(26 ms/copy on nsga2.py, 38 ms on muta_lambda.py).
**Status:** ✅ Validated and merged — 483/483 tests passing
**Reproduce:** `python experiments/self_evolution_astmutator.py --mutants 100`

## Candidates

- **A. re-parse** — `ast.parse(code)` per attempt instead of deepcopying the
  cached tree (a fresh parse measured 4.4–6.6x faster than deepcopy at every
  file size, and guarantees the same pristine-tree invariant).
- **B. pickle** — snapshot `pickle.dumps(tree)` once, `pickle.loads` per attempt.
- **100 meta-mutants** — ASTMutator mutating its own `apply_random_mutation`.

## Gates & oracle

Same production machinery as chapter 1, with a **seeded differential oracle**:
for identical RNG seeds, a candidate must produce *byte-identical output* to
the baseline across a 7-file corpus (tiny/lambda-heavy/broken-syntax/empty +
3 real modules) × 30 seeds. Benchmark gate across 4 file sizes
(34/239/377/1594 lines), gmean ≥ 1.10x, no size below 0.98x.

## Results

| Outcome | Count |
|---|---|
| Total candidates | 102 |
| Rejected by security gate | 1 — **the pickle variant** |
| Rejected by seeded oracle | 17 (3 of them faster-but-incorrect) |
| Correct but below threshold (noise ~1.0x) | 83 |
| **Accepted** | **1 — re-parse, 1.76x gmean** |

| Benchmark | constants.py | fitness_vector.py | nsga2.py | muta_lambda.py |
|---|---|---|---|---|
| Speedup (per-call) | 1.83x | 1.74x | 1.72x | 1.72x |

**End-to-end** (60-mutation loop on nsga2.py, no profiler): 0.840 s → 0.567 s
= **1.48x**.

## Two instructive defeats

1. **Security gate rejected the pickle candidate** (`ast:call:pickle.dumps`,
   `ast:call:pickle.loads`) — and it was *right*: `pickle.loads` is a
   deserialization primitive equivalent to code execution. Even the `self`
   profile does not waive it. Defense in depth working exactly as designed;
   the equally-fast re-parse variant won instead.
2. **The first experiment run produced zero real meta-mutants.** Method source
   extracted via `inspect.getsource` is indented; mutating it raised a silent
   `SyntaxError` and returned the input unchanged, and the security scan then
   blocked all 100 "mutants" as unparseable. The harness now dedents and
   strips the decorator first. Lesson: *validate that your mutants actually
   mutated* — a pipeline can look busy while doing nothing.

## A measurement artifact caught red-handed

A quick post-merge check suggested **6.87x** end-to-end — too good to be true,
and it was: the baseline had been measured **with cProfile enabled**, which
disproportionately penalizes deepcopy (1M+ instrumented Python-level calls)
versus C-level `ast.parse`. Re-measured cleanly: 1.48x. Never compare a
profiled run against an unprofiled one.

---

# Ledger — victories & defeats (complete record)

> "Las derrotas son las que más enseñan." Registro completo, sin maquillaje.

## Victories (validated & merged)

| # | What | Evidence |
|---|---|---|
| V1 | `_get_fitness()` +10.2% (2026-06, EMPIRICAL_EVIDENCE.md) | 149/149 tests |
| V2 | AST parse cache, MsgPack checkpoints, vectorized dominance (Phase 6) | PHASE6_BENCHMARK_REPORT.md |
| V3 | Self-application found a real crash: 4 mutation operators broke on lambda bodies (`node.body` not a list) | fixed + `tests/test_mutator_robustness.py` |
| V4 | `ProfileMode.SELF` — introspection-only waiver; eval/exec/pickle/imports still blocked | `tests/test_self_profile.py` (10 tests) |
| V5 | `_crowding_distance` size-gated hybrid: **1.49x gmean** (1.88x at N=1000), exact equivalence on 74 populations | ch. 1, merged |
| V6 | `apply_random_mutation` re-parse: **1.76x gmean** per call, **1.48x** end-to-end | ch. 2, merged |
| V7 | Gates rejected **28 faster-but-incorrect candidates** across both chapters (25 + 3) — the false-speedup class that killed the 2026-06 experiments never reached the population | chs. 1–2 JSON results |

## Defeats (and what each one taught)

| # | What failed | Lesson |
|---|---|---|
| D1 | Fitness-directed migration lost to plain ring topology, 57.6% vs 92.2% (2026-06) | Simpler beats "intelligent" until proven otherwise |
| D2 | `dominates()` loop unrolling: −15.6%; `weighted_sum()` fast path: −13.4% (2026-06, reverted) | Measure after, not just before |
| D3 | Unvalidated AST mutations reported +97%/+100% false speedups (2026-06) | Correctness oracles are non-negotiable |
| D4 | Pure-NumPy crowding variant: 2x on big fronts, **0.28x on small ones** — initially accepted because the benchmark gate only measured large sizes | Benchmark gates must cover the *common* case, not the flattering one |
| D5 | Pickle copy variant blocked by the security scanner | The gates outrank the optimizer — as they should |
| D6 | First meta-mutation run: 100 mutants, 0 actual mutations (indented source → silent SyntaxError) | Verify your pipeline does work, not just runs |
| D7 | "6.87x!" — profiled baseline vs unprofiled candidate | Identical measurement conditions or the number is fiction |
| D8 | 83/100 valid meta-mutants landed within noise (0.92–1.07x); random mutation alone found no real optimization in either chapter | Random search doesn't beat engineered/LLM candidates on mature code — the gates + candidate quality are the product |
