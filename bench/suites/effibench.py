"""``effibench`` — Tier 1. Efficiency measured against human canonical solutions.

Why this suite is the anchor of the whole plan: EffiBench ships, for every
problem, a *human canonical solution* that held the top efficiency slot on the
LeetCode leaderboard. That turns an unfalsifiable "3.6x faster" into a
falsifiable ratio:

    ratio_to_human = candidate_latency / canonical_latency

The published EffiBench finding is that GPT-4-generated code averages ~3.12x
the execution time of the canonical solution (and up to 13.89x in the worst
case). The claim this suite is designed to test is therefore not "MutaLambda
is fast" but "MutaLambda moves the *ratio* from ~3.1x toward 1.0x while every
held-out test still passes".

Adapter notes
-------------
EffiBench rows are LeetCode-style: a ``Solution`` class plus a driver. We wrap
each problem into a module-level entrypoint so the harness can call it
directly, derive the ground truth from the *canonical* solution (never from
the model output), and split the provided tests into visible/held-out.

Rows whose test inputs cannot be reconstructed as plain Python literals are
skipped rather than guessed at; the skip count is reported.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from bench.datasets import require
from bench.spec import BenchTask, Workload
from bench.suites._common import expected_for, limited, split_tests

SUITE = "effibench"
TIER = "tier1"
DATASET = "effibench"

_ENTRY_TEMPLATE = '''
def {entry}(*args, **kwargs):
    return Solution().{method}(*args, **kwargs)
'''


def _iter_rows(root: Path) -> Iterator[Dict[str, Any]]:
    """Yield dataset rows from whatever layout the cached clone provides."""
    candidates: List[Path] = []
    for pattern in ("**/*.json", "**/*.jsonl"):
        candidates.extend(sorted(root.glob(pattern)))
    for path in candidates:
        if path.name == "_muta_manifest.json":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if path.suffix == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            rows = data if isinstance(data, list) else [data]
            for row in rows:
                if isinstance(row, dict):
                    yield row


def _pick(row: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if row.get(k):
            return row[k]
    return None


def _method_name(code: str) -> Optional[str]:
    """First public method of ``class Solution`` — the LeetCode entrypoint."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Solution":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    return item.name
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            return node.name
    return None


def _parse_inputs(raw: Any) -> Optional[List[List[Any]]]:
    """Turn EffiBench's test payload into arg lists, or give up cleanly."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            try:
                raw = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                return None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    out: List[List[Any]] = []
    for item in raw:
        if isinstance(item, dict):
            args = item.get("input") if "input" in item else item.get("args")
            if isinstance(args, dict):
                out.append([list(args.values())])
            elif isinstance(args, list):
                out.append(list(args))
            elif args is not None:
                out.append([args])
        elif isinstance(item, list):
            out.append(list(item))
        else:
            out.append([item])
    return [a for a in out if a] or None


def _build_task(row: Dict[str, Any], index: int) -> Optional[BenchTask]:
    canonical = _pick(row, "canonical_solution", "canonical", "human_solution", "solution")
    if not isinstance(canonical, str) or "def " not in canonical:
        return None
    slow = _pick(row, "llm_solution", "model_solution", "generated_solution") or canonical
    method = _method_name(canonical)
    if not method:
        return None

    arg_sets = _parse_inputs(_pick(row, "test_case", "test_cases", "inputs", "tests"))
    if not arg_sets or len(arg_sets) < 3:
        return None

    entry = "effibench_entry"
    canonical_module = canonical + _ENTRY_TEMPLATE.format(entry=entry, method=method)
    slow_module = slow + _ENTRY_TEMPLATE.format(entry=entry, method=method)

    try:
        tests = expected_for(canonical_module, entry, arg_sets[:24])
    except Exception:
        return None  # canonical does not execute on these inputs → skip, don't fake

    visible, holdout = split_tests(tests, visible=max(2, len(tests) // 3))
    workload_args = [t["args"] for t in tests[: min(8, len(tests))]]

    task_id = f"effibench/{_pick(row, 'problem_id', 'task_id', 'id') or index}"
    return BenchTask(
        task_id=task_id,
        suite=SUITE,
        tier=TIER,
        source_code=slow_module,
        entrypoint=entry,
        workload=Workload(calls=[[a, {}] for a in workload_args], warmups=2,
                          samples=9, timeout_sec=120.0),
        visible_tests=visible,
        holdout_tests=holdout,
        reference_code=canonical_module,
        reference_label="human canonical (EffiBench)",
        metadata={
            "source": "EffiBench (NeurIPS 2024)",
            "problem": _pick(row, "title", "problem", "name"),
            "difficulty": row.get("difficulty"),
            "baseline_is_llm_code": slow is not canonical,
            "citation": "arXiv:2402.02037",
        },
    )


def load_tasks(limit: Optional[int] = None) -> List[BenchTask]:
    root = require(DATASET, SUITE)
    tasks: List[BenchTask] = []
    skipped = 0
    for i, row in enumerate(_iter_rows(root)):
        task = _build_task(row, i)
        if task is None:
            skipped += 1
            continue
        tasks.append(task)
        if limit and len(tasks) >= limit:
            break
    if not tasks:
        from bench.datasets import DatasetUnavailable

        raise DatasetUnavailable(
            f"EffiBench cache at {root} yielded no usable tasks ({skipped} rows skipped).\n"
            "The upstream layout changed or only metadata was cloned. Inspect the cache "
            "and adjust bench/suites/effibench.py::_build_task — do not relax the "
            "ground-truth derivation to make rows load."
        )
    if skipped:
        print(f"[effibench] {len(tasks)} tasks loaded, {skipped} rows skipped "
              "(unreconstructible inputs)")
    return limited(tasks, limit)
