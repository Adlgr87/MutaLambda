"""CoreUAST → Python source emitter."""

import ast
from typing import Optional

from muta_ext.uast.core_uast import (
    CoreUAST,
    LiteralNode,
    Identifier,
    BinaryOp,
    UnaryOp,
    Call,
    Assign,
    If,
    For,
    While,
    Return,
    Function,
    ParallelFor,
    Comment,
    Opaque,
    Node,
    TryExcept,
    ExceptClause,
    StructDef,
    FieldDef,
    TypeAnnotation,
    MatchArm,
    Match,
    Reference,
)


class PythonEmitter:
    """Emit CoreUAST back to Python source code."""

    language = "python"

    @staticmethod
    def _join_expr(parts: list) -> str:
        """Join emitted expression fragments without leaking statement indent.

        ``Opaque`` fragments keep the leading indentation that belongs to the
        surrounding statement; when they are used *inside* an expression
        (``if <cond>:``, ``for x in <it>:`` ...) that indentation is noise.
        ``" ".join`` already flattens multi-line fragments, so stripping each
        part here only removes spurious leading whitespace.
        """
        return " ".join(part.strip() for part in parts)

    def can_emit(self, uast: CoreUAST) -> bool:
        """Check if UAST is for Python language."""
        return uast.language == "python"

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST to Python source."""
        lines = []
        for node in uast.body:
            lines.extend(self._emit_node(node, indent=0))
        return "\n".join(lines)

    def _emit_node(self, node: Optional[Node], indent: int = 0) -> list:  # noqa: C901
        """Emit a single node to source lines."""
        if node is None:
            return []
        indent_str = "    " * indent

        if isinstance(node, LiteralNode):
            return [repr(node.value)]
        if isinstance(node, Identifier):
            return [node.name]
        if isinstance(node, BinaryOp):
            left = self._join_expr(self._emit_node(node.left, indent))
            right = self._join_expr(self._emit_node(node.right, indent))
            return [f"{left} {node.op} {right}"]
        if isinstance(node, UnaryOp):
            operand = self._join_expr(self._emit_node(node.operand, indent))
            return [f"{node.op}{operand}"]
        if isinstance(node, Call):
            func = self._join_expr(self._emit_node(node.func, indent))
            args = ", ".join(self._join_expr(self._emit_node(a, indent)) for a in node.args)
            return [f"{func}({args})"]
        if isinstance(node, Assign):
            if isinstance(node.target, list):
                targets = ", ".join(
                    self._join_expr(self._emit_node(t, indent)) for t in node.target
                )
            else:
                targets = self._join_expr(self._emit_node(node.target, indent))
            value = self._join_expr(self._emit_node(node.value, indent))
            return [f"{indent_str}{targets} = {value}"]
        if isinstance(node, If):
            condition = self._join_expr(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}if {condition}:"]
            for n in node.then_body:
                lines.extend(self._emit_node(n, indent + 1))
            if node.else_body:
                lines.append(f"{indent_str}else:")
                for n in node.else_body:
                    lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, For):
            var = self._join_expr(self._emit_node(node.var, indent))
            iterable = self._join_expr(
                self._emit_node(node.iterable, indent)
            )  # BUGFIX: For.iterable
            lines = [f"{indent_str}for {var} in {iterable}:"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, While):
            condition = self._join_expr(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}while {condition}:"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, Return):
            if node.value:
                val = self._join_expr(self._emit_node(node.value, indent))
                return [f"{indent_str}return {val}"]
            return [f"{indent_str}return"]
        if isinstance(node, Function):
            params = ", ".join(self._join_expr(self._emit_node(p, indent)) for p in node.params)
            lines = [f"{indent_str}def {node.name.name}({params}):"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, Opaque):
            return [f"{indent_str}{node.original_text}"]
        if isinstance(node, TryExcept):
            lines = []
            lines.append(f"{indent_str}try:")
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            for clause in node.except_clauses:
                if clause.exception_type:
                    exc_type = self._join_expr(
                        self._emit_node(clause.exception_type, indent)
                    )
                    if clause.binding:
                        lines.append(f"{indent_str}except {exc_type} as {clause.binding}:")
                    else:
                        lines.append(f"{indent_str}except {exc_type}:")
                else:
                    lines.append(f"{indent_str}except:")
                for n in clause.body:
                    lines.extend(self._emit_node(n, indent + 1))
            if node.finally_body:
                lines.append(f"{indent_str}finally:")
                for n in node.finally_body:
                    lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, StructDef):
            lines = [f"{indent_str}class {node.name}:"]
            for field in node.fields:
                if field.default:
                    default_val = self._join_expr(self._emit_node(field.default, indent))
                    lines.append(f"{indent_str}    {field.name} = {default_val}")
            for method in node.methods:
                lines.extend(self._emit_function(method, indent + 1))
            return lines
        if isinstance(node, ParallelFor):
            var = " ".join(self._emit_node(node.var, indent))
            start_code = " ".join(self._emit_node(node.start, indent)) if node.start else "0"
            end_code = " ".join(self._emit_node(node.end, indent)) if node.end else "len(iterable)"

            # Emit body as lambda expression
            body_lines = []
            for child in node.body:
                body_lines.extend(self._emit_node(child, indent + 1))
            body_str = " ".join(body_lines) if body_lines else "pass"

            if node.reduction:
                # Map-reduce pattern for parallel execution
                map_expr = f"map(lambda {var}: ({body_str}), range({start_code}, {end_code}))"
                if node.reduction == "sum":
                    return [f"{indent_str}{var} = sum({map_expr})"]
                elif node.reduction == "prod":
                    return [
                        f"{indent_str}import math",
                        f"{indent_str}{var} = math.prod({map_expr})",
                    ]
                elif node.reduction == "max":
                    return [f"{indent_str}{var} = max({map_expr})"]
                elif node.reduction == "min":
                    return [f"{indent_str}{var} = min({map_expr})"]
            else:
                # Parallel execution without reduction
                return [
                    f"{indent_str}from concurrent.futures import ThreadPoolExecutor",
                    f"{indent_str}with ThreadPoolExecutor() as _exec:",
                    f"{indent_str}    list(_exec.map(lambda {var}: ({body_str}), range({start_code}, {end_code})))",
                ]
            return []
        if isinstance(node, Match):
            subject = self._join_expr(self._emit_node(node.subject, indent))
            lines = [f"{indent_str}match {subject}:"]
            for arm in node.arms:
                pattern = self._join_expr(self._emit_node(arm.pattern, indent))
                lines.append(f"{indent_str}    case {pattern}:")
                for n in arm.body:
                    lines.extend(self._emit_node(n, indent + 2))
            return lines
        if isinstance(node, Reference):
            target = self._join_expr(self._emit_node(node.target, indent))
            return [f"&mut {target}" if node.is_mutable else f"&{target}"]
        if isinstance(node, TypeAnnotation):
            return [node.type_name]
        # Fallback
        return [f"{indent_str}# Unimplemented: {type(node).__name__}"]

    def _emit_function(self, func: "Function", indent: int = 0) -> list:
        """Emit a Function node to source lines."""
        indent_str = "    " * indent
        params = ", ".join(p.name for p in func.params) if func.params else ""
        lines = [f"{indent_str}def {func.name.name}({params}):"]
        for n in func.body:
            lines.extend(self._emit_node(n, indent + 1))
        return lines


# Module-level convenience function
def emit_from_uast(uast: CoreUAST) -> str:
    """Emit CoreUAST to source code."""
    emitter = PythonEmitter()
    return emitter.emit(uast)
