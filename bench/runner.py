"""Benchmark runner CLI.

    python -m bench.runner list
    python -m bench.runner datasets
    python -m bench.runner run --suite smoke --optimizer baseline --repeats 3
    python -m bench.runner run --suite smoke --optimizer mutalambda:deep \
        --ablation no_hfc --ablation no_thc --out results/
    python -m bench.runner compare results/smoke/*/report.json

The pipeline per task is fixed and deliberately boring:

    baseline (all tests)  →  optimize (visible tests only)  →  optimized (all
    tests)  →  held-out re-check  →  invariants  →  reference ratio  →
    integrity verdict  →  record

Only the *visible* test split ever reaches the optimizer. The held-out split
and the invariants decide whether a speedup is real.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from bench import invariants as inv
from bench.datasets import DatasetUnavailable, status as dataset_status
from bench.integrity import evaluate_integrity, evaluate_integrity_native
from bench.measure import (
    calibrate_noise, environment_fingerprint, measure, measure_interleaved,
    measure_repeated,
)
from bench.native import environment_native, measure_native_repeated
from bench.optimizers import (
    ABLATIONS, Budget, LLMSettings, MutaLambdaOptimizer, build_optimizer, budget_for,
)
from bench.report import aggregate, render_comparison, render_markdown, render_task_card
from bench.spec import BenchTask, SuiteReport, TaskRecord
from bench.suites import REGISTRY, list_suites, load_tasks


def _environment_for(tasks: Sequence[BenchTask]) -> Dict[str, Any]:
    env = environment_fingerprint()
    if any(t.language != "python" for t in tasks):
        env["native"] = environment_native()
    return env


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _git_dirty() -> bool:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                             text=True, timeout=5)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def _diff(before: str, after: str, task_id: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{task_id}", tofile=f"b/{task_id}",
    ))


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> float:
    try:
        n, d = float(numerator), float(denominator)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")
    if not d or d <= 0 or n != n or d != d or n in (float("inf"),) or d == float("inf"):
        return float("nan")
    return n / d


def _quality_value(wrapped_code: str, task: BenchTask) -> Optional[float]:
    """Tier-3 support: run the objective probe and read its numeric value.

    The measurement driver only reports pass/fail, so an objective (packing
    quality, bins used, ...) needs its own one-shot subprocess. The probe must
    define ``_muta_quality()`` returning a float.
    """
    import tempfile
    import os

    runner = (
        f"{wrapped_code}\n\n"
        "import json, sys\n"
        "print(json.dumps({'quality': float(_muta_quality())}))\n"
    )
    with tempfile.TemporaryDirectory(prefix="mutabench_q_") as tmp:
        path = Path(tmp) / "probe.py"
        path.write_text(runner, encoding="utf-8")
        try:
            out = subprocess.run([sys.executable, "-I", str(path)], capture_output=True,
                                 text=True, timeout=task.workload.timeout_sec,
                                 cwd=tmp, env={"PATH": os.environ.get("PATH", "")})
        except subprocess.SubprocessError:
            return None
    for line in reversed((out.stdout or "").strip().splitlines()):
        try:
            return float(json.loads(line)["quality"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return None


def _native_measure(code: str, task: BenchTask, repeats: int,
                    *, tests_key: str = "native_tests") -> Dict[str, Any]:
    meta = task.metadata or {}
    return measure_native_repeated(
        code,
        tests=meta.get(tests_key) or [],
        workload=meta.get("native_workload") or [],
        repeats=repeats,
        warmups=task.workload.warmups,
        samples=task.workload.samples,
        timeout_sec=task.workload.timeout_sec,
    )


def run_task_native(task: BenchTask, optimizer, budget: Budget, *,
                    repeats: int) -> TaskRecord:
    """C++ path (PIE). Same contract as run_task, different measurement engine."""
    baseline = _native_measure(task.source_code, task, repeats)

    t0 = time.perf_counter()
    outcome = optimizer.optimize(task, budget)
    opt_wall = time.perf_counter() - t0
    code = outcome.code or task.source_code

    optimized = _native_measure(code, task, repeats)
    holdout_run = _native_measure(code, task, 1, tests_key="native_holdout")
    holdout_info = {
        "tests_total": holdout_run.get("tests_total", 0),
        "tests_passed": holdout_run.get("tests_passed", 0),
        "failures": holdout_run.get("failures", []),
        "error": holdout_run.get("error", ""),
    }

    reference: Dict[str, Any] = {}
    if task.reference_code:
        ref = _native_measure(task.reference_code, task, max(1, repeats // 2 or 1))
        reference = {
            "label": task.reference_label or "human fast pair",
            "latency_ms_mean": ref["latency_ms_mean"],
            "mem_peak_mb_mean": ref["mem_peak_mb_mean"],
            "all_pass": ref["all_pass"],
            "baseline_ratio": _safe_ratio(baseline["latency_ms_mean"], ref["latency_ms_mean"]),
            "optimized_ratio": _safe_ratio(optimized["latency_ms_mean"], ref["latency_ms_mean"]),
        }

    integrity = evaluate_integrity_native(task, code, holdout=holdout_info,
                                          baseline=baseline, optimized=optimized)
    notes = list(integrity.reasons())
    if outcome.error:
        notes.append(f"optimizer error: {outcome.error}")

    speedup = _safe_ratio(baseline["latency_ms_mean"], optimized["latency_ms_mean"])
    memory_ratio = _safe_ratio(optimized["mem_peak_mb_mean"], baseline["mem_peak_mb_mean"])
    counted = bool(integrity.counted and optimized.get("all_pass") and speedup == speedup)

    return TaskRecord(
        task_id=task.task_id, suite=task.suite, tier=task.tier,
        optimizer=getattr(optimizer, "name", "unknown"),
        fingerprint=task.fingerprint(),
        baseline=baseline, optimized=optimized, reference=reference,
        integrity=integrity.to_dict(),
        budget={
            "wall_sec": round(outcome.wall_sec or opt_wall, 3),
            "llm_calls": outcome.llm_calls, "tokens": outcome.tokens,
            "cost_usd": outcome.cost_usd, "generations": outcome.generations,
            "budget": budget.to_dict(), "meta": outcome.meta,
        },
        diff=_diff(task.source_code, code, task.task_id),
        repeats=repeats, counted=counted, speedup=speedup,
        memory_ratio=memory_ratio,
        ratio_to_reference=reference.get("optimized_ratio", float("nan")),
        notes=notes,
    )


def run_task(
    task: BenchTask,
    optimizer,
    budget: Budget,
    *,
    repeats: int,
) -> TaskRecord:
    if task.language != "python":
        return run_task_native(task, optimizer, budget, repeats=repeats)

    t0 = time.perf_counter()
    outcome = optimizer.optimize(task, budget)
    opt_wall = time.perf_counter() - t0
    code = outcome.code or task.source_code

    # Baseline, candidate and reference are measured interleaved in the same
    # session so machine drift hits all of them equally.
    variants = {"baseline": task.source_code, "optimized": code}
    if task.reference_code:
        variants["reference"] = task.reference_code
    measured = measure_interleaved(variants, task, repeats=repeats)
    baseline = measured["baseline"]
    optimized = measured["optimized"]
    holdout = measure(code, task, tests=task.holdout_tests, tests_only=True)
    holdout_info = {
        "tests_total": holdout.tests_total,
        "tests_passed": holdout.tests_passed,
        "failures": holdout.failures,
        "error": holdout.error,
    }

    notes: List[str] = []
    if outcome.error:
        notes.append(f"optimizer error: {outcome.error}")

    # ── invariants (tier 2) ────────────────────────────────────────────────
    invariant_result: Dict[str, Any] = {}
    if task.invariants:
        wrapped, inv_tests = inv.build_invariant_module(code, task)
        inv_run = measure(wrapped, task, tests=inv_tests, tests_only=True)
        invariant_result = inv.summarise(inv_tests, inv_run.failures)
        invariant_result["error"] = inv_run.error
        if not invariant_result.get("all_hold"):
            notes.append("invariants violated: " + ", ".join(invariant_result.get("violated", [])))

    # ── reference / human canonical ────────────────────────────────────────
    reference: Dict[str, Any] = {}
    if task.reference_code:
        ref = measured["reference"]
        reference = {
            "label": task.reference_label or "canonical",
            "latency_ms_mean": ref["latency_ms_mean"],
            "mem_peak_mb_mean": ref["mem_peak_mb_mean"],
            "all_pass": ref["all_pass"],
            "baseline_ratio": _safe_ratio(baseline["latency_ms_mean"], ref["latency_ms_mean"]),
            "optimized_ratio": _safe_ratio(optimized["latency_ms_mean"], ref["latency_ms_mean"]),
        }

    # ── tier-3 quality objective ───────────────────────────────────────────
    quality: Dict[str, Any] = {}
    if (task.metadata or {}).get("quality_probe"):
        probe = task.metadata["quality_probe"]
        qb = _quality_value(f"{task.source_code}\n\n{probe}\n", task)
        qo = _quality_value(f"{code}\n\n{probe}\n", task)
        higher = bool(task.metadata.get("quality_higher_is_better", True))
        improved = None
        if qb is not None and qo is not None:
            improved = (qo > qb) if higher else (qo < qb)
        quality = {"baseline": qb, "optimized": qo,
                   "higher_is_better": higher, "improved": improved}

    integrity = evaluate_integrity(
        task, code, holdout=holdout_info, baseline=baseline, optimized=optimized,
    )
    notes.extend(integrity.reasons())

    speedup = _safe_ratio(baseline["latency_ms_mean"], optimized["latency_ms_mean"])
    memory_ratio = _safe_ratio(optimized["mem_peak_mb_mean"], baseline["mem_peak_mb_mean"])

    counted = bool(
        integrity.counted
        and optimized.get("all_pass")
        and (not task.invariants or invariant_result.get("all_hold"))
        and speedup == speedup  # not NaN
    )
    if task.invariants and not invariant_result.get("all_hold"):
        notes.append("excluded: invariant violation")

    record = TaskRecord(
        task_id=task.task_id,
        suite=task.suite,
        tier=task.tier,
        optimizer=getattr(optimizer, "name", "unknown"),
        fingerprint=task.fingerprint(),
        baseline=baseline,
        optimized=dict(optimized, invariants=invariant_result, quality=quality),
        reference=reference,
        integrity=integrity.to_dict(),
        budget={
            "wall_sec": round(outcome.wall_sec or opt_wall, 3),
            "llm_calls": outcome.llm_calls,
            "tokens": outcome.tokens,
            "cost_usd": outcome.cost_usd,
            "generations": outcome.generations,
            "budget": budget.to_dict(),
            "meta": outcome.meta,
        },
        diff=_diff(task.source_code, code, task.task_id),
        repeats=repeats,
        counted=counted,
        speedup=speedup,
        memory_ratio=memory_ratio,
        ratio_to_reference=reference.get("optimized_ratio", float("nan")),
        notes=notes,
    )
    return record


def run_suite(
    suite: str,
    optimizer_spec: str,
    *,
    repeats: int = 5,
    limit: int = 0,
    budget: Optional[Budget] = None,
    llm: Optional[LLMSettings] = None,
    task_filter: str = "",
    command: str = "",
    verbose: bool = True,
    calibrate: bool = True,
) -> SuiteReport:
    meta = REGISTRY.get(suite)
    if meta is None:
        raise KeyError(f"unknown suite '{suite}'")
    tasks = load_tasks(suite, limit=limit)
    if task_filter:
        tasks = [t for t in tasks if task_filter in t.task_id]
    if not tasks:
        raise DatasetUnavailable(f"suite '{suite}' produced no tasks (filter='{task_filter}')")

    optimizer = build_optimizer(optimizer_spec, llm=llm)
    effective_budget = budget_for(optimizer_spec, budget)

    env = _environment_for(tasks)
    if calibrate and tasks[0].language == "python":
        if verbose:
            print("calibrating measurement noise on this machine …", flush=True)
        env["noise_calibration"] = calibrate_noise(tasks[0], repeats=max(2, repeats // 2))

    report = SuiteReport(
        suite=suite,
        tier=meta["tier"],
        optimizer=getattr(optimizer, "name", optimizer_spec),
        env=env,
        config={
            "repeats": repeats,
            "limit": limit,
            "budget": effective_budget.to_dict(),
            "optimizer": optimizer.describe(),
            "git_commit": _git_commit(),
            "git_dirty": _git_dirty(),
            "command": command or " ".join(sys.argv),
            "llm": (llm.to_dict() if llm else None),
            "suite_status": meta.get("status"),
        },
        started_at=time.time(),
    )

    for i, task in enumerate(tasks, 1):
        if verbose:
            print(f"[{i}/{len(tasks)}] {task.task_id} …", flush=True)
        record = run_task(task, optimizer, effective_budget, repeats=repeats)
        report.records.append(record)
        if verbose:
            print(
                f"    speedup {record.speedup:.2f}x · "
                f"tests {record.optimized.get('tests_passed')}/{record.optimized.get('tests_total')} · "
                f"integrity {record.integrity.get('verdict')}",
                flush=True,
            )

    report.finished_at = time.time()
    report.aggregates = aggregate(
        report.records,
        noise_band=float((env.get("noise_calibration") or {}).get("noise_band") or 1.0),
    )
    return report


def write_artifacts(report: SuiteReport, out_dir: Path, *, include_diffs: bool = True) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(report.started_at or time.time()))
    safe_opt = report.optimizer.replace(":", "_").replace("/", "_")
    root = out_dir / report.suite / f"{safe_opt}-{stamp}"
    (root / "tasks").mkdir(parents=True, exist_ok=True)

    (root / "report.json").write_text(
        json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    (root / "report.md").write_text(
        render_markdown(report, include_diffs=False), encoding="utf-8")

    cards: List[str] = [f"# {report.suite} — task cards (`{report.optimizer}`)", ""]
    for rec in report.records:
        tdir = root / "tasks" / rec.task_id.replace("/", "__")
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "record.json").write_text(
            json.dumps(rec.to_dict(), indent=2, default=str), encoding="utf-8")
        if include_diffs and rec.diff.strip():
            (tdir / "optimized.patch").write_text(rec.diff, encoding="utf-8")
        cards.append(render_task_card(rec))
        cards.append("")
    (root / "task_cards.md").write_text("\n".join(cards), encoding="utf-8")
    return root


# ── CLI ────────────────────────────────────────────────────────────────────

def _cmd_list(args: argparse.Namespace) -> int:
    rows = list_suites()
    width = max(len(r["name"]) for r in rows)
    print(f"{'suite'.ljust(width)}  tier   status        dataset            summary")
    for r in rows:
        print(f"{r['name'].ljust(width)}  {r['tier']}  {r['status'].ljust(12)} "
              f"{(r['dataset'] or '—').ljust(18)} {r['summary']}")
    return 0


def _cmd_datasets(args: argparse.Namespace) -> int:
    for row in dataset_status():
        mark = "✔" if row["available"] else "✘"
        print(f"{mark} {row['key']:<18} {row['kind']:<7} {row['size_hint']:<12} {row['path']}")
        print(f"    {row['description']}")
    print("\nFetch with: python scripts/fetch_bench_datasets.py <key>")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    llm = LLMSettings(
        backend=args.llm_backend,
        model=args.llm_model,
        temperature=args.temperature,
        timeout_sec=args.llm_timeout,
        usd_per_1k_prompt=args.usd_per_1k_prompt,
        usd_per_1k_completion=args.usd_per_1k_completion,
    )
    budget = None
    if args.generations or args.islands or args.population or args.max_llm_calls:
        base = budget_for(args.optimizer)
        budget = Budget(
            generations=args.generations or base.generations,
            islands=args.islands or base.islands,
            population=args.population or base.population,
            wall_sec=args.wall_sec or base.wall_sec,
            max_llm_calls=args.max_llm_calls or base.max_llm_calls,
            variants=base.variants,
        )
    spec = args.optimizer
    if args.ablation:
        unknown = [a for a in args.ablation if a not in ABLATIONS]
        if unknown:
            print(f"unknown ablation(s): {unknown}; valid: {list(ABLATIONS)}", file=sys.stderr)
            return 2
        if not spec.startswith("mutalambda"):
            print("--ablation only applies to mutalambda optimizers", file=sys.stderr)
            return 2
        spec = spec + "-" + "-".join(args.ablation)

    try:
        report = run_suite(
            args.suite, spec,
            repeats=args.repeats, limit=args.limit, budget=budget, llm=llm,
            task_filter=args.task, command=" ".join(sys.argv), verbose=not args.quiet,
            calibrate=not args.no_calibrate,
        )
    except DatasetUnavailable as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 3

    md = render_markdown(report, include_diffs=args.include_diffs)
    print()
    print(md)

    if args.out:
        root = write_artifacts(report, Path(args.out), include_diffs=True)
        print(f"\nArtifacts: {root}")

    agg = report.aggregates
    if args.fail_under_correctness and agg["correctness_rate"] < args.fail_under_correctness:
        print(f"FAIL: correctness {agg['correctness_rate']:.3f} < "
              f"{args.fail_under_correctness}", file=sys.stderr)
        return 1
    if args.fail_on_rejected and agg["integrity_verdicts"].get("rejected"):
        print("FAIL: integrity gate rejected at least one candidate", file=sys.stderr)
        return 1
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    reports: List[SuiteReport] = []
    for path in args.reports:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        rep = SuiteReport(
            suite=data["suite"], tier=data["tier"], optimizer=data["optimizer"],
            env=data.get("env", {}), config=data.get("config", {}),
            aggregates=data.get("aggregates", {}),
        )
        rep.records = [TaskRecord(**r) for r in data.get("records", [])]
        reports.append(rep)
    print(render_comparison(reports))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bench.runner",
                                description="MutaLambda public benchmark harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list benchmark suites").set_defaults(func=_cmd_list)
    sub.add_parser("datasets", help="show dataset cache status").set_defaults(func=_cmd_datasets)

    r = sub.add_parser("run", help="run a suite against an optimizer")
    r.add_argument("--suite", required=True)
    r.add_argument("--optimizer", default="baseline",
                   help="baseline | numpy | llm-oneshot | mutalambda:fast | mutalambda:deep")
    r.add_argument("--ablation", action="append", default=[],
                   help=f"disable a component; repeatable. Valid: {list(ABLATIONS)}")
    r.add_argument("--repeats", type=int, default=5,
                   help="independent measurement processes per variant (default 5)")
    r.add_argument("--limit", type=int, default=0, help="max tasks (0 = all)")
    r.add_argument("--task", default="", help="substring filter on task id")
    r.add_argument("--out", default="", help="artifact directory")
    r.add_argument("--include-diffs", action="store_true")
    r.add_argument("--quiet", action="store_true")
    r.add_argument("--no-calibrate", action="store_true",
                   help="skip the identical-code noise-floor calibration")
    r.add_argument("--generations", type=int, default=0)
    r.add_argument("--islands", type=int, default=0)
    r.add_argument("--population", type=int, default=0)
    r.add_argument("--wall-sec", type=float, default=0.0)
    r.add_argument("--max-llm-calls", type=int, default=0)
    r.add_argument("--llm-backend", default="ollama",
                   help="ollama | openai | anthropic | openrouter | mistral "
                        "(Groq: use openai + MUTALAMBDA_OPENAI_URL)")
    r.add_argument("--llm-model", default="qwen2.5-coder:7b")
    r.add_argument("--llm-timeout", type=float, default=120.0)
    r.add_argument("--temperature", type=float, default=0.2)
    r.add_argument("--usd-per-1k-prompt", type=float, default=0.0)
    r.add_argument("--usd-per-1k-completion", type=float, default=0.0)
    r.add_argument("--fail-under-correctness", type=float, default=0.0)
    r.add_argument("--fail-on-rejected", action="store_true")
    r.set_defaults(func=_cmd_run)

    c = sub.add_parser("compare", help="compare report.json files side by side")
    c.add_argument("reports", nargs="+")
    c.set_defaults(func=_cmd_compare)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
