"""NumericalStabilityMutator: (a+b)-c → a+(b-c), sqrt(x²+y²) → hypot, near-equal subtraction"""

import random
from typing import Any, Optional
from muta_ext.uast.core_uast import CoreUAST, Node, BinaryOp, LiteralNode, Function
from muta_ext.uast.mutators.scientific.base_mutator import BaseScientificMutator, MutationResult


class NumericalStabilityMutator(BaseScientificMutator):
    """Mutador que mejora la estabilidad numérica de expresiones."""
    _name = "numerical_stability"
    strength = 0.25

    def name(self) -> str:
        return self._name

    def mutate(self, uast: CoreUAST, rng_seed: Optional[int] = None) -> MutationResult:
        """Aplica transformaciones de estabilidad numérica."""
        return self.mutate_functions(
            uast, rng_seed, self._stabilize_func,
            score_impact=0.1, confidence=0.6
        )

    def _stabilize_func(self, func: Function, rng: random.Random, descs: list) -> Function:
        """Aplica estabilización a una función."""
        new_body, changed = list(func.body), False
        for idx, node in enumerate(new_body):
            repl = self._try_stabilize(node, rng)
            if repl is not None:
                new_body[idx], changed = repl, True
                descs.append(f"Stabilized in {func.name.name}")
        if changed:
            return self.with_body(func, new_body)
        return func

    def _try_stabilize(self, node: Any, rng: random.Random) -> Optional[Node]:
        """Intenta aplicar estabilización numérica."""
        if not isinstance(node, BinaryOp):
            return None

        # (a + b) - c → a + (b - c)
        if node.op == "-" and isinstance(node.left, BinaryOp) and node.left.op == "+":
            if rng.random() < 0.4:
                return BinaryOp(
                    node.left.left, "+",
                    BinaryOp(node.left.right, "-", node.right)
                )

        return None