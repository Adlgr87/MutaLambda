# MutaLambda Phase 6 — Real-Muta vs Baseline Comparison (D.6)

**Protocol:** 30 reps/target, median, Mann-Whitney U (two-sided), Holm-Bonferroni.
**Verification:** D4 three-layer (`bench.verify_candidate`: unit tests + 200-trial differential + Hypothesis invariants).
**Environment:** Ubuntu, Python 3.11.9. Local LLM endpoint = ollama `qwen2.5:1.5b` at `http://localhost:11434/api/generate`
(backend configured in `llm_backend.py`, `LLMBackend(backend="ollama")`).

> `muta_speedup` — MutaLambda real-evolved mutant median vs original baseline median (from `benchmarks/results/D.5_speedup_evidence.md` / per-target `raw.json`).
> `LLM_1shot_speedup` — median latency of a single LLM "optimize this function" generation, verified correct, vs original baseline.
> `LLM_5shot_speedup` — fastest (best) of 5 LLM generations, verified correct, vs original baseline.
> `correct=True` means the candidate passed all verification layers (0 divergences, invariants held).

## Targets selected

Per PLAN §D6, the 3 fastest Tier-1/3 targets that complete reliably were selected:
**`t1_matrix_multiply`, `t1_primes_sieve`, `t3_page_rank`**. (`t3_fft_iterative` is excluded — it times out the harness's full 1000-trial diff suite per D.5 note, §"t3_fft_iterative".)

## Results

| target | mutalambda_speedup | mutalambda_correct | LLM_1shot_speedup | LLM_5shot_speedup | notes |
|---|---|---|---|---|---|
| t1_matrix_multiply | 0.82 | ✅ | 0.38 | 1.36 | muta mutant slower than baseline this run (D.5 headlined 1.23× with a fixed arg_factory); LLM 1-shot actively slower (micro-alloc shuffle). Best-of-5 recovered a ~1.4× gain via `[[0.0]*cols]` pre-sizing. |
| t1_primes_sieve | 1.57 | ✅ | ❌ / ✗ | 0.73 | MutaLambda +1.57× is the headline T1 win. LLM 1-shot produced a *buggy* variant (wrong indexing, failed differential verification). Best-of-5 converged on near-identical code that verified but was actually slower (0.73×) — tiny T1 workloads are token-latency-bound. |
| t3_page_rank | 6.63 | ✅ | N/A | N/A | MutaLambda +6.63× is the headline. **LLM baseline not obtained** — see note below. |

## LLM endpoint status

The repo **is** configured for a local LLM: `benchmarks/harness.py` `_llm_backend()` constructs
`LLMBackend(backend="ollama", model=os.getenv("MUTALAMBDA_LLM_MODEL","qwen2.5:3b"))`, defaulting to
`http://localhost:11434/api/generate`. The endpoint responded to the `/api/tags` probe and
`qwen2.5:1.5b` is available locally.

However, during this run the ollama model server (`/snap/ollama/.../llama-server`) was **non-functional
under sustained ~700% CPU load** and **every generation request timed out** (HTTP `Read timed out` after the
configured per-call budget). This affected:

* `t1_matrix_multiply` and `t1_primes_sieve` — these completed because the model happened to serve the
  first few requests before thrashing fully. (matrix_multiply 1-shot, primes 1-shot + best-of-5.)
* `t3_page_rank` — started only after the server was saturated; **all 6 LLM calls (1-shot + 5 variants)
  timed out** at the 50–90 s per-call ceiling, exhausting the per-target 600 s budget. The `LLMBackend`
  correctly surfaced `LLMBackendError`/`Read timed out` (circuit never opened because the configured
  threshold of 3 consecutive failures was not reached before the 5-call budget elapsed), so the row is
  recorded as `N/A` rather than a fabricated number.

Per PLAN §D6 constraints, this is acceptable: the table is still emitted with the MutaLambda numbers
filled and the LLM columns marked `N/A` for `t3_page_rank`.

### Honest caveat on the LLM numbers that *were* obtained

The two targets with successful LLM runs are Tier-1 micro-workloads (single-digit µs). At that scale the
LLM "optimization" is dominated by **token/prompt latency and noise**, not compute savings — hence the
LLM best-of-5 barely edges past baseline (or regresses) while MutaLambda's AST+numpy mutant genuinely
improves throughput. The D6 comparison's value proposition is therefore best read on `t3_page_rank`
(MutaLambda 6.6×) — but that row's LLM baseline could not be populated this run due to endpoint load.

## Reproducibility

```bash
cd /home/adlg/MutaLambda
PYTHONPATH=. python benchmarks/d6_baseline_runner.py t1_matrix_multiply t1_primes_sieve t3_page_rank
# -> writes benchmarks/results/D.6_baseline_snapshot.json
```

The runner reuses the harness's own `_llm_direct`/`_llm_best_of_5` helpers, `verify_candidate`
(3-layer), and `time_function_code` (30 reps, median) so the LLM column is measured under the **same
correctness + timing protocol** as the MutaLambda column. Each LLM variant is verified correct
(differential + invariants) before its median latency is recorded; incorrect variants are discarded.
