"""The integrity gates must reject the classic ways of faking a benchmark win."""

from __future__ import annotations

import pytest

from bench.integrity import (
    CLEAN, NOTE, REJECTED, SUSPECT, evaluate_integrity, evaluate_integrity_native,
    strip_markdown_fences,
)
from bench.spec import BenchTask, Workload
from bench.suites import smoke

pytestmark = pytest.mark.bench


def _task() -> BenchTask:
    return smoke.load_tasks(limit=1)[0]  # smoke/sum_squares


CLEAN_HOLDOUT = {"tests_total": 5, "tests_passed": 5, "failures": []}
GOOD_TIMING = {"latency_ms_mean": 10.0, "latency_ms_std": 0.2,
               "first_sample_ms": 10.0, "steady_p50_ms": 10.0}


def _verdict(code: str, *, task=None, holdout=None, optimized=None) -> str:
    task = task or _task()
    return evaluate_integrity(
        task, code,
        holdout=holdout or CLEAN_HOLDOUT,
        baseline={"latency_ms_mean": 20.0, "latency_ms_std": 0.3},
        optimized=optimized or GOOD_TIMING,
    ).verdict


def test_honest_optimization_is_clean():
    code = "def sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    assert _verdict(code) == CLEAN


def test_syntax_error_is_rejected():
    assert _verdict("def sum_squares(n)\n    return 1") == REJECTED


def test_missing_entrypoint_is_rejected():
    assert _verdict("def other(n):\n    return n\n") == REJECTED


def test_constant_returning_entrypoint_is_rejected():
    assert _verdict("def sum_squares(n):\n    return 338350\n") == REJECTED


def test_forbidden_import_is_rejected():
    code = "import socket\n\ndef sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    assert _verdict(code) == REJECTED


def test_dynamic_execution_is_rejected():
    code = (
        "def sum_squares(n):\n"
        "    return eval('n * (n + 1) * (2 * n + 1) // 6')\n"
    )
    assert _verdict(code) == REJECTED


def test_clock_import_is_suspect_not_clean():
    code = "import time\n\ndef sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    assert _verdict(code) == SUSPECT


def test_hardcoded_lookup_table_is_rejected():
    task = _task()
    answers = {tuple(t["args"])[0]: t["expected"] for t in task.all_tests}
    table = ", ".join(f"{k}: {v}" for k, v in answers.items())
    code = (
        f"_TABLE = {{{table}}}\n\n"
        "def sum_squares(n):\n"
        "    if n in _TABLE:\n"
        "        return _TABLE[n]\n"
        "    return sum(i * i for i in range(1, n + 1))\n"
    )
    assert _verdict(code, task=task) == REJECTED


def test_holdout_failure_is_rejected():
    code = "def sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    bad_holdout = {"tests_total": 5, "tests_passed": 3,
                   "failures": [{"index": 0, "reason": "mismatch"}]}
    assert _verdict(code, holdout=bad_holdout) == REJECTED


def test_missing_holdout_is_suspect():
    code = "def sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    assert _verdict(code, holdout={"tests_total": 0, "tests_passed": 0}) == SUSPECT


def test_memoisation_is_flagged_as_suspect():
    code = (
        "from functools import lru_cache\n\n"
        "@lru_cache(maxsize=None)\n"
        "def sum_squares(n):\n"
        "    return n * (n + 1) * (2 * n + 1) // 6\n"
    )
    assert _verdict(code) == SUSPECT


def test_warm_cache_anomaly_is_flagged():
    code = "def sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    optimized = dict(GOOD_TIMING, first_sample_ms=500.0, steady_p50_ms=1.0)
    assert _verdict(code, optimized=optimized) == SUSPECT


def test_large_speedup_is_noted_but_still_counted():
    """A real O(n) -> O(1) win must not be punished for being large."""
    code = "def sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    report = evaluate_integrity(
        _task(), code, holdout=CLEAN_HOLDOUT,
        baseline={"latency_ms_mean": 5000.0, "latency_ms_std": 1.0},
        optimized=dict(GOOD_TIMING, latency_ms_mean=0.001, latency_ms_std=0.00002),
    )
    assert report.verdict == CLEAN
    assert report.counted
    assert any(f.check == "large_speedup" for f in report.findings)


def test_noisy_measurement_is_flagged():
    code = "def sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n"
    optimized = dict(GOOD_TIMING, latency_ms_std=5.0)
    assert _verdict(code, optimized=optimized) == SUSPECT


def test_findings_are_explainable():
    report = evaluate_integrity(
        _task(), "import socket\ndef sum_squares(n):\n    return 1\n",
        holdout=CLEAN_HOLDOUT,
        baseline={"latency_ms_mean": 20.0}, optimized=GOOD_TIMING,
    )
    assert report.reasons()
    assert all(": " in reason for reason in report.reasons())


# ── native (C++) gates ─────────────────────────────────────────────────────

def _cpp_task() -> BenchTask:
    return BenchTask(
        task_id="pie/test", suite="pie", tier="tier1", language="cpp",
        source_code="int main(){return 0;}", entrypoint="main",
        workload=Workload(),
        metadata={"native_tests": [
            {"stdin": "1\n", "expected_stdout": "yes 12345"},
            {"stdin": "2\n", "expected_stdout": "no 67890"},
        ]},
    )


def test_cpp_missing_main_is_rejected():
    report = evaluate_integrity_native(
        _cpp_task(), "int foo(){return 0;}",
        holdout=CLEAN_HOLDOUT, baseline={"latency_ms_mean": 10.0},
        optimized=GOOD_TIMING,
    )
    assert report.verdict == REJECTED


def test_cpp_system_call_is_rejected():
    code = '#include <cstdlib>\nint main(){ system("cat out.txt"); return 0; }'
    report = evaluate_integrity_native(
        _cpp_task(), code, holdout=CLEAN_HOLDOUT,
        baseline={"latency_ms_mean": 10.0}, optimized=GOOD_TIMING,
    )
    assert report.verdict == REJECTED


def test_cpp_pasted_expected_output_is_rejected():
    code = 'int main(){ printf("yes 12345"); printf("no 67890"); return 0; }'
    report = evaluate_integrity_native(
        _cpp_task(), code, holdout=CLEAN_HOLDOUT,
        baseline={"latency_ms_mean": 10.0}, optimized=GOOD_TIMING,
    )
    assert report.verdict == REJECTED


def test_strip_markdown_fences():
    assert strip_markdown_fences("blah\n```python\ndef f():\n    pass\n```\n") == \
        "def f():\n    pass"
    assert strip_markdown_fences("def f(): pass") == "def f(): pass"
