"""Tier-2 scientific invariants: optimize physics without breaking physics.

An invariant is a property of the *entrypoint's behaviour* that must survive
optimization even though no unit test asserts it directly — energy that must
not be created, mass that must balance, a curve that must stay monotonic, a
result that must stay finite.

Implementation: each invariant compiles to a zero-argument checker function
that is appended to the candidate module and executed as a normal test case by
``bench.measure``. That keeps the whole thing sandboxed and stdlib-only, and
it means an invariant failure looks exactly like a test failure to the runner.

Mapping to the repo's existing Scientific Mode
(``muta_ext/scientific/invariants.py``): the same physical properties, but
expressed as black-box probes over the entrypoint so they can be attached to
third-party benchmark tasks (EffiBench+) rather than to MutaLambda-native
scientific targets.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence, Tuple

from bench.spec import BenchTask

INVARIANT_NAMES = (
    "custom",
    "determinism",
    "non_negative",
    "bounded",
    "finite",
    "monotonic",
    "mass_balance",
    "energy_conservation",
    "perturbation_stability",
    "idempotent",
)

_PRELUDE = '''

# ── MutaLambda benchmark invariant harness (appended, not part of the task) ──
def _muta_inv_flatten(value):
    if isinstance(value, dict):
        out = []
        for k in sorted(value, key=repr):
            out.extend(_muta_inv_flatten(value[k]))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for v in value:
            out.extend(_muta_inv_flatten(v))
        return out
    return [value]


def _muta_inv_numbers(value):
    return [float(v) for v in _muta_inv_flatten(value)
            if isinstance(v, (int, float)) and not isinstance(v, bool)]
'''


def _probes(task: BenchTask, params: Dict[str, Any], limit: int = 6) -> List[List[Any]]:
    probes = params.get("probes")
    if probes:
        return [[list(p.get("args", p)), dict(p.get("kwargs", {}))] if isinstance(p, dict)
                else [list(p), {}] for p in probes]
    calls = task.workload.normalised_calls()[:limit]
    if calls:
        return calls
    return [[list(tc.get("args", [])), dict(tc.get("kwargs", {}))] for tc in task.all_tests[:limit]]


def _emit(name: str, task: BenchTask, params: Dict[str, Any]) -> str:
    ep = task.entrypoint
    probes = json.dumps(_probes(task, params))
    tol = float(params.get("tol", 1e-9))
    fn = f"_muta_inv_{name}"

    if name == "custom":
        # Suite-provided predicate. Must be a body that returns True/False and
        # may call the entrypoint. Used where correctness IS feasibility
        # (tier-3 heuristic discovery), so the check cannot be a fixed expected
        # value.
        body = "\n" + params.get("code", "    return True").rstrip()
    elif name == "determinism":
        body = f'''
    for args, kwargs in {probes}:
        a = {ep}(*args, **kwargs)
        b = {ep}(*args, **kwargs)
        if repr(a) != repr(b):
            return False
    return True'''
    elif name == "non_negative":
        body = f'''
    for args, kwargs in {probes}:
        for v in _muta_inv_numbers({ep}(*args, **kwargs)):
            if v < -{tol}:
                return False
    return True'''
    elif name == "finite":
        body = f'''
    import math
    for args, kwargs in {probes}:
        for v in _muta_inv_numbers({ep}(*args, **kwargs)):
            if math.isnan(v) or math.isinf(v):
                return False
    return True'''
    elif name == "bounded":
        lo = float(params.get("low", 0.0))
        hi = float(params.get("high", 1.0))
        body = f'''
    for args, kwargs in {probes}:
        for v in _muta_inv_numbers({ep}(*args, **kwargs)):
            if v < {lo} - {tol} or v > {hi} + {tol}:
                return False
    return True'''
    elif name == "monotonic":
        idx = int(params.get("arg_index", 0))
        direction = str(params.get("direction", "non_decreasing"))
        cmp_ = "<" if direction == "non_decreasing" else ">"
        body = f'''
    seq = sorted({probes}, key=lambda p: p[0][{idx}])
    prev = None
    for args, kwargs in seq:
        vals = _muta_inv_numbers({ep}(*args, **kwargs))
        cur = sum(vals)
        if prev is not None and cur {cmp_} prev - {tol}:
            return False
        prev = cur
    return True'''
    elif name in {"mass_balance", "energy_conservation"}:
        # Total of the output must match the total the input carries in.
        key = params.get("total_key")
        expr = f"sum(_muta_inv_numbers(out.get({key!r})))" if key else "sum(_muta_inv_numbers(out))"
        in_expr = params.get("input_total_expr", "sum(_muta_inv_numbers(args))")
        rel = float(params.get("rel_tol", 1e-6))
        body = f'''
    for args, kwargs in {probes}:
        out = {ep}(*args, **kwargs)
        total_out = {expr}
        total_in = {in_expr}
        scale = max(1.0, abs(total_in))
        if abs(total_out - total_in) / scale > {rel}:
            return False
    return True'''
    elif name == "perturbation_stability":
        eps = float(params.get("epsilon", 1e-6))
        gain = float(params.get("max_gain", 1e3))
        idx = int(params.get("arg_index", 0))
        body = f'''
    for args, kwargs in {probes}:
        base = args[{idx}]
        if not isinstance(base, (int, float)) or isinstance(base, bool):
            continue
        a0 = sum(_muta_inv_numbers({ep}(*args, **kwargs)))
        pert = list(args)
        pert[{idx}] = base * (1.0 + {eps}) + {eps}
        a1 = sum(_muta_inv_numbers({ep}(*pert, **kwargs)))
        denom = abs(base) * {eps} + {eps}
        if abs(a1 - a0) / denom > {gain}:
            return False
    return True'''
    elif name == "idempotent":
        body = f'''
    for args, kwargs in {probes}:
        once = {ep}(*args, **kwargs)
        twice = {ep}(once) if not kwargs else {ep}(once, **kwargs)
        if repr(once) != repr(twice):
            return False
    return True'''
    else:
        raise ValueError(f"unknown invariant: {name}")

    indented = "\n".join(
        ("    " + line) if line.strip() else line for line in body.splitlines()
    )
    return f'''

def {fn}():
    try:{indented}
    except Exception:
        return False
'''


def build_invariant_module(code: str, task: BenchTask) -> Tuple[str, List[Dict[str, Any]]]:
    """Return ``(code_with_checkers, invariant_test_cases)``.

    The returned tests are ordinary ``bench.measure`` test dicts, so invariant
    violations are reported through the same channel as correctness failures.
    """
    if not task.invariants:
        return code, []
    params_all: Dict[str, Dict[str, Any]] = task.metadata.get("invariant_params") or {}
    chunks = [code, _PRELUDE]
    tests: List[Dict[str, Any]] = []
    for name in task.invariants:
        if name not in INVARIANT_NAMES:
            continue
        chunks.append(_emit(name, task, params_all.get(name, {})))
        tests.append({
            "function": f"_muta_inv_{name}",
            "args": [],
            "expected": True,
            "comparison": "equal",
            "invariant": name,
        })
    return "\n".join(chunks), tests


def summarise(tests: Sequence[Dict[str, Any]], failures: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Map driver failures back onto invariant names for the report."""
    failed_idx = {int(f.get("index", -1)) for f in failures}
    broken = [t.get("invariant") for i, t in enumerate(tests) if i in failed_idx]
    return {
        "checked": [t.get("invariant") for t in tests],
        "violated": [b for b in broken if b],
        "all_hold": not broken,
    }
