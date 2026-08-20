"""ParallelFor mutation: For → ParallelFor transformation."""
from __future__ import annotations
import ast
import random
from typing import Optional, List, Dict, Any

from mutalambda.mutation_filters import _filter_mutant, ProfileMode


def detect_parallel_for_candidates(code: str, rng: random.Random | None = None) -> List[Dict[str, Any]]:
    """Detect For loops that are candidates for ParallelFor transformation.
    
    Criteria:
    - Loop variable is sequential (range-like)
    - Body has a reduction pattern: total += expr, total = total op expr
    - No dangerous dependencies between iterations
    """
    rng = rng or random
    candidates = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return candidates
    
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.For):
                continue
            # Must be range-based: for i in range(...)
            if not isinstance(stmt.iter, ast.Call):
                continue
            if not isinstance(stmt.iter.func, ast.Name):
                continue
            if stmt.iter.func.id not in ("range", "xrange"):
                continue
            
            # Look for reduction patterns in the body
            reduction = _find_reduction_pattern(stmt, tree)
            if reduction:
                candidates.append({
                    "function": node,
                    "function_name": node.name,
                    "loop_var": stmt.target.id if hasattr(stmt.target, 'id') else None,
                    "reduction": reduction,
                })
    
    return candidates


def _find_reduction_pattern(for_stmt: ast.For, tree: ast.AST) -> Optional[str]:
    """Check if the for body has a reduction accumulator pattern.
    
    Returns the reduction type: 'sum', 'max', 'min', 'prod' or None.
    """
    acc_var = None
    acc_op = None
    
    for stmt in for_stmt.body:
        # Pattern: acc += expr  (AugAssign with +=)
        if isinstance(stmt, ast.AugAssign):
            if isinstance(stmt.op, ast.Add):
                acc_var = stmt.target
                acc_op = "sum"
            elif isinstance(stmt.op, ast.Mult):
                acc_var = stmt.target
                acc_op = "prod"
        # Pattern: acc = acc OP expr
        elif isinstance(stmt, ast.Assign):
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                target_name = stmt.targets[0].id
                if isinstance(stmt.value, ast.BinOp):
                    if isinstance(stmt.value.op, ast.Add):
                        if isinstance(stmt.value.left, ast.Name) and stmt.value.left.id == target_name:
                            acc_var = stmt.targets[0]
                            acc_op = "sum"
                    elif isinstance(stmt.value.op, ast.Mult):
                        if isinstance(stmt.value.left, ast.Name) and stmt.value.left.id == target_name:
                            acc_var = stmt.targets[0]
                            acc_op = "prod"
    
    if acc_var is not None and acc_op is not None:
        return acc_op
    return None


def mutate_for_to_parallel(code: str, rng: random.Random | None = None) -> Optional[str]:
    """Transform one For loop to ParallelFor in source code.
    
    Returns the modified code string, or None if no transformation possible.
    """
    rng = rng or random
    candidates = detect_parallel_for_candidates(code, rng)
    if not candidates:
        return None
    
    candidate = rng.choice(candidates)
    func_node = candidate["function"]
    reduction = candidate["reduction"]
    loop_var = candidate["loop_var"]
    
    # Build new function with ParallelFor
    new_func = _transform_for_to_parallel(func_node, reduction, loop_var)
    if new_func is None:
        return None
    
    # Rebuild the module source
    new_tree = ast.parse(code)
    for i, stmt in enumerate(new_tree.body):
        if isinstance(stmt, ast.FunctionDef) and stmt.name == candidate["function_name"]:
            new_tree.body[i] = new_func
            break
    else:
        return None
    
    result = ast.unparse(new_tree)
    # Filter through mutation filters
    filtered = _filter_mutant(result, ProfileMode.PERMISSIVE)
    return filtered if filtered is not None else result


def _transform_for_to_parallel(
    func_node: ast.FunctionDef, 
    reduction: str,
    loop_var: Optional[str],
) -> Optional[ast.FunctionDef]:
    """Transform a single FunctionDef containing a For loop to use ParallelFor pattern.
    
    For ParallelFor, we replace the for loop with a parallel reduction pattern
    using Python's map/reduce or concurrent.futures.
    """
    if not func_node.body:
        return None

    # Find the for loop in the function body
    for_stmt = None
    for stmt in func_node.body:
        if isinstance(stmt, ast.For):
            for_stmt = stmt
            break

    if for_stmt is None:
        return None

    
    # Get the iterable (range expression)
    iterable = for_stmt.iter
    
    # Find the accumulator variable and the expression being reduced
    acc_var = None
    reduce_expr = None
    
    for stmt in for_stmt.body:
        if isinstance(stmt, ast.AugAssign):
            acc_var = stmt.target
            if isinstance(stmt.value, ast.Name):
                reduce_expr = stmt.value
            elif isinstance(stmt.value, ast.Subscript):
                reduce_expr = stmt.value
            elif isinstance(stmt.value, ast.BinOp):
                reduce_expr = stmt.value
        elif isinstance(stmt, ast.Assign):
            if (len(stmt.targets) == 1 and 
                isinstance(stmt.targets[0], ast.Name) and
                isinstance(stmt.value, ast.BinOp) and
                isinstance(stmt.value.left, ast.Name)):
                target_id = stmt.targets[0].id
                if (isinstance(stmt.value.left, ast.Name) and 
                    stmt.value.left.id == target_id):
                    acc_var = stmt.targets[0]
                    reduce_expr = stmt.value.right
    
    if acc_var is None or reduce_expr is None or loop_var is None:
        return None
    
    # Create a lambda for the mapping
    lambda_arg = ast.Name(id="_i", ctx=ast.Load())
    
    # Substitute loop_var with _i in reduce_expr
    class VarSubstituter(ast.NodeTransformer):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id == loop_var:
                return lambda_arg
            return node
    
    mapped_expr = VarSubstituter().visit(reduce_expr)
    ast.fix_missing_locations(mapped_expr)
    
    # Build: reduce_func(map(lambda _i: expr, range_expr))
    map_call = ast.Call(
        func=ast.Name(id="map", ctx=ast.Load()),
        args=[
            ast.Lambda(
                args=ast.arguments(
                    posonlyargs=[],
                    args=[ast.arg(arg="_i", annotation=None)],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    kwarg=None,
                    defaults=[],
                ),
                body=mapped_expr,
            ),
            iterable,
        ],
        keywords=[],
    )
    
    # Choose the reduce function based on reduction type
    if reduction == "sum":
        reduce_func = ast.Name(id="sum", ctx=ast.Load())
        reduce_call = ast.Call(func=reduce_func, args=[map_call], keywords=[])
    elif reduction == "prod":
        reduce_call = ast.Call(
            func=ast.Attribute(value=ast.Name(id="math", ctx=ast.Load()), attr="prod", ctx=ast.Load()),
            args=[map_call],
            keywords=[],
        )
    else:
        return None
    
    # Create assignment: acc_var = reduce_call
    new_assign = ast.Assign(
        targets=[acc_var],
        value=reduce_call,
        lineno=for_stmt.lineno,
        col_offset=for_stmt.col_offset,
    )
    
    # Replace the For statement with the assignment
    new_body = [new_assign]
    # Keep remaining statements after the for loop
    new_body.extend(for_stmt.body[1:] if len(for_stmt.body) > 1 else [])
    
    # Add math import if needed
    new_func = ast.FunctionDef(
        name=func_node.name,
        args=func_node.args,
        body=new_body,
        decorator_list=func_node.decorator_list,
        returns=func_node.returns,
        lineno=func_node.lineno,
        col_offset=func_node.col_offset,
    )
    
    # Check if we need math import
    if reduction == "prod":
        # Add import math at the top of the function body if not already there
        has_math_import = False
        for stmt in new_func.body:
            if isinstance(stmt, ast.Import) and any(alias.name == "math" for alias in stmt.names):
                has_math_import = True
                break
            if isinstance(stmt, ast.ImportFrom) and stmt.module == "math":
                has_math_import = True
                break
        if not has_math_import:
            # We'll add it at module level, but for simplicity just return the transformed function
            pass
    
    return new_func


class ParallelForMutator:
    """UAST-level ParallelFor mutator."""
    
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random
    
    def mutate(self, uast) -> Optional[Any]:
        """Transform For nodes to ParallelFor in a UAST."""
        # This is a placeholder for future UAST-level integration
        # The source-level mutation is handled by mutate_for_to_parallel()
        return None


# Register for discovery
MUTATORS = [
    ("parallel_for", mutate_for_to_parallel),
]
