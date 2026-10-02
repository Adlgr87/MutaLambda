"""The e2e gate must actually distinguish a healthy pipeline from a broken one.

For a long time it did not. `tests/e2e_tests.py` asserted only
`final_good > -1e4` and `final_bad > -1e5` — i.e. "neither score is -inf" —
so it passed while reporting `good=-1.0  bad=-1.0`, meaning the "good" LLM
stub scored exactly the same as the deliberately-broken one.

The root cause was not in the engine. The stub emitted its own test harness
that dispatched with `globals()[fn](*args)`, left over from before the sandbox
generated its own wrapper. The ML-002 security scanner rejects `globals` as a
sensitive name, so every candidate was thrown out before a single test case
ran, and correctness was 0.0 (score -1.0) regardless of whether the code was
correct. A green gate was reporting on an evolution that never happened.

These tests pin all three properties: the stub stays executable, the verdict
is a real comparison with a margin, and "never measured" is reported
differently from "measured and worse".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_tests import (  # noqa: E402
    BAD_MAX_SCORE,
    GOOD_MIN_SCORE,
    UNEVALUATED_SCORE,
    build_test_cases_sum,
    classify,
    diagnose_candidate,
    make_llm_stub,
)
from runners import scan_code_security  # noqa: E402


# ── The stub must survive the security scanner ─────────────────────────────


@pytest.mark.parametrize("mode", ["good", "bad"])
def test_stub_output_is_not_rejected_by_the_security_scanner(mode):
    """Regression: `globals()` in the stub made every candidate unevaluable."""
    code = make_llm_stub(mode)("any prompt")
    findings = scan_code_security(code)
    assert findings == [], (
        f"the {mode!r} stub emits code the sandbox will reject ({findings}); "
        f"every candidate would score -1.0 regardless of correctness"
    )


def test_stub_does_not_ship_its_own_harness():
    """The sandbox supplies the harness; a second one is dead weight and a hazard."""
    code = make_llm_stub("good")("")
    assert "globals(" not in code
    assert "sys.stdin" not in code
    assert "__main__" not in code


@pytest.mark.parametrize(
    "mode,n,expected",
    [("good", 0, 0), ("good", 1, 0), ("good", 5, 10), ("bad", 5, 5), ("bad", 1, 1)],
)
def test_stub_semantics_are_what_the_test_cases_assume(mode, n, expected):
    """good must satisfy the spec; bad must genuinely violate it."""
    ns: dict = {}
    exec(make_llm_stub(mode)(""), ns)  # noqa: S102 - our own fixture
    assert ns["compute_sum"](n) == expected


def test_good_and_bad_actually_disagree():
    cases = build_test_cases_sum()
    good_ns: dict = {}
    bad_ns: dict = {}
    exec(make_llm_stub("good")(""), good_ns)  # noqa: S102
    exec(make_llm_stub("bad")(""), bad_ns)  # noqa: S102

    good_pass = sum(1 for c in cases if good_ns["compute_sum"](*c["args"]) == c["expected"])
    bad_pass = sum(1 for c in cases if bad_ns["compute_sum"](*c["args"]) == c["expected"])

    assert good_pass == len(cases), "the 'good' stub does not solve its own test cases"
    assert bad_pass < good_pass, "the 'bad' stub is not actually worse"


# ── The verdict must be a real comparison ──────────────────────────────────


@pytest.mark.parametrize(
    "good,bad,expected_code,why",
    [
        (1.1235, -0.3333, 0, "clear success"),
        (0.9770, -0.6667, 0, "measured success"),
        (UNEVALUATED_SCORE, -0.3333, 2, "good never evaluated"),
        (0.97, UNEVALUATED_SCORE, 2, "bad never evaluated"),
        (UNEVALUATED_SCORE, UNEVALUATED_SCORE, 2, "the original bug"),
        (-0.5, 0.3, 1, "good loses to bad"),
        (0.4, 0.4, 1, "tie"),
        (0.2, -0.5, 1, "good below the floor"),
        (0.9, 0.3, 1, "bad above the ceiling"),
    ],
)
def test_classify_exit_codes(good, bad, expected_code, why):
    code, verdict = classify(good, bad)
    assert code == expected_code, f"{why}: got exit {code}, expected {expected_code} ({verdict})"
    assert verdict, "every verdict must carry an explanation"


def test_indeterminate_is_distinct_from_failure():
    """Exit 2 must not be conflated with exit 1.

    "the pipeline measured nothing" is an instrumentation fault; "good lost to
    bad" is a quality regression. Collapsing them is what let the broken gate
    look green.
    """
    unmeasured, _ = classify(UNEVALUATED_SCORE, UNEVALUATED_SCORE)
    regression, _ = classify(-0.5, 0.3)
    assert unmeasured == 2 and regression == 1
    assert unmeasured != regression


def test_thresholds_are_a_real_margin():
    assert GOOD_MIN_SCORE > BAD_MAX_SCORE, "thresholds must leave a gap"


# ── The diagnosis must name the cause ──────────────────────────────────────


def test_diagnosis_reports_a_security_rejection():
    """The failure mode that actually happened must be named, not inferred."""
    code = (
        "import sys, json\n"
        "def compute_sum(n):\n    return sum(range(n))\n"
        "def _run():\n    got = globals()['compute_sum'](1)\n"
    )
    report = "\n".join(diagnose_candidate(code, build_test_cases_sum()))
    assert "ESCÁNER DE SEGURIDAD" in report
    assert "globals" in report
    assert "NUNCA se ejecutó" in report


def test_diagnosis_reports_per_case_got_vs_expected():
    report = "\n".join(
        diagnose_candidate("def compute_sum(n):\n    return n\n", build_test_cases_sum())
    )
    assert "FAIL" in report
    assert "esperaba" in report
    assert "comparador=" in report


def test_diagnosis_surfaces_a_silenced_exception():
    report = "\n".join(
        diagnose_candidate("def compute_sum(n):\n    return 1 / 0\n", build_test_cases_sum())
    )
    assert "ZeroDivisionError" in report, "the exception must not be swallowed"


def test_diagnosis_reports_an_undefined_comparator():
    cases = [dict(c, comparison="typo_comparator") for c in build_test_cases_sum()]
    report = "\n".join(
        diagnose_candidate("def compute_sum(n):\n    return sum(range(n))\n", cases)
    )
    assert "COMPARADOR INDEFINIDO" in report


def test_diagnosis_reports_a_missing_function():
    report = "\n".join(
        diagnose_candidate("def something_else(n):\n    return n\n", build_test_cases_sum())
    )
    assert "ausente" in report


def test_diagnosis_never_raises_on_hostile_input():
    """A diagnostic that crashes hides the thing it was meant to explain."""
    for code in ("", "def f(", "raise SystemExit(1)", "x = 1"):
        assert isinstance(diagnose_candidate(code, build_test_cases_sum()), list)


# ── The gate, executed ─────────────────────────────────────────────────────


@pytest.mark.e2e
def test_full_pipeline_gate_passes():
    """Run the real gate under pytest.

    `run_tests.sh` invokes `pytest -m e2e tests/e2e_tests.py`, but that file is
    a script with no test functions, so the phase collected nothing and the
    gate was never enforced anywhere except the GitHub workflow. This wrapper
    makes it a real test.
    """
    import e2e_tests

    out_good = e2e_tests.run_e2e(llm_mode="good", fast=True, use_archive=False, serial=True)
    out_bad = e2e_tests.run_e2e(llm_mode="bad", fast=True, use_archive=False, serial=True)

    good = out_good["agent_metrics"]["best_score_history"][-1]
    bad = out_bad["agent_metrics"]["best_score_history"][-1]
    code, verdict = classify(good, bad)

    if code != 0:
        detail = "\n".join(diagnose_candidate(out_good["best_solution_code"], build_test_cases_sum()))
        pytest.fail(f"{verdict}\ngood={good} bad={bad}\n{detail}")

    assert good >= GOOD_MIN_SCORE
    assert bad <= BAD_MAX_SCORE
