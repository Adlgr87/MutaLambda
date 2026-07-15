"""Differential testing: baseline vs candidate (ML-M03).

For each input case, compare outputs and exception types between a baseline
implementation and a candidate. Used as a promotion gate when a seed/baseline
source is available.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from comparison import compare_values


@dataclass
class CaseDiff:
    index: int
    ok: bool
    baseline_value: Any = None
    candidate_value: Any = None
    baseline_error: str = ""
    candidate_error: str = ""
    message: str = ""


@dataclass
class DifferentialResult:
    equivalent: bool
    cases: List[CaseDiff] = field(default_factory=list)
    compared: int = 0
    mismatches: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "equivalent": self.equivalent,
            "compared": self.compared,
            "mismatches": self.mismatches,
            "cases": [
                {
                    "index": c.index,
                    "ok": c.ok,
                    "message": c.message,
                    "baseline_error": c.baseline_error,
                    "candidate_error": c.candidate_error,
                }
                for c in self.cases
            ],
        }


def _call(fn: Callable, args: list, kwargs: dict) -> Tuple[Any, Optional[BaseException]]:
    try:
        return fn(*args, **kwargs), None
    except BaseException as exc:  # noqa: BLE001 — intentional differential capture
        return None, exc


def _load_function(code: str, function_name: str) -> Callable:
    namespace: Dict[str, Any] = {"__name__": "__mutalambda_diff__"}
    exec(compile(code, "<diff_candidate>", "exec"), namespace, namespace)  # noqa: S102
    fn = namespace.get(function_name)
    if not callable(fn):
        raise NameError(f"function not found: {function_name}")
    return fn


def differential_test(
    baseline_code: str,
    candidate_code: str,
    test_cases: List[Dict[str, Any]],
    *,
    default_function: str = "",
    comparison: str = "equal",
) -> DifferentialResult:
    """Compare baseline and candidate on declarative test cases.

    Only ``function``-style cases are supported (no expression eval).
    """
    result = DifferentialResult(equivalent=True)
    if not test_cases:
        result.equivalent = False
        result.cases.append(
            CaseDiff(index=-1, ok=False, message="no_test_cases")
        )
        return result

    # Infer function name if uniform across cases.
    fn_names = {tc.get("function") for tc in test_cases if isinstance(tc, dict)}
    fn_names.discard(None)
    if not fn_names and default_function:
        fn_names = {default_function}

    # Load all needed functions once.
    baseline_fns: Dict[str, Callable] = {}
    candidate_fns: Dict[str, Callable] = {}
    try:
        for name in fn_names:
            baseline_fns[name] = _load_function(baseline_code, name)
            candidate_fns[name] = _load_function(candidate_code, name)
    except Exception as exc:
        result.equivalent = False
        result.cases.append(
            CaseDiff(index=-1, ok=False, message=f"load_error:{exc}")
        )
        return result

    for idx, tc in enumerate(test_cases):
        if not isinstance(tc, dict) or "function" not in tc:
            # Skip non-declarative cases rather than silently treating as equal.
            result.cases.append(
                CaseDiff(index=idx, ok=False, message="unsupported_case_shape")
            )
            result.mismatches += 1
            result.equivalent = False
            continue

        name = tc["function"]
        args = list(tc.get("args", []))
        kwargs = dict(tc.get("kwargs", {}))
        cmp_mode = tc.get("comparison", comparison)

        b_val, b_err = _call(baseline_fns[name], args, kwargs)
        c_val, c_err = _call(candidate_fns[name], args, kwargs)
        result.compared += 1

        case = CaseDiff(
            index=idx,
            ok=True,
            baseline_value=b_val,
            candidate_value=c_val,
            baseline_error=type(b_err).__name__ if b_err else "",
            candidate_error=type(c_err).__name__ if c_err else "",
        )

        if b_err is None and c_err is None:
            if not compare_values(c_val, b_val, cmp_mode):
                # Also allow expected if provided (candidate vs expected is separate)
                case.ok = False
                case.message = f"value_mismatch baseline={b_val!r} candidate={c_val!r}"
        elif b_err is not None and c_err is not None:
            if type(b_err) is not type(c_err):
                case.ok = False
                case.message = (
                    f"exception_type_mismatch "
                    f"{type(b_err).__name__} vs {type(c_err).__name__}"
                )
            else:
                case.message = "both_raised_same_type"
        else:
            case.ok = False
            case.message = (
                f"exception_asymmetry baseline={case.baseline_error or 'ok'} "
                f"candidate={case.candidate_error or 'ok'}"
            )

        if not case.ok:
            result.mismatches += 1
            result.equivalent = False
        result.cases.append(case)

    return result


def format_diff_summary(result: DifferentialResult) -> str:
    if result.equivalent:
        return f"differential OK ({result.compared} cases)"
    return (
        f"differential FAIL mismatches={result.mismatches}/{result.compared} "
        f"first={result.cases[0].message if result.cases else ''}"
    )
