"""Horizontal code transfer engine for MutaLambda."""

from __future__ import annotations

import ast
import copy
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models import Individual


@dataclass
class FragmentRecord:
    """Reusable code fragment discovered from successful individuals."""

    name: str
    code: str
    donor_id: str
    donor_score: float
    survival_gens: int = 0


@dataclass
class THCConfig:
    """Configuration for horizontal transfer."""

    enabled: bool = False
    max_transfers_per_generation: int = 1
    min_donor_score: float = 0.0
    validate_in_sandbox: bool = True


@dataclass
class THCMetrics:
    """Telemetry for THC."""

    thc_transfer_rate: float = 0.0
    fragment_survival_gens: float = 0.0
    hybrid_lineage_depth: int = 0
    transfers_attempted: int = 0
    transfers_accepted: int = 0


class HorizontalTransferEngine:
    """Extracts successful functions and injects them into compatible receivers."""

    def __init__(
        self,
        config: Optional[THCConfig] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.config = config or THCConfig()
        self.rng = rng or random.Random()
        self.fragments: Dict[str, FragmentRecord] = {}
        self.metrics = THCMetrics()

    def apply(self, population: List[Individual], evaluator: Any, generation: int) -> List[Individual]:
        """Create validated hybrid individuals and replace weak candidates."""
        if not self.config.enabled or len(population) < 2:
            return population

        self._harvest(population)
        if not self.fragments:
            return population

        accepted: List[Individual] = []
        attempted = 0
        candidates = sorted(population, key=lambda ind: ind.score)
        for receiver in candidates:
            if attempted >= self.config.max_transfers_per_generation:
                break
            compatible = [
                fragment for fragment in self.fragments.values()
                if fragment.donor_id != receiver.id
            ]
            if not compatible:
                continue
            fragment = self.rng.choice(compatible)
            attempted += 1
            hybrid_code = self._inject(receiver.code, fragment)
            if hybrid_code == receiver.code:
                continue
            hybrid = Individual(
                code=hybrid_code,
                parent_ids=[receiver.id, fragment.donor_id],
                tier=getattr(receiver, "tier", "laboratory"),
            )
            setattr(hybrid, "imported_fragments", [fragment.name])
            setattr(hybrid, "creation_reason", "thc_transfer")

            if self.config.validate_in_sandbox:
                result = evaluator.evaluate_batch([hybrid.code])[0]
                hybrid.score = result.score
                hybrid.fitness = result.fitness
                hybrid.passed = bool(result.passed and result.fitness.correctness >= 1.0)
                if hybrid.score < receiver.score:
                    continue
            accepted.append(hybrid)

        if accepted:
            survivors = sorted(population, key=lambda ind: ind.score, reverse=True)
            keep = max(0, len(population) - len(accepted))
            population = survivors[:keep] + accepted

        for fragment in self.fragments.values():
            fragment.survival_gens += 1

        self.metrics = THCMetrics(
            thc_transfer_rate=len(accepted) / max(1, len(population)),
            fragment_survival_gens=(
                sum(f.survival_gens for f in self.fragments.values()) / max(1, len(self.fragments))
            ),
            hybrid_lineage_depth=max((len(getattr(ind, "parent_ids", []) or []) for ind in accepted), default=0),
            transfers_attempted=attempted,
            transfers_accepted=len(accepted),
        )
        return population

    def _harvest(self, population: List[Individual]) -> None:
        for ind in population:
            if ind.score < self.config.min_donor_score:
                continue
            try:
                tree = ast.parse(ind.code)
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = getattr(node, "name", "")
                    if name.startswith("_"):
                        continue
                    self.fragments[name] = FragmentRecord(
                        name=name,
                        code=ast.unparse(node),
                        donor_id=ind.id,
                        donor_score=ind.score,
                    )

    def _inject(self, receiver_code: str, fragment: FragmentRecord) -> str:
        try:
            receiver = ast.parse(receiver_code)
            frag_tree = ast.parse(fragment.code)
        except SyntaxError:
            return receiver_code

        frag_node = frag_tree.body[0] if frag_tree.body else None
        if frag_node is None:
            return receiver_code

        replaced = False
        new_body = []
        for node in receiver.body:
            if (
                isinstance(node, type(frag_node))
                and getattr(node, "name", None) == getattr(frag_node, "name", None)
            ):
                new_body.append(copy.deepcopy(frag_node))
                replaced = True
            else:
                new_body.append(node)
        if not replaced:
            new_body.append(copy.deepcopy(frag_node))
        receiver.body = new_body
        ast.fix_missing_locations(receiver)
        try:
            code = ast.unparse(receiver)
            ast.parse(code)
            return code
        except Exception:
            return receiver_code
