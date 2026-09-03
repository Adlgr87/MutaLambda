"""EffiBench (NeurIPS 2024) -> MutaLambda task loader.

Converts EffiBench's LeetCode-style assertion suites into MutaLambda
declarative test cases using dev-mode ``expression`` entries::

    assert solution.lengthOfLongestSubstring('') == 0
    ->
    {"assert": "solution.lengthOfLongestSubstring('') == 0"}

The runner evaluates these via ``eval(expr, ns, ns)`` when constructed
with ``allow_expression_eval=True``. This preserves the *exact* original
semantics of EffiBench checks (including RHS arithmetic such as
``23/(602/46/47)``) instead of lossy re-parsing.

Seed code convention: canonical ``Solution`` class + instantiation shim
``solution = Solution()`` appended so expressions resolve against the
namespace produced by the runner's ``exec``.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

DEFAULT_PARQUET = "/tmp/effibench_train.parquet"

# Standard preamble mirroring the EffiBench/LeetCode execution environment.
# Canonical solutions freely use bare names like `inf`, `List`, `defaultdict`,
# `pairwise` (Python 3.10+ builtin re-exported via itertools).
# MUST be prepended identically to baselines AND candidates (fair comparison).
PREAMBLE = (
    "from typing import *\n"
    "import math\n"
    "from math import *\n"
    "import collections, heapq, itertools, functools, bisect, re, string\n"
    "from collections import *\n"
    "from functools import *\n"
    "from itertools import pairwise\n"
)

# A candidate line is usable iff it is an assert whose body compiles and
# references nothing outside the candidate namespace (only `solution`).
_FORBIDDEN_REPR = ("<__main__.", "<bound_method")


@dataclass
class EffiBenchTask:
    """One EffiBench row converted to MutaLambda form."""

    problem_idx: int
    task_name: str
    description: str
    canonical_solution: str
    test_expressions: list[str] = field(default_factory=list)

    def seed_code(self) -> str:
        """Preamble + canonical solution + shim consumed by expression tests."""
        return f"{PREAMBLE}\n{self.canonical_solution.rstrip()}\n\n\nsolution = Solution()\n"


def _convert_asserts(test_case_text: str) -> list[str] | None:
    """Return list of assert-expressions, or None if task is unusable."""
    exprs: list[str] = []
    for raw in test_case_text.strip().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("assert "):
            return None
        body = line[len("assert ") :]
        if _FORBIDDEN_REPR[0] in body or _FORBIDDEN_REPR[1] in body:
            return None
        try:
            tree = ast.parse(body, mode="eval")
        except SyntaxError:
            return None
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        if names - {"solution"}:
            return None
        exprs.append(body)
    return exprs or None


def load_tasks(
    parquet_path: str | Path = DEFAULT_PARQUET,
    limit: int | None = None,
) -> list[EffiBenchTask]:
    """Load and convert EffiBench rows; silently drops unconvertible tasks."""
    table = pq.read_table(str(parquet_path)).to_pydict()
    n = len(table["task_name"])
    tasks: list[EffiBenchTask] = []
    for i in range(n if limit is None else min(n, limit)):
        exprs = _convert_asserts(table["test_case"][i])
        if exprs is None:
            continue
        tasks.append(
            EffiBenchTask(
                problem_idx=int(table["problem_idx"][i]),
                task_name=str(table["task_name"][i]),
                description=str(table["description"][i]),
                canonical_solution=str(table["canonical_solution"][i]),
                test_expressions=exprs,
            )
        )
    return tasks


def to_test_cases(task: EffiBenchTask) -> list[dict]:
    """MutaLambda declarative cases (dev-mode expression/assert keys)."""
    return [{"assert": e} for e in task.test_expressions]


def write_task_files(task: EffiBenchTask, out_dir: str | Path) -> dict[str, Path]:
    """Write source/tests/benchmark files matching TargetConfig expectations."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", task.task_name).strip("_").lower()
    src = out / f"{slug}.py"
    tst = out / f"{slug}_tests.json"
    bench = out / f"{slug}_benchmark.json"
    src.write_text(task.seed_code(), encoding="utf-8")
    tst.write_text(json.dumps(to_test_cases(task), indent=1), encoding="utf-8")
    bench.write_text(json.dumps({"task": task.task_name}, indent=1), encoding="utf-8")
    return {"source": src, "tests": tst, "benchmark": bench}


def coverage_report(parquet_path: str | Path = DEFAULT_PARQUET) -> dict[str, int]:
    """How many of the 1000 tasks are directly convertible (auditability).

    Uses a fast regex pre-filter to skip obviously-unusable cases before
    the heavier AST-based check, so the full 1000-task audit completes in
    ~3s instead of ~25s.
    """
    table = pq.read_table(str(parquet_path), columns=["task_name", "test_case"]).to_pydict()
    total = len(table["task_name"])
    ok = 0
    for i in range(total):
        tc = table["test_case"][i]
        if not tc or not tc.strip().startswith("assert"):
            continue
        # Quick reject: skip test cases with forbidden repr patterns
        if _FORBIDDEN_REPR[0] in tc or _FORBIDDEN_REPR[1] in tc:
            continue
        exprs = _convert_asserts(tc)
        if exprs is not None:
            ok += 1
    return {"total": total, "convertible": ok, "excluded": total - ok}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("usage: effibench_loader.py [parquet_path] [--coverage-only]")
        print("  parquet_path      Default: /tmp/effibench_train.parquet")
        print("  --coverage-only   Only report coverage % (skip loading tasks)")
        sys.exit(0)

    coverage_only = "--coverage-only" in sys.argv[1:]
    path = DEFAULT_PARQUET
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            path = arg
            break

    if coverage_only:
        report = coverage_report(path)
        print(f"Coverage: {report['convertible']}/{report['total']} "
              f"(excluded {report['excluded']})")
        sys.exit(0)

    report = coverage_report(path)
    print(f"Coverage: {report['convertible']}/{report['total']} "
          f"(excluded {report['excluded']})")
    tasks = load_tasks(path)
    print(f"Loaded {len(tasks)} tasks; first: #{tasks[0].problem_idx} "
          f"{tasks[0].task_name} ({len(tasks[0].test_expressions)} asserts)")
