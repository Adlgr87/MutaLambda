"""Tests for the Fase-2 tiered evaluation ladder (O6 N1/N2/N3 + A4).

Acceptance focus:
  * **zero false positives** — correct variants pass N1 (and the ladder);
  * **N1 < 1 ms** in-memory nanopass guard;
  * **N3 share ≤ 20%** of the batch by construction;
  * minimal test subset covers the target's entry functions (A4).
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import EvalResult  # noqa: E402
from optimization_flags import reset_optimization_flags  # noqa: E402
from tiered_evaluator import (  # noqa: E402
    TestSubsetSelector,
    TieredEvaluator,
    TieredOfflineEvaluator,
    detects_io,
    eval_in_process,
    n1_nanopass_check,
    tiering_active,
)

BASELINE = '''
def half(n):
    return n // 2

def solution(data, k=32):
    out = []
    for i in range(0, len(data), k):
        out.append(sum(data[i:i + k]))
    return out


def trivial(x):
    return x + 1
'''

VARIANT = BASELINE.replace(
    "    for i in range(0, len(data), k):\n        out.append(sum(data[i:i + k]))",
    "    i = 0\n    while i < len(data):\n        out.append(sum(data[i:i + k]))\n        i = i + k",
)

TESTS = [
    {"function": "solution", "args": [[1, 2, 3, 4], 2], "expected": [3, 7], "comparison": "equal"},
    {"function": "solution", "args": [[], 4], "expected": [], "comparison": "equal"},
    {"function": "solution", "args": [[10, 20], 100], "expected": [30], "comparison": "equal"},
    {"function": "half", "args": [10], "expected": 5, "comparison": "equal"},
    {"function": "trivial", "args": [41], "expected": 42, "comparison": "equal"},
]

BROKEN_API = BASELINE.replace("def solution", "def solutioX")
BROKEN_SYNTAX = "def f(:\n    pass"
WRONG_ANSWER = BASELINE.replace("return x + 1", "return x + 2")
IO_CODE = (
    "import os\n\n"
    "def half(n):\n    return n // 2\n\n"
    "def solution(data, k=32):\n    return os.listdir('.')\n\n"
    "def trivial(x):\n    return x + 1\n"
)


# ── N1: in-memory nanopass guard ────────────────────────────────────────────


def test_n1_baseline_passes_under_1ms() -> None:
    start = time.perf_counter()
    r = n1_nanopass_check(BASELINE, BASELINE)
    elapsed_ms = (time.perf_counter() - start) * 1e3
    assert r.passed is True
    assert r.api_compatible is True
    assert r.ms < 1.0, f"N1 took {r.ms:.3f} ms (budget 1.0)"
    assert elapsed_ms < 5.0  # wall-clock sanity incl. first-call overhead


def test_n1_rejects_syntax_error() -> None:
    r = n1_nanopass_check(BROKEN_SYNTAX, BASELINE)
    assert r.passed is False
    assert r.reason.startswith("syntax_error")


def test_n1_rejects_api_break() -> None:
    r = n1_nanopass_check(BROKEN_API, BASELINE)
    assert r.passed is False
    assert "api_mismatch" in r.reason
    assert "solution" in r.missing_functions


def test_n1_rejects_security_finding() -> None:
    r = n1_nanopass_check(IO_CODE, BASELINE)
    assert r.passed is False
    assert r.reason.startswith("security")
    assert r.security_findings


def test_n1_zero_false_positives_on_correct_variants() -> None:
    """Every API-preserving, semantically correct variant must pass N1."""
    variants = [
        VARIANT,
        BASELINE.replace("return x + 1", "return 1 + x"),
        BASELINE.replace("k=32", "k=16"),
        BASELINE + "\n# trailing comment\n",
    ]
    for code in variants:
        r = n1_nanopass_check(code, BASELINE)
        assert r.passed is True, f"false positive: {r.reason}"


# ── A4: minimal test subset ─────────────────────────────────────────────────


def test_subset_covers_all_entry_functions() -> None:
    sel = TestSubsetSelector(BASELINE, TESTS)
    subset = sel.select()
    fns = {t["function"] for t in subset}
    assert {"solution", "half", "trivial"} <= fns
    assert len(subset) <= len(TESTS)
    meta = sel.meta()
    assert meta["subset_size"] == len(subset)
    assert meta["total_tests"] == len(TESTS)


def test_subset_respects_max_tests() -> None:
    sel = TestSubsetSelector(BASELINE, TESTS, max_tests=2)
    subset = sel.select()
    assert len(subset) == 2
    # entry-point tests are kept first
    assert any(t["function"] == "solution" for t in subset)


def test_subset_coverage_guided_still_valid() -> None:
    sel = TestSubsetSelector(BASELINE, TESTS, coverage_guided=True)
    subset = sel.select()
    assert subset
    assert sel.meta()["mode"] == "coverage_guided"


def test_subset_deterministic() -> None:
    a = TestSubsetSelector(BASELINE, TESTS).select()
    b = TestSubsetSelector(BASELINE, TESTS).select()
    assert a == b


# ── N2: I/O detection + in-process evaluation ───────────────────────────────


def test_detects_io() -> None:
    assert detects_io(IO_CODE) is True
    assert detects_io(BASELINE) is False
    assert detects_io("import subprocess\n") is True


def test_eval_in_process_all_pass() -> None:
    res = eval_in_process(BASELINE, TESTS)
    assert res["passed"] is True
    assert res["score"] == 1.0
    assert res["error"] == ""


def test_eval_in_process_wrong_answer() -> None:
    res = eval_in_process(WRONG_ANSWER, TESTS)
    assert res["passed"] is False
    assert 0.0 < res["score"] < 1.0
    failed = [r for r in res["results"] if not r["passed"]]
    assert failed and failed[0]["error"] == "value_mismatch"


def test_eval_in_process_raising_candidate() -> None:
    bad = BASELINE.replace("return x + 1", "raise ValueError('boom')")
    res = eval_in_process(bad, TESTS)
    assert res["passed"] is False
    assert any(r["error"].startswith("raised") for r in res["results"])


def test_eval_in_process_unparseable() -> None:
    res = eval_in_process(BROKEN_SYNTAX, TESTS)
    assert res["passed"] is False
    assert res["error"].startswith("exec")


# ── Full ladder: TieredEvaluator ────────────────────────────────────────────


def test_ladder_zero_false_positives() -> None:
    te = TieredEvaluator(BASELINE, TESTS, sandbox_top_pct=20.0)
    correct = [BASELINE, VARIANT, BASELINE.replace("return x + 1", "return 1 + x")]
    results = te.evaluate_batch(correct)
    for tr in results:
        assert tr.passed is True, f"false positive at tier {tr.tier}: {tr.n1.reason if tr.n1 else ''}"


def test_ladder_rejects_broken_at_n1() -> None:
    te = TieredEvaluator(BASELINE, TESTS, sandbox_top_pct=20.0)
    results = te.evaluate_batch([BASELINE, BROKEN_API, BROKEN_SYNTAX, WRONG_ANSWER])
    tiers = [tr.tier for tr in results]
    assert tiers[1] == "n1_reject"
    assert tiers[2] == "n1_reject"
    assert results[1].n1.reason.startswith("api_mismatch")
    assert results[2].n1.reason.startswith("syntax_error")
    # wrong answer is NOT rejected by N1 (it is API-compatible) — N2/N3 decide
    assert results[3].tier in ("n2", "n3")
    assert results[3].passed is False


def test_ladder_n3_share_bounded_at_scale() -> None:
    """≤20 % of the batch may touch N3 (acceptance criterion)."""
    n = 100
    codes = []
    for i in range(n):
        if i % 10 == 0:
            codes.append(BROKEN_SYNTAX)  # 10% broken syntax
        elif i % 13 == 0:
            codes.append(WRONG_ANSWER)  # some wrong answers
        else:
            codes.append(VARIANT if i % 2 else BASELINE)
    te = TieredEvaluator(BASELINE, TESTS, sandbox_top_pct=20.0)
    results = te.evaluate_batch(codes)
    stats = te.stats()
    assert stats["total"] == n
    n3 = sum(1 for r in results if r.tier == "n3")
    assert n3 <= n * 0.20 + 1, f"N3 share {n3}/{n} exceeds 20 %"
    assert stats["n3_pct"] <= 20.0 + (1.0 / n) * 100.0
    # zero false positives among the correct candidates
    correct_idx = [i for i, c in enumerate(codes) if c in (BASELINE, VARIANT)]
    for i in correct_idx:
        assert results[i].passed is True


def test_ladder_io_candidate_uses_subprocess_path() -> None:
    te = TieredEvaluator(BASELINE, TESTS, sandbox_top_pct=20.0, n3_enabled=False)
    # N1 security rejects import os; use a pure-but-slow variant instead to
    # exercise the in-process path, then an I/O-free N2.
    results = te.evaluate_batch([BASELINE, IO_CODE])
    assert results[0].tier == "n2"
    assert results[1].tier == "n1_reject"  # security finding


def test_ladder_stats_recorded() -> None:
    te = TieredEvaluator(BASELINE, TESTS, sandbox_top_pct=20.0)
    te.evaluate_batch([BASELINE, VARIANT, BROKEN_API])
    s = te.stats()
    for key in ("total", "n1_rejected", "n2_final", "n3_count", "n3_pct",
                "n1_mean_ms", "n2_mean_ms", "subset_size", "total_ms"):
        assert key in s
    assert s["n1_rejected"] == 1
    assert s["n1_mean_ms"] < 1.5


def test_tiered_result_serializable() -> None:
    te = TieredEvaluator(BASELINE, TESTS, sandbox_top_pct=20.0)
    results = te.evaluate_batch([BASELINE, BROKEN_API])
    blob = json.dumps([tr.to_dict() for tr in results])
    assert "code_hash" in blob


# ── TieredOfflineEvaluator (engine drop-in) ─────────────────────────────────


def test_offline_adapter_n1_only_rejects_broken() -> None:
    def scorer(code: str) -> float:
        import ast

        try:
            ast.parse(code)
            return 1.0
        except SyntaxError:
            return float("-inf")

    ev = TieredOfflineEvaluator(BASELINE, scorer)
    evs = ev.evaluate_batch([BASELINE, BROKEN_SYNTAX, BROKEN_API])
    assert isinstance(evs[0], EvalResult)
    assert evs[0].passed is True
    assert evs[1].passed is False
    assert evs[2].passed is False
    assert ev.score(BASELINE) == 1.0
    assert ev.score(BROKEN_SYNTAX) == float("-inf")


def test_offline_adapter_with_tests_runs_ladder() -> None:
    def scorer(code: str) -> float:
        return 0.9

    ev = TieredOfflineEvaluator(BASELINE, scorer, test_cases=TESTS)
    evs = ev.evaluate_batch([BASELINE, VARIANT, WRONG_ANSWER])
    assert all(isinstance(e, EvalResult) for e in evs)
    assert evs[0].passed is True
    assert evs[1].passed is True
    assert evs[2].passed is False
    assert ev.stats().get("total") == 3


# ── flags wiring (rule 6) ───────────────────────────────────────────────────


def test_tiering_active_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", raising=False)
    reset_optimization_flags()
    try:
        assert tiering_active() is False
    finally:
        reset_optimization_flags()


def test_tiering_active_with_flag(monkeypatch) -> None:
    monkeypatch.setenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", "1")
    reset_optimization_flags()
    try:
        assert tiering_active() is True
    finally:
        monkeypatch.delenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", raising=False)
        reset_optimization_flags()


def test_from_flags_builds_evaluator(monkeypatch) -> None:
    monkeypatch.setenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", "1")
    reset_optimization_flags()
    try:
        te = TieredEvaluator.from_flags(BASELINE, TESTS)
        assert te.sandbox_top_pct == 20.0
        assert te.min_cpu_pct == 0.5
        assert te.n1_enabled is True
        assert te.n2_enabled is True
    finally:
        monkeypatch.delenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", raising=False)
        reset_optimization_flags()
