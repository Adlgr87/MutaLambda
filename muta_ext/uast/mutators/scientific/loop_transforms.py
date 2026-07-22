"""LoopFusionMutator y LoopFissionMutator."""

import random
from typing import Optional
from muta_ext.uast.core_uast import CoreUAST, Node, Function, For, Identifier
from muta_ext.uast.mutators.scientific.base_mutator import BaseScientificMutator, MutationResult


class LoopFusionMutator(BaseScientificMutator):
    """Fusiona bucles adyacentes con el mismo rango."""
    name = "loop_fusion"
    strength = 0.2

    def name(self) -> str:
        return self.name

    def mutate(self, uast: CoreUAST, rng_seed: Optional[int] = None) -> MutationResult:
        """Fusiona bucles adyacentes."""
        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()
        new_body, changed, descs = list(uast.body), False, []

        for idx, node in enumerate(new_body):
            if isinstance(node, Function):
                nf = self._fuse_in_func(node, rng, descs)
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
            score_impact=0.2, confidence=0.6
        )

    def _fuse_in_func(self, func: Function, rng: random.Random, descs: list) -> Function:
        """Busca y fusiona bucles en una función."""
        new_body, changed = list(func.body), False
        i = 0
        while i < len(new_body) - 1:
            if isinstance(new_body[i], For) and isinstance(new_body[i + 1], For):
                fused = self._fuse(new_body[i], new_body[i + 1], rng)
                if fused is not None:
                    new_body[i] = fused
                    del new_body[i + 1]
                    changed = True
                    descs.append(f"Fused in {func.name.name}")
                    continue
            i += 1
        if changed:
            return Function(
                func.name, list(func.params), new_body,
                list(func.decorators), func.return_type, func.tag
            )
        return func

    def _fuse(self, loop1: For, loop2: For, rng: random.Random) -> Optional[For]:
        """Fusiona dos bucles si son compatibles."""
        if not (isinstance(loop1.var, Identifier) and isinstance(loop2.var, Identifier)):
            return None
        if loop1.var.name != loop2.var.name:
            return None
        if str(loop1.iterable) != str(loop2.iterable):
            return None
        if rng.random() >= 0.4:
            return None
        return For(
            loop1.var, loop1.iterable,
            loop1.body + loop2.body, loop1.is_traditional
        )


class LoopFissionMutator(BaseScientificMutator):
    """Divide bucles con múltiples estamentos."""
    name = "loop_fission"
    strength = 0.15

    def name(self) -> str:
        return self.name

    def mutate(self, uast: CoreUAST, rng_seed: Optional[int] = None) -> MutationResult:
        """Aplica fission a bucles."""
        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()
        new_body, changed, descs = list(uast.body), False, []

        for idx, node in enumerate(new_body):
            if isinstance(node, Function):
                nf = self._fission_in_func(node, rng, descs)
                if nf is not node:
                    new_body[idx] = nf
                    changed = True

        if not changed:
            return MutationResult(
                CoreUAST(list(uast.body), uast.language, dict(uast.metadata)),
                applied=False
            )

        return MutationResult(
            CoreUAST(new_body, uast.language, dict(uast.metadata)),
            applied=True, description="; ".join(descs),
            score_impact=0.15, confidence=0.5
        )

    def _fission_in_func(self, func: Function, rng: random.Random, descs: list) -> Optional[Function]:
        """Aplica fission a bucles en una función."""
        new_body, changed = list(func.body), False
        insert_offset = 0

        for idx, node in enumerate(new_body):
            if isinstance(node, For) and len(node.body) >= 2 and rng.random() < 0.3:
                mid = len(node.body) // 2
                l1 = For(node.var, node.iterable, node.body[:mid], node.is_traditional)
                l2 = For(node.var, node.iterable, node.body[mid:], node.is_traditional)
                new_body[idx + insert_offset] = l1
                new_body.insert(idx + insert_offset + 1, l2)
                insert_offset += 1
                changed = True
                descs.append(f"Fissioned in {func.name.name}")

        if changed:
            return Function(
                func.name, list(func.params), new_body,
                list(func.decorators), func.return_type, func.tag
            )
        return func