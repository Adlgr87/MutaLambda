#!/usr/bin/env python3
"""Go → CoreUAST adapter using tree-sitter."""
from typing import Any, Optional, List

try:
    from tree_sitter import Language, Parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from muta_ext.uast.adapters.base import BaseAdapter
from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, Comment, Opaque,
    TryExcept, ExceptClause, StructDef, FieldDef, TypeAnnotation,
    Match, MatchArm, Reference, Break, Node
)


def _get_text(node: Any, source: bytes) -> str:
    """Extract text from node, handling both str and bytes."""
    text = source[node.start_byte:node.end_byte]
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return text


class GoAdapter(BaseAdapter):
    """Go source to CoreUAST converter using tree-sitter."""

    language = "go"

    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            raise ModuleNotFoundError("No module named 'tree_sitter'", name="tree_sitter")
        from tree_sitter_go import language as go_lang
        self._parser = Parser(Language(go_lang()))

    @property
    def language(self) -> str:
        return "go"

    def can_parse(self, source: str) -> bool:
        """Check if source is valid Go."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            return not tree.root_node.has_error
        except Exception:
            return False

    def parse_to_uast(self, source: str) -> CoreUAST:
        """Parse Go source to CoreUAST."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            if tree.root_node.has_error:
                # Try to continue anyway for partial parsing
                pass
            return self._transform(tree.root_node, source.encode("utf-8"))
        except Exception as e:
            raise ValueError(f"Cannot parse Go source: {e}")

    def _transform(self, node: Any, source: bytes) -> CoreUAST:
        """Transform tree-sitter node to CoreUAST."""
        body = []

        for child in node.children:
            uast_node = self._visit(child, source)
            if uast_node is not None:
                body.append(uast_node)

        return CoreUAST(
            body=body,
            language="go",
            metadata={"source": source.decode("utf-8", errors="replace")}
        )

    def _visit(self, node: Any, source: bytes) -> Optional[Node]:
        """Visit and transform a tree-sitter node."""
        node_type = node.type
        method = f"_visit_{node_type.replace('-', '_')}"
        visitor = getattr(self, method, None)

        if visitor:
            return visitor(node, source)

        # Default: Opaque for unsupported nodes
        return Opaque(original_text=_get_text(node, source), lang="go")

    # ===== Declarations =====

    def _visit_package_clause(self, node: Any, source: bytes) -> Optional[Node]:
        """Transform package clause."""
        return None  # Skip package declarations in UAST

    def _visit_import_declaration(self, node: Any, source: bytes) -> Optional[Node]:
        """Transform import declaration."""
        imports = []
        for child in node.children:
            if child.type == "import_spec":
                name = _get_text(child, source).strip('"')
                imports.append(Identifier(name=name))
        return Opaque(original_text=f"import {imports}", lang="go")

    def _visit_function_declaration(self, node: Any, source: bytes) -> Function:
        """Transform function declaration."""
        name_id = None
        params = []
        return_type = None
        body = []

        for child in node.children:
            if child.type == "identifier":
                name_id = Identifier(name=_get_text(child, source))
            elif child.type == "parameters":
                params = self._extract_parameters(child, source)
            elif child.type == "field_declaration_list":
                # Handle return type
                for field in child.children:
                    if field.type == "field_declaration":
                        for fchild in field.children:
                            if fchild.type == "type_identifier":
                                return_type = _get_text(fchild, source)
            elif child.type == "body":
                for stmt in child.children:
                    stmt_node = self._visit(stmt, source)
                    if stmt_node:
                        body.append(stmt_node)

        return Function(
            name=name_id or Identifier(name="unknown"),
            params=params,
            body=body,
            return_type=return_type
        )

    def _visit_method_declaration(self, node: Any, source: bytes) -> Function:
        """Transform method declaration (similar to function)."""
        return self._visit_function_declaration(node, source)

    def _visit_type_declaration(self, node: Any, source: bytes) -> Optional[Node]:
        """Transform type declaration (struct, interface)."""
        for child in node.children:
            if child.type == "type_spec":
                return self._visit_type_spec(child, source)
        return None

    def _visit_type_spec(self, node: Any, source: bytes) -> Optional[Node]:
        """Transform type spec."""
        name = None
        type_node = None

        for child in node.children:
            if child.type == "identifier":
                name = _get_text(child, source)
            else:
                type_node = child

        if not name or not type_node:
            return None

        if type_node.type == "struct_type":
            return self._visit_struct_type(type_node, source, name)
        elif type_node.type == "interface_type":
            return self._visit_interface_type(type_node, source, name)
        elif type_node.type == "pointer_type":
            # Type alias with pointer
            inner = _get_text(type_node.children[0], source) if type_node.children else "unknown"
            return Opaque(original_text=f"type {name} *{inner}", lang="go")
        else:
            # Basic type alias
            return Opaque(original_text=f"type {name}", lang="go")

    def _visit_struct_type(self, node: Any, source: bytes, name: str) -> StructDef:
        """Transform struct type."""
        fields = []
        methods = []

        for child in node.children:
            if child.type == "field_declaration_list":
                for field in child.children:
                    if field.type == "field_declaration":
                        field_def = self._visit_field_declaration(field, source)
                        if field_def:
                            fields.append(field_def)

        return StructDef(name=name, fields=fields, methods=methods)

    def _visit_field_declaration(self, node: Any, source: bytes) -> Optional[FieldDef]:
        """Transform field declaration."""
        names = []
        type_name = None

        for child in node.children:
            if child.type == "identifier":
                names.append(_get_text(child, source))
            elif child.type in ("type_identifier", "pointer_type", "array_type"):
                type_name = _get_text(child, source)

        if not names or not type_name:
            return None

        # Handle multiple names (comma-separated)
        result = []
        for name in names:
            result.append(FieldDef(name=name, type_annotation=TypeAnnotation(type_name=type_name)))
        return result[0] if len(result) == 1 else None

    def _visit_interface_type(self, node: Any, source: bytes, name: str) -> Opaque:
        """Transform interface type."""
        methods = []
        for child in node.children:
            if child.type == "interface_type_literal":
                for method in child.children:
                    if method.type == "method_spec":
                        methods.append(_get_text(method, source))
        return Opaque(original_text=f"type {name} interface {{ {', '.join(methods)} }}", lang="go")

    # ===== Expressions =====

    def _visit_expression_statement(self, node: Any, source: bytes) -> Optional[Node]:
        """Transform expression statement."""
        for child in node.children:
            if child.type == "expression":
                return self._visit(child, source)
        return None

    def _visit_call_expression(self, node: Any, source: bytes) -> Optional[Call]:
        """Transform call expression."""
        func = None
        args = []

        for child in node.children:
            if child.type == "identifier":
                func = Identifier(name=_get_text(child, source))
            elif child.type == "arguments":
                for arg in child.children:
                    if arg.type in ("expression", "binary_expression", "unary_expression"):
                        arg_node = self._visit(arg, source)
                        if arg_node:
                            args.append(arg_node)

        if func:
            return Call(func=func, args=args)
        return None

    def _visit_binary_expression(self, node: Any, source: bytes) -> Optional[BinaryOp]:
        """Transform binary expression."""
        parts = []
        op = "?"

        for child in node.children:
            text = _get_text(child, source)
            if text in ("+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "&", "|", "^", "<<", ">>"):
                op_map = {"&&": "and", "||": "or"}
                op = op_map.get(text, text)
            else:
                child_node = self._visit(child, source)
                if child_node:
                    parts.append(child_node)

        if len(parts) >= 2:
            return BinaryOp(left=parts[0], op=op, right=parts[1])
        return None

    def _visit_unary_expression(self, node: Any, source: bytes) -> Optional[UnaryOp]:
        """Transform unary expression."""
        op = "?"
        operand = None

        for child in node.children:
            text = _get_text(child, source)
            if text in ("!", "-", "+", "&", "*"):
                op = "not" if text == "!" else text
            else:
                operand = self._visit(child, source)

        if operand:
            return UnaryOp(op=op, operand=operand)
        return None

    def _visit_identifier(self, node: Any, source: bytes) -> Identifier:
        """Transform identifier."""
        return Identifier(name=_get_text(node, source))

    def _visit_basic_lit(self, node: Any, source: bytes) -> LiteralNode:
        """Transform basic literal."""
        text = _get_text(node, source)
        # Remove quotes for strings
        if text.startswith('"') or text.startswith("'"):
            return LiteralNode(value=text.strip('"').strip("'"), type_hint="str")
        try:
            if '.' in text:
                return LiteralNode(value=float(text), type_hint="f64")
            return LiteralNode(value=int(text), type_hint="i64")
        except ValueError:
            return LiteralNode(value=text)

    def _visit_index_expression(self, node: Any, source: bytes) -> Optional[Call]:
        """Transform index expression (array/slice/map access)."""
        collection = None
        index = None

        for child in node.children:
            if child.type == "expression":
                if collection is None:
                    collection = self._visit(child, source)
                else:
                    index = self._visit(child, source)

        if collection and index:
            # Emit as function call for UAST compatibility
            return Call(func=Identifier(name="index"), args=[collection, index])
        return None

    # ===== Statements =====

    def _visit_short_var_declaration(self, node: Any, source: bytes) -> Optional[Assign]:
        """Transform short variable declaration (:=)."""
        left = []
        right = None

        for child in node.children:
            if child.type == "expression_list":
                for expr in child.children:
                    if expr.type == "identifier":
                        left.append(Identifier(name=_get_text(expr, source)))
            elif child.type == "expression":
                right = self._visit(child, source)

        if left and right:
            target = left[0] if len(left) == 1 else left
            return Assign(target=target, value=right)
        return None

    def _visit_var_declaration(self, node: Any, source: bytes) -> Optional[Node]:
        """Transform variable declaration."""
        # Parse var x int = value
        variables = []
        type_name = None
        value = None

        for child in node.children:
            if child.type == "identifier":
                variables.append(Identifier(name=_get_text(child, source)))
            elif child.type == "type_identifier":
                type_name = _get_text(child, source)
            elif child.type == "expression":
                value = self._visit(child, source)

        if variables and value:
            return Assign(target=variables[0], value=value)
        return None

    def _visit_if_statement(self, node: Any, source: bytes) -> If:
        """Transform if statement."""
        condition = None
        then_body = []
        else_body = []

        for child in node.children:
            if child.type == "expression" and condition is None:
                condition = self._visit(child, source)
            elif child.type == "statement_list":
                if not then_body:
                    for stmt in child.children:
                        stmt_node = self._visit(stmt, source)
                        if stmt_node:
                            then_body.append(stmt_node)
                else:
                    for stmt in child.children:
                        stmt_node = self._visit(stmt, source)
                        if stmt_node:
                            else_body.append(stmt_node)

        return If(
            condition=condition or Opaque(original_text="true", lang="go"),
            then_body=then_body or [Opaque(original_text="{}", lang="go")],
            else_body=else_body if else_body else None
        )

    def _visit_for_statement(self, node: Any, source: bytes) -> For:
        """Transform for statement."""
        var = None
        iterable = None
        body = []

        for child in node.children:
            if child.type == "expression_list":
                for expr in child.children:
                    if expr.type == "identifier":
                        var = Identifier(name=_get_text(expr, source))
                    else:
                        iterable = self._visit(expr, source)
            elif child.type == "statement_list":
                for stmt in child.children:
                    stmt_node = self._visit(stmt, source)
                    if stmt_node:
                        body.append(stmt_node)

        return For(
            var=var or Identifier(name="i"),
            iterable=iterable or Opaque(original_text="range", lang="go"),
            body=body
        )

    def _visit_return_statement(self, node: Any, source: bytes) -> Return:
        """Transform return statement."""
        value = None
        for child in node.children:
            if child.type == "expression":
                value = self._visit(child, source)
        return Return(value=value)

    def _visit_break_statement(self, node: Any, source: bytes) -> Break:
        """Transform break statement."""
        return Break()

    def _visit_continue_statement(self, node: Any, source: bytes) -> Opaque:
        """Transform continue statement."""
        return Opaque(original_text="continue", lang="go")

    def _visit_send_statement(self, node: Any, source: bytes) -> Opaque:
        """Transform channel send statement."""
        return Opaque(original_text="channel_send", lang="go")

    def _visit_receive_expression(self, node: Any, source: bytes) -> Opaque:
        """Transform channel receive expression."""
        return Opaque(original_text="channel_receive", lang="go")

    # ===== Helpers =====

    def _extract_parameters(self, node: Any, source: bytes) -> List[Identifier]:
        """Extract parameters from parameter node."""
        params = []
        for child in node.children:
            if child.type == "parameter_declaration":
                for param_child in child.children:
                    if param_child.type == "identifier":
                        params.append(Identifier(name=_get_text(param_child, source)))
            elif child.type == "identifier":
                params.append(Identifier(name=_get_text(child, source)))
        return params


def parse_to_uast(source: str) -> CoreUAST:
    """Parse Go source to CoreUAST."""
    adapter = GoAdapter()
    return adapter.parse_to_uast(source)
