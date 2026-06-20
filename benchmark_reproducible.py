"""Reproducible benchmark harness for MutaLambda.

Example:
    python benchmark_reproducible.py --runs 100 --generations 20 --islands 4
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import statistics
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

from muta_lambda import EvolveConfig, Individual, MutaLambdaAgent


@dataclass
class BenchmarkRun:
    run_id: int
    best_score: float
    elapsed_sec: float
    generations: int
    parseable: bool


def _build_test_cases() -> List[Dict[str, Any]]:
    return [
        {"function": "compute_sum", "args": [0], "expected": 0},
        {"function": "compute_sum", "args": [1], "expected": 0},
        {"function": "compute_sum", "args": [5], "expected": 10},
        {"function": "compute_sum", "args": [100], "expected": 4950},
    ]


def _make_llm_stub(prompt: str) -> str:
    """Deterministic LLM stub that produces a correct module."""
    return (
        "import sys, json\n"
        "def compute_sum(n):\n"
        "    return n * (n - 1) // 2\n\n"
        "def _run():\n"
        "    test_cases = json.loads(sys.stdin.read() or '[]')\n"
        "    passed = 0\n"
        "    total = max(1, len(test_cases))\n"
        "    for tc in test_cases:\n"
        "        fn = tc.get('function')\n"
        "        args = tc.get('args', [])\n"
        "        expected = tc.get('expected')\n"
        "        try:\n"
        "            got = globals()[fn](*args)\n"
        "            if got == expected:\n"
        "                passed += 1\n"
        "        except Exception:\n"
        "            pass\n"
        "    print(json.dumps({'passed': passed, 'total': total}))\n\n"
        "if __name__ == '__main__':\n"
        "    _run()\n"
    )


def _seed_code() -> str:
    return (
        "import sys, json\n"
        "def compute_sum(n):\n"
        "    return 0\n\n"
        "def _run():\n"
        "    test_cases = json.loads(sys.stdin.read() or '[]')\n"
        "    passed = 0\n"
        "    total = max(1, len(test_cases))\n"
        "    for tc in test_cases:\n"
        "        fn = tc.get('function')\n"
        "        args = tc.get('args', [])\n"
        "        expected = tc.get('expected')\n"
        "        try:\n"
        "            got = globals()[fn](*args)\n"
        "            if got == expected:\n"
        "                passed += 1\n"
        "        except Exception:\n"
        "            pass\n"
        "    print(json.dumps({'passed': passed, 'total': total}))\n\n"
        "if __name__ == '__main__':\n"
        "    _run()\n"
    )


def run_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    random.seed(args.seed)
    test_cases = _build_test_cases()
    runs: List[BenchmarkRun] = []

    for run_id in range(args.runs):
        cfg = EvolveConfig(
            num_islands=args.islands,
            generations=args.generations,
            seed_codes=[_seed_code()],
            topology=args.topology,
            population_size=args.pop_size,
            top_k=max(2, args.pop_size // 3),
            migration_interval=args.migration_interval,
            migrants_per_island=args.migrants_per_island,
            archive_solutions=False,
            prompt_evolution=False,
            checkpoint_interval=0,
            novelty_alpha=args.novelty_alpha,
            early_stop_patience=args.early_stop_patience,
            early_stop_delta=0.0,
        )
        agent = MutaLambdaAgent(
            config=cfg,
            test_cases=test_cases,
            llm_fn=_make_llm_stub,
            timeout_sec=args.timeout,
        )
        start = time.perf_counter()
        best: Individual = agent.run(task="Benchmark compute_sum")
        elapsed = time.perf_counter() - start
        try:
            ast.parse(best.code)
            parseable = True
        except SyntaxError:
            parseable = False
        runs.append(
            BenchmarkRun(
                run_id=run_id,
                best_score=best.score,
                elapsed_sec=elapsed,
                generations=len(agent.get_metrics()["best_score_history"]),
                parseable=parseable,
            )
        )

    scores = [run.best_score for run in runs]
    elapsed = [run.elapsed_sec for run in runs]
    summary = {
        "runs": args.runs,
        "seed": args.seed,
        "mean_best_score": statistics.fmean(scores),
        "std_best_score": statistics.stdev(scores) if len(scores) > 1 else 0.0,
        "mean_elapsed_sec": statistics.fmean(elapsed),
        "std_elapsed_sec": statistics.stdev(elapsed) if len(elapsed) > 1 else 0.0,
        "parseable_rate": sum(1 for run in runs if run.parseable) / len(runs),
        "runs_detail": [asdict(run) for run in runs],
    }
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MutaLambda repeatedly and report mean ± std.")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--islands", type=int, default=3)
    parser.add_argument("--pop-size", type=int, default=6)
    parser.add_argument("--topology", default="ring", choices=["ring", "fully_connected", "random", "mesh"])
    parser.add_argument("--migration-interval", type=int, default=1)
    parser.add_argument("--migrants-per-island", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--novelty-alpha", type=float, default=0.0)
    parser.add_argument("--early-stop-patience", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run_benchmark(args)


if __name__ == "__main__":
    main()
