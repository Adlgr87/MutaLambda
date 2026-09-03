"""
D4 — Three-layer correctness verification for benchmark candidates.

verify_candidate(original, mutated, test_cases) -> VerificationResult
  Layer 1: existing unit tests on mutated code (differential_test over test_cases)
  Layer 2: differential testing with 1000 random inputs vs original
  Layer 3: property-based testing with Hypothesis on declared invariants
"""
from __future__ import annotations

import inspect
import random
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from differential import differential_test, DifferentialResult
from comparison import compare_values

try:
    from hypothesis import given, settings, strategies as st, Phase
    from hypothesis.errors import InvalidArgument
    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


@dataclass
class VerificationResult:
    ok: bool
    layer1_ok: bool = False
    layer2_ok: bool = False
    layer3_ok: bool = False
    layer1_msg: str = ""
    layer2_msg: str = ""
    layer3_msg: str = ""
    differential_trials: int = 0
    divergences: int = 0
    max_abs_error: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "layer1_ok": self.layer1_ok,
            "layer2_ok": self.layer2_ok,
            "layer3_ok": self.layer3_ok,
            "layer1_msg": self.layer1_msg,
            "layer2_msg": self.layer2_msg,
            "layer3_msg": self.layer3_msg,
            "differential_trials": self.differential_trials,
            "divergences": self.divergences,
            "max_abs_error": self.max_abs_error,
            "details": self.details,
        }


def _load_function(code: str, function_name: str) -> Callable:
    """Exec source code and return the callable by name."""
    namespace: Dict[str, Any] = {"__name__": "__verify__"}
    exec(compile(code, "<verify_candidate>", "exec"), namespace, namespace)  # noqa: S102
    fn = namespace.get(function_name)
    if not callable(fn):
        raise NameError(f"function not found: {function_name}")
    return fn


def _infer_arg_generators(sample_args: List[Any]) -> List[Callable[[random.Random], Any]]:
    """Build a per-position random-arg generator from sample argument values.

    Preserves type (list/ndarray/float/str/int/tuple/callable) and roughly the
    value range/shape seen in the declared test cases, so differential fuzzing
    exercises the function with realistic inputs.
    """
    import numpy as np

    def _gen_float(v, rng):
        base = float(v) if _is_number(v) else 0.0
        span = max(abs(base), 1.0)
        return rng.uniform(-span, span)

    def _make(v):
        if _is_number(v):
            return (lambda rng: _gen_float(v, rng))
        if isinstance(v, (list, tuple, np.ndarray)):
            seq = list(v)
            return (lambda rng: _seq_like(seq, rng))
        if isinstance(v, str):
            chars = v if v else "abc "
            return (lambda rng: "".join(rng.choice(chars) for _ in range(rng.randint(1, max(len(chars), 4)))))
        if callable(v):  # e.g. a lambda in test args (newton_raphson) — pass through
            return (lambda rng: v)
        return (lambda rng: rng.uniform(-100.0, 100.0))

    generators = []
    for v in sample_args:
        if isinstance(v, (list, tuple, np.ndarray)):
            generators.append(_make(list(v)))
        else:
            generators.append(_make(v))
    return generators


def _seq_like(sample: list, rng: random.Random) -> Any:
    import numpy as np
    if len(sample) == 0:
        return np.array([], dtype=float)
    if _is_number(sample[0]):
        vals = [rng.uniform(min(float(min(sample)), -1.0), max(float(max(sample)), 1.0))
                for _ in range(rng.randint(0, max(len(sample) * 2, 1)))]
        return np.array(vals, dtype=float)
    if isinstance(sample[0], (list, tuple)):
        rows = rng.randint(0, max(len(sample), 1))
        cols = max(len(sample[0]), 1)
        return np.random.uniform(-10, 10, size=(rows, cols)).tolist()
    return sample[:]


def _is_number(v) -> bool:
    try:
        float(v); return True
    except (TypeError, ValueError):
        return False


def _signature_args(fn: Callable, rng: random.Random, sample_args: Optional[List[Any]] = None) -> Tuple[tuple, dict]:
    """Generate random args. Prefer structure inferred from sample_args (test cases)."""
    if sample_args:
        gens = _infer_arg_generators(sample_args)
        return tuple(g(rng) for g in gens), {}
    # Fallback: signature-based heuristic
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        sig = None
    args: List[Any] = []
    if sig is None:
        return args, {}
    for name, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            ann = param.annotation
            low = str(ann).lower() if not isinstance(ann, type) else ann.__name__
            if "float" in low or "int" in low:
                args.append(rng.uniform(-100.0, 100.0))
            elif "str" in low:
                args.append("".join(rng.choice("abc ") for _ in range(rng.randint(1, 8))))
            elif "list" in low:
                args.append([rng.uniform(-10.0, 10.0) for _ in range(rng.randint(0, 10))])
            else:
                args.append(rng.uniform(-100.0, 100.0))
    return tuple(args), {}


def _approx_equal(a: Any, b: Any, rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> bool:
    """Deep approximate equality for nested numbers/arrays/lists."""
    try:
        import numpy as np
        if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
            return bool(np.allclose(np.asarray(a), np.asarray(b), rtol=rel_tol, atol=abs_tol))
    except ImportError:
        pass
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(_approx_equal(x, y, rel_tol, abs_tol) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
    try:
        return bool(math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol))
    except (TypeError, ValueError):
        return a == b


def _same_exception_type(orig_exc: Optional[BaseException], mut_exc: Optional[BaseException]) -> bool:
    if orig_exc is None and mut_exc is None:
        return True
    if orig_exc is not None and mut_exc is not None:
        return type(orig_exc) is type(mut_exc)
    return False


def verify_candidate(
    original: str,
    mutated: str,
    test_cases: List[Dict[str, Any]],
    *,
    function_name: str,
    random_trials: int = 1000,
    invariants: Optional[List[str]] = None,
    input_strategy: Optional[str] = None,
    sample_args: Optional[List[Any]] = None,
    seed: int = 42,
) -> VerificationResult:
    """Run all three verification layers on mutated code.

    Parameters
    ----------
    original, mutated : str
        Full source code of the original and mutated implementations.
    test_cases : list[dict]
        Declarative test cases (Layer 1 + Layer 2 baseline via differential_test).
    function_name : str
        Name of the function under test.
    random_trials : int
        Number of random differential inputs (Layer 2). Default 1000 per D4 spec.
    invariants : list[str]
        Hypothesis-style property invariant strings (Layer 3).
    input_strategy : str
        Hypothesis strategy expression string for random input generation.
    seed : int
        RNG seed for reproducibility.
    """
    result = VerificationResult(ok=False)
    rng = random.Random(seed)

    # ---- Layer 1: existing unit tests on mutated code ----
    l1 = differential_test(original, mutated, test_cases, default_function=function_name)
    result.layer1_ok = l1.equivalent
    result.layer1_msg = (
        f"differential OK ({l1.compared} cases, {l1.mismatches} mismatches)"
        if l1.equivalent else
        f"FAILED {l1.mismatches}/{l1.compared} cases: {l1.cases[0].message if l1.cases else ''}"
    )
    if not l1.equivalent:
        result.ok = False
        return result

    # ---- Layer 2: differential testing with random inputs ----
    # Infer realistic arg structure from test_cases if not explicitly provided.
    if sample_args is None and test_cases:
        sample_args = list(test_cases[0].get("args", []))
    orig_fn = _load_function(original, function_name)
    try:
        mut_fn = _load_function(mutated, function_name)
    except Exception as exc:
        result.layer2_ok = False
        result.layer2_msg = f"mutated function failed to load: {exc}"
        return result

    divergences = 0
    max_err = 0.0
    checked = 0
    for _ in range(random_trials):
        args, kwargs = _signature_args(orig_fn, rng, sample_args)
        orig_val, orig_exc = None, None
        mut_val, mut_exc = None, None
        try:
            orig_val = orig_fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            orig_exc = exc
        try:
            mut_val = mut_fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            mut_exc = exc

        checked += 1
        if not _same_exception_type(orig_exc, mut_exc):
            divergences += 1
            continue
        if orig_exc is None and mut_exc is None:
            if not _approx_equal(orig_val, mut_val):
                divergences += 1
                # track magnitude of divergence
                try:
                    err = abs(float(orig_val) - float(mut_val))
                    max_err = max(max_err, err)
                except (TypeError, ValueError):
                    pass

    result.differential_trials = checked
    result.divergences = divergences
    result.max_abs_error = max_err
    result.layer2_ok = divergences == 0
    result.layer2_msg = (
        f"OK ({checked} random trials, 0 divergences)"
        if divergences == 0 else
        f"FAILED {divergences}/{checked} divergences, max_abs_error={max_err}"
    )
    if not result.layer2_ok:
        result.ok = False
        return result

    # ---- Layer 3: property-based testing with Hypothesis ----
    result.layer3_ok = True
    result.layer3_msg = "skipped"
    if not HAS_HYPOTHESIS:
        result.layer3_msg = "hypothesis not installed — layer skipped"
        result.ok = result.layer1_ok and result.layer2_ok
        return result

    invariants = invariants or []
    if not invariants:
        result.layer3_msg = "no invariants declared — layer skipped"
        result.ok = result.layer1_ok and result.layer2_ok
        return result

    failures: List[str] = []
    for inv in invariants:
        strat_src = input_strategy or "st.floats(min_value=-100, max_value=100)"
        try:
            strat = eval(strat_src, {"st": st, "np": __import__("numpy"), "math": math})  # noqa: S307
        except Exception as exc:
            failures.append(f"strategy_error: {exc}")
            continue
        # Invariant is a boolean Python expression over input `x` and `out` (the return value).
        g: Dict[str, Any] = {"st": st, "math": math, "np": __import__("numpy"),
                             function_name: mut_fn, "__builtins__": __builtins__}
        # Call with correct unpacking: single-param fn gets fn(x); multi-param gets fn(*x).
        nparams = sum(1 for p in inspect.signature(mut_fn).parameters.values()
                      if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
        call_expr = function_name + "(*x)" if nparams > 1 else function_name + "(x)"
        test_fn_src = (
            "def _check(x):\n"
            "    try:\n"
            "        out = " + call_expr + "\n"
            "    except Exception:\n"
            "        return True\n"
            "    return bool(" + inv + ")\n"
        )
        try:
            exec(test_fn_src, g, g)
            _check = g["_check"]
        except Exception as exc:
            failures.append(f"compile_error: {exc}")
            continue

        # Define the Hypothesis test as a module-level function (no defaults) so
        # @given can be applied, then invoke it.
        _test_ns: Dict[str, Any] = {"_check": _check, "__builtins__": __builtins__}
        exec(
            "def _hypothesis_test(x):\n    assert _check(x)\n",
            _test_ns, _test_ns,
        )
        _hypothesis_test = _test_ns["_hypothesis_test"]
        _hypothesis_test = given(strat)(  # type: ignore
            settings(max_examples=200, deadline=None, phases=[Phase.generate],
                     suppress_health_check=[])(_hypothesis_test)
        )
        try:
            _hypothesis_test()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"invariant_fail: {inv!r}: {exc}")

    if failures:
        result.layer3_ok = False
        result.layer3_msg = f"FAILED: {failures[:2]}"
        result.ok = False
    else:
        result.layer3_ok = True
        result.layer3_msg = "OK (Hypothesis property tests passed)"
        result.ok = True
    return result
