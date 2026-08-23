"""``pie`` — Tier 1. Performance-Improving Edits: beat the human, over -O3.

PIE is the hardest honest test of the whole project: 77k+ C++ submission pairs
where a human programmer made their own program faster, with unit tests, and
the baseline is compiled at ``-O3``. There is no room for "we removed the
obvious quadratic loop" credit — the compiler already did the easy part and a
human already did the clever part.

Metrics this suite reports (the same two PIE uses):

* **%Opt** — share of programs made at least 10% faster while every held-out
  test still passes.
* **Speedup** — baseline/candidate wall-clock, geomean, over -O3 binaries.

and one PIE itself cannot report:

* **ratio to the human's own fast version** — the reference pair is in the
  dataset, so "did we beat the human who wrote the improvement?" is a number,
  not a vibe.

Measurement caveat, stated everywhere the numbers appear: upstream PIE uses
gem5 simulation precisely because wall-clock on commodity hardware invents
phantom speedups. This harness uses wall-clock with repeats and cross-run std.
Those two numbers are *not* interchangeable and must never be put in the same
column without a footnote.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from bench.datasets import DatasetUnavailable, dataset_path, require
from bench.spec import BenchTask, Workload
from bench.suites._common import limited

SUITE = "pie"
TIER = "tier1"
DATASET = "pie"

TESTS_ENV = "MUTALAMBDA_PIE_TESTS"
MIN_TESTS = 4


def _iter_pairs(root: Path) -> Iterator[Dict[str, Any]]:
    for path in sorted(root.rglob("*.jsonl")):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        yield row
        except OSError:
            continue


def _codes(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    slow = row.get("input") or row.get("src_code") or row.get("code_v0")
    fast = row.get("target") or row.get("tgt_code") or row.get("code_v1")
    if isinstance(slow, str) and isinstance(fast, str) and "int main" in slow:
        return slow, fast
    return None


def _tests_root() -> Optional[Path]:
    env = os.getenv(TESTS_ENV)
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    for candidate in (
        dataset_path(DATASET) / "tests",
        dataset_path(DATASET) / "data" / "codenet" / "merged_test_cases",
        dataset_path(DATASET) / "merged_test_cases",
    ):
        if candidate.exists():
            return candidate
    return None


def _load_cases(tests_root: Path, problem_id: str) -> List[Dict[str, str]]:
    """Read ``{problem}/input.N.txt`` + ``output.N.txt`` pairs."""
    pdir = tests_root / str(problem_id)
    if not pdir.exists():
        return []
    cases: List[Dict[str, str]] = []
    for inp in sorted(pdir.glob("input.*.txt")):
        out = pdir / inp.name.replace("input", "output")
        if not out.exists():
            continue
        try:
            cases.append({
                "stdin": inp.read_text(encoding="utf-8", errors="ignore"),
                "expected_stdout": out.read_text(encoding="utf-8", errors="ignore"),
            })
        except OSError:
            continue
    if not cases:  # alternative layout: inputs.txt / outputs.txt
        inp, out = pdir / "inputs.txt", pdir / "outputs.txt"
        if inp.exists() and out.exists():
            cases.append({
                "stdin": inp.read_text(encoding="utf-8", errors="ignore"),
                "expected_stdout": out.read_text(encoding="utf-8", errors="ignore"),
            })
    return cases


def _split(cases: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Visible = the small ones, held-out = the rest (incl. the largest)."""
    ordered = sorted(cases, key=lambda c: len(c["stdin"]))
    n_visible = max(1, min(len(ordered) // 3, 5))
    return ordered[:n_visible], ordered[n_visible:]


def load_tasks(limit: Optional[int] = None, min_tests: int = MIN_TESTS) -> List[BenchTask]:
    root = require(DATASET, SUITE)
    tests_root = _tests_root()
    if tests_root is None:
        raise DatasetUnavailable(
            "PIE test cases are distributed separately from the code pairs.\n"
            f"  Point {TESTS_ENV} at a directory laid out as "
            "<problem_id>/input.N.txt + output.N.txt\n"
            "  (see https://github.com/madaan/pie-perf#evaluating-your-method)\n"
            "  Without them a 'speedup' is unverifiable and this suite refuses to run."
        )

    tasks: List[BenchTask] = []
    skipped_no_tests = 0
    for row in _iter_pairs(root):
        pair = _codes(row)
        if pair is None:
            continue
        slow, fast = pair
        problem_id = str(row.get("problem_id") or row.get("problem") or "")
        if not problem_id:
            continue
        cases = _load_cases(tests_root, problem_id)
        if len(cases) < min_tests:
            skipped_no_tests += 1
            continue
        visible, holdout = _split(cases)
        workload = [c["stdin"] for c in sorted(cases, key=lambda c: -len(c["stdin"]))[:3]]

        pair_id = row.get("submission_id_v0") or row.get("id") or len(tasks)
        tasks.append(BenchTask(
            task_id=f"pie/{problem_id}/{pair_id}",
            suite=SUITE,
            tier=TIER,
            language="cpp",
            source_code=slow,
            entrypoint="main",
            workload=Workload(calls=[], warmups=1, samples=5, timeout_sec=30.0),
            visible_tests=[],
            holdout_tests=[],
            reference_code=fast,
            reference_label="human performance-improving edit (PIE)",
            metadata={
                "source": "PIE (ICLR 2024)",
                "citation": "arXiv:2302.07867",
                "problem_id": problem_id,
                "native_tests": visible + holdout,
                "native_visible": visible,
                "native_holdout": holdout,
                "native_workload": workload,
                "compile_flags": "-O3 -std=c++17",
                "measurement": "wall-clock (upstream PIE uses gem5; not comparable)",
                "human_speedup_reported": row.get("speedup"),
            },
        ))
        if limit and len(tasks) >= limit:
            break

    if not tasks:
        raise DatasetUnavailable(
            f"No PIE tasks could be assembled from {root}.\n"
            f"  {skipped_no_tests} pairs were skipped for having fewer than "
            f"{min_tests} test cases available under {tests_root}."
        )
    return limited(tasks, limit)
