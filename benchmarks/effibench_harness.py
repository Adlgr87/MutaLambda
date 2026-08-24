"""EffiBench evaluation harness for MutaLambda.

Methodology (no-super-bug):
  * Baseline  : EffiBench canonical solution evaluated with the SAME runner,
                same samples/warmups policy as candidates.
  * Candidate : LLM-generated rewrite (optional; --llm), gated by
                correctness == 1.0 before any speedup is counted.
  * Timing    : real percentiles from multiple in-runner samples
                (EvaluationService.benchmark_samples), subprocess-isolated.

Headline metrics mirror EffiBench paper conventions:
  * ratio_to_canonical : candidate p50 / baseline p50 (paper: GPT-4 = 3.12x)
  * opt_pct            : % of tasks improved beyond --min-improvement
  * mean_speedup       : mean of baseline/candidate among kept improvements
  * correctness_rate   : fraction of tasks where candidate passes 100% tests

Usage:
  python benchmarks/effibench_harness.py --smoke                  # pipeline check, no LLM
  python benchmarks/effibench_harness.py --baseline-only          # infra stats over N tasks
  python benchmarks/effibench_harness.py --tasks 100 --llm \
      --backend ollama --model qwen2.5-coder:7b --out results.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.effibench_loader import PREAMBLE, load_tasks, to_test_cases
from evaluation_service import EvaluationService


def make_service(task_expressions: list[str], args: argparse.Namespace) -> EvaluationService:
    return EvaluationService(
        test_cases=[{"assert": e} for e in task_expressions],
        allow_expression_eval=True,
        enforce_ast_scan=False,
        timeout_sec=args.timeout,
        memory_mb=args.memory_mb,
        benchmark_samples=args.samples,
        benchmark_warmups=args.warmups,
    )


def eval_code(svc: EvaluationService, code: str) -> dict:
    r = svc.evaluate_one(code)
    return {
        "correctness": round(r.fitness.correctness, 4),
        "p50_ms": round(r.fitness.latency_p50 * 1000.0, 4),
        "memory_peak_mb": round(r.fitness.memory_peak_mb, 2),
        "tests_passed": int(r.metrics.get("tests_passed", 0)),
        "tests_total": int(r.metrics.get("tests_total", 0)),
    }


FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def extract_code(llm_output: str) -> str:
    m = FENCE_RE.search(llm_output)
    return (m.group(1) if m else llm_output).strip() + "\n"


PROMPT_TMPL = """You are optimizing Python code for speed while preserving exact behavior.

Task: {task_name}
{description}

Current correct implementation:
```python
{code}
```

Rewrite it to run significantly faster (better algorithm or data structure).
Hard constraints:
- Keep class name `Solution` and identical method names/signatures.
- The file MUST end with the line: solution = Solution()
- typing, math, collections, heapq, itertools, functools, bisect are already
  imported at module top; you may use them directly.
- Output ONLY the complete Python file, no explanations, no markdown fences."""


def run_task(task, args: argparse.Namespace, generate=None) -> dict:
    svc = make_service(task.test_expressions, args)

    baseline = eval_code(svc, task.seed_code())
    rec: dict = {
        "problem_idx": task.problem_idx,
        "task_name": task.task_name,
        "n_tests": len(task.test_expressions),
        "baseline": baseline,
    }
    if baseline["correctness"] < 1.0:
        rec["status"] = "baseline_fail"
        return rec

    if args.baseline_only:
        rec["status"] = "baseline"
        rec["n_baseline_tests_ok"] = int(baseline["tests_passed"])
        return rec

    candidate_code = None
    if args.smoke:
        # Pipeline integrity: candidate == canonical must yield ratio ~1.0.
        candidate_code = task.seed_code()
        rec["status"] = "smoke_identity"
    elif generate is not None:
        t0 = time.monotonic()
        try:
            raw = generate(
                PROMPT_TMPL.format(
                    task_name=task.task_name,
                    description=task.description[:1500],
                    code=task.canonical_solution,
                )
            )
            candidate_code = PREAMBLE + "\n" + extract_code(raw)
            rec["llm_wall_sec"] = round(time.monotonic() - t0, 2)
        except Exception as exc:  # backend down / timeout / budget
            rec["status"] = f"llm_error: {type(exc).__name__}"
            return rec
        rec["status"] = "llm"

    cand = eval_code(svc, candidate_code)
    rec["candidate"] = cand
    if cand["correctness"] < 1.0:
        rec["kept"] = False
        rec["speedup"] = None
        rec["ratio_to_canonical"] = None
        return rec

    ratio = cand["p50_ms"] / max(baseline["p50_ms"], 1e-9)
    rec["ratio_to_canonical"] = round(ratio, 4)
    rec["speedup"] = round(1.0 / ratio, 4) if ratio > 0 else None
    rec["kept"] = ratio < (1.0 - args.min_improvement)
    return rec


def summarize(records: list[dict], min_improvement: float) -> dict:
    valid = [r for r in records if r.get("ratio_to_canonical") is not None]
    ratios = [r["ratio_to_canonical"] for r in valid]
    kept = [r for r in valid if r["kept"]]
    speeds = [r["speedup"] for r in kept]
    baseline_fails = sum(1 for r in records if r.get("status") == "baseline_fail")
    llm_correct = sum(1 for r in records if r.get("status") == "llm" and
                      r.get("candidate", {}).get("correctness") == 1.0)
    llm_total = sum(1 for r in records if r.get("status") == "llm")
    return {
        "n_tasks": len(records),
        "n_valid_comparisons": len(valid),
        "n_baseline_fail": baseline_fails,
        "median_ratio_to_canonical": round(statistics.median(ratios), 4) if ratios else None,
        "mean_ratio_to_canonical": round(statistics.fmean(ratios), 4) if ratios else None,
        "max_ratio_to_canonical": round(max(ratios), 4) if ratios else None,
        "opt_pct": round(100.0 * len(kept) / len(valid), 2) if valid else None,
        "mean_speedup_when_improved": round(statistics.fmean(speeds), 4) if speeds else None,
        "max_speedup": round(max(speeds), 4) if speeds else None,
        "llm_correctness_rate": round(llm_correct / llm_total, 4) if llm_total else None,
        "note": f"opt threshold: ratio < {1 - min_improvement:.2f}",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet", default="/tmp/effibench_train.parquet")
    p.add_argument("--tasks", type=int, default=10)
    p.add_argument("--skip", type=int, default=0, help="stride start offset")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--baseline-only", action="store_true")
    p.add_argument("--llm", action="store_true")
    p.add_argument("--backend", default="ollama")
    p.add_argument("--model", default="qwen2.5-coder:7b")
    p.add_argument("--samples", type=int, default=7)
    p.add_argument("--warmups", type=int, default=2)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--memory-mb", type=int, default=512)
    p.add_argument("--min-improvement", type=float, default=0.05)
    p.add_argument("--out", default="benchmarks/results_effibench.json")
    args = p.parse_args()

    tasks = load_tasks(args.parquet)
    selected = tasks[args.skip::][: args.tasks] if not args.smoke else tasks[: args.tasks]
    print(f"Loaded {len(tasks)} convertible tasks; running {len(selected)} "
          f"(mode={'smoke' if args.smoke else 'baseline' if args.baseline_only else 'llm'})")

    generate = None
    if args.llm and not args.smoke:
        from llm_backend import LLMBackend

        llm_backend = LLMBackend(
            backend=args.backend,
            model=args.model,
            timeout_sec=300.0,
            temperature=0.2,
            connect_timeout_sec=30.0,
            read_timeout_sec=240.0,
        )

        def generate(prompt: str) -> str:
            return llm_backend.generate(prompt)

        print(f"LLM backend: {args.backend}:{args.model}")

    records = []
    for i, task in enumerate(selected):
        rec = run_task(task, args, generate)
        records.append(rec)
        tag = rec.get("status", "?")
        extra = ""
        if rec.get("ratio_to_canonical") is not None:
            extra = f" ratio={rec['ratio_to_canonical']} kept={rec['kept']}"
        print(f"[{i+1}/{len(selected)}] #{task.problem_idx} {task.task_name[:44]:44s} "
              f"{tag}{extra}")

    summary = summarize(records, args.min_improvement)
    report = {"benchmark": "EffiBench", "mode": "smoke" if args.smoke else
              "baseline" if args.baseline_only else "llm",
              "config": vars(args) | {"parquet": str(args.parquet)},
              "summary": summary, "results": records}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print("\n== SUMMARY ==")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nReport written to {out}")

    if args.smoke:
        if args.baseline_only:
            # Baseline-only smoke: verify all baselines passed at least once.
            n_ok = sum(1 for r in records if r["baseline"]["correctness"] > 0)
            ok = n_ok == len(selected) and summary["n_baseline_fail"] == 0
        else:
            ok = (summary["n_valid_comparisons"] > 0
                  and summary["mean_ratio_to_canonical"] is not None)
        print(f"SMOKE {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
