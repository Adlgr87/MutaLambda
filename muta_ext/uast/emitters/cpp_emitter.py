#!/usr/bin/env python3
"""CoreUAST → C++ source emitter."""
import shutil
import subprocess
from typing import Optional

from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, Comment, Opaque,
    TryExcept, ExceptClause, StructDef, FieldDef, TypeAnnotation,
    Match, MatchArm, Reference, Break
)


class CppEmitter:
    """Emit CoreUAST back to C++ source code."""

    language = "cpp"

    def can_emit(self, uast: CoreUAST) -> bool:
        """Check if UAST is for C++ language."""
        return uast.language == "cpp"

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST to C++ source."""
        lines = []
        for node in uast.body:
            lines.extend(self._emit_node(node, indent=0))
        code = "\n".join(lines)
        
        # Try to format with clang-format if available
        if shutil.which("clang-format"):
            try:
                result = subprocess.run(
                    ["clang-format"],
                    input=code,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass
        
        return code

    def _emit_node(self, node: Optional[Any], indent: int = 0) -> list:
        """Emit a single node to source lines."""
        if node is None:
            return []
        indent_str = "    " * indent
        
        if isinstance(node, LiteralNode):
            if node.value is None:
                return ["()"]
            if isinstance(node.value, bool):
                return ["true" if node.value else "false"]
            if isinstance(node.value, str):
                return [f'"{node.value}"']
            return [repr(node.value)]
        
        if isinstance(node, Identifier):
            return [node.name]
        
        if isinstance(node, BinaryOp):
            left = " ".join(self._emit_node(node.left, indent))
            right = " ".join(self._emit_node(node.right, indent))
            op = node.op.replace("and", "&&").replace("or", "||")
            return [f"{left} {op} {right}"]
        
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
            return [f"{indent_str}{targets} = {value};"]
        
        if isinstance(node, If):
            condition = " ".join(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}if ({condition}) {{"]
            for n in node.then_body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            if node.else_body:
                lines.append(f"{indent_str}else {{")
                for n in node.else_body:
                    lines.extend(self._emit_node(n, indent + 1))
                lines.append(f"{indent_str}}}")
            return lines
        
        if isinstance(node, For):
            var = " ".join(self._emit_node(node.var, indent))
            iterable = " ".join(self._emit_node(node.iter, indent))
            lines = [f"{indent_str}for (int {var} : {iterable}) {{"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            return lines
        
        if isinstance(node, While):
            condition = " ".join(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}while ({condition}) {{"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            return lines
        
        if isinstance(node, Return):
            if node.value:
                val = " ".join(self._emit_node(node.value, indent))
                return [f"{indent_str}return {val};"]
            return [f"{indent_str}return;"]
        
        if isinstance(node, Function):
            params = ", ".join(p.name for p in node.params) if node.params else ""
            lines = [f"{indent_str}auto {node.name.name}({params}) {{"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            return lines
        
        if isinstance(node, StructDef):
            lines = [f"{indent_str}struct {node.name} {{"]
            for field in node.fields:
                if field.type_annotation:
                    type_name = " ".join(self._emit_node(field.type_annotation, indent))
                    lines.append(f"{indent_str}    {type_name} {field.name};")
                else:
                    lines.append(f"{indent_str}    int {field.name};")
            lines.append(f"{indent_str}}};")
            return lines
        
        if isinstance(node, Match):
            subject = " ".join(self._emit_node(node.subject, indent))
            lines = [f"{indent_str}// Match expression on {subject}"]
            for arm in node.arms:
                pattern = " ".join(self._emit_node(arm.pattern, indent))
                lines.append(f"{indent_str}// case {pattern}:")
            return lines
        
        if isinstance(node, Reference):
            target = " ".join(self._emit_node(node.target, indent))
            return [f"&{target}" if node.is_mutable else f"&{target}"]
        
        if isinstance(node, TypeAnnotation):
            return [node.type_name]
        
        if isinstance(node, Opaque):
            return [f"{indent_str}// Opaque: {node.original_text[:50]}"]
        
        return [f"{indent_str}// Unimplemented: {type(node).__name__}"]


def emit_from_uast(uast: CoreUAST) -> str:
    """Emit CoreUAST to C++ source code."""
    emitter = CppEmitter()
    return emitter.emit(uast)