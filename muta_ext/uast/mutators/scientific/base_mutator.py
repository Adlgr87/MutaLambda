"""Base classes para operadores de mutación científicos."""

from __future__ import annotations
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

# Import CoreUAST nodes - will work with actual imports
try:
    from muta_ext.uast.core_uast import CoreUAST, Node, Function, For, While, If
except ImportError:
    # Fallback for testing
    @dataclass
    class Node: pass
    @dataclass
    class CoreUAST:
        body: List = []
        language: str = "python"
        metadata: Dict = {}
    @dataclass
    class Function(Node):
        name: Any = None
        params: List = []
        body: List = []
        decorators: List = []
        return_type: Any = None
        tag: Any = None
    @dataclass
    class For(Node):
        var: Any = None
        iterable: Any = None
        body: List = []
        is_traditional: bool = True
    @dataclass
    class While(Node):
        condition: Any = None
        body: List = []
        is_traditional: bool = True
    @dataclass
    class If(Node):
        condition: Any = None
        then_body: List = []
        else_body: Any = None


@dataclass
class MutationResult:
    """Resultado de aplicar un mutador a un UAST.

    Attributes:
        mutated_uast: UAST resultante (puede ser igual al original)
        applied: Si realmente se aplicó una mutación
        description: Descripción del cambio aplicado
        score_impact: Impacto estimado en el score
        confidence: Confianza en el cambio (0.0 - 1.0)
    """
    mutated_uast: CoreUAST
    applied: bool = False
    description: str = ""
    score_impact: float = 0.0
    confidence: float = 0.5


class BaseMutator(ABC):
    """Interfaz base para mutadores de UAST."""

    @abstractmethod
    def mutate(self, uast: CoreUAST, rng_seed: Optional[int] = None) -> MutationResult:
        """Aplica una mutación al UAST.

        Args:
            uast: UAST a mutar
            rng_seed: Semilla para reproducibilidad

        Returns:
            MutationResult con UAST mutado
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Nombre identificador del mutador."""
        ...

    @abstractmethod
    def domain_tags(self) -> Dict[str, str]:
        """Etiquetas de dominio para clasificación."""
        ...


class BaseScientificMutator(BaseMutator):
    """Base para mutadores de dominio científico."""
    domain = "scientific"
    strength = 0.3

    def domain_tags(self) -> Dict[str, str]:
        return {"domain": self.domain, "strength": str(self.strength)}

    def mutate_functions(
        self,
        uast: CoreUAST,
        rng_seed: Optional[int],
        transform: Callable[[Function, random.Random, List[str]], Optional[Function]],
        *,
        score_impact: float,
        confidence: float,
    ) -> MutationResult:
        """Apply ``transform`` to every top-level function and wrap the result.

        ``transform(func, rng, descriptions)`` returns the rewritten function, or
        the function itself when nothing changed. The mutation is reported as
        applied only when at least one function was rewritten.
        """
        rng = random.Random(rng_seed) if rng_seed is not None else random.Random()
        new_body, changed = list(uast.body), False
        descs: List[str] = []

        for idx, node in enumerate(new_body):
            if isinstance(node, Function):
                nf = transform(node, rng, descs)
                if nf is not None and nf is not node:
                    new_body[idx], changed = nf, True

        if not changed:
            return MutationResult(
                CoreUAST(list(uast.body), uast.language, dict(uast.metadata)),
                applied=False
            )

        return MutationResult(
            CoreUAST(new_body, uast.language, dict(uast.metadata)),
            applied=True, description="; ".join(descs),
            score_impact=score_impact, confidence=confidence
        )

    @staticmethod
    def with_body(func: Function, body: List) -> Function:
        """Copy ``func`` with a new body."""
        return Function(
            func.name, list(func.params), body,
            list(func.decorators), func.return_type, func.tag
        )

    def find_functions(self, uast: CoreUAST) -> List[Function]:
        """Encuentra todas las funciones definidas en el UAST."""
        return [n for n in uast.body if isinstance(n, Function)]

    def find_loops(self, uast: CoreUAST) -> List[For]:
        """Encuentra todos los bucles en el UAST."""
        loops: List[For] = []
        for n in uast.body:
            loops.extend(self._collect_loops(n))
        return loops

    def _collect_loops(self, node: Node) -> List[For]:
        """Recopila bucles recursivamente desde un nodo."""
        loops: List[For] = []
        if isinstance(node, (For, While)):
            loops.append(node)
        body: List = []
        if isinstance(node, Function):
            body = node.body
        elif isinstance(node, If):
            body = node.then_body + (node.else_body or [])
        elif isinstance(node, For):
            body = node.body
        elif isinstance(node, While):
            body = node.body
        for c in body:
            loops.extend(self._collect_loops(c))
        return loops