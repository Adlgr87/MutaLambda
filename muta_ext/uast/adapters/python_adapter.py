"""Python → CoreUAST adapter using tree-sitter (with ast fallback)."""
from typing import List, Optional
import ast as stdlib_ast

try:
    from tree_sitter import Language, Parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from muta_ext.uast.core_uast import (
    CoreUAST, LiteralNode, Identifier, BinaryOp, UnaryOp, Call,
    Assign, If, For, While, Return, Function, ParallelFor,
    Comment, Opaque, Node, TryExcept, ExceptClause, StructDef,
    FieldDef, TypeAnnotation, MatchArm, Match
)


def _get_tree_sitter_language():
    """Lazy load tree-sitter language."""
    if not TREE_SITTER_AVAILABLE:
        return None
    # This would need the compiled language library
    # For now, return None to use ast fallback
    return None


class PythonAdapter:
    """Python source to CoreUAST converter."""

    language = "python"

    def __init__(self, use_tree_sitter: bool = True):
        self.use_tree_sitter = use_tree_sitter and TREE_SITTER_AVAILABLE

    def can_parse(self, source: str) -> bool:
        """Check if source is valid Python."""
        try:
            stdlib_ast.parse(source)
            return True
        except SyntaxError:
            return False

    def parse_to_uast(self, source: str) -> CoreUAST:
        """Parse Python source to CoreUAST using stdlib ast (tree-sitter optional)."""
        try:
            tree = stdlib_ast.parse(source)
            return self._transform(tree)
        except SyntaxError as e:
            raise ValueError(f"Cannot parse Python source: {e}")

    def _transform(self, tree: stdlib_ast.AST) -> CoreUAST:
        """Transform stdlib ast.Module to CoreUAST."""
        body = [self._visit(node) for node in tree.body]
        return CoreUAST(
            body=body,
            language="python",
            metadata={"source_hash": str(hash(tree))}
        )

    def _visit(self, node: stdlib_ast.AST) -> Optional[Node]:
        """Visit and transform an AST node."""
        if node is None:
            return None

        method = f"_visit_{node.__class__.__name__}"
        visitor = getattr(self, method, self._visit_unknown)
        return visitor(node)

    def _visit_Constant(self, node: stdlib_ast.Constant) -> LiteralNode:
        """Transform Constant to LiteralNode."""
        type_hint = None
        if isinstance(node.value, int):
            type_hint = "i64"
        elif isinstance(node.value, float):
            type_hint = "f64"
        elif isinstance(node.value, str):
            type_hint = "str"
        return LiteralNode(value=node.value, type_hint=type_hint)

    def _visit_Name(self, node: stdlib_ast.Name) -> Identifier:
        """Transform Name to Identifier."""
        return Identifier(name=node.id)

    def _visit_BinOp(self, node: stdlib_ast.BinOp) -> BinaryOp:
        """Transform BinOp to BinaryOp."""
        op_map = {
            stdlib_ast.Add: "+", stdlib_ast.Sub: "-",
            stdlib_ast.Mult: "*", stdlib_ast.Div: "/",
            stdlib_ast.Mod: "%", stdlib_ast.And: "and",
            stdlib_ast.Or: "or", stdlib_ast.Eq: "==",
            stdlib_ast.Lt: "<", stdlib_ast.LtE: "<=",
            stdlib_ast.Gt: ">", stdlib_ast.GtE: ">="
        }
        op = op_map.get(type(node.op), "?")
        return BinaryOp(
            left=self._visit(node.left),
            op=op,
            right=self._visit(node.right)
        )

    def _visit_UnaryOp(self, node: stdlib_ast.UnaryOp) -> UnaryOp:
        """Transform UnaryOp to UnaryOp."""
        op_map = {
            stdlib_ast.Not: "not",
            stdlib_ast.USub: "-",
            stdlib_ast.UAdd: "+"
        }
        return UnaryOp(
            op=op_map.get(type(node.op), "?"),
            operand=self._visit(node.operand)
        )

    def _visit_Call(self, node: stdlib_ast.Call) -> Call:
        """Transform Call to Call."""
        func = self._visit(node.func) if isinstance(node.func, stdlib_ast.Name) else Identifier(name="unknown")
        args = [self._visit(arg) for arg in node.args]
        keywords = {kw.arg: self._visit(kw.value) for kw in node.keywords if kw.arg}
        return Call(func=func, args=args, keywords=keywords)

    def _visit_Assign(self, node: stdlib_ast.Assign) -> Assign:
        """Transform Assign to Assign."""
        targets = [self._visit(t) for t in node.targets if isinstance(t, stdlib_ast.Name)]
        target = targets[0] if len(targets) == 1 else targets
        return Assign(target=target, value=self._visit(node.value))

    def _visit_If(self, node: stdlib_ast.If) -> If:
        """Transform If to If."""
        return If(
            condition=self._visit(node.test),
            then_body=[self._visit(n) for n in node.body],
            else_body=[self._visit(n) for n in node.orelse] if node.orelse else None
        )

    def _visit_For(self, node: stdlib_ast.For) -> For:
        """Transform For to For."""
        return For(
            var=self._visit(node.target),
            iterable=self._visit(node.iter),
            body=[self._visit(n) for n in node.body]
        )

    def _visit_While(self, node: stdlib_ast.While) -> While:
        """Transform While to While."""
        return While(
            condition=self._visit(node.test),
            body=[self._visit(n) for n in node.body]
        )

    def _visit_Return(self, node: stdlib_ast.Return) -> Return:
        """Transform Return to Return."""
        return Return(value=self._visit(node.value) if node.value else None)

    def _visit_FunctionDef(self, node: stdlib_ast.FunctionDef) -> Function:
        """Transform FunctionDef to Function."""
        params = [Identifier(name=arg.arg) for arg in node.args.args]
        decorators = [self._visit(d) for d in node.decorator_list if isinstance(d, stdlib_ast.Call)]
        return Function(
            name=Identifier(name=node.name),
            params=params,
            body=[self._visit(n) for n in node.body],
            decorators=decorators
        )

    def _visit_Try(self, node: stdlib_ast.Try) -> TryExcept:
        """Transform Try to TryExcept."""
        except_clauses = []
        for handler in node.handlers:
            exc_type = self._visit(handler.type) if handler.type else None
            except_clauses.append(ExceptClause(
                exception_type=exc_type,
                binding=handler.name,
                body=[self._visit(n) for n in handler.body]
            ))
        
        return TryExcept(
            body=[self._visit(n) for n in node.body],
            except_clauses=except_clauses,
            finally_body=[self._visit(n) for n in node.finalbody] if node.finalbody else None
        )

    def _visit_ClassDef(self, node: stdlib_ast.ClassDef) -> StructDef:
        """Transform ClassDef to StructDef (simple classes only)."""
        # For simple classes without metaclasses/templates - treat complex ones as Opaque
        if node.decorator_list or node.bases or node.keywords:
            return Opaque(
                original_text=stdlib_ast.unparse(node) if hasattr(stdlib_ast, 'unparse') else str(node),
                lang="python"
            )
        
        fields = []
        methods = []
        
        for item in node.body:
            if isinstance(item, stdlib_ast.Assign):
                for target in item.targets:
                    if isinstance(target, stdlib_ast.Name):
                        fields.append(FieldDef(
                            name=target.id,
                            type_annotation=None,
                            default=self._visit(item.value)
                        ))
            elif isinstance(item, stdlib_ast.FunctionDef):
                methods.append(self._visit(item))
        
        return StructDef(
            name=node.name,
            fields=fields,
            methods=methods
        )

    def _visit_Match(self, node: stdlib_ast.Match) -> Match:
        """Transform Match to Match (Python 3.10+)."""
        # Check Python version for Match support
        import sys
        if sys.version_info < (3, 10):
            return Opaque(original_text=f"match {node.subject}", lang="python")
        
        arms = []
        for case in node.cases:
            pattern = self._visit(case.pattern)
            guard = self._visit(case.guard) if case.guard else None
            arms.append(MatchArm(
                pattern=pattern,
                guard=guard,
                body=[self._visit(n) for n in case.body]
            ))
        
        return Match(
            subject=self._visit(node.subject),
            arms=arms
        )

    def _visit_AnnAssign(self, node: stdlib_ast.AnnAssign) -> Assign:
        """Transform AnnAssign (annotated assignment) to Assign with TypeAnnotation."""
        # For now, treat as regular assignment
        target = self._visit(node.target) if isinstance(node.target, stdlib_ast.Name) else None
        if target and node.value:
            return Assign(target=target, value=self._visit(node.value))
        return Opaque(
            original_text=stdlib_ast.unparse(node) if hasattr(stdlib_ast, 'unparse') else str(node),
            lang="python"
        )

    def _visit_unknown(self, node: stdlib_ast.AST) -> Opaque:
        """Transform unknown node to Opaque."""
        return Opaque(
            original_text=stdlib_ast.unparse(node) if hasattr(stdlib_ast, 'unparse') else str(node),
            lang="python"
        )


# Module-level convenience function
def parse_to_uast(source: str, use_tree_sitter: bool = False) -> CoreUAST:
    """Parse Python source to CoreUAST."""
    adapter = PythonAdapter(use_tree_sitter=use_tree_sitter)
    return adapter.parse_to_uast(source)