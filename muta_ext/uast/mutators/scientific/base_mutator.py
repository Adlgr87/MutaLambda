"""Base classes para operadores de mutación científicos."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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