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
    """Compone múltiples steppers con selección ponderada o bandit.

    Attributes
    ----------
    steppers : List[MutationStepper]
        Lista de steppers registrados.
    rng : random.Random
        Generador de números aleatorios para selección.
    bandit : optional OperatorBandit
        When set, selects operators adaptively (ML-M04).
    """

    def __init__(
        self,
        steppers: List[MutationStepper],
        rng: Optional[random.Random] = None,
        bandit: Optional[object] = None,
    ):
        self.steppers = steppers
        self.rng = rng or random.Random()
        self.bandit = bandit
        self._stats: Dict[str, int] = {}  # stepper_name → call count
        self._by_name: Dict[str, MutationStepper] = {s.name: s for s in steppers}

        if self.bandit is not None:
            for s in steppers:
                try:
                    self.bandit.register(s.name)  # type: ignore[attr-defined]
                except Exception:
                    pass

        # Normalizar pesos (fallback when bandit disabled)
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
        """Selecciona un stepper (bandit o peso) y aplica la mutación.

        Args:
            code: Código fuente a mutar.
            context: Diccionario contextual (opcional).

        Returns:
            MutationResult con el código mutado.
        """
        ctx = context or {}

        stepper = None
        if self.bandit is not None and self._by_name:
            try:
                name = self.bandit.select()  # type: ignore[attr-defined]
                stepper = self._by_name.get(name)
            except Exception:
                stepper = None
        if stepper is None:
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
        result.metadata = dict(result.metadata or {})
        result.metadata["operator"] = stepper.name
        return result

    def report_outcome(
        self,
        operator: str,
        *,
        syntax_or_security_failure: bool = False,
        correct: bool = False,
        improved: bool = False,
        gain: float = 0.0,
    ) -> None:
        """Update optional bandit with observed reward."""
        if self.bandit is None:
            return
        try:
            from operator_bandit import compute_operator_reward

            reward = compute_operator_reward(
                syntax_or_security_failure=syntax_or_security_failure,
                correct=correct,
                improved=improved,
                gain=gain,
            )
            self.bandit.update(  # type: ignore[attr-defined]
                operator,
                reward,
                valid=correct and not syntax_or_security_failure,
                improved=improved,
                gain=gain,
            )
        except Exception:
            pass

    def stats(self) -> Dict[str, int]:
        """Estadísticas de uso de steppers."""
        return dict(self._stats)


# ── Built-in stepper implementations ─────────────────────────────────────────


class ASTStepper:
    """Stepper de mutación AST-guaranteed.

    Implementación (opt-in) que delega en ``ASTMutator`` del motor MutaLambda
    para asegurar que la mutación mantiene sintaxis válida.
    """

    def __init__(self, weight: float = 0.6):
        self._weight = weight

    @property
    def name(self) -> str:
        return "ast"

    @property
    def weight(self) -> float:
        return self._weight

    def step(self, code: str, context: Dict, rng: random.Random) -> MutationResult:
        op_name = "ast_mutator"
        try:
            # Import local para evitar ciclos; ASTMutator vive en muta_lambda.py
            from muta_lambda import ASTMutator  # type: ignore

            mutated = ASTMutator.apply_random_mutation(code)
            if not mutated:
                return MutationResult(
                    code=code,
                    stepper_name=self.name,
                    success=False,
                    metadata={"operator": op_name, "error": "empty_mutation"},
                )

            return MutationResult(
                code=mutated,
                stepper_name=self.name,
                success=True,
                metadata={"operator": op_name},
            )
        except Exception as e:
            # Graceful degradation: conservar el código original
            return MutationResult(
                code=code,
                stepper_name=self.name,
                success=False,
                metadata={"operator": op_name, "error": str(e)},
            )


class CrossBranchStepper:
    """Stepper de crossover entre ramas genealógicas distantes.

    Requiere contexto para acceder a linaje / agent y seleccionar un segundo
    progenitor. Si el contexto no está presente, degrada con success=False.
    """

    def __init__(self, weight: float = 0.1):
        self._weight = weight

    @property
    def name(self) -> str:
        return "cross_branch"

    @property
    def weight(self) -> float:
        return self._weight

    def step(self, code: str, context: Dict, rng: random.Random) -> MutationResult:
        # Mínimo contrato: requiere un objeto "agent" o una interfaz equivalente.
        agent = context.get("agent")
        if agent is None:
            return MutationResult(
                code=code,
                stepper_name=self.name,
                success=False,
                metadata={"info": "requires agent context"},
            )

        # Si el agente expone un hook de crossover cross-branch, úsalo.
        try:
            crossover_fn = getattr(agent, "_cross_branch_crossover", None)
            if not callable(crossover_fn):
                return MutationResult(
                    code=code,
                    stepper_name=self.name,
                    success=False,
                    metadata={"info": "agent_missing_cross_branch_hook"},
                )

            # Se asume que el hook devuelve un objeto Individual o código.
            result = crossover_fn(context.get("island"))  # type: ignore[arg-type]
            out_code = getattr(result, "code", None)
            if isinstance(out_code, str) and out_code:
                return MutationResult(
                    code=out_code,
                    stepper_name=self.name,
                    success=True,
                    metadata={"operator": "cross_branch"},
                )
        except Exception as e:
            return MutationResult(
                code=code,
                stepper_name=self.name,
                success=False,
                metadata={"error": str(e), "operator": "cross_branch"},
            )

        return MutationResult(
            code=code,
            stepper_name=self.name,
            success=False,
            metadata={"info": "cross_branch_unavailable"},
        )
