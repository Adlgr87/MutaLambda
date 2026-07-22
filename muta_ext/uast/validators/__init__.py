"""UAST validators for mutation safety and correctness."""
from typing import List, Optional

from muta_ext.uast.core_uast import (
    CoreUAST, Node, Opaque, LiteralNode, Identifier, BinaryOp, UnaryOp,
    Call, Assign, If, For, While, Return, Function
)


class UASTValidator:
    """Validate CoreUAST transformations."""

    @staticmethod
    def validate_structure(uast: CoreUAST) -> List[str]:
        """Validate UAST structure. Returns list of errors."""
        errors = []
        for node in uast.body:
            errors.extend(UASTValidator._validate_node(node))
        return errors

    @staticmethod
    def _validate_node(node: Optional[Node]) -> List[str]:
        """Validate a single node."""
        if node is None:
            return []
        
        errors = []
        
        # Check for Opaque nodes that shouldn't be mutated
        if isinstance(node, Opaque):
            errors.append(f"Unrecognized construct: {node.original_text[:50]}...")
        
        # Recursively validate children
        if isinstance(node, BinaryOp):
            errors.extend(UASTValidator._validate_node(node.left))
            errors.extend(UASTValidator._validate_node(node.right))
        elif isinstance(node, If):
            errors.extend(UASTValidator._validate_node(node.condition))
            for n in node.then_body:
                errors.extend(UASTValidator._validate_node(n))
            if node.else_body:
                for n in node.else_body:
                    errors.extend(UASTValidator._validate_node(n))
        elif isinstance(node, For):
            errors.extend(UASTValidator._validate_node(node.var))
            errors.extend(UASTValidator._validate_node(node.iterable))
            for n in node.body:
                errors.extend(UASTValidator._validate_node(n))
        elif isinstance(node, While):
            errors.extend(UASTValidator._validate_node(node.condition))
            for n in node.body:
                errors.extend(UASTValidator._validate_node(n))
        elif isinstance(node, Function):
            for n in node.body:
                errors.extend(UASTValidator._validate_node(n))
        
        return errors

    @staticmethod
    def is_valid(uast: CoreUAST) -> bool:
        """Check if UAST is valid (no errors)."""
        return len(UASTValidator.validate_structure(uast)) == 0


__all__ = ["UASTValidator"]
