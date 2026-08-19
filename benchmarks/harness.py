"""
Bloque D - Benchmark harness for MutaLambda.

D2: 30 targets across 4 tiers (in benchmarks/targets/).
D3: 30 repetitions, median + IQR, Mann-Whitney U, Holm-Bonferroni, Cliff's delta.
D4: 3-layer verification (delegated to benchmarks/verification.py).
D5: raw.json + .diff per target in benchmarks/results/<target>/.
D6: compares Original, MutaLambda, LLM-direct(ollama), LLM best-of-5, Numba, mypyc.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import statistics
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking import run_callable_benchmark  # noqa: E402
from benchmarks.verification import verify_candidate  # noqa: E402
from comparison import compare_values  # noqa: E402

try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
TARGETS_DIR = BENCHMARKS_DIR / "targets"
RESULTS_BASE = BENCHMARKS_DIR / "results"

REPS = 30
WARMUPS = 5
DIFF_TRIALS = 1000
ALT_DIFF_TRIALS = 1000
SKIP_COMPILERS = False


# ── statistics helpers (D3) ─────────────────────────────────────────
def median_iqr(samples):
    """Return (median, iqr, p95)."""
    if not samples:
        return float("inf"), 0.0, float("inf")
    s = sorted(samples)
    n = len(s)
    md = statistics.median(s)
    q1 = s[int(0.25 * (n - 1))]
    q3 = s[int(0.75 * (n - 1))]
    p95 = s[int(0.95 * (n - 1))] if n > 1 else s[0]
    return md, q3 - q1, p95


def mann_whitney_p(a, b):
    """Mann-Whitney U p-value (non-parametric, two-sided)."""
    from scipy.stats import mannwhitneyu
    if len(a) < 2 or len(b) < 2:
        return 1.0
    try:
        _, p = mannwhitneyu(a, b, alternative="two-sided")
        return float(p)
    except Exception:
        return 1.0


def cliffs_delta(a, b):
    """Cliff's delta effect size in [-1, 1]."""
    if not a or not b:
        return 0.0
    a = np.asarray(a); b = np.asarray(b)
    more = np.sum(a[:, None] > b[None, :])
    less = np.sum(a[:, None] < b[None, :])
    return float((more - less) / (len(a) * len(b)))


def holm_bonferroni(pvals):
    """Holm-Bonferroni step-down correction across all targets."""
    n = len(pvals)
    order = sorted(range(n), key=lambda i: pvals[i])
    adj = [0.0] * n
    running_max = 0.0
    for rank, idx in enumerate(order):
        val = (n - rank) * pvals[idx]
        val = min(val, 1.0)
        running_max = max(running_max, val)
        adj[idx] = running_max
    return adj


def time_callable(fn, reps=REPS, warmups=WARMUPS):
    """Measure wall-clock latency of a zero-arg callable; return per-rep seconds."""
    latencies = []
    for _ in range(warmups):
        try:
            fn()
        except Exception:
            pass
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        latencies.append(time.perf_counter() - start)
    return latencies


def time_function_code(code, function_name, arg_factory, reps=REPS):
    """Exec source, build fn, time it with fresh args each rep."""
    ns = {"__name__": "__bench__"}
    exec(compile(code, "<bench>", "exec"), ns, ns)  # noqa: S102
    fn = ns[function_name]
    latencies = []
    for _ in range(WARMUPS):
        try:
            fn(*arg_factory())
        except Exception:
            pass
    for _ in range(reps):
        args = arg_factory()
        start = time.perf_counter()
        fn(*args)
        latencies.append(time.perf_counter() - start)
    return latencies


# ── arg factory ─────────────────────────────────────────────────────
def _build_arg_factory(sample_args):
    """Return a factory producing fresh random args matching sample_args structure.

    For functions like euclidean_distances(a, b) where a, b are lists of arrays
    with matching dimensionality, dimensions are shared across top-level args.
    """
    import random as _r
    rng = _r.Random(12345)

    # Determine shared dimension for array args (e.g. euclidean_distances(a, b))
    array_dims = {}
    # Determine shared "inner" dimension for list-of-lists matrix pairs so that
    # matrix_multiply(a, b) gets compatible dimensions: a is rows×k, b is k×cols.
    inner_dims = {}
    first_lol_idx = None
    for idx, v in enumerate(sample_args):
        if isinstance(v, np.ndarray):
            array_dims[idx] = len(v)
        elif isinstance(v, (list, tuple)) and v and isinstance(v[0], np.ndarray):
            array_dims[idx] = len(v[0])
        elif isinstance(v, (list, tuple)) and v and isinstance(v[0], (list, tuple)):
            # list-of-lists (e.g. matrix). Record first such arg so we can share inner dim.
            if first_lol_idx is None:
                first_lol_idx = idx
                inner_dims[idx] = len(v)          # outer dim (rows)
                if v and isinstance(v[0], (list, tuple)):
                    inner_dims[(idx, 'inner')] = len(v[0])  # inner dim (cols of a == rows of b)

    def make_one(v, top_idx=None):
        if isinstance(v, (list, tuple)):
            n = len(v)
            if n == 0:
                return lambda: np.array([], dtype=float)
            elem = v[0]
            if isinstance(elem, np.ndarray):
                # Use shared dim if available for this top-level arg
                dim = array_dims.get(top_idx, len(elem)) if top_idx is not None else len(elem)
                gen_arr = (lambda d=dim: np.random.uniform(-10, 10, size=max(d, rng.randint(1, max(d, 2)))))
                return (lambda: [gen_arr() for _ in range(rng.randint(1, max(n, 1)))])
            if isinstance(elem, (list, tuple)):
                # list-of-lists (matrix): keep inner dimension consistent across
                # paired args so matrix_multiply(a,b) has compatible shapes.
                base_rows = n
                base_cols = len(elem)
                if top_idx == first_lol_idx:
                    # First matrix: pick and remember the shared inner (col) dimension.
                    def _gen_first():
                        if (first_lol_idx, 'cols') not in inner_dims:
                            inner_dims[(first_lol_idx, 'cols')] = rng.randint(2, max(base_cols, 2))
                        cols = inner_dims[(first_lol_idx, 'cols')]
                        rows = rng.randint(2, max(base_rows, 2))
                        return [[rng.randint(-5, 5) for _ in range(cols)] for _ in range(rows)]
                    return _gen_first
                elif first_lol_idx is not None and (first_lol_idx, 'cols') in inner_dims:
                    shared = inner_dims[(first_lol_idx, 'cols')]
                    def _gen_second():
                        cols = rng.randint(2, max(base_cols, 2))
                        rows = shared  # rows of b must equal cols of a for matmul
                        return [[rng.randint(-5, 5) for _ in range(cols)] for _ in range(rows)]
                    return _gen_second
                else:
                    def _gen_plain():
                        cols = rng.randint(2, max(base_cols, 2))
                        rows = rng.randint(2, max(base_rows, 2))
                        return [[rng.randint(-5, 5) for _ in range(cols)] for _ in range(rows)]
                    return _gen_plain
            inner = make_one(elem, top_idx)
            return (lambda: [inner() for _ in range(max(rng.randint(1, n * 2), 1))])
        if isinstance(v, np.ndarray):
            dim = array_dims.get(top_idx, len(v)) if top_idx is not None else len(v)
            return (lambda: np.random.uniform(-10, 10, size=max(dim, rng.randint(1, max(dim, 2)))))
        if isinstance(v, str):
            chars = v or "abc"
            return (lambda: "".join(rng.choice(chars) for _ in range(rng.randint(1, 8))))
        if isinstance(v, bool):
            return (lambda: rng.random() < 0.5)
        if isinstance(v, int):
            return (lambda: rng.randint(-1000, 1000))
        if isinstance(v, float):
            return (lambda: rng.uniform(-1000, 1000))
        if callable(v):
            return (lambda: v)
        return (lambda: rng.uniform(-1000, 1000))

    gens = [make_one(a, top_idx=idx) for idx, a in enumerate(sample_args)]

    def factory():
        return tuple(g() for g in gens)
    return factory


def _build_arg_factory_from_strategy(strategy_str, validator=None, n_samples=5):
    """Build an arg factory from a Hypothesis strategy string.

    Draws a fixed set of valid argument tuples once (deterministic), then
    cycles through them on each call. If ``validator`` (the target function)
    is provided, samples that raise are discarded so benchmarking never fails
    on invalid generated inputs.
    """
    try:
        from hypothesis import given, settings as hyp_settings
        from hypothesis import strategies as st
        strat = eval(strategy_str, {"st": st})  # noqa: S307
    except Exception:
        def factory():
            return ()
        return factory

    samples = []
    @given(strat)
    @hyp_settings(max_examples=n_samples * 8, deadline=None)
    def _collect(x):
        samples.append(x)
    _collect()

    # Optionally filter out samples that crash the target function.
    if validator is not None:
        ok = []
        for x in samples:
            args = tuple(x) if isinstance(x, tuple) else (x,)
            try:
                validator(*args)
            except Exception:
                continue
            ok.append(args)
        samples = ok if ok else samples

    if not samples:
        samples = [()]

    idx = 0
    def factory():
        nonlocal idx
        val = samples[idx % len(samples)]
        idx += 1
        return val if isinstance(val, tuple) else (val,)
    return factory


# ── candidate generators (D6 alternatives) ─────────────────────────
def _mutate_code(code, function_name, mod=None, arg_factory=None, max_tries=12):
    """Produce a MutaLambda-style mutated candidate that PASSES verification.

    Tries AST mutations and NumPy-vectorized variants; keeps the fastest one
    that is verified correct against the original. Falls back to original if
    none are both correct and faster.
    """
    from evolution_engine import ASTMutator
    import random as _r
    rng = _r.Random(7)
    attempts = []
    # 1) numpy vectorization variants (often correct + faster for numeric targets)
    try:
        from numpy_optimizer import generate_numpy_variants
        attempts += [v for v in generate_numpy_variants(code, 8) if v.strip() != code.strip()]
    except Exception:
        pass
    # 2) AST random mutations (deterministic seed for reproducibility)
    for _ in range(8):
        m = ASTMutator.apply_random_mutation(code)
        if m and m.strip() != code.strip():
            attempts.append(m)
    # 3) Try ASTMutator several times with different seeds
    for _ in range(4):
        m = ASTMutator.apply_random_mutation(code)
        if m and m.strip() != code.strip() and m not in attempts:
            attempts.append(m)

    # Filter to correct candidates and benchmark, keep fastest correct
    baseline_samples = time_function_code(code, function_name, arg_factory, reps=min(REPS, 10))
    best = code
    best_samples = baseline_samples
    import os
    os.environ["MUTALAMBDA_LOG_LEVEL"] = "ERROR"
    for cand in attempts:
        if mod is not None and arg_factory is not None:
            ver = _verify(code, cand, mod, trials=12)
            if not ver.ok:
                continue
            # benchmark candidate quickly to pick the fastest correct
            try:
                samples = time_function_code(cand, function_name, arg_factory, reps=min(REPS, 10))
            except Exception:
                continue
            if statistics.mean(samples) < statistics.mean(best_samples):
                best = cand; best_samples = samples
    return best


def _is_valid_python(code):
    try:
        compile(code, "<cand>", "exec")
        return True
    except SyntaxError:
        return False


def _extract_function(resp, function_name):
    """Extract a `def function_name...` block from LLM text."""
    import re
    m = re.search(rf"(def {re.escape(function_name)}\b.*)", resp, re.DOTALL)
    if m:
        body = m.group(0)
        lines = body.split("\n")
        kept = [lines[0]]
        for ln in lines[1:]:
            if ln and not ln.startswith(" ") and not ln.startswith("\t") and ln.strip().startswith("def "):
                break
            kept.append(ln)
        text = "\n".join(kept)
        if _is_valid_python(text):
            return text
    return None


def _llm_backend():
    try:
        from llm_backend import LLMBackend
        model = os.getenv("MUTALAMBDA_LLM_MODEL", "qwen2.5:3b")
        return LLMBackend(backend="ollama", model=model, timeout_sec=90.0, temperature=0.1)
    except Exception:
        return None


def _llm_direct(code, function_name):
    """D6: LLM direct optimization (1-shot, no evolution) via ollama."""
    b = _llm_backend()
    if b is None:
        return code
    prompt = ("Optimize this Python function for speed. Return ONLY the code, no explanation.\n"
              "```python\n" + code + "\n```\nOptimized:\n")
    try:
        resp = b.generate(prompt)
    except Exception:
        return code
    return _extract_function(resp, function_name) or code


def _llm_best_of_5(code, function_name):
    """D6: LLM generate 5 variants, pick first valid that differs."""
    for _ in range(5):
        c = _llm_direct(code, function_name)
        if c.strip() != code.strip() and _is_valid_python(c):
            return c
    return code


def _compile_numba(code, function_name):
    """Return (callable, source) of a numba-JIT-wrapped function, or None."""
    if not HAS_NUMBA:
        return None
    ns = {"__name__": "__nb__", "njit": njit, "np": np}
    try:
        exec(compile(code, "<nb>", "exec"), ns, ns)  # noqa: S102
    except Exception:
        return None
    decorated = code.replace(f"def {function_name}", f"@njit\ndef {function_name}", 1)
    ns2 = {"njit": njit, "np": np}
    try:
        exec(compile(decorated, "<nb2>", "exec"), ns2, ns2)  # noqa: S103
    except Exception:
        return None
    return ns2.get(function_name), decorated


def _run_mypyc_compile(code, function_name):
    """Compile a source file with the mypyc CLI; return the compiled callable or None."""
    import shutil
    if not shutil.which("mypyc"):
        return None
    mod_file = REPO_ROOT / "_mpyc_target.py"
    try:
        mod_file.write_text(code)
        out_dir = REPO_ROOT / "_mpyc_out"
        out_dir.mkdir(exist_ok=True)
        proc = subprocess.run(["mypyc", str(mod_file)], capture_output=True, text=True,
                              timeout=120, cwd=str(REPO_ROOT))
        if proc.returncode != 0:
            return None
        sys.path.insert(0, str(out_dir))
        mod = importlib.import_module(mod_file.stem)
        return getattr(mod, function_name, None)
    except Exception:
        return None
    finally:
        if mod_file.exists():
            mod_file.unlink(missing_ok=True)


# ── Real MutaLambda engine (D6 MutaLambda column) ──────────────────
def _run_real_mutalambda(code, function_name, test_cases):
    """Run the REAL MutaLambda evolution engine (MutaLambdaAgent) with ASTMutator LLM.

    Returns best optimized source or None. Uses the repo's established mock-LLM
    pattern (bench_phase6.py) so the real island engine + correctness gates run.
    """
    import io
    from contextlib import redirect_stdout
    import muta_lambda as _ml
    from mutation_filters import _filter_mutant
    if not hasattr(_ml, "_filter_mutant"):
        _ml._filter_mutant = _filter_mutant
    from evolution_engine import ASTMutator
    from muta_lambda import EvolveConfig, MutaLambdaAgent

    def mock_llm(prompt):
        lines = prompt.split("\n")
        code_lines = [l for l in lines
                      if l.strip()
                      and not l.startswith(("You are", "Task:", "Improve", "Return",
                                            "Instructions:", "Constraints:", "Evaluation", "Scoring"))]
        c = "\n".join(code_lines).strip()
        if not c:
            return "def solution():\n    return 42"
        return ASTMutator.apply_random_mutation(c)

    cfg = EvolveConfig(
        num_islands=2, generations=4, population_size=5,
        seed_codes=[code], topology="ring", top_k=2,
        checkpoint_enabled=False, prompt_evolution=False, hfc_enabled=False,
        thc_enabled=False, spatial_enabled=False, workflow_enabled=True,
        allow_untested=False, enforce_differential=True, llm_backend="direct",
    )
    cfg.sandbox_timeout = 15.0
    sink = io.StringIO()
    try:
        with redirect_stdout(sink):
            agent = MutaLambdaAgent(config=cfg, llm_fn=mock_llm, test_cases=test_cases,
                                    timeout_sec=15.0, task=f"Optimize {function_name} for speed")
            best = agent.run(task=f"Optimize {function_name} for speed")
            agent.shutdown()
    except Exception:
        return None
    if best is None:
        return None
    mutated = best.code
    return mutated if mutated.strip() != code.strip() else None


# ── data structures ─────────────────────────────────────────────────
@dataclass
class VariantStat:
    median_s: float
    iqr: float
    p95: float
    mean_s: float
    n: int
    samples: List[float] = field(default_factory=list)


@dataclass
class TargetResult:
    target: str
    tier: int
    git_sha: str
    mutalambda_version: str
    env: Dict[str, Any]
    baseline: VariantStat
    optimized: VariantStat
    speedup: Optional[float] = None
    correctness: Dict[str, Any] = field(default_factory=dict)
    statistics: Dict[str, Any] = field(default_factory=dict)
    mutation_applied: str = ""
    diff_path: str = ""
    alternatives: Dict[str, VariantStat] = field(default_factory=dict)
    alternatives_correct: Dict[str, bool] = field(default_factory=dict)


def get_git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), stderr=subprocess.DEVNULL, text=True
        ).strip()[:12]
    except Exception:
        return "unknown"


def _pkg_version(name):
    try:
        mod = importlib.import_module(name)
        return getattr(mod, "__version__", "unknown")
    except ImportError:
        return None


def _cpu_info():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "unknown"


def _env_info():
    import platform
    return {
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu": _cpu_info(),
        "numpy": np.__version__,
        "numba": _pkg_version("numba"),
        "mypyc_available": _which("mypyc"),
        "hypothesis": _pkg_version("hypothesis"),
        "scipy": _pkg_version("scipy"),
    }


def _which(cmd):
    import shutil
    return shutil.which(cmd)


def _json_default(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.float32, np.float64)):
        return float(o)
    return str(o)


def _to_stat(samples):
    if not samples:
        return None
    md, iqr, p95 = median_iqr(samples)
    return VariantStat(md, iqr, p95, statistics.mean(samples), len(samples), list(samples))


def _stat_dict(s):
    if s is None:
        return {"median_s": None, "iqr": None, "p95": None, "n": 0, "error": "unavailable"}
    return {"median_s": round(s.median_s, 6), "iqr": round(s.iqr, 6),
            "p95": round(s.p95, 6), "mean_s": round(s.mean_s, 6), "n": s.n,
            "samples": [round(x, 8) for x in s.samples]}


def _make_diff(original, mutated):
    import difflib
    o = original.splitlines(keepends=True)
    m = mutated.splitlines(keepends=True)
    diff = list(difflib.unified_diff(o, m, fromfile="original", tofile="optimized", n=3))
    return "".join(diff)


def _verify(code, src, mod, trials=DIFF_TRIALS):
    """Run 3-layer verification; returns VerificationResult."""
    return verify_candidate(code, src, mod.test_cases, function_name=mod.function_name,
                            invariants=mod.invariants, input_strategy=getattr(mod, 'input_strategy', None),
                            random_trials=trials, seed=42)


def _bench_alt(src, function_name, arg_factory, code, mod):
    """Benchmark alternative source (LLM). Returns (samples, correct)."""
    if src is None or src.strip() == code.strip():
        return [], True
    if isinstance(src, str):
        ver = _verify(code, src, mod, trials=ALT_DIFF_TRIALS)  # global, overridable via --alt-trials
        if not ver.ok:
            return [], False
        try:
            samples = time_function_code(src, function_name, arg_factory, reps=REPS)
        except Exception:
            samples = []
        return samples, True
    return [], True


def _bench_callable(fn, arg_factory, code, function_name, mod):
    """Benchmark a callable (numba/mypyc) against original."""
    try:
        args = arg_factory()
        ns = {"__name__": "__cmp__"}; exec(compile(code, "<c>", "exec"), ns, ns)  # noqa: S102
        orig_fn = ns[function_name]
        a = orig_fn(*args); b = fn(*args)
        if not np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), rtol=1e-9, atol=1e-12):
            return [], False
    except Exception:
        return [], False
    try:
        samples = time_callable(lambda: fn(*arg_factory()), reps=REPS)
    except Exception:
        samples = []
    return samples, True


# ── per-target benchmark ──────────────────────────────────────────
def _compile_function(code, function_name):
    """Compile source into a callable function for validation."""
    ns = {"__name__": "__bench__"}
    exec(compile(code, "<bench>", "exec"), ns, ns)  # noqa: S102
    return ns[function_name]


def bench_one_target(mod, target_name, use_real_mutalambda=True, skip_llm=False):
    code = mod.source
    function_name = mod.function_name
    test_cases = mod.test_cases
    sample_args = list(test_cases[0]["args"]) if test_cases else []
    # Allow target to override arg generation (e.g. for correlated inputs like confusion_matrix).
    arg_factory = getattr(mod, 'arg_factory', None)
    if arg_factory is None:
        if hasattr(mod, 'input_strategy') and mod.input_strategy:
            arg_factory = _build_arg_factory_from_strategy(mod.input_strategy, validator=None)
        else:
            arg_factory = _build_arg_factory(sample_args)

    # Baseline timing
    # Build a callable for strategy validation if needed.
    try:
        baseline_fn = _compile_function(code, function_name)
    except Exception:
        baseline_fn = None
    if arg_factory is not None and baseline_fn is not None:
        # Rebuild a validating factory now that we have the function.
        if hasattr(mod, 'input_strategy') and mod.input_strategy and not getattr(mod, 'arg_factory', None):
            arg_factory = _build_arg_factory_from_strategy(mod.input_strategy, validator=baseline_fn)
    try:
        baseline_samples = time_function_code(code, function_name, arg_factory, reps=REPS)
    except Exception as exc:
        print(f"  [{target_name}] baseline timing failed: {exc}")
        return None
    b_med, b_iqr, b_p95 = median_iqr(baseline_samples)
    baseline_stat = VariantStat(b_med, b_iqr, b_p95, statistics.mean(baseline_samples), REPS, baseline_samples)

    # Candidate
    if use_real_mutalambda:
        candidate_src = _run_real_mutalambda(code, function_name, test_cases)
        mutation_label = "MutaLambda real evolution" if candidate_src is not None else "AST+numpy fallback"
        if candidate_src is None:
            candidate_src = _mutate_code(code, function_name, mod, arg_factory)
    else:
        candidate_src = _mutate_code(code, function_name, mod, arg_factory)
        mutation_label = "AST+numpy mutation (no real engine)"

    verification = _verify(code, candidate_src, mod)

    candidate_stat = VariantStat(float("inf"), 0.0, float("inf"), float("inf"), 0)
    if verification.ok:
        try:
            cand_samples = time_function_code(candidate_src, function_name, arg_factory, reps=REPS)
        except Exception as exc:
            print(f"  [{target_name}] candidate timing failed: {exc}")
            cand_samples = []
        if cand_samples:
            c_med, c_iqr, c_p95 = median_iqr(cand_samples)
            candidate_stat = VariantStat(c_med, c_iqr, c_p95, statistics.mean(cand_samples), REPS, cand_samples)

    # D6 alternatives
    alts = {}
    if not skip_llm:
        llm_src = _llm_direct(code, function_name)
        alts["llm_direct"] = _bench_alt(llm_src, function_name, arg_factory, code, mod)
        llm5_src = _llm_best_of_5(code, function_name)
        alts["llm_best_of_5"] = _bench_alt(llm5_src, function_name, arg_factory, code, mod)
    if not SKIP_COMPILERS:
        nb = _compile_numba(code, function_name)
        if nb is not None:
            nb_fn, _ = nb
            alts["numba"] = _bench_callable(nb_fn, arg_factory, code, function_name, mod)
        mp = _run_mypyc_compile(code, function_name)
        if mp is not None:
            alts["mypyc"] = _bench_callable(mp, arg_factory, code, function_name, mod)

    p_val = mann_whitney_p(baseline_samples, candidate_stat.samples or baseline_samples)
    delta = cliffs_delta(baseline_samples, candidate_stat.samples or baseline_samples)
    speedup = (round(b_med / candidate_stat.median_s, 4)
               if candidate_stat.median_s > 0 and candidate_stat.median_s != float("inf") else None)

    correctness = {
        "verified": verification.ok,
        "unit_tests": "passed" if verification.layer1_ok else "FAILED",
        "differential_trials": verification.differential_trials,
        "divergences": verification.divergences,
        "max_abs_error": verification.max_abs_error,
        "layer3": verification.layer3_msg,
    }

    result = TargetResult(
        target=target_name, tier=mod.TIER, git_sha=get_git_sha(),
        mutalambda_version="4.0.0", env=_env_info(),
        baseline=baseline_stat, optimized=candidate_stat, speedup=speedup,
        correctness=correctness,
        statistics={"mann_whitney_u_p": p_val, "cliffs_delta": delta},
        mutation_applied=mutation_label,
        alternatives={k: _to_stat(v[0]) for k, v in alts.items()},
        alternatives_correct={k: v[1] for k, v in alts.items()},
    )

    diff_text = _make_diff(code, candidate_src)
    run_dir = RESULTS_BASE / target_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{target_name}.diff").write_text(diff_text)
    result.diff_path = f"benchmarks/results/{target_name}/{target_name}.diff"

    raw = {
        "target": target_name, "tier": mod.TIER, "git_sha": result.git_sha,
        "mutalambda_version": result.mutalambda_version, "env": result.env,
        "baseline": _stat_dict(baseline_stat), "optimized": _stat_dict(candidate_stat),
        "speedup": speedup, "correctness": correctness, "statistics": result.statistics,
        "mutation_applied": mutation_label, "diff": result.diff_path,
        "alternatives": {k: _stat_dict(v) for k, v in result.alternatives.items()},
        "alternatives_correct": result.alternatives_correct,
        "protocol": {"repeticiones": REPS, "warmup": WARMUPS, "metrica": "mediana",
                     "dispersion": "IQR + p95", "significancia": "Mann-Whitney U",
                     "efecto": "Cliffs delta", "correccion": "Holm-Bonferroni sobre todos los targets"},
    }
    (run_dir / "raw.json").write_text(json.dumps(raw, indent=2, default=_json_default))
    return result


def _load_targets():
    mods = []
    for f in sorted(os.listdir(TARGETS_DIR)):
        if f.startswith(("t1_", "t2_", "t3_", "t4_")) and f.endswith(".py"):
            mod = importlib.import_module("benchmarks.targets." + f[:-3])
            mods.append((f[:-3], mod))
    return mods


def _aggregate_holm(results):
    """Apply Holm-Bonferroni across all targets; update raw.json on disk."""
    pvals = []
    idxs = []
    for i, r in enumerate(results):
        if r.statistics.get("mann_whitney_u_p") is not None and r.optimized.n > 0:
            pvals.append(r.statistics["mann_whitney_u_p"])
            idxs.append(i)
    if not pvals:
        return
    adj = holm_bonferroni(pvals)
    for i, r in zip(idxs, adj):
        results[i].statistics["p_adj_holm"] = r
        results[i].statistics["significant"] = bool(r < 0.05) and results[i].speedup is not None and results[i].speedup > 1.0
        rd = RESULTS_BASE / results[i].target
        if (rd / "raw.json").exists():
            raw = json.loads((rd / "raw.json").read_text())
            raw["statistics"]["p_adj_holm"] = r
            raw["statistics"]["significant"] = results[i].statistics["significant"]
            raw["statistics"]["speedup_significant"] = results[i].statistics["significant"]
            (rd / "raw.json").write_text(json.dumps(raw, indent=2, default=_json_default))


def _write_summary(results):
    run_dir = RESULTS_BASE / "latest"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = {"git_sha": get_git_sha(),
               "generated_at": datetime.now(timezone.utc).isoformat(),
               "total_targets": len(results), "significant_targets": [],
               "non_significant_targets": []}
    from collections import Counter
    tc = Counter()
    sig = 0
    for r in results:
        tc[r.tier] += 1
        if r.statistics.get("significant", False):
            sig += 1
            summary["significant_targets"].append(r.target)
        else:
            summary["non_significant_targets"].append(r.target)
    summary["by_tier"] = {f"tier{t}": tc[t] for t in sorted(tc)}
    summary["significant_count"] = sig
    summary["improved_count"] = sig
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=_json_default))
    env = results[0].env if results else _env_info()
    (run_dir / "env.json").write_text(json.dumps(env, indent=2, default=_json_default))
    print("\n=== SUMMARY ===")
    print(f"Targets: {len(results)} | Significant (p_adj<0.05 & faster): {sig}")
    for r in results:
        tag = "SIG " if r.statistics.get("significant") else "    "
        alts = {k: (round(v.median_s, 6) if v and v.median_s else None) for k, v in r.alternatives.items()}
        print(f"  {tag} {r.target:26s} T{r.tier} muta_speedup={r.speedup} "
              f"L2div={r.correctness.get('divergences')} corr={r.correctness.get('verified')} "
              f"alts_ok={r.alternatives_correct}")


def _run_bench_target(target_name, use_real, skip_llm):
    import importlib
    mod = importlib.import_module(f"targets.{target_name}")
    print(f"\n--- Target: {target_name} (tier {mod.TIER}) {'[REAL MutaLambda]' if use_real else ''}")
    try:
        r = bench_one_target(mod, target_name, use_real_mutalambda=use_real, skip_llm=skip_llm)
        if r:
            print(f"  speedup={r.speedup} correct={r.correctness.get('verified')} "
                  f"L2div={r.correctness.get('divergences')}")
        return r
    except Exception as e:
        print(f"  ERROR [{target_name}]: {e}")
        traceback.print_exc()
        return None


def main():
    global REPS, ALT_DIFF_TRIALS, SKIP_COMPILERS
    parser = argparse.ArgumentParser(description="MutaLambda Bloque D benchmark harness")
    parser.add_argument("--targets", nargs="*", default=[], help="specific target module names")
    parser.add_argument("--all", action="store_true", help="run all targets")
    parser.add_argument("--real-muta", type=int, default=0,
                        help="number of targets to run REAL MutaLambda engine on")
    parser.add_argument("--skip-llm", action="store_true", help="skip LLM direct/best-of-5 (faster, no network)")
    parser.add_argument("--skip-compilers", action="store_true",
                        help="skip numba + mypyc compilation (much faster; needed for CI)")
    parser.add_argument("--alt-trials", type=int, default=DIFF_TRIALS, help="differential trials for alternatives")
    parser.add_argument("--reps", type=int, default=REPS)
    parser.add_argument("--parallel", type=int, default=1,
                        help="number of targets to benchmark in parallel (default 1)")
    args = parser.parse_args()
    REPS = args.reps
    ALT_DIFF_TRIALS = args.alt_trials
    SKIP_COMPILERS = args.skip_compilers
    targets = _load_targets()
    if args.all:
        selected = targets
    elif args.targets:
        sel = set(args.targets)
        selected = [t for t in targets if t[0] in sel]
    else:
        selected = targets[:5]
    print(f"MutaLambda Bloque D harness: {len(selected)} targets, {REPS} reps, parallel={args.parallel}")
    real_indices = set(range(args.real_muta))
    results = []
    if args.parallel > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=args.parallel) as ex:
            futs = {ex.submit(_run_bench_target, name, i in real_indices, args.skip_llm): name
                    for i, (name, mod) in enumerate(selected)}
            for fut in as_completed(futs):
                r = fut.result()
                if r:
                    results.append(r)
    else:
        for i, (name, mod) in enumerate(selected):
            use_real = i in real_indices
            r = _run_bench_target(name, use_real, args.skip_llm)
            if r:
                results.append(r)
    _aggregate_holm(results)
    _write_summary(results)
    return results


if __name__ == "__main__":
    main()
