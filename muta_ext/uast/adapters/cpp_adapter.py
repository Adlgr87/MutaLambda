#!/usr/bin/env python3
"""C++ → CoreUAST adapter using tree-sitter."""
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


class CppAdapter(BaseAdapter):
    """C++ source to CoreUAST converter using tree-sitter."""

    language = "cpp"
    
    def __init__(self):
        from tree_sitter_cpp import language as cpp_lang
        self._parser = Parser(Language(cpp_lang()))

    def can_parse(self, source: str) -> bool:
        """Check if source is valid C++."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            return not tree.root_node.has_error
        except Exception:
            return False

    def parse_to_uast(self, source: str) -> CoreUAST:
        """Parse C++ source to CoreUAST."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            if tree.root_node.has_error:
                raise ValueError("C++ source has parse errors")
            return self._transform(tree.root_node, source)
        except Exception as e:
            raise ValueError(f"Cannot parse C++ source: {e}")

    def _transform(self, node: Any, source: str) -> CoreUAST:
        """Transform tree-sitter node to CoreUAST."""
        body = []
        
        for child in node.children:
            uast_node = self._visit(child, source)
            if uast_node is not None:
                body.append(uast_node)
        
        return CoreUAST(
            body=body,
            language="cpp",
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
        return Opaque(original_text=_get_text(node, source), lang="cpp")

    def _visit_function_definition(self, node: Any, source: str) -> Function:
        """Transform C++ function_definition to Function."""
        name_id = None
        params = []
        body = []
        
        for child in node.children:
            if child.type == "identifier":
                name_id = Identifier(name=_get_text(child, source))
            elif child.type == "parameter_list":
                for param in child.children:
                    if param.type == "parameter_declaration":
                        p = self._extract_cpp_parameter(param, source)
                        if p:
                            params.append(p)
            elif child.type == "compound_statement":
                for stmt in child.children:
                    if stmt.type not in ("{", "}"):
                        stmt_node = self._visit(stmt, source)
                        if stmt_node:
                            body.append(stmt_node)
        
        return Function(
            name=name_id or Identifier(name="unknown"),
            params=params,
            body=body
        )

    def _extract_cpp_parameter(self, node: Any, source: str) -> Optional[Identifier]:
        """Extract parameter from C++ parameter_declaration."""
        for child in node.children:
            if child.type == "identifier":
                return Identifier(name=_get_text(child, source))
        return None

    def _visit_if_statement(self, node: Any, source: str) -> If:
        """Transform C++ if_statement to If."""
        condition = None
        then_body = []
        else_body = []
        
        for child in node.children:
            text = _get_text(child, source)
            if text == "if" or (condition is None and child.type == "("):
                # Get condition from inside parens
                for c in child.children:
                    if c.type == ")":
                        continue
                    result = self._visit(c, source)
                    if result:
                        condition = result
            elif child.type == "compound_statement":
                for stmt in child.children:
                    if stmt.type not in ("{", "}"):
                        stmt_node = self._visit(stmt, source)
                        if stmt_node:
                            then_body.append(stmt_node)
            elif child.type == "else_clause":
                for c in child.children:
                    if c.type == "compound_statement":
                        for stmt in c.children:
                            if stmt.type not in ("{", "}"):
                                stmt_node = self._visit(stmt, source)
                                if stmt_node:
                                    else_body.append(stmt_node)
        
        return If(
            condition=condition or Opaque(original_text="?", lang="cpp"),
            then_body=then_body or [Opaque(original_text="?", lang="cpp")],
            else_body=else_body if else_body else None
        )

    def _visit_for_statement(self, node: Any, source: str) -> For:
        """Transform C++ for_statement to For."""
        var = Identifier(name="i")
        iterable = Opaque(original_text="?")
        body = []
        
        for child in node.children:
            if child.type == "identifier":
                var = Identifier(name=_get_text(child, source))
            elif child.type == "compound_statement":
                for stmt in child.children:
                    if stmt.type not in ("{", "}"):
                        stmt_node = self._visit(stmt, source)
                        if stmt_node:
                            body.append(stmt_node)
        
        return For(var=var, iterable=iterable, body=body)

    def _visit_while_statement(self, node: Any, source: str) -> While:
        """Transform C++ while_statement to While."""
        condition = Opaque(original_text="?")
        body = []
        
        for child in node.children:
            if child.type == "compound_statement":
                for stmt in child.children:
                    if stmt.type not in ("{", "}"):
                        stmt_node = self._visit(stmt, source)
                        if stmt_node:
                            body.append(stmt_node)
            else:
                result = self._visit(child, source)
                if result and isinstance(result, (BinaryOp, Identifier, LiteralNode)):
                    condition = result
        
        return While(condition=condition, body=body)

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
        return Opaque(original_text=_get_text(node, source), lang="cpp")

    def _visit_identifier(self, node: Any, source: str) -> Identifier:
        """Transform identifier to Identifier."""
        return Identifier(name=_get_text(node, source))

    def _visit_literal(self, node: Any, source: str) -> LiteralNode:
        """Transform literal to LiteralNode."""
        value_str = _get_text(node, source)
        if value_str.startswith('"'):
            return LiteralNode(value=value_str.strip('"'), type_hint="str")
        try:
            return LiteralNode(value=int(value_str))
        except ValueError:
            return LiteralNode(value=value_str)

    def _visit_return_statement(self, node: Any, source: str) -> Return:
        """Transform return_statement to Return."""
        value = None
        for child in node.children:
            if child.type not in (";", "return"):
                value = self._visit(child, source)
        
        return Return(value=value)

    def _visit_struct_specifier(self, node: Any, source: str) -> StructDef:
        """Transform C++ struct_specifier to StructDef."""
        name = "unknown"
        fields = []
        
        for child in node.children:
            if child.type == "identifier":
                name = _get_text(child, source)
            elif child.type == "field_declaration_list":
                for field in child.children:
                    if field.type == "field_declaration":
                        f = self._visit_cpp_field(field, source)
                        if f:
                            fields.append(f)
        
        return StructDef(name=name, fields=fields, methods=[])

    def _visit_cpp_field(self, node: Any, source: str) -> Optional[FieldDef]:
        """Extract field from C++ field_declaration."""
        name = None
        type_ann = None
        
        for child in node.children:
            if child.type == "identifier":
                name = _get_text(child, source)
            elif child.type in ("type_identifier", "primitive_type"):
                type_ann = TypeAnnotation(type_name=_get_text(child, source))
        
        if name:
            return FieldDef(name=name, type_annotation=type_ann)
        return None


def parse_to_uast(source: str) -> CoreUAST:
    """Parse C++ source to CoreUAST."""
    adapter = CppAdapter()
    return adapter.parse_to_uast(source)