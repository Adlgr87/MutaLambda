"""
D6 baseline runner: compare MutaLambda real-evolved mutants against LLM-direct (1-shot)
and LLM best-of-5 baselines on the same targets, using the same verification + timing
protocol as benchmarks/harness.py.

Outputs a JSON snapshot consumed by the report generator.
"""
from __future__ import annotations

import os
import sys
import statistics
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
# Harness imports benchmarks package paths
sys.path.insert(0, REPO_ROOT)
from pathlib import Path

BENCHMARKS_DIR = Path(REPO_ROOT) / "benchmarks"
RESULTS_BASE = BENCHMARKS_DIR / "results"
TARGETS_DIR = BENCHMARKS_DIR / "targets"

# Reuse the harness's LLM + verification + timing helpers.
from benchmarks.harness import (  # noqa: E402
    _llm_backend, _extract_function, _is_valid_python,
    _build_arg_factory, _build_arg_factory_from_strategy, _verify,
    time_function_code, median_iqr, get_git_sha, _env_info,
)
from llm_backend import parse_structured_response  # noqa: E402
from benchmarks.verification import verify_candidate  # noqa: E402
import json
import importlib
import re

# Per the task constraints: cap time spent on LLM inference per target.
LLM_TIMEOUT_PER_TARGET = 600  # seconds wall clock
REPS = 30


def _load_target(name):
    sys.path.insert(0, str(BENCHMARKS_DIR))
    return importlib.import_module(f"targets.{name}")


def _arg_factory(mod):
    """Build the arg factory the same way bench_one_target does."""
    sample_args = list(mod.test_cases[0]["args"]) if mod.test_cases else []
    af = getattr(mod, "arg_factory", None)
    if af is None:
        if hasattr(mod, "input_strategy") and mod.input_strategy:
            af = _build_arg_factory_from_strategy(mod.input_strategy, validator=None)
            if af is None:
                af = _build_arg_factory(sample_args)
        else:
            af = _build_arg_factory(sample_args)
    return af


def _baseline_samples(code, fn_name, arg_factory):
    """Time the ORIGINAL (unmutated) source."""
    return time_function_code(code, fn_name, arg_factory, reps=REPS)


def _candidate_samples(src, fn_name, arg_factory):
    try:
        return time_function_code(src, fn_name, arg_factory, reps=REPS)
    except Exception:
        return []  # treat as non-runnable / inf


def _strip_fences(resp: str) -> str:
    """Strip markdown code fences from an LLM response, return inner content."""
    parsed = parse_structured_response(resp)
    code = parsed.code or resp or ""
    # remove a trailing fence if parse left one
    code = re.sub(r"```+\s*$", "", code.strip()).strip()
    return code


def _llm_1shot(code, fn_name, backend):
    """1-shot: a single LLM optimize call."""
    prompt = (
        "Optimize this Python function for speed. Return ONLY the code, no explanation.\n"
        "```python\n" + code + "\n```\nOptimized:\n"
    )
    try:
        resp = backend.generate(prompt)
    except Exception as exc:
        return None, f"llm_generate_error: {exc}"
    clean = _strip_fences(resp)
    src = _extract_function(clean, fn_name)
    if src is None or not _is_valid_python(src):
        return None, "extract_invalid"
    if src.strip() == code.strip():
        return None, "no_change"
    return src, "ok"


def _llm_best_of_5(code, fn_name, backend, mod):
    """5 LLM variants, pick the fastest one that verifies correct."""
    variants = []
    for i in range(5):
        # Vary temperature / prompt hint to encourage diversity.
        b = backend
        b.temperature = 0.2 + 0.1 * i
        hint = ["use numpy vectorization", "use loop unrolling and micro-opts",
                "minimize allocations and precompute", "use local variable bindings",
                "rewrite with comprehensions"][i]
        prompt = (
            f"Optimize this Python function for speed (hint: {hint}). "
            f"Return ONLY the code, no explanation.\n```python\n{code}\n```\nOptimized:\n"
        )
        try:
            resp = b.generate(prompt)
        except Exception as exc:
            variants.append((None, f"err: {exc}"))
            continue
        clean = _strip_fences(resp)
        src = _extract_function(clean, fn_name)
        if src is None or not _is_valid_python(src) or src.strip() == code.strip():
            variants.append((None, "invalid_or_nochange"))
            continue
        variants.append((src, "generated"))
    return variants


def run_target(name):
    mod = _load_target(name)
    fn_name = mod.function_name
    code = mod.source
    arg_factory = _arg_factory(mod)
    original_baseline_ms = median_iqr(_baseline_samples(code, fn_name, arg_factory))[0] * 1000.0

    result = {
        "target": name,
        "function": fn_name,
        "tier": mod.TIER,
        "baseline_median_ms": round(original_baseline_ms, 6),
        "llm_1shot": {"speedup": None, "correct": None, "median_ms": None, "src": None, "note": ""},
        "llm_best_of_5": {"speedup": None, "correct": None, "median_ms": None, "src": None, "note": ""},
    }

    backend = _llm_backend()
    if backend is None:
        result["llm_1shot"]["note"] = "no_llm_backend"
        result["llm_best_of_5"]["note"] = "no_llm_backend"
        return result
    # Cap per-call latency so we stay within the 600s/target budget even when the
    # local model is CPU-thrashing. Tight connect/read timeouts + single retry.
    try:
        backend.timeout_sec = 90.0
        backend.connect_timeout_sec = 10.0
        backend.read_timeout_sec = 90.0
        backend.max_retries = 0
        backend.circuit_failure_threshold = 99
        backend.circuit_cooldown_sec = 5.0
    except Exception:
        pass

    wall = time.time()

    # ---- 1-shot ----
    if time.time() - wall > LLM_TIMEOUT_PER_TARGET:
        result["llm_1shot"]["note"] = "timeout_budget_exceeded"
    else:
        try:
            src, note = _llm_1shot(code, fn_name, backend)
        except Exception as exc:
            src, note = None, f"llm_error: {type(exc).__name__}"
        if src is not None:
            ver = verify_candidate(code, src, mod.test_cases, function_name=fn_name,
                                   invariants=getattr(mod, "invariants", None),
                                   input_strategy=getattr(mod, "input_strategy", None),
                                   random_trials=200, seed=42)
            correct = ver.ok
            samples = _candidate_samples(src, fn_name, arg_factory)
            med = median_iqr(samples)[0] * 1000.0 if samples else float("inf")
            speedup = round(original_baseline_ms / med, 4) if (samples and med > 0 and med != float("inf")) else None
            result["llm_1shot"] = {
                "speedup": speedup, "correct": correct,
                "median_ms": None if med == float("inf") else round(med, 6),
                "src": src, "note": note if not correct else note,
            }
        else:
            result["llm_1shot"]["note"] = note

    # ---- best-of-5 ----
    if time.time() - wall > LLM_TIMEOUT_PER_TARGET:
        result["llm_best_of_5"]["note"] = "timeout_budget_exceeded"
    else:
        try:
            variants = _llm_best_of_5(code, fn_name, backend, mod)
        except Exception as exc:
            variants = []
            print(f"  [5-shot] llm_error: {type(exc).__name__}: {exc}", flush=True)
        best = None
        best_med = None
        best_note = ""
        for src, note in variants:
            if src is None:
                continue
            ver = verify_candidate(code, src, mod.test_cases, function_name=fn_name,
                                   invariants=getattr(mod, "invariants", None),
                                   input_strategy=getattr(mod, "input_strategy", None),
                                   random_trials=200, seed=42)
            if not ver.ok:
                continue
            samples = _candidate_samples(src, fn_name, arg_factory)
            med = median_iqr(samples)[0] * 1000.0 if samples else float("inf")
            if best_med is None or med < best_med:
                best, best_med, best_note = src, med, note
        if best is not None:
            speedup = round(original_baseline_ms / best_med, 4) if (best_med > 0 and best_med != float("inf")) else None
            result["llm_best_of_5"] = {
                "speedup": speedup, "correct": True,
                "median_ms": None if best_med == float("inf") else round(best_med, 6),
                "src": best, "note": best_note,
            }
        else:
            result["llm_best_of_5"]["note"] = "no_correct_variant"

    return result


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["t3_page_rank", "t1_primes_sieve", "t1_matrix_multiply"]
    # Resume from any previously-saved snapshot so partial runs survive.
    snap_path = RESULTS_BASE / "D.6_baseline_snapshot.json"
    out = []
    if snap_path.exists():
        try:
            out = json.loads(snap_path.read_text())
        except Exception:
            out = []
    done = {r.get("target") for r in out}
    for t in targets:
        if t in done:
            print(f"\n=== {t} === (already done, skipping)", flush=True)
            continue
        print(f"\n=== {t} ===", flush=True)
        try:
            r = run_target(t)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            r = {"target": t, "function": "", "tier": None, "baseline_median_ms": None,
                 "error": f"runner_crashed: {exc}",
                 "llm_1shot": {"speedup": None, "correct": None, "median_ms": None, "src": None, "note": "runner_error"},
                 "llm_best_of_5": {"speedup": None, "correct": None, "median_ms": None, "src": None, "note": "runner_error"}}
        out.append(r)
        # Persist incrementally so partial progress survives a crash/timeout.
        (RESULTS_BASE / "D.6_baseline_snapshot.json").write_text(json.dumps(out, indent=2, default=str))
        print(f"  baseline_ms={r['baseline_median_ms']} "
              f"1shot_speedup={r['llm_1shot']['speedup']} correct={r['llm_1shot']['correct']} "
              f"5shot_speedup={r['llm_best_of_5']['speedup']} correct={r['llm_best_of_5']['correct']}", flush=True)
    out_path = RESULTS_BASE / "D.6_baseline_snapshot.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
