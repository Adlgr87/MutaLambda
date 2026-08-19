"""
Differential testing: run a set of test cases against original and mutated code,
check output equivalence (D2/D4 Layer 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TestCaseResult:
    name: str
    args: tuple
    kwargs: dict
    expected: Any
    actual: Any
    match: bool
    message: str = ""


@dataclass
class DifferentialResult:
    equivalent: bool
    compared: int
    mismatches: int
    cases: List[TestCaseResult] = field(default_factory=list)


def _load_fn(code: str, function_name: str) -> Any:
    ns: Dict[str, Any] = {"__name__": "__diff__"}
    exec(compile(code, "<diff>", "exec"), ns, ns)  # noqa: S102
    return ns[function_name]


def _values_equal(a: Any, b: Any, rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> bool:
    try:
        from benchmarks.comparison import compare_values
        ok, _ = compare_values(a, b, rel_tol, abs_tol)
        return ok
    except Exception:
        return a == b


def differential_test(
    original: str,
    mutated: str,
    test_cases: List[Dict[str, Any]],
    *,
    default_function: str,
    rel_tol: float = 1e-9,
    abs_tol: float = 1e-12,
) -> DifferentialResult:
    """Run test cases against both implementations and compare outputs.

    Each test case dict: {"name"?: ..., "args": [...], "kwargs": {...}, "expected": ...}
    """
    cases: List[TestCaseResult] = []
    mismatches = 0

    orig_fn = _load_fn(original, default_function)
    try:
        mut_fn = _load_fn(mutated, default_function)
    except Exception as exc:
        return DifferentialResult(equivalent=False, compared=0, mismatches=0,
                                  cases=[TestCaseResult(
                                      name="__compile__", args=(), kwargs={},
                                      expected=None, actual=None, match=False,
                                      message=f"mutated failed to load: {exc}")])

    for tc in test_cases:
        name = tc.get("name", str(len(cases)))
        args = tuple(tc.get("args", []))
        kwargs = tc.get("kwargs", {})
        expected = tc.get("expected")

        orig_exc: Optional[BaseException] = None
        mut_exc: Optional[BaseException] = None
        orig_val: Any = None
        mut_val: Any = None

        try:
            orig_val = orig_fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            orig_exc = exc

        try:
            mut_val = mut_fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            mut_exc = exc

        match = True
        message = ""
        if orig_exc is not None or mut_exc is not None:
            if type(orig_exc) is not type(mut_exc) if (orig_exc and mut_exc) else (orig_exc is not mut_exc):
                match = False
                message = f"exception mismatch: orig={type(orig_exc).__name__ if orig_exc else None}, mut={type(mut_exc).__name__ if mut_exc else None}"
        else:
            if not _values_equal(orig_val, mut_val, rel_tol, abs_tol):
                match = False
                message = f"value mismatch: expected={expected if expected is not None else orig_val}, actual={mut_val}"

        if expected is not None and not orig_exc:
            # If test case declares expected, prefer comparing against it
            if not _values_equal(orig_val, expected, rel_tol, abs_tol):
                # original itself doesn't match expected — likely a test spec issue
                message = f"reference mismatch: fn returned {orig_val}, expected {expected}"
                match = _values_equal(mut_val, expected, rel_tol, abs_tol)

        cases.append(TestCaseResult(
            name=name, args=args, kwargs=kwargs, expected=expected,
            actual=mut_val, match=match, message=message))
        if not match:
            mismatches += 1

    return DifferentialResult(
        equivalent=(mismatches == 0),
        compared=len(test_cases),
        mismatches=mismatches,
        cases=cases,
    )