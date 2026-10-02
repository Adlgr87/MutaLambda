"""The sandbox harness's inlined comparator must stay in step with the canonical one.

``comparison.compare_values`` is the single source of truth, but the sandbox
harness cannot import it: the harness source is assembled as a string and
executed in a child process with a restricted builtins namespace and no access
to project packages. So a second implementation is unavoidable.

What *is* avoidable is the two drifting apart silently, which is what had
happened: the canonical function raises ``ValueError`` on an unknown comparator
while the inlined copy ended with a bare ``return got == expected``. A typo in a
``comparison:`` field therefore produced ``passed=True, correctness=1.0`` in the
sandbox - the correctness gate reporting a pass it had never verified.

These tests pin the two together on every comparator they share, and pin the
disagreement that remains (unknown comparators) to a defined, visible outcome.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from comparison import COMPARATORS, compare_values
from runners import SubprocessRunner, build_wrapper_source

# (got, expected, comparison) triples covering each shared comparator's
# agreement AND disagreement cases.
PARITY_CASES = [
    (1, 1, "equal"),
    (1, 2, "equal"),
    ("a", "a", "equal"),
    ([1, 2], [1, 2], "equal"),
    (1.0000000001, 1.0, "float_close"),
    (1.5, 2.5, "float_close"),
    ("not-a-number", 1.0, "float_close"),
    (None, 1.0, "float_close"),
    ([1.0, 2.0], [1.0, 2.0], "array_allclose"),
    ([1.0, 2.0], [1.0, 9.0], "array_allclose"),
    ("abc", "b", "contains"),
    ("abc", "z", "contains"),
    ([1, 2, 3], 2, "contains"),
    (5, 2, "contains"),  # TypeError path
    (1, 1, "EQUAL"),  # case-insensitivity
    (1, 1, ""),  # empty -> defaults to equal
    (1, 1, None),  # None -> defaults to equal
]


def _harness_compare(got, expected, comparison):
    """Run the *inlined* comparator exactly as the sandbox would."""
    src = build_wrapper_source("/dev/null", memory_mb=0, allow_expression_eval=False)
    # Lift just the comparator out of the generated harness and exercise it in
    # isolation, so we test the shipped source rather than a copy of it.
    ns: dict = {}
    exec(src.split("def _run_case")[0], ns)  # noqa: S102 - test-only, fixed input
    return ns["_compare"](got, expected, comparison)


@pytest.mark.parametrize("got,expected,comparison", PARITY_CASES)
def test_inlined_comparator_matches_canonical(got, expected, comparison):
    assert _harness_compare(got, expected, comparison) == compare_values(
        got, expected, comparison
    ), f"divergence on {comparison!r} with got={got!r} expected={expected!r}"


def test_canonical_rejects_unknown_comparator():
    """Strict is correct: an unknown comparator means correctness is unprovable."""
    with pytest.raises(ValueError, match="Unknown comparison"):
        compare_values(1, 1, "no_such_comparator")


def test_harness_records_unknown_comparator_instead_of_silently_passing():
    """The harness cannot raise across the process boundary, so it records."""
    src = build_wrapper_source("/dev/null", memory_mb=0, allow_expression_eval=False)
    ns: dict = {}
    exec(src.split("def _run_case")[0], ns)  # noqa: S102 - test-only, fixed input

    assert ns["_compare"](1, 1, "no_such_comparator") is True  # historical fallback
    assert ns["_COMPARATOR_FALLBACKS"] == ["no_such_comparator"], (
        "unknown comparator was not recorded; the fallback is silent again"
    )


def test_known_comparator_list_is_in_sync():
    """The harness's allowlist must not drift from the canonical COMPARATORS."""
    src = build_wrapper_source("/dev/null", memory_mb=0, allow_expression_eval=False)
    match = re.search(r"_KNOWN_COMPARATORS = \(([^)]*)\)", src)
    assert match, "_KNOWN_COMPARATORS vanished from the harness"
    harness_known = {c.strip().strip("'\"") for c in match.group(1).split(",") if c.strip()}

    # predicate_registered is deliberately absent: predicates are registered in
    # the parent process and cannot cross into the sandbox. It must therefore
    # be reported as unverifiable rather than quietly compared with ==.
    assert harness_known == set(COMPARATORS) - {"predicate_registered"}, (
        "harness comparator allowlist drifted from comparison.COMPARATORS"
    )


# ── End-to-end through a real sandbox subprocess ───────────────────────────


@pytest.mark.parametrize(
    "comparison,expect_passed",
    [("equal", True), ("typo_comparator", False), ("predicate_registered", False)],
)
def test_sandbox_marks_unverifiable_results(comparison, expect_passed):
    """Regression: a typo'd comparator used to yield passed=True, correctness=1.0."""
    runner = SubprocessRunner(timeout_sec=15)
    result = runner.run(
        "def f():\n    return 1\n",
        [{"function": "f", "args": [], "expected": 1, "comparison": comparison}],
    )

    assert result.passed is expect_passed
    if not expect_passed:
        assert result.metrics["comparator_undefined"] == 1.0, (
            "unverifiable result was not flagged"
        )
    else:
        assert "comparator_undefined" not in result.metrics


def test_a_genuinely_correct_candidate_is_unaffected():
    """The flag must not leak onto ordinary, verifiable evaluations."""
    runner = SubprocessRunner(timeout_sec=15)
    result = runner.run(
        "def f(x):\n    return x * 2\n",
        [
            {"function": "f", "args": [2], "expected": 4},
            {"function": "f", "args": [3], "expected": 6, "comparison": "float_close"},
        ],
    )
    assert result.passed is True
    assert "comparator_undefined" not in result.metrics


def test_unknown_comparator_cannot_beat_a_real_solution():
    """The whole point: unverifiable must not outrank verified-correct."""
    runner = SubprocessRunner(timeout_sec=15)
    honest = runner.run(
        "def f():\n    return 1\n", [{"function": "f", "args": [], "expected": 1}]
    )
    bogus = runner.run(
        "def f():\n    return 1\n",
        [{"function": "f", "args": [], "expected": 1, "comparison": "made_up"}],
    )
    assert honest.passed and not bogus.passed


# ── Static audit of the shipped test fixtures ──────────────────────────────


def test_no_shipped_fixture_uses_an_undefined_comparator():
    """Step 0 of the comparator remediation, enforced: scan the repo's own data.

    If this fails, some shipped preset/example declares a comparator that the
    sandbox cannot verify, and whatever it reported was never a real pass.
    """
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in list(root.rglob("*.json")) + list(root.rglob("*.yaml")):
        if any(p in path.parts for p in (".git", ".venv", "node_modules", "reports")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for found in re.findall(r'["\']comparison["\']\s*:\s*["\']([^"\']+)["\']', text):
            if found.lower() not in COMPARATORS:
                offenders.append(f"{path.relative_to(root)}: {found!r}")

    assert not offenders, "undefined comparators in shipped fixtures:\n" + "\n".join(offenders)
