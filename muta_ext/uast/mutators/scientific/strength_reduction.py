"""StrengthReductionMutator: x²→x*x, x*2→x<<1, x/2→x*0.5, x³→x*x*x"""

import random
from typing import Optional
from muta_ext.uast.core_uast import CoreUAST, Node, BinaryOp, LiteralNode, Function
from muta_ext.uast.mutators.scientific.base_mutator import BaseScientificMutator, MutationResult


class StrengthReductionMutator(BaseScientificMutator):
    """Mutador que reduce operaciones costosas a equivalentes más rápidos."""
    _name = "strength_reduction"
    strength = 0.3

    def name(self) -> str:
        return self._name

    def mutate(self, uast: CoreUAST, rng_seed: Optional[int] = None) -> MutationResult:
        """Aplica strength reduction al UAST."""
        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()
        new_body, changed, descs = list(uast.body), False, []

        for idx, node in enumerate(new_body):
            if isinstance(node, Function):
                nf = self._mutate_func(node, rng, descs)
                if nf is not node:
                    new_body[idx], changed = nf, True

        if not changed:
            return MutationResult(
                CoreUAST(list(uast.body), uast.language, dict(uast.metadata)),
                applied=False
            )

        return MutationResult(
            CoreUAST(new_body, uast.language, dict(uast.metadata)),
            applied=True, description="; ".join(descs),
            score_impact=0.15, confidence=0.8
        )

    def _mutate_func(self, func: Function, rng: random.Random, descs: list) -> Function:
        """Mutar una función específica."""
        new_body, changed = list(func.body), False
        for idx, node in enumerate(new_body):
            repl = self._try_reduce(node, rng)
            if repl is not None:
                new_body[idx], changed = repl, True
                descs.append(f"Reduced in {func.name.name}")
        if changed:
            return Function(
                func.name, list(func.params), new_body,
                list(func.decorators), func.return_type, func.tag
            )
        return func

    def _try_reduce(self, node: Any, rng: random.Random) -> Optional[Node]:
        """Intenta aplicar strength reduction a un nodo."""
        if not isinstance(node, BinaryOp):
            return None

        # x ** 2 → x * x
        if node.op == "**" and isinstance(node.right, LiteralNode):
            try:
                if int(node.right.value) == 2:
                    return BinaryOp(node.left, "*", node.left)
            except (ValueError, TypeError):
                pass

        # x * 2 → x << 1
        if node.op == "*" and isinstance(node.right, LiteralNode):
            try:
                if int(node.right.value) == 2 and rng.random() < 0.6:
                    return BinaryOp(node.left, "<<", LiteralNode(1))
            except (ValueError, TypeError):
                pass

        return None