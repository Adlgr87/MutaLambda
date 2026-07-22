"""CoreUAST → Python source emitter."""
import ast
from typing import Optional

from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, ParallelFor,
    Comment, Opaque, Node, TryExcept, ExceptClause, StructDef,
    FieldDef, TypeAnnotation, MatchArm, Match, Reference
)


class PythonEmitter:
    """Emit CoreUAST back to Python source code."""

    language = "python"

    def can_emit(self, uast: CoreUAST) -> bool:
        """Check if UAST is for Python language."""
        return uast.language == "python"

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST to Python source."""
        lines = []
        for node in uast.body:
            lines.extend(self._emit_node(node, indent=0))
        return "\n".join(lines)

    def _emit_node(self, node: Optional[Node], indent: int = 0) -> list:
        """Emit a single node to source lines."""
        if node is None:
            return []
        indent_str = "    " * indent
        
        if isinstance(node, LiteralNode):
            return [repr(node.value)]
        if isinstance(node, Identifier):
            return [node.name]
        if isinstance(node, BinaryOp):
            left = " ".join(self._emit_node(node.left, indent))
            right = " ".join(self._emit_node(node.right, indent))
            return [f"{left} {node.op} {right}"]
        if isinstance(node, UnaryOp):
            operand = " ".join(self._emit_node(node.operand, indent))
            return [f"{node.op}{operand}"]
        if isinstance(node, Call):
            func = " ".join(self._emit_node(node.func, indent))
            args = ", ".join(" ".join(self._emit_node(a, indent)) for a in node.args)
            return [f"{func}({args})"]
        if isinstance(node, Assign):
            if isinstance(node.target, list):
                targets = ", ".join(" ".join(self._emit_node(t, indent)) for t in node.target)
            else:
                targets = " ".join(self._emit_node(node.target, indent))
            value = " ".join(self._emit_node(node.value, indent))
            return [f"{indent_str}{targets} = {value}"]
        if isinstance(node, If):
            condition = " ".join(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}if {condition}:"]
            for n in node.then_body:
                lines.extend(self._emit_node(n, indent + 1))
            if node.else_body:
                lines.append(f"{indent_str}else:")
                for n in node.else_body:
                    lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, For):
            var = " ".join(self._emit_node(node.var, indent))
            iterable = " ".join(self._emit_node(node.iter, indent))
            lines = [f"{indent_str}for {var} in {iterable}:"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, While):
            condition = " ".join(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}while {condition}:"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            return lines
        if isinstance(node, Return):
            if node.value:
                val = " ".join(self._emit_node(node.value, indent))
                return [f"{indent_str}return {val}"]
            return [f"{indent_str}return"]
        if isinstance(node, Function):
            params = ", ".join(" ".join(self._emit_node(p, indent)) for p in node.params)
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
                    exc_type = " ".join(self._emit_node(clause.exception_type, indent))
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
                    default_val = " ".join(self._emit_node(field.default, indent))
                    lines.append(f"{indent_str}    {field.name} = {default_val}")
            for method in node.methods:
                lines.extend(self._emit_function(method, indent + 1))
            return lines
        if isinstance(node, Match):
            subject = " ".join(self._emit_node(node.subject, indent))
            lines = [f"{indent_str}match {subject}:"]
            for arm in node.arms:
                pattern = " ".join(self._emit_node(arm.pattern, indent))
                lines.append(f"{indent_str}    case {pattern}:")
                for n in arm.body:
                    lines.extend(self._emit_node(n, indent + 2))
            return lines
        if isinstance(node, Reference):
            target = " ".join(self._emit_node(node.target, indent))
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
