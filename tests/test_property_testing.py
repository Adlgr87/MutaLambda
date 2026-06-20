"""Tests for property-based testing helpers."""

import pytest

from property_testing import HAS_Z3, verify_invariant_z3


pytestmark = pytest.mark.skipif(not HAS_Z3, reason="z3-solver is not installed")


def test_verify_invariant_z3_holds_for_nonnegative_result():
    holds, counterexample = verify_invariant_z3(
        "def f(x):\n    return x * x",
        "result >= 0",
    )

    assert holds is True
    assert counterexample is None


def test_verify_invariant_z3_finds_counterexample():
    holds, counterexample = verify_invariant_z3(
        "def f(x):\n    return x - 1",
        "result >= 0",
    )

    assert holds is False
    assert counterexample is not None


def test_verify_invariant_z3_rejects_unsupported_invariant():
    holds, counterexample = verify_invariant_z3(
        "def f(x):\n    return x + 1",
        "abs(result) < 2",
    )

    assert holds is False
    assert counterexample == "Invariant must be a simple comparison like result >= 0"


def test_verify_invariant_z3_parses_equality():
    holds, counterexample = verify_invariant_z3(
        "def f(x):\n    return x",
        "result == 0",
    )

    assert holds is False
    assert counterexample is not None


def test_verify_invariant_z3_parses_inequality():
    holds, counterexample = verify_invariant_z3(
        "def f(x):\n    return x",
        "result != 0",
    )

    assert holds is False
    assert counterexample is not None
