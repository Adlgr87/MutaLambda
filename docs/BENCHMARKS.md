# Benchmarking MutaLambda — methodology and status

This document is the contract for every performance number this project
publishes. It exists because the field is full of unfalsifiable claims
("3.6x faster!") and because MutaLambda's own README, until now, carried a
row of internal targets that nobody outside the author's machine could
reproduce.

The rule is simple:

> **A number is publishable only if a stranger can re-derive it from this
> repository, a stated dataset, and a stated machine — and only if the
> harness that produced it was actively trying to catch us cheating.**

---

## 1. What is measured

| Dimension | How | Why it is not optional |
|---|---|---|
| Latency | p50 of N samples per process, mean ± std across R independent processes | A single run measures the allocator's mood, not the code |
| Memory | `tracemalloc` peak on a dedicated pass | Timing and memory instrumentation distort each other |
| Correctness | Visible split (given to the optimizer) + **held-out split** (never shown) | Optimizers overfit to the tests they can see |
| Invariants | Black-box physical properties re-checked after optimization | Tests cover values; invariants cover behaviour |
| Cost | LLM calls, approximate tokens, wall-clock, estimated USD | "Cheaper than AlphaEvolve" is a claim about the denominator |
| Integrity | Static + dynamic gates (§4) | Otherwise the fastest strategy is to cheat |

Speedup is always `baseline_mean_p50 / optimized_mean_p50`, and both sides are
measured **interleaved** (A/B/A/B, rotating who goes first) in the same
session so CPU frequency drift hits both equally.

---

## 2. The tiers

### Tier 1 — table stakes

| Suite | Status | What it settles |
|---|---|---|
| `effibench` | ready | Ratio to the *human canonical* solution. EffiBench's headline finding is that GPT-4 code averages ~3.12x the canonical execution time (13.89x worst case). Our claim to test: how far toward 1.0x can the ratio be pushed with 100% held-out correctness? |
| `pie` | ready | %Opt and speedup on C++ pairs **already compiled at -O3**, where a human already made the program faster. If MutaLambda cannot beat the human here, there is no story. |
| `polybench` | ready | 30 numerical kernels — where the NumPy/vectorisation mutators either show up or do not. |
| `pyperformance` | planned | Whole-application workloads. Deliberately unimplemented, see §6. |

### Tier 2 — the differentiators

| Suite | Status | What it settles |
|---|---|---|
| `effibench-plus` | ready | Same tasks, plus conservation/monotonicity/finiteness invariants. The claim: a generic optimizer breaks the physics; Scientific Mode does not. Both are run on the same tasks with the same budget, or the comparison is worthless. |
| `rosetta` | experimental | Does an optimization found in Python survive UAST emission to Rust/C++? A negative result here gets published too. |

### Tier 3 — the moonshot

| Suite | Status | What it settles |
|---|---|---|
| `eoh` | ready | Heuristic discovery (online bin packing, circle packing n=26). Different metric: solution quality per dollar, versus AlphaEvolve-class systems. |

---

## 3. The visible / held-out split

Every task carries two test sets:

* **visible** — handed to the optimizer, used as its own correctness gate;
* **held-out** — never serialised into any prompt, never reachable from the
  optimizer process.

A candidate that fails one held-out test is `rejected`: no speedup credit, and
it appears in the report with the failing case. This is the single most
important line of defence, because "optimize until the given tests pass" is
exactly what an LLM will do if you let it.

The split is deterministic (fixed seed, published) so runs are comparable.

---

## 4. Integrity gates (the anti-super-bug layer)

Implemented in `bench/integrity.py`; each returns a human-readable reason that
goes straight into the report.

| Gate | Verdict | Catches |
|---|---|---|
| `parses` | rejected | Non-compiling output scored as a win |
| `forbidden_imports` | rejected | `socket`, `subprocess`, `pickle`, filesystem access |
| `dangerous_calls` | rejected | `eval`/`exec`/`open`, `sys.settrace` |
| `entrypoint_preserved` | rejected | Renaming the function so tests silently no-op |
| `no_op_entrypoint` | rejected | Returning a constant, ignoring inputs |
| `hardcoded_answers` | rejected | Expected outputs pasted in as new literals |
| `holdout` | rejected | Overfitting to the visible tests |
| `cross_call_memoization` | suspect | Caching that only wins because the benchmark reuses inputs |
| `warm_cache_anomaly` | suspect | First sample ≫ steady state |
| `measurement_stability` | suspect | Cross-run std > 25% of the mean — a noisy machine, not a result |
| `large_speedup` | note | ≥100x: legitimate for O(n)→O(1), but the diff gets a manual look |
| `clock_surface` | suspect | Importing `time`/`sys`/`threading` inside a timed candidate |

C++ candidates (PIE) get the equivalent regex-level gates: no `system()`, no
`<fstream>`, no `<chrono>` tampering, no expected output pasted as a literal,
`main()` must survive.

**Verdict semantics:** `clean` and `note` count toward headline numbers;
`suspect` is published but excluded from every aggregate; `rejected` is a
failure. The excluded list, with reasons, is printed under the headline table
— so the number of tasks quietly dropped is itself a published metric.

---

## 5. The noise floor

Before a suite runs, the harness measures **identical code against itself**
and publishes the ratio:

```
- measurement noise floor: identical code measured 0.834x against itself
  → speedups below 1.20x on this machine are within measurement noise
```

The %Opt threshold is then `max(1.10, noise_band)`. On a quiet, pinned
machine that is PIE's 10% convention; on a shared 2-vCPU cloud box it might be
1.3x, and marginal "wins" are listed separately as *within noise* instead of
being counted. A benchmark that cannot state its own error bars is a demo.

**For publication runs:** `performance` governor, turbo disabled, no other
load, `--repeats 5` minimum. The report prints the governor and warns when it
is not `performance`.

---

## 6. Why `pyperformance` is deliberately not implemented

pyperformance benchmarks are whole applications driven by an upstream harness
that owns setup, teardown and timing. There is no "function to optimize".
Pointing an evolutionary optimizer at them without first declaring *which
modules it is allowed to rewrite* produces numbers that look impressive and
mean nothing. The suite raises with the concrete plan (declare an optimization
surface, run the upstream harness against the patched surface, compare with
`pyperformance compare`). PolyBench carries the numeric argument in the
meantime.

The same standard applies to `rosetta`, which is marked `experimental` and
refuses to emit tasks until they have a machine-checkable I/O contract.

---

## 7. Running it

```bash
# what exists, and what each suite needs
python -m bench.runner list
python -m bench.runner datasets

# self-test: identity must report ~1.00x and 100% correctness
python -m bench.runner run --suite smoke --optimizer baseline --repeats 5

# deterministic mutators only — how much does the LLM actually add?
python -m bench.runner run --suite polybench --optimizer numpy --repeats 5

# the control group every comparison table needs
python -m bench.runner run --suite effibench --optimizer llm-oneshot \
    --llm-backend openai --llm-model gpt-4o-mini --limit 50

# the system under test
python -m bench.runner run --suite effibench --optimizer mutalambda:deep \
    --repeats 5 --out results/ --include-diffs

# ablations: which component is actually doing the work?
for a in no_hfc no_thc no_prompt_evolution single_island; do
  python -m bench.runner run --suite effibench --optimizer mutalambda:deep \
      --ablation "$a" --out results/
done
python -m bench.runner compare results/effibench/*/report.json
```

### Datasets

```bash
python scripts/fetch_bench_datasets.py --list
python scripts/fetch_bench_datasets.py effibench polybench-python
MUTALAMBDA_BENCH_CACHE=/data/bench python scripts/fetch_bench_datasets.py pie
```

Nothing is committed to the repo; each fetch prints the upstream licence and
writes a manifest with the git revision or sha256 actually obtained.

### LLM backends

`--llm-backend` accepts `ollama | openai | anthropic | openrouter | mistral`.
Groq and other OpenAI-compatible endpoints work through the `openai` backend:

```bash
export OPENAI_API_KEY=...            # your Groq key
export MUTALAMBDA_OPENAI_URL=https://api.groq.com/openai/v1/chat/completions
python -m bench.runner run --suite smoke --optimizer mutalambda:fast \
    --llm-backend openai --llm-model qwen/qwen3-coder-30b \
    --usd-per-1k-prompt 0.0002 --usd-per-1k-completion 0.0008
```

There is also `--llm-backend mock`: a deterministic stub for CI. Any report
produced with it is stamped **"Not a publishable result"** in its own header.

---

## 8. The publication format

Per task, the harness emits exactly the audit card the plan called for:

```
### effibench/042
- Original: 120.4 ms p50, 45.1 MB peak, 8/8 tests pass
- mutalambda:deep: 41.2 ms (65.8% faster), 32.0 MB, 8/8 tests pass,
  11,842 tokens, 44.6s wall
- Repeats: 5 (mean ± std reported)
- Integrity: clean (0 findings)
```

plus `report.json` (full records), `report.md`, `task_cards.md` and
`tasks/<id>/optimized.patch` under `--out`. The JSON carries the schema
version, the git commit, whether the tree was dirty, the environment
fingerprint, the noise calibration and the exact command line.

### What a claim must include

Never publish `3.6x faster`. Publish:

> `mutalambda:deep` on EffiBench (n=1000, 5 repeats, Xeon 8375C, performance
> governor, noise floor 1.04x): %Opt 43.1%, speedup geomean 2.14x,
> held-out correctness 96.8%, ratio-to-human 3.09x → 1.31x, 12 tasks excluded
> by integrity gates (listed), $4.12 in tokens with Qwen3-Coder-30B.

### Honesty notes that must travel with specific suites

* **PIE**: upstream reports **gem5-simulated** speedups precisely because
  wall-clock on commodity hardware invents phantom improvements. This harness
  reports wall-clock with repeats and std. The two are not interchangeable and
  must never appear in the same column without a footnote.
* **EffiBench**: the 3.12x figure is *GPT-4's* ratio in the original paper, on
  the original hardware. Our before/after ratios are measured here, on this
  machine, and only comparable to each other.
* **EoH / AlphaEvolve**: quality numbers are only comparable at the same
  problem size and the same feasibility tolerance (circle packing: state `n`).

---

## 9. Status and remaining work

| Item | State |
|---|---|
| Core measurement, integrity gates, reporting, ablations | done, 43 tests |
| `smoke`, `eoh` (native), `polybench` (reference formulation) | run today, no download |
| `effibench`, `effibench-plus`, `pie` adapters | written; need a real dataset fetch to validate row-shape assumptions against upstream |
| `polybench` full 30-kernel wiring from upstream PolyBench/Python | partial: kernels needing class-state wiring are skipped |
| `rosetta` cross-language emission through the UAST emitters | not wired — the honest blocker is the I/O contract |
| `pyperformance` | planned, see §6 |
| Docker image `ghcr.io/adlgr87/mutalambda:bench` | not built yet |

Anything in this table marked as not done must not appear in a README claim
until it is.

---

## 10. CI

The harness CI workflow lives at **`docs/ci/benchmark-harness.yml`** and is not
installed automatically (the automation account that produced this change is
not allowed to create GitHub Actions workflows). Enable it with:

```bash
cp docs/ci/benchmark-harness.yml .github/workflows/
git add .github/workflows/benchmark-harness.yml && git commit -m "ci: benchmark harness"
```

It runs the harness unit tests, checks that every suite is self-describing, and
executes the identity self-test with `--fail-under-correctness 1.0
--fail-on-rejected`. It deliberately does **not** publish performance numbers:
a shared GitHub runner is far too noisy, and pretending otherwise is exactly the
failure mode this harness exists to prevent.
