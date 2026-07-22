"""CoreUAST → Python source emitter."""
from typing import Optional

from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, ParallelFor,
    Comment, Opaque, Node
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
        # Fallback
        return [f"{indent_str}# Unimplemented: {type(node).__name__}"]


# Module-level convenience function
def emit_from_uast(uast: CoreUAST) -> str:
    """Emit CoreUAST to source code."""
    emitter = PythonEmitter()
    return emitter.emit(uast)
