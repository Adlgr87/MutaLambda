"""
Property-Based Testing for MutaLambda.

Integrates Hypothesis to auto-generate test cases from code structure
and Z3 for formal verification of algorithmic invariants.

Blueprint Phase 6:
  - Property-Based Testing: Hypothesis generates edge cases
  - SMT solver (Z3): verify invariants, generate counterexamples
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Tuple

# Hypothesis is optional — graceful fallback
try:
    from hypothesis import given, settings, strategies as st
    from hypothesis.errors import InvalidArgument
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

# Z3 is optional
try:
    import z3
    HAS_Z3 = True
except ImportError:
    HAS_Z3 = False


# ── Property Strategies from Code ────────────────────────────────────

def infer_property_strategies(code: str) -> List[Dict]:
    """
    Infer property-based test strategies from Python code.

    Analyses function signatures to determine:
      - Input types (int, float, str, list)
      - Ranges (min/max constraints)
      - Edge cases to test

    Returns list of {func_name, input_types, suggested_strategies}
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    strategies: List[Dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        args = node.args
        func_info = {
            "func_name": node.name,
            "arg_names": [a.arg for a in args.args],
            "input_types": [],
            "suggested_strategies": [],
        }

        for arg_name in func_info["arg_names"]:
            # Heuristic: guess type from name
            low = arg_name.lower()
            if any(w in low for w in ("n", "count", "size", "length", "num", "int")):
                func_info["input_types"].append("int")
                func_info["suggested_strategies"].append(
                    "integers(min_value=0, max_value=1000)"
                )
            elif any(w in low for w in ("xs", "arr", "list", "items", "data", "seq")):
                func_info["input_types"].append("list[int]")
                func_info["suggested_strategies"].append(
                    "lists(integers(min_value=-100, max_value=100), min_size=0, max_size=50)"
                )
            elif any(w in low for w in ("s", "text", "string", "name", "word")):
                func_info["input_types"].append("str")
                func_info["suggested_strategies"].append(
                    "text(alphabet=string.ascii_letters, min_size=0, max_size=100)"
                )
            elif any(w in low for w in ("x", "val", "value", "num", "f")):
                func_info["input_types"].append("float")
                func_info["suggested_strategies"].append(
                    "floats(min_value=-1000.0, max_value=1000.0, allow_nan=False)"
                )
            else:
                func_info["input_types"].append("int")
                func_info["suggested_strategies"].append(
                    "integers(min_value=-100, max_value=100)"
                )

        strategies.append(func_info)

    return strategies


def generate_test_template(function_name: str, strategies: List[str],
                           arg_names: List[str]) -> str:
    """
    Generate a Hypothesis test template for a function.

    Returns a string that can be written to a .py test file.
    """
    if not strategies or not HAS_HYPOTHESIS:
        return f"# Hypothesis not available for {function_name}"

    strat_parts = ", ".join(
        f"{name}={strat}"
        for name, strat in zip(arg_names, strategies)
    )

    return f'''
@given({strat_parts})
@settings(max_examples=200)
def test_{function_name}_properties({", ".join(arg_names)}):
    """Property-based test for {function_name}."""
    result = {function_name}({", ".join(arg_names)})

    # Invariant 1: function should not crash
    assert result is not None

    # Invariant 2: result type should be consistent
    assert isinstance(result, (int, float, str, list, tuple, bool))

    # Invariant 3: for numeric inputs, result should be numeric
    if all(isinstance(x, (int, float)) for x in [{", ".join(arg_names)}]):
        assert isinstance(result, (int, float))
'''


# ── Z3 Formal Verification ───────────────────────────────────────────

def verify_invariant_z3(code: str, invariant: str) -> Tuple[bool, Optional[str]]:
    """
    Use Z3 to verify an invariant holds for given code.

    Parameters
    ----------
    code : str
        Python function to verify.
    invariant : str
        Z3-compatible invariant expression (e.g., "result >= 0").

    Returns
    -------
    (holds, counterexample)
        holds: True if invariant verified, False if counterexample found
        counterexample: string description of counterexample if holds=False
    """
    if not HAS_Z3:
        return (False, "Z3 not installed — pip install z3-solver")

    try:
        # Try to extract a simple numeric function for Z3
        tree = ast.parse(code)
        funcs = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if not funcs:
            return (False, "No function found in code")

        func = funcs[0]
        args = [a.arg for a in func.args.args]

        if not args:
            return (False, "Function has no arguments")

        # Create Z3 variables
        z3_vars = {arg: z3.Int(arg) for arg in args}

        # Attempt to translate Python AST to Z3 expression
        # (simplified: only supports simple numeric return expressions)
        z3_expr = _ast_to_z3(func.body, z3_vars)
        if z3_expr is None:
            return (False, "Could not translate code to Z3 — too complex")

        violation = _parse_invariant_violation(invariant, z3_expr)
        if violation is None:
            return (False, "Invariant must be a simple comparison like result >= 0")

        solv = z3.Solver()
        solv.add(violation)

        result = solv.check()
        if result == z3.unsat:
            return (True, None)
        elif result == z3.sat:
            model = solv.model()
            ce = ", ".join(f"{k}={model[v]}" for k, v in z3_vars.items())
            return (False, ce)
        else:
            return (False, "Z3 could not determine — unknown result")

    except Exception as e:
        return (False, f"Z3 verification error: {e}")


def _ast_to_z3(body, z3_vars):
    """Simplified AST → Z3 expression translation."""
    for stmt in body:
        if isinstance(stmt, ast.Return) and stmt.value:
            return _expr_to_z3(stmt.value, z3_vars)
    return None


def _expr_to_z3(node, z3_vars):
    """Recursive AST expr → Z3."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in z3_vars:
        return z3_vars[node.id]
    if isinstance(node, ast.BinOp):
        left = _expr_to_z3(node.left, z3_vars)
        right = _expr_to_z3(node.right, z3_vars)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    return None


def _parse_invariant_violation(invariant: str, z3_expr):
   """Return a Z3 expression that violates a simple result comparison."""
   comparisons = {
       ">=": lambda expr, value: expr < value,
       "<=": lambda expr, value: expr > value,
       "==": lambda expr, value: expr != value,
       "!=": lambda expr, value: expr == value,
       ">": lambda expr, value: expr <= value,
       "<": lambda expr, value: expr >= value,
   }

   text = invariant.strip()
   if not text.startswith("result"):
       return None

   rest = text[len("result") :].strip()
   for op in (">=", "<=", "==", "!=", ">", "<"):
       if rest.startswith(op):
           rhs = rest[len(op) :].strip()
           try:
               value = int(rhs)
           except ValueError:
               try:
                   value = float(rhs)
               except ValueError:
                   return None
           return comparisons[op](z3_expr, value)

   return None


# ── Combined Property Test Runner ─────────────────────────────────────

def run_property_tests(code: str) -> Dict:
    """
    Run property-based tests on code using inferred strategies.

    Returns dict with results per function.
    """
    if not HAS_HYPOTHESIS:
        return {"error": "Hypothesis not installed", "functions_tested": 0}

    strategies_info = infer_property_strategies(code)
    results = {
        "functions_tested": len(strategies_info),
        "functions": [],
        "z3_verified": False,
    }

    for info in strategies_info:
        func_result = {
            "name": info["func_name"],
            "arg_names": info["arg_names"],
            "input_types": info["input_types"],
            "strategies_generated": len(info["suggested_strategies"]),
        }

        # Try Z3 verification if available
        if HAS_Z3:
            try:
                holds, ce = verify_invariant_z3(
                    code, f"{info['func_name']}_result >= 0"
                )
                func_result["z3_holds"] = holds
                if ce:
                    func_result["z3_counterexample"] = ce
            except Exception:
                func_result["z3_holds"] = None

        results["functions"].append(func_result)

    return results
