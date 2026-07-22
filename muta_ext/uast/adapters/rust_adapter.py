#!/usr/bin/env python3
"""Rust → CoreUAST adapter using tree-sitter."""
from typing import Any, Optional

from tree_sitter import Language, Parser

from muta_ext.uast.adapters.base import BaseAdapter
from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, Comment, Opaque,
    TryExcept, ExceptClause, StructDef, FieldDef, TypeAnnotation,
    Match, MatchArm, Reference, Break
)


def _get_text(node: Any, source: str) -> str:
    """Extract text from node, handling both str and bytes."""
    text = source[node.start_byte:node.end_byte]
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return text


class RustAdapter(BaseAdapter):
    """Rust source to CoreUAST converter using tree-sitter."""

    language = "rust"
    
    def __init__(self):
        # Load Rust language from installed package
        from tree_sitter_rust import language as rust_lang
        self._parser = Parser(Language(rust_lang()))

    def can_parse(self, source: str) -> bool:
        """Check if source is valid Rust."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            return not tree.root_node.has_error
        except Exception:
            return False

    def parse_to_uast(self, source: str) -> CoreUAST:
        """Parse Rust source to CoreUAST."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            if tree.root_node.has_error:
                raise ValueError("Rust source has parse errors")
            return self._transform(tree.root_node, source)
        except Exception as e:
            raise ValueError(f"Cannot parse Rust source: {e}")

    def _transform(self, node: Any, source: str) -> CoreUAST:
        """Transform tree-sitter node to CoreUAST."""
        body = []
        
        for child in node.children:
            uast_node = self._visit(child, source)
            if uast_node is not None:
                body.append(uast_node)
        
        return CoreUAST(
            body=body,
            language="rust",
            metadata={"source": source}
        )

    def _visit(self, node: Any, source: str) -> Optional[Any]:
        """Visit and transform a tree-sitter node."""
        node_type = node.type
        
        method = f"_visit_{node_type}"
        visitor = getattr(self, method, None)
        
        if visitor:
            return visitor(node, source)
        
        # Default: Opaque for unsupported nodes
        return Opaque(original_text=_get_text(node, source), lang="rust")

    def _visit_function_item(self, node: Any, source: str) -> Function:
        """Transform Rust function_item to Function."""
        name_id = None
        params = []
        body = []
        
        for child in node.children:
            text = _get_text(child, source)
            if child.type == "identifier":
                name_id = Identifier(name=text)
            elif child.type == "parameters":
                for param in child.children:
                    if param.type == "parameter":
                        param_node = self._extract_parameter(param, source)
                        if param_node:
                            params.append(param_node)
            elif child.type == "block":
                for stmt in child.children:
                    stmt_node = self._visit(stmt, source)
                    if stmt_node:
                        body.append(stmt_node)
        
        return Function(
            name=name_id or Identifier(name="unknown"),
            params=params,
            body=body
        )

    def _extract_parameter(self, node: Any, source: str) -> Optional[Identifier]:
        """Extract parameter from Rust parameter node."""
        for child in node.children:
            if child.type == "identifier":
                return Identifier(name=_get_text(child, source))
        return None

    def _visit_if_expression(self, node: Any, source: str) -> If:
        """Transform Rust if_expression to If."""
        condition = None
        then_body = []
        else_body = []
        
        for i, child in enumerate(node.children):
            if i == 0:
                # First child is condition
                condition = self._visit_expression(child, source)
            elif child.type == "block":
                # First block is then, second is else
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
            condition=condition or Opaque(original_text="?", lang="rust"),
            then_body=then_body or [Opaque(original_text="?", lang="rust")],
            else_body=else_body if else_body else None
        )

    def _visit_expression(self, node: Any, source: str) -> Optional[Any]:
        """Visit an expression node."""
        # Return first meaningful child
        for child in node.children:
            result = self._visit(child, source)
            if result is not None and not isinstance(result, Opaque):
                return result
        return None

    def _visit_binary_expression(self, node: Any, source: str) -> BinaryOp:
        """Transform binary_expression to BinaryOp."""
        parts = []
        op = "?"
        
        for child in node.children:
            text = _get_text(child, source)
            if text in ("+", "-", "*", "/", "%", "&&", "||", "==", "!=", "<", ">", "<=", ">="):
                op_map = {"&&": "and", "||": "or"}
                op = op_map.get(text, text)
            else:
                child_node = self._visit(child, source)
                if child_node:
                    parts.append(child_node)
        
        if len(parts) >= 2:
            return BinaryOp(left=parts[0], op=op, right=parts[1])
        return Opaque(original_text=_get_text(node, source), lang="rust")

    def _visit_unary_expression(self, node: Any, source: str) -> UnaryOp:
        """Transform unary_expression to UnaryOp."""
        op = "?"
        operand = None
        
        for child in node.children:
            text = _get_text(child, source)
            if text in ("!", "-"):
                op = "not" if text == "!" else text
            else:
                operand = self._visit(child, source)
        
        return UnaryOp(op=op, operand=operand or Opaque(original_text="?", lang="rust"))

    def _visit_identifier(self, node: Any, source: str) -> Identifier:
        """Transform identifier to Identifier."""
        return Identifier(name=_get_text(node, source))

    def _visit_integer_literal(self, node: Any, source: str) -> LiteralNode:
        """Transform integer_literal to LiteralNode."""
        value = _get_text(node, source)
        try:
            return LiteralNode(value=int(value))
        except ValueError:
            return LiteralNode(value=value)

    def _visit_string_literal(self, node: Any, source: str) -> LiteralNode:
        """Transform string_literal to LiteralNode."""
        value = _get_text(node, source).strip('"').strip("'")
        return LiteralNode(value=value, type_hint="str")

    def _visit_boolean_literal(self, node: Any, source: str) -> LiteralNode:
        """Transform boolean_literal to LiteralNode."""
        value = _get_text(node, source)
        return LiteralNode(value=value == "true", type_hint="bool")

    def _visit_call_expression(self, node: Any, source: str) -> Call:
        """Transform call_expression to Call."""
        func = None
        args = []
        
        for child in node.children:
            if child.type in ("identifier", "field_expression"):
                func = self._visit(child, source)
            elif child.type == "arguments":
                for arg in child.children:
                    if arg.type not in ("(", ")"):
                        arg_node = self._visit(arg, source)
                        if arg_node:
                            args.append(arg_node)
        
        return Call(func=func or Identifier(name="unknown"), args=args)

    def _visit_struct_item(self, node: Any, source: str) -> StructDef:
        """Transform Rust struct_item to StructDef."""
        name = "unknown"
        fields = []
        
        for child in node.children:
            if child.type == "identifier":
                name = _get_text(child, source)
            elif child.type == "field_declaration_list":
                for field in child.children:
                    if field.type == "field_declaration":
                        field_node = self._visit_field_declaration(field, source)
                        if field_node:
                            fields.append(field_node)
        
        return StructDef(name=name, fields=fields, methods=[])

    def _visit_field_declaration(self, node: Any, source: str) -> Optional[FieldDef]:
        """Extract field from field_declaration."""
        name = None
        type_ann = None
        
        for child in node.children:
            if child.type == "identifier":
                name = _get_text(child, source)
            elif child.type == "type_identifier":
                type_ann = TypeAnnotation(type_name=_get_text(child, source))
        
        if name:
            return FieldDef(name=name, type_annotation=type_ann)
        return None

    def _visit_type_identifier(self, node: Any, source: str) -> TypeAnnotation:
        """Transform type_identifier to TypeAnnotation."""
        return TypeAnnotation(type_name=_get_text(node, source))

    def _visit_match_expression(self, node: Any, source: str) -> Match:
        """Transform Rust match_expression to Match."""
        subject = Opaque(original_text="?", lang="rust")
        arms = []
        
        for child in node.children:
            if child.type in ("expression", "identifier", "literal"):
                subject = self._visit(child, source) or subject
            elif child.type == "match_block":
                for arm in child.children:
                    arm_node = self._visit_match_arm(arm, source)
                    if arm_node:
                        arms.append(arm_node)
        
        return Match(subject=subject, arms=arms)

    def _visit_match_arm(self, node: Any, source: str) -> Optional[MatchArm]:
        """Transform match arm to MatchArm."""
        pattern = Opaque(original_text="_", lang="rust")
        body = []
        
        for child in node.children:
            if child.type in ("_", "literal", "identifier"):
                pattern = self._visit(child, source) or pattern
            elif child.type == "block":
                for stmt in child.children:
                    stmt_node = self._visit(stmt, source)
                    if stmt_node:
                        body.append(stmt_node)
        
        return MatchArm(pattern=pattern, body=body)


def parse_to_uast(source: str) -> CoreUAST:
    """Parse Rust source to CoreUAST."""
    adapter = RustAdapter()
    return adapter.parse_to_uast(source)