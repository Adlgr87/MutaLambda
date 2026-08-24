"""HumanEval (OpenAI, MIT license) -> MutaLambda declarative test format.

AST-parses each task's canonical_solution trailing `check(...)` block and
converts every assert into {function, args, expected, comparison} cases.

Handled patterns:
    check(candidate(a, b) == expected)            -> comparison: equal/float_close
    check(candidate(...) != wrong)                -> skipped (negative asserts)
    check(abs(candidate(x) - y) < tol)            -> comparison: float_close
    check(candidate(...) in container)            -> comparison: contains

Usage:
    python3 he_convert.py    # writes data/humaneval_cases.json
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from textwrap import dedent

HERE = Path(__file__).parent
RAW_PATH = HERE / "data" / "HumanEval.jsonl"
OUT_PATH = HERE / "data" / "humaneval_cases.json"


def _literal(node: ast.AST):
    """Evaluate a pure-literal expression into a Python object (type-exact)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_literal(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {_literal(k): _literal(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Set):
        return {_literal(e) for e in node.elts}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _literal(node.operand)
        if isinstance(v, (int, float)):
            return -v if isinstance(node.op, ast.USub) else v
    return None


def _all_literals(nodes) -> bool:
    for n in nodes:
        v = _literal(n)
        if v is None and not (isinstance(n, ast.Constant) and n.value is None):
            return False
    return True


def _is_floaty(obj) -> bool:
    if isinstance(obj, float):
        return True
    if isinstance(obj, (list, tuple)):
        return any(_is_floaty(o) for o in obj)
    return False


class _Checker(ast.NodeVisitor):
    """Collect (function, args, expected, comparison) tuples from check() calls."""

    def __init__(self, entry_point: str):
        self.entry_point = entry_point
        self.cases: list[dict] = []
        self.skipped = 0

    # --- pattern dispatch --------------------------------------------------
    def visit_Assert(self, node: ast.Assert) -> None:
        if node.msg is not None:
            self.skipped += 1
            return
        inner = node.test
        result = self._eq(inner) or self._abs_lt(inner) or self._contains(inner)
        if result is None:
            self.skipped += 1
        elif result.get("__skip__"):
            self.skipped += 1
        else:
            self.cases.append(result)

    def visit_Expr(self, node: ast.Expr) -> None:
        call = node.value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "check"
            and len(call.args) == 1
        ):
            self.skipped += 1
            return
        inner = call.args[0]
        result = self._eq(inner) or self._abs_lt(inner) or self._contains(inner)
        if result is None:
            self.skipped += 1
        elif result.get("__skip__"):
            self.skipped += 1
        else:
            self.cases.append(result)

    def _mk(self, fn_name, arg_nodes, expected, comparison):
        return {
            "function": fn_name,
            "args": [_literal(a) for a in arg_nodes],
            "expected": expected,
            "comparison": comparison,
        }

    # --- check(candidate(args) == expected) ---------------------------------
    def _eq(self, inner):
        if not (isinstance(inner, ast.Compare) and len(inner.ops) == 1):
            return None
        op = inner.ops[0]
        if isinstance(op, ast.Eq):
            left, right = inner.left, inner.comparators[0]
        elif isinstance(op, ast.NotEq):
            return {"__skip__": True}
        else:
            return None
        fn_name, arg_nodes, exp_node = self._candidate_call(left, right)
        if fn_name is None:
            return None
        if not _all_literals(arg_nodes):
            return None
        expected = _literal(exp_node)
        if expected is None and not (
            isinstance(exp_node, ast.Constant) and exp_node.value is None
        ):
            return None
        floaty = _is_floaty(expected) or any(
            _is_floaty(_literal(a)) for a in arg_nodes
        )
        comparison = "float_close" if floaty else "equal"
        return self._mk(fn_name, arg_nodes, expected, comparison)

    # --- check(abs(candidate(...) - x) < tol) -------------------------------
    def _abs_lt(self, inner):
        if not (
            isinstance(inner, ast.Compare)
            and len(inner.ops) == 1
            and isinstance(inner.ops[0], (ast.Lt, ast.LtE))
        ):
            return None
        left = inner.left
        if not (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Name)
            and left.func.id == "abs"
            and left.args
        ):
            return None
        diff = left.args[0]
        if not (isinstance(diff, ast.BinOp) and isinstance(diff.op, ast.Sub)):
            return None
        cand_side, exp_node = diff.left, diff.right
        fn_name, arg_nodes = self._bare_candidate(cand_side)
        if fn_name is None:
            fn_name, arg_nodes = self._bare_candidate(diff.right)
            exp_node = diff.left
        if fn_name is None:
            return None
        if not _all_literals(arg_nodes):
            return None
        expected = _literal(exp_node)
        if expected is None and not (
            isinstance(exp_node, ast.Constant) and exp_node.value is None
        ):
            return None
        return self._mk(fn_name, arg_nodes, expected, "float_close")

    # --- check(candidate(...) in container) ---------------------------------
    def _contains(self, inner):
        if not (isinstance(inner, ast.Compare) and len(inner.ops) == 1):
            return None
        op = inner.ops[0]
        if isinstance(op, ast.In):
            elem, container = inner.left, inner.comparators[0]
        elif isinstance(op, ast.NotIn):
            return {"__skip__": True}
        else:
            return None
        fn_name, arg_nodes = self._bare_candidate(elem)
        if fn_name is None:
            return None
        if not _all_literals(arg_nodes):
            return None
        container_v = _literal(container)
        if container_v is None:
            return None
        # runner 'contains' semantics: expected in got  => expected=container
        return self._mk(fn_name, arg_nodes, container_v, "contains")

    # --- helpers -------------------------------------------------------------
    def _candidate_call(self, left, right):
        """Return (fn_name, arg_nodes, expected_node) for candidate(...)==exp."""
        if isinstance(left, ast.Call):
            fn_name, arg_nodes = self._bare_candidate(left)
            return fn_name, arg_nodes, right
        if isinstance(right, ast.Call):
            fn_name, arg_nodes = self._bare_candidate(right)
            return fn_name, arg_nodes, left
        return None, None, None

    def _bare_candidate(self, node):
        if not isinstance(node, ast.Call):
            return None, None
        fn = node.func
        # HumanEval passes the solution as parameter named 'candidate';
        # accept the entry-point name too for robustness.
        if isinstance(fn, ast.Name) and fn.id in ("candidate", self.entry_point):
            return self.entry_point, list(node.args)
        return None, None


def extract_cases(entry_point: str, test_block: str):
    tree = ast.parse(dedent(test_block))
    func_def = next((n for n in tree.body if isinstance(n, ast.FunctionDef)), None)
    if func_def is None:
        raise ValueError("no function def found")
    checker = _Checker(entry_point)
    for stmt in func_def.body:
        checker.visit(stmt)
    cases = [c for c in checker.cases if not c.get("__skip__")]
    return cases, checker.skipped


def main() -> int:
    if not RAW_PATH.exists():
        print("missing data/HumanEval.jsonl", file=sys.stderr)
        return 1
    out = []
    total_cases = 0
    zero_case_tasks = []
    total_skipped = 0
    for line in RAW_PATH.read_text().splitlines():
        if not line.strip():
            continue
        task = json.loads(line)
        try:
            cases, skipped = extract_cases(task["entry_point"], task["test"])
        except Exception as exc:  # noqa: BLE001
            print(f"WARN {task['task_id']}: {exc}", file=sys.stderr)
            cases, skipped = [], 0
        if not cases:
            zero_case_tasks.append(task["task_id"])
        total_cases += len(cases)
        total_skipped += skipped
        out.append(
            {
                "task_id": task["task_id"],
                "prompt": task["prompt"],
                "entry_point": task["entry_point"],
                "cases": cases,
                "skipped_asserts": skipped,
            }
        )
    OUT_PATH.write_text(json.dumps(out))
    print(
        f"{len(out)} tasks | {total_cases} converted cases | "
        f"{total_skipped} asserts skipped | "
        f"{len(zero_case_tasks)} tasks without convertible cases"
    )
    if zero_case_tasks:
        print("zero-case:", ", ".join(zero_case_tasks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
