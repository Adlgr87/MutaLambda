#!/usr/bin/env python3
"""UAST v2 native mutators — in-place, seeded, verifiable nanopasses.

These passes are where the mutable representation pays off: a rewrite touches
only the affected slots (``set_child`` / ``node.replace``), parent pointers and
Merkle hashes update along the path to the root, and no frozen dataclass tree is
rebuilt.  ``LegacyMutatorPass`` closes the loop in the other direction, wrapping
every existing legacy mutator through the bidirectional converter.

All passes are deterministic for a given ``seed`` and count the rewrites they
performed (``pass.mutations``), which the pipeline reports.
"""

from __future__ import annotations

import math
import random
import typing as T
from typing import Any, Callable, List, Optional

from muta_ext.uast2.core import (
    BinaryOp,
    Call,
    CoreUAST,
    Identifier,
    If,
    LiteralNode,
    UnaryOp,
    UASTNode,
    While,
    walk,
)
from muta_ext.uast2.passes import MutationPass, Pass
from muta_ext.uast2.visitor import NodeTransformer

__all__ = [
    "available_legacy_mutators",
    "ConstantFoldingPass",
    "CommutativeSwapPass",
    "RangeBoundPass",
    "NegateConditionPass",
    "LegacyMutatorPass",
    "default_mutators",
]

_COMMUTATIVE = {"+", "*", "and", "or"}
_FOLDABLE = {"+", "-", "*"}
_COMPARISON_FLIP = {"<": ">=", ">": "<=", "<=": ">", ">=": "<", "==": "!=", "!=": "=="}


class _InPlaceTransformer(NodeTransformer):
    """NodeTransformer that counts replacements so passes can report mutations."""

    def __init__(self) -> None:
        self.replacements = 0

    def record(self) -> None:
        """Count one structural rewrite."""
        self.replacements += 1


class ConstantFoldingPass(MutationPass):
    """Fold literal arithmetic (``1 + 2`` → ``3``) in place."""

    name = "constant_folding"
    preserves_math = False  # cambia la aritmética/flujo a propósito
    description = "Folds +/-/* on numeric literals (and 'not' on booleans)."

    def __init__(self, fold_strings: bool = False, verify_with=None) -> None:
        super().__init__(verify_with=verify_with)
        self.fold_strings = fold_strings

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:
        pass_ = self

        class _Folder(_InPlaceTransformer):
            def visit_BinaryOp(self, node: BinaryOp) -> UASTNode:
                self.generic_visit(node)
                left, right = node.left, node.right
                if not (isinstance(left, LiteralNode) and isinstance(right, LiteralNode)):
                    return node
                folded = _fold(node.op, left.value, right.value, pass_.fold_strings)
                if folded is _UNFOLDABLE:
                    return node
                literal = LiteralNode(value=folded, type_hint=left.type_hint or right.type_hint)
                literal.lineno, literal.col_offset = node.lineno, node.col_offset
                literal.end_lineno, literal.end_col_offset = node.end_lineno, node.end_col_offset
                self.record()
                return literal

            def visit_UnaryOp(self, node: UnaryOp) -> UASTNode:
                self.generic_visit(node)
                operand = node.operand
                if node.op == "-" and isinstance(operand, LiteralNode) and isinstance(
                    operand.value, (int, float)
                ) and not isinstance(operand.value, bool):
                    self.record()
                    return LiteralNode(value=-operand.value, type_hint=operand.type_hint)
                if node.op == "not" and isinstance(operand, LiteralNode) and isinstance(
                    operand.value, bool
                ):
                    self.record()
                    return LiteralNode(value=not operand.value, type_hint="bool")
                return node

        transformer = _Folder()
        transformer.transform(root)
        self._record(transformer.replacements)


class CommutativeSwapPass(MutationPass):
    """Swap the operands of a commutative operation (seeded, in place)."""

    name = "commutative_swap"
    description = "Swaps a+b → b+a (and *, and, or) with probability `rate`."

    def __init__(
        self,
        rate: float = 0.3,
        seed: Optional[int] = None,
        rng: Optional[random.Random] = None,
        verify_with=None,
    ) -> None:
        super().__init__(verify_with=verify_with)
        self.rate = rate
        self.rng = rng or random.Random(seed)

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:
        from muta_ext.uast2.core import set_child

        rng = self.rng
        for node in walk(root):
            if not isinstance(node, BinaryOp) or node.op not in _COMMUTATIVE:
                continue
            if rng.random() >= self.rate:
                continue
            left, right = node.left, node.right
            # Slot surgery: both children move, nothing is rebuilt.
            set_child(node, "left", right)
            set_child(node, "right", left)
            self._record()


class RangeBoundPass(MutationPass):
    """Perturb literal bounds of ``range(...)`` calls by ±1."""

    name = "range_bound"
    preserves_math = False  # cambia la aritmética/flujo a propósito
    description = "Mutates integer literals inside range() by ±step (off-by-one)."

    def __init__(
        self,
        step: int = 1,
        rate: float = 1.0,
        seed: Optional[int] = None,
        rng: Optional[random.Random] = None,
        verify_with=None,
    ) -> None:
        super().__init__(verify_with=verify_with)
        self.step = step
        self.rate = rate
        self.rng = rng or random.Random(seed)

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:
        from muta_ext.uast2.core import set_child

        rng = self.rng
        for node in walk(root):
            if not isinstance(node, Call):
                continue
            func = node.func
            if not (isinstance(func, Identifier) and func.name == "range"):
                continue
            for index, arg in enumerate(node.args):
                if not isinstance(arg, LiteralNode) or not isinstance(arg.value, int):
                    continue
                if isinstance(arg.value, bool) or rng.random() >= self.rate:
                    continue
                delta = self.step if rng.random() < 0.5 else -self.step
                replacement = LiteralNode(value=arg.value + delta, type_hint=arg.type_hint)
                replacement.lineno, replacement.col_offset = arg.lineno, arg.col_offset
                set_child(node, ("args", index), replacement)
                self._record()


class NegateConditionPass(MutationPass):
    """Negate ``if``/``while`` conditions in place (flip comparisons when possible)."""

    name = "negate_condition"
    preserves_math = False  # cambia la aritmética/flujo a propósito
    description = "Flips comparison operators or wraps the condition in `not`."

    def __init__(
        self,
        rate: float = 0.5,
        seed: Optional[int] = None,
        rng: Optional[random.Random] = None,
        verify_with=None,
    ) -> None:
        super().__init__(verify_with=verify_with)
        self.rate = rate
        self.rng = rng or random.Random(seed)

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:
        rng = self.rng
        for node in walk(root):
            if not isinstance(node, (If, While)):
                continue
            condition = node.condition
            if condition is None or rng.random() >= self.rate:
                continue
            if isinstance(condition, BinaryOp) and condition.op in _COMPARISON_FLIP:
                # Flip in place: one attribute write, no subtree rebuild.
                condition.op = _COMPARISON_FLIP[condition.op]
                from muta_ext.uast2.merkle import invalidate_up

                invalidate_up(condition)
                self._record()
            else:
                from muta_ext.uast2.core import set_child

                wrapper = UnaryOp(op="not", operand=None)
                wrapper.lineno, wrapper.col_offset = condition.lineno, condition.col_offset
                # ``set_child`` re-parents both levels: the previous condition
                # becomes the operand of the new ``not`` node, which itself
                # takes over the condition slot of the ``if``/``while``.
                set_child(wrapper, "operand", condition)
                set_child(node, "condition", wrapper)
                self._record()


class LegacyMutatorPass(MutationPass):
    """Runs a frozen legacy mutator through the converter (explicit reuse)."""

    name = "legacy_mutator"
    preserves_math = False  # cambia la aritmética/flujo a propósito
    description = "Wraps a muta_ext.uast.mutators class over the v2 document."

    def __init__(
        self,
        mutator: Any,
        seed: int = 0,
        legacy_name: str = "legacy_mutator",
        verify_with=None,
    ) -> None:
        super().__init__(verify_with=verify_with)
        self.mutator = mutator
        self.seed = seed
        self.name = legacy_name

    def run(self, root: CoreUAST, arena: Optional[Any] = None) -> None:
        from muta_ext.uast2.convert import legacy_to_v2

        legacy_document = root.to_legacy()
        mutated = self.mutator.mutate(legacy_document, random.Random(self.seed))
        if mutated is legacy_document or mutated is None:
            return
        mutated_v2 = legacy_to_v2(mutated)
        root.body[:] = mutated_v2.body
        root.metadata = dict(mutated_v2.metadata or root.metadata)
        root.prepare(arena)
        self._record()

    @classmethod
    def from_registry(cls, name: str, seed: int = 0) -> "LegacyMutatorPass":
        """Build a pass from a legacy mutator class name (``SwapConditionMutator``...).

        The class name is resolved against ``muta_ext.uast.mutators.base_mutator``
        (the module that ships the five built-in mutators) and exposed class
        attributes, so generated mutators can be plugged in the same way.
        """
        from muta_ext.uast.mutators import base_mutator as legacy_base

        mutator_cls = getattr(legacy_base, name, None)
        if mutator_cls is None:
            raise ValueError(
                f"Unknown legacy mutator {name!r}. Available: "
                + ", ".join(sorted(getattr(legacy_base, "__all__", [])))
            )
        return cls(mutator_cls(), seed=seed, legacy_name=f"legacy_{name}")


_UNFOLDABLE = object()


def _fold(op: str, left: Any, right: Any, fold_strings: bool) -> Any:
    """Return the folded value or :data:`_UNFOLDABLE` when the symbols are unsafe."""
    if isinstance(left, bool) or isinstance(right, bool):
        return _UNFOLDABLE  # keep boolean logic intact (short-circuit semantics)
    if fold_strings and isinstance(left, str) and isinstance(right, str) and op == "+":
        return left + right
    if not (isinstance(left, (int, float)) and isinstance(right, (int, float))):
        return _UNFOLDABLE
    if op not in _FOLDABLE:
        return _UNFOLDABLE
    if op == "*" and (abs(left) > 2**32 or abs(right) > 2**32):
        return _UNFOLDABLE  # avoid building huge literals
    try:
        value = left + right if op == "+" else left - right if op == "-" else left * right
    except Exception:  # pragma: no cover - defensive
        return _UNFOLDABLE
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return _UNFOLDABLE
    if isinstance(value, int) and abs(value) > 2**64:
        return _UNFOLDABLE
    return value


def available_legacy_mutators() -> List[str]:
    """Names of the frozen legacy mutator classes usable through the bridge."""
    try:
        from muta_ext.uast.mutators import base_mutator as legacy_base
    except Exception:  # pragma: no cover - legacy package is always present
        return []
    names = list(getattr(legacy_base, "__all__", []) or [])
    if not names:
        names = [
            name
            for name, value in vars(legacy_base).items()
            if isinstance(value, type) and name.endswith("Mutator")
        ]
    return sorted(names)


def default_mutators(seed: Optional[int] = None) -> List[Pass]:
    """The standard in-place mutation set (deterministic when *seed* is given)."""
    return [
        ConstantFoldingPass(),
        CommutativeSwapPass(seed=seed),
        RangeBoundPass(seed=None if seed is None else seed + 1),
        NegateConditionPass(seed=None if seed is None else seed + 2),
    ]
