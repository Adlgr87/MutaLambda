#!/usr/bin/env python3
"""CoreUAST → Go source emitter."""
import shutil
import subprocess
import tempfile
from typing import Any, Optional, List

from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, Comment, Opaque,
    TryExcept, ExceptClause, StructDef, FieldDef, TypeAnnotation,
    Match, MatchArm, Reference, Break, ParallelFor, Node
)


class GoEmitter:
    """Emit CoreUAST back to Go source code."""

    language = "go"

    def can_emit(self, uast: CoreUAST) -> bool:
        """Check if UAST is for Go language."""
        return uast.language == "go"

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST to Go source."""
        lines = ["package main"]
        lines.append("")

        for node in uast.body:
            emitted = self._emit_node(node, indent=0)
            if emitted:
                lines.extend(emitted)
            lines.append("")

        code = "\n".join(lines)

        # Try to format with gofmt if available
        if shutil.which("gofmt"):
            try:
                result = subprocess.run(
                    ["gofmt"],
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

        indent_str = "\t" * indent

        if isinstance(node, LiteralNode):
            if node.value is None:
                return ["nil"]
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
            args = [", ".join(self._emit_node(a, indent)) for a in node.args]
            return [f"{func}({', '.join(args)})"]

        if isinstance(node, Assign):
            if isinstance(node.target, list):
                targets = ", ".join(self._emit_node(t, indent) for t in node.target)
            else:
                targets = "".join(self._emit_node(node.target, indent))
            value = "".join(self._emit_node(node.value, indent))
            return [f"{indent_str}{targets} := {value}"]

        if isinstance(node, If):
            condition = " ".join(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}if {condition} {{"]
            for n in node.then_body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            if node.else_body:
                lines.append(indent_str + "} else {")
                for n in node.else_body:
                    lines.extend(self._emit_node(n, indent + 1))
                lines.append(f"{indent_str}}}")
            return lines

        if isinstance(node, For):
            var = self._emit_node(node.var, indent)[0] if node.var else "i"
            iterable = " ".join(self._emit_node(node.iterable, indent))
            lines = [f"{indent_str}for {var} := range {iterable} {{"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            return lines

        if isinstance(node, While):
            condition = " ".join(self._emit_node(node.condition, indent))
            lines = [f"{indent_str}for {condition} {{"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            return lines

        if isinstance(node, Return):
            if node.value:
                val = " ".join(self._emit_node(node.value, indent))
                return [f"{indent_str}return {val}"]
            return [f"{indent_str}return"]

        if isinstance(node, Function):
            params = ", ".join(p.name for p in node.params) if node.params else ""
            ret = f" {node.return_type}" if node.return_type else ""
            lines = [f"{indent_str}func {node.name.name}({params}){ret} {{"]
            for n in node.body:
                lines.extend(self._emit_node(n, indent + 1))
            lines.append(f"{indent_str}}}")
            return lines

        if isinstance(node, StructDef):
            lines = [f"{indent_str}type {node.name} struct {{"]
            for field in node.fields:
                ann = ""
                if field.type_annotation:
                    ann = f" {field.type_annotation.type_name}"
                lines.append(f"{indent_str}\t{field.name}{ann}")
            lines.append(f"{indent_str}}}")
            for method in node.methods:
                lines.extend(self._emit_function(method, indent))
            return lines

        if isinstance(node, Match):
            subject = " ".join(self._emit_node(node.subject, indent))
            lines = [f"{indent_str}switch {subject} {{"]
            for arm in node.arms:
                pattern = " ".join(self._emit_node(arm.pattern, indent))
                lines.append(f"{indent_str}\tcase {pattern}:")
                for n in arm.body:
                    lines.extend(self._emit_node(n, indent + 2))
            lines.append(f"{indent_str}}}")
            return lines

        if isinstance(node, Reference):
            target = " ".join(self._emit_node(node.target, indent))
            return [f"&{target}" if node.is_mutable else f"*{target}"]

        if isinstance(node, TypeAnnotation):
            return [node.type_name]

        if isinstance(node, Break):
            return [f"{indent_str}break"]

        if isinstance(node, Opaque):
            return [f"{indent_str}// {node.original_text[:60]}"]

        if isinstance(node, ParallelFor):
            var = self._emit_node(node.var, indent)[0] if node.var else "i"
            start_code = " ".join(self._emit_node(node.start, indent)) if node.start else "0"
            end_code = " ".join(self._emit_node(node.end, indent)) if node.end else "len(slice)"
            body_lines = []
            for child in node.body:
                body_lines.extend(self._emit_node(child, indent + 1))
            body_str = "\n".join(body_lines)

            # Go parallelism using goroutines
            return [
                f"{indent_str}var wg sync.WaitGroup",
                f"{indent_str}for {var} := {start_code}; {var} < {end_code}; {var}++ {{",
                f"{indent_str}\twg.Add(1)",
                f"{indent_str}\tgo func(i {self._get_go_type(node.var)}) {{",
                f"{indent_str}\t\tdefer wg.Done()",
                body_str,
                f"{indent_str}\t}}({var})",
                f"{indent_str}}}",
                f"{indent_str}wg.Wait()",
            ]

        return [f"{indent_str}// Unimplemented: {type(node).__name__}"]

    def _emit_function(self, func: Function, indent: int = 0) -> list:
        """Emit a Function node to source lines."""
        indent_str = "\t" * indent
        params = ", ".join(p.name for p in func.params) if func.params else ""
        ret = f" {func.return_type}" if func.return_type else ""
        lines = [f"{indent_str}func {func.name.name}({params}){ret} {{"]
        for n in func.body:
            lines.extend(self._emit_node(n, indent + 1))
        lines.append(f"{indent_str}}}")
        return lines

    def _get_go_type(self, var: Optional[Identifier]) -> str:
        """Get appropriate Go type for a variable."""
        if not var:
            return "int"
        # Infer type from identifier name conventions
        if var.name.endswith("Count") or var.name.endswith("Size"):
            return "int"
        return "int"  # Default


def emit_from_uast(uast: CoreUAST) -> str:
    """Emit CoreUAST to Go source code."""
    emitter = GoEmitter()
    return emitter.emit(uast)
