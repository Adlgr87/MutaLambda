"""The measurement engine must be unbiased and must not trust the candidate."""

from __future__ import annotations

import pytest

from bench.invariants import build_invariant_module
from bench.measure import (
    calibrate_noise, environment_fingerprint, measure, measure_interleaved,
)
from bench.spec import BenchTask, Workload
from bench.suites import smoke

pytestmark = pytest.mark.bench


def _tiny_task(**kwargs) -> BenchTask:
    code = "def f(n):\n    return sum(i * i for i in range(n))\n"
    defaults = dict(
        task_id="unit/f", suite="unit", tier="tier1", source_code=code, entrypoint="f",
        workload=Workload(calls=[[[2000], {}]], warmups=1, samples=3, timeout_sec=30.0),
        visible_tests=[{"function": "f", "args": [10], "expected": 285}],
        holdout_tests=[{"function": "f", "args": [5], "expected": 30}],
    )
    defaults.update(kwargs)
    return BenchTask(**defaults)


def test_measure_reports_latency_and_tests():
    task = _tiny_task()
    m = measure(task.source_code, task)
    assert m.ok
    assert m.all_pass
    assert m.latency_ms_p50 > 0
    assert len(m.samples) == task.workload.samples


def test_failing_candidate_is_reported_not_crashed():
    task = _tiny_task()
    m = measure("def f(n):\n    return 0\n", task)
    assert m.tests_passed == 0
    assert m.error == "tests_failed"


def test_broken_syntax_is_reported():
    task = _tiny_task()
    m = measure("def f(n)\n  return", task)
    assert not m.ok
    assert m.error.startswith("load:")


def test_missing_entrypoint_is_reported():
    task = _tiny_task()
    m = measure("def other(n):\n    return n\n", task)
    assert m.tests_passed == 0


def test_candidate_stdout_cannot_forge_the_report():
    """A candidate printing a fake JSON report must not be believed."""
    task = _tiny_task()
    evil = (
        'print(\'{"ok": true, "tests_passed": 99, "tests_total": 99, '
        '"samples": [0.0001], "mem_peak_mb": 0.0}\')\n'
        "def f(n):\n    return 0\n"
    )
    m = measure(evil, task)
    # The driver's own report is printed last, so the forged line loses.
    assert m.tests_passed != 99
    assert m.tests_total == 2


def test_infinite_loop_times_out_instead_of_hanging():
    task = _tiny_task(
        workload=Workload(calls=[[[10], {}]], warmups=0, samples=1, timeout_sec=3.0),
        visible_tests=[], holdout_tests=[],
    )
    m = measure("def f(n):\n    while True:\n        pass\n", task)
    assert m.timed_out
    assert m.error == "timeout"


def test_identity_measurement_is_unbiased():
    """Same code measured as two variants must land within a wide-but-finite band."""
    task = _tiny_task()
    result = measure_interleaved({"a": task.source_code, "b": task.source_code},
                                 task, repeats=3)
    ratio = result["a"]["latency_ms_mean"] / result["b"]["latency_ms_mean"]
    assert 0.5 < ratio < 2.0, f"identity ratio {ratio} — measurement is biased"


def test_calibration_reports_a_noise_band():
    noise = calibrate_noise(_tiny_task(), repeats=2)
    assert noise["available"]
    assert noise["noise_band"] >= 1.0
    assert "noise" in noise["interpretation"]


def test_environment_fingerprint_has_what_a_reviewer_needs():
    env = environment_fingerprint()
    for key in ("python", "platform", "cpu_count", "governor"):
        assert key in env


def test_invariants_catch_a_physics_breaking_optimization():
    task = next(t for t in smoke.load_tasks() if t.task_id == "smoke/normalize")
    assert "bounded" in task.invariants

    # "Optimization" that skips the division: 30x faster, and wrong.
    cheat = "def normalize(values):\n    return [float(v) for v in values]\n"
    wrapped, tests = build_invariant_module(cheat, task)
    m = measure(wrapped, task, tests=tests, tests_only=True)
    assert m.tests_passed < m.tests_total, "bounded invariant should have failed"


def test_invariants_pass_for_an_honest_rewrite():
    task = next(t for t in smoke.load_tasks() if t.task_id == "smoke/normalize")
    honest = (
        "def normalize(values):\n"
        "    lo = min(values)\n"
        "    hi = max(values)\n"
        "    span = hi - lo\n"
        "    if span == 0:\n"
        "        return [0.0] * len(values)\n"
        "    return [(v - lo) / span for v in values]\n"
    )
    wrapped, tests = build_invariant_module(honest, task)
    m = measure(wrapped, task, tests=tests, tests_only=True)
    assert m.tests_passed == m.tests_total
