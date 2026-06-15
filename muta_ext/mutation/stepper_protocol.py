"""
Mutation Stepper Protocol
==========================

Protocolo de composición de steppers de mutación. Define una interfaz
común para todos los operadores de mutación (AST, LLM, crossover,
cross-branch) permitiendo composición y pesos configurables vía YAML.

Inspirado en el patrón Strategy + Chain of Responsibility.

Usage
-----
    steppers = [
        ASTStepper(weight=0.6),
        CrossBranchStepper(weight=0.1),
    ]
    composer = MutationComposer(steppers, rng=random.Random(42))
    result = composer.step(code, context={"score": -5.0, "error": "..."})
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, runtime_checkable
import random
import logging

logger = logging.getLogger(__name__)


@dataclass
class MutationResult:
    """Resultado de una operación de mutación.

    Attributes
    ----------
    code : str
        Código mutado.
    stepper_name : str
        Nombre del stepper que produjo esta mutación.
    success : bool
        True si la mutación se aplicó correctamente.
    metadata : dict
        Información adicional (tipo de operador, diff stats, etc.).
    """
    code: str
    stepper_name: str = "unknown"
    success: bool = True
    metadata: Dict = field(default_factory=dict)


@runtime_checkable
class MutationStepper(Protocol):
    """Protocolo para steppers de mutación componibles.

    Cada stepper implementa una estrategia de mutación específica
    (AST, LLM, crossover, etc.) y puede ser compuesto con otros
    steppers vía pesos.

    Methods
    -------
    step(code, context, rng) -> MutationResult
        Aplica la mutación y retorna el resultado.
    name : str (property)
        Identificador único del stepper.
    weight : float (property)
        Peso relativo para composición (0.0–1.0).
    """

    def step(self, code: str, context: Dict, rng: random.Random) -> MutationResult:
        """Aplica la mutación al código dado.

        Args:
            code: Código fuente a mutar.
            context: Diccionario con información contextual
                (score, error_info, generation, island_id, etc.).
            rng: Instancia de random.Random para reproducibilidad.

        Returns:
            MutationResult con el código mutado y metadata.
        """
        ...

    @property
    def name(self) -> str:
        """Identificador único del stepper."""
        ...

    @property
    def weight(self) -> float:
        """Peso relativo para composición (0.0–1.0)."""
        ...


class MutationComposer:
    """Compone múltiples steppers con selección ponderada.

    Attributes
    ----------
    steppers : List[MutationStepper]
        Lista de steppers registrados.
    rng : random.Random
        Generador de números aleatorios para selección.
    """

    def __init__(self, steppers: List[MutationStepper],
                 rng: Optional[random.Random] = None):
        self.steppers = steppers
        self.rng = rng or random.Random()
        self._stats: Dict[str, int] = {}  # stepper_name → call count

        # Normalizar pesos
        total_weight = sum(s.weight for s in steppers)
        if total_weight > 0:
            self._cumulative = []
            cum = 0.0
            for s in steppers:
                cum += s.weight / total_weight
                self._cumulative.append(cum)
        else:
            self._cumulative = [1.0 / len(steppers)] * len(steppers)

    def step(self, code: str, context: Optional[Dict] = None) -> MutationResult:
        """Selecciona un stepper por peso y aplica la mutación.

        Args:
            code: Código fuente a mutar.
            context: Diccionario contextual (opcional).

        Returns:
            MutationResult con el código mutado.
        """
        ctx = context or {}

        # Selección ponderada
        roll = self.rng.random()
        for i, cum in enumerate(self._cumulative):
            if roll <= cum:
                stepper = self.steppers[i]
                break
        else:
            stepper = self.steppers[-1]

        result = stepper.step(code, ctx, self.rng)
        self._stats[stepper.name] = self._stats.get(stepper.name, 0) + 1

        return result

    def stats(self) -> Dict[str, int]:
        """Estadísticas de uso de steppers."""
        return dict(self._stats)


# ── Built-in stepper implementations ─────────────────────────────────────────


class ASTStepper:
    """Stepper de mutación AST-guaranteed (13 operadores)."""

    def __init__(self, weight: float = 0.6):
        self._weight = weight

    @property
    def name(self) -> str:
        return "ast"

    @property
    def weight(self) -> float:
        return self._weight

    def step(self, code: str, context: Dict, rng: random.Random) -> MutationResult:
        # ASTStepper delegates to Island._mutate_with_context
        # Fallback: lightweight inline mutation for testing
        ops = [
            ("rename_var", lambda c: c.replace("x", "_x").replace("_x", "x", 1)),
            ("dead_store", lambda c: c + "\n    _unused = 0"),
            ("swap_ifelse", lambda c: c),
            ("add_early_return", lambda c: "    return None\n" + c),
        ]
        op_name, op_fn = rng.choice(ops)
        try:
            mutated = op_fn(code)
            return MutationResult(
                code=mutated, stepper_name=self.name, success=True,
                metadata={"operator": op_name},
            )
        except Exception as e:
            return MutationResult(
                code=code, stepper_name=self.name, success=False,
                metadata={"operator": op_name, "error": str(e)},
            )


class CrossBranchStepper:
    """Stepper de crossover entre ramas genealógicas distantes."""

    def __init__(self, weight: float = 0.1):
        self._weight = weight

    @property
    def name(self) -> str:
        return "cross_branch"

    @property
    def weight(self) -> float:
        return self._weight

    def step(self, code: str, context: Dict, rng: random.Random) -> MutationResult:
        # Delegado al agente (requiere acceso al LineageGraph)
        return MutationResult(
            code=code, stepper_name=self.name, success=False,
            metadata={"info": "requires agent context"},
        )