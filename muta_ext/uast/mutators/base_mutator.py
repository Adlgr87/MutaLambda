#!/usr/bin/env python3
"""Core UAST mutators for structural transformations."""
from __future__ import annotations

import copy
import random
from typing import Optional

from muta_ext.uast.core_uast import (
    CoreUAST, Node, BinaryOp, If, For, While, Assign, Identifier,
    LiteralNode, TryExcept, StructDef, Match, Opaque
)


class BaseMutator:
    """Base class for UAST mutators."""
    
    def mutate(self, uast: CoreUAST, rng: random.Random) -> CoreUAST:
        """Apply mutation to UAST. Must return a NEW UAST (immutability)."""
        raise NotImplementedError


class SwapConditionMutator(BaseMutator):
    """Swap operands of commutative binary operators (+, *, and, or)."""
    
    COMMUtATIVE_OPS = {"+", "*", "and", "or"}
    
    def mutate(self, uast: CoreUAST, rng: random.Random) -> CoreUAST:
        """Swap operands of a random commutative binary operation."""
        new_body = []
        mutated = False
        
        for node in uast.body:
            mutated_node = self._mutate_node(node, rng, mutated)
            if mutated_node is not None:
                if isinstance(mutated_node, BinaryOp) and mutated_node.op in self.COMMUTATIVE_OPS:
                    # Swap left and right
                    mutated_node = BinaryOp(
                        left=mutated_node.right,
                        op=mutated_node.op,
                        right=mutated_node.left,
                        tag=mutated_node.tag,
                        location=mutated_node.location
                    )
                    mutated = True
            new_body.append(mutated_node)
        
        if not mutated:
            return uast
        
        return CoreUAST(
            body=new_body,
            language=uast.language,
            metadata=uast.metadata.copy()
        )
    
    def _mutate_node(self, node: Node, rng: random.Random, already_mutated: bool) -> Node:
        """Recursively visit and potentially mutate nodes."""
        if already_mutated:
            return node
        
        if isinstance(node, BinaryOp):
            if node.op in self.COMMUTATIVE_OPS and rng.random() < 0.3:
                return BinaryOp(
                    left=node.right,
                    op=node.op,
                    right=node.left,
                    tag=node.tag,
                    location=node.location
                )
            return BinaryOp(
                left=self._mutate_node(node.left, rng, already_mutated),
                op=node.op,
                right=self._mutate_node(node.right, rng, already_mutated),
                tag=node.tag,
                location=node.location
            )
        
        if isinstance(node, If):
            return If(
                condition=self._mutate_node(node.condition, rng, already_mutated),
                then_body=[self._mutate_node(n, rng, already_mutated) for n in (node.then_body or [])],
                else_body=[self._mutate_node(n, rng, already_mutated) for n in (node.else_body or [])] if node.else_body else None,
                tag=node.tag,
                location=node.location
            )
        
        if isinstance(node, For):
            return For(
                var=node.var,
                iterable=node.iterable,
                body=[self._mutate_node(n, rng, already_mutated) for n in node.body],
                is_traditional=node.is_traditional,
                tag=node.tag,
                location=node.location
            )
        
        if isinstance(node, While):
            return While(
                condition=node.condition,
                body=[self._mutate_node(n, rng, already_mutated) for n in node.body],
                tag=node.tag,
                location=node.location
            )
        
        if isinstance(node, Assign) and isinstance(node.value, BinaryOp):
            if node.value.op in self.COMMUTATIVE_OPS and rng.random() < 0.3:
                return Assign(
                    target=node.target,
                    value=BinaryOp(
                        left=node.value.right,
                        op=node.value.op,
                        right=node.value.left,
                        tag=node.value.tag,
                        location=node.value.location
                    ),
                    tag=node.tag,
                    location=node.location
                )
        
        if isinstance(node, Opaque):
            return node
        
        return node


class NegateConditionMutator(BaseMutator):
    """Negate a condition in an If node and swap branches."""
    
    def mutate(self, uast: CoreUAST, rng: random.Random) -> CoreUAST:
        """Negate a random If condition."""
        new_body = []
        mutated = False
        
        for node in uast.body:
            result = self._try_negate(node, rng, mutated)
            if result is not None:
                new_body.append(result)
                mutated = True
            else:
                new_body.append(node)
        
        if not mutated:
            return uast
        
        return CoreUAST(
            body=new_body,
            language=uast.language,
            metadata=uast.metadata.copy()
        )
    
    def _try_negate(self, node: Node, rng: random.Random, already_mutated: bool) -> Node | None:
        """Try to negate an If node. Returns modified node or None."""
        if already_mutated:
            return None
        
        if isinstance(node, If):
            # Negate the condition
            negated_cond = self._negate_node(node.condition)
            return If(
                condition=negated_cond,
                then_body=node.else_body if node.else_body else [],
                else_body=node.then_body,
                tag=node.tag,
                location=node.location
            )
        
        return None
    
    def _negate_node(self, node: Node) -> Node:
        """Negate a condition node."""
        if isinstance(node, BinaryOp):
            op_map = {
                "<": ">=", ">": "<=", "<=": ">", ">=": "<",
                "==": "!=", "!=": "=="
            }
            new_op = op_map.get(node.op, node.op)
            return BinaryOp(left=node.left, op=new_op, right=node.right)
        
        if isinstance(node, Identifier):
            return UnaryOp(op="not", operand=node)
        
        return UnaryOp(op="not", operand=node)


class LoopBoundMutator(BaseMutator):
    """Adjust loop bounds (±1, change comparison operators)."""
    
    def mutate(self, uast: CoreUAST, rng: random.Random) -> CoreUAST:
        """Mutate loop bounds in For/While nodes."""
        new_body = []
        mutated = False
        
        for node in uast.body:
            result = self._try_mutate_loop(node, rng)
            if result is not None:
                new_body.append(result)
                mutated = True
            else:
                new_body.append(node)
        
        if not mutated:
            return uast
        
        return CoreUAST(
            body=new_body,
            language=uast.language,
            metadata=uast.metadata.copy()
        )
    
    def _try_mutate_loop(self, node: Node, rng: random.Random) -> Node | None:
        """Try to mutate loop bounds."""
        if isinstance(node, For) and isinstance(node.iterable, Call):
            # Try to modify range() call
            return For(
                var=node.var,
                iterable=self._mutate_range_call(node.iterable, rng),
                body=node.body,
                is_traditional=node.is_traditional,
                tag=node.tag,
                location=node.location
            )
        
        if isinstance(node, While):
            # Try to mutate while condition
            return While(
                condition=self._mutate_while_condition(node.condition, rng),
                body=node.body,
                tag=node.tag,
                location=node.location
            )
        
        return None
    
    def _mutate_range_call(self, call: Call, rng: random.Random) -> Call:
        """Mutate a range() call by adjusting bounds."""
        # Simple: just add/subtract 1 from numeric args
        new_args = []
        for arg in call.args:
            if isinstance(arg, LiteralNode) and isinstance(arg.value, int):
                adjustment = rng.choice([-1, 1])
                new_args.append(LiteralNode(value=arg.value + adjustment, type_hint=arg.type_hint))
            else:
                new_args.append(arg)
        return Call(func=call.func, args=new_args, keywords=call.keywords)
    
    def _mutate_while_condition(self, cond: Node, rng: random.Random) -> Node:
        """Mutate while condition."""
        if isinstance(cond, BinaryOp) and cond.op in ["<", "<=", ">", ">="]:
            op_map = {"<": "<=", "<=": "<", ">": ">=", ">=": "<"}
            return BinaryOp(left=cond.left, op=op_map.get(cond.op, cond.op), right=cond.right)
        return cond


class ReorderStatementsMutator(BaseMutator):
    """Reorder independent statements in a block."""
    
    def mutate(self, uast: CoreUAST, rng: random.Random) -> CoreUAST:
        """Reorder statements if there are at least 2 statements."""
        if len(uast.body) < 2:
            return uast
        
        # Create a new list with shuffled order
        body_list = list(uast.body)
        rng.shuffle(body_list)
        
        # Only apply if order actually changed
        if body_list == list(uast.body):
            return uast
        
        return CoreUAST(
            body=body_list,
            language=uast.language,
            metadata=uast.metadata.copy()
        )


class InlineVariableMutator(BaseMutator):
    """Replace identifier with its assigned literal value."""
    
    def mutate(self, uast: CoreUAST, rng: random.Random) -> CoreUAST:
        """Inline variable assignments where possible."""
        # Simple implementation: replace identifier usage if its value is a literal
        # This is a simplified version - full implementation would track scope
        if len(uast.body) < 2:
            return uast
        
        # Look for Assign -> Identifier pattern
        for i, node in enumerate(uast.body):
            if isinstance(node, Assign) and isinstance(node.target, Identifier):
                if isinstance(node.value, LiteralNode):
                    # Replace subsequent uses of this variable
                    new_body = []
                    var_name = node.target.name
                    
                    for j, other_node in enumerate(uast.body):
                        if i == j:
                            continue  # Skip the assignment itself
                        new_body.append(self._inline_identifier(other_node, var_name, node.value.value))
                    
                    if len(new_body) > 0:
                        return CoreUAST(
                            body=new_body,
                            language=uast.language,
                            metadata=uast.metadata.copy()
                        )
        
        return uast
    
    def _inline_identifier(self, node: Node, var_name: str, value: Any) -> Node:
        """Replace identifier with literal value."""
        if isinstance(node, Identifier) and node.name == var_name:
            return LiteralNode(value=value)
        
        if isinstance(node, BinaryOp):
            return BinaryOp(
                left=self._inline_identifier(node.left, var_name, value),
                op=node.op,
                right=self._inline_identifier(node.right, var_name, value)
            )
        
        return node


# Export mutator classes
__all__ = [
    "BaseMutator",
    "SwapConditionMutator",
    "NegateConditionMutator", 
    "LoopBoundMutator",
    "ReorderStatementsMutator",
    "InlineVariableMutator"
]