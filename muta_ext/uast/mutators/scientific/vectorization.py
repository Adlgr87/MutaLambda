"""SafeVectorizationMutator: loop reduction → np.sum/prod"""

import random
from typing import Optional
from muta_ext.uast.core_uast import CoreUAST, Node, BinaryOp, Function, For, Identifier, Assign, Call, LiteralNode
from muta_ext.uast.mutators.scientific.base_mutator import BaseScientificMutator, MutationResult


class SafeVectorizationMutator(BaseScientificMutator):
    """Mutador que vectoriza bucles simples a operaciones numpy."""
    name = "safe_vectorization"
    strength = 0.2

    def name(self) -> str:
        return self.name

    def mutate(self, uast: CoreUAST, rng_seed: Optional[int] = None) -> MutationResult:
        """Intenta vectorizar bucles simples."""
        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()
        new_body, changed, descs = list(uast.body), False, []

        for idx, node in enumerate(new_body):
            if isinstance(node, Function):
                nf = self._try_vectorize(node, rng, descs)
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
            score_impact=0.3, confidence=0.5
        )

    def _try_vectorize(self, func: Function, rng: random.Random, descs: list) -> Function:
        """Intenta vectorizar bucles en una función."""
        new_body, changed = list(func.body), False
        for idx, node in enumerate(new_body):
            if isinstance(node, For) and len(node.body) == 1:
                repl = self._vectorize_loop(node, rng)
                if repl is not None:
                    new_body[idx], changed = repl, True
                    descs.append(f"Vectorized in {func.name.name}")
        if changed:
            return Function(
                func.name, list(func.params), new_body,
                list(func.decorators), func.return_type, func.tag
            )
        return func

    def _vectorize_loop(self, loop: For, rng: random.Random) -> Optional[Node]:
        """Vectoriza un bucle for simple a np.sum/prod."""
        # Check for pattern: for i in range(...): total += arr[i]
        if not isinstance(loop.var, Identifier):
            return None

        # Check if iterable is range call
        if not isinstance(loop.iterable, Call):
            return None
        if not isinstance(loop.iterable.func, Identifier):
            return None
        if loop.iterable.func.name != "range":
            return None

        stmt = loop.body[0]
        if not isinstance(stmt, Assign):
            return None
        if not isinstance(stmt.value, BinaryOp):
            return None
        if stmt.value.op not in ("+", "+="):
            return None

        if not isinstance(stmt.value.right, Call):
            return None
        if not isinstance(stmt.value.right.func, Identifier):
            return None
        if rng.random() >= 0.5:
            return None

        return Assign(
            stmt.target,
            Call(Identifier("np.sum"), [Identifier(stmt.value.right.func.name)])
        )