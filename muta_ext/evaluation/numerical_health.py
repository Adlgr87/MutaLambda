"""
Numerical Health Evaluation
============================

Meta-evaluador de estabilidad numérica para funciones generadas.
NO ejecuta el código candidato — analiza su estructura para detectar
patrones numéricamente inestables (stiffness, mal condicionamiento).

Se integra como dimensión opcional en FitnessVector (numerical_health).

Activation
----------
    config.enable_numerical_health = True
"""

import ast
import math
from dataclasses import dataclass
from typing import Optional
import logging

from muta_ext.config.scientific_extension import EvolutionaryExtensionConfig

logger = logging.getLogger(__name__)


@dataclass
class NumericalHealth:
    """Diagnóstico de salud numérica de una función generada.

    Attributes
    ----------
    stiffness_ratio : float
        Estimación de la razón de rigidez (max/min eigenvalue ratio).
        Valores altos (>1000) indican sistemas stiff propensos a
        inestabilidad numérica. 0.0 = no aplicable.
    condition_number : float
        Estimación del número de condición. Valores >1e6 son
        problemáticos. 0.0 = no aplicable.
    has_nested_loops : bool
        True si la función contiene bucles anidados con dependencias.
    has_division : bool
        True si hay división sin protección contra cero.
    has_exponential : bool
        True si hay llamadas a exp/log que pueden diverger.
    is_stable : bool
        True si ningún indicador supera umbrales de riesgo.
    score : float
        Puntuación normalizada 0.0–1.0 (1.0 = perfectamente estable).
    """

    stiffness_ratio: float = 0.0
    condition_number: float = 0.0
    has_nested_loops: bool = False
    has_division: bool = False
    has_exponential: bool = False
    is_stable: bool = True
    score: float = 1.0

    # Thresholds
    STIFFNESS_THRESHOLD: float = 1000.0
    CONDITION_THRESHOLD: float = 1e6


def evaluate_numerical_health(
    code: str,
    config: Optional[EvolutionaryExtensionConfig] = None,
) -> NumericalHealth:
    """Analiza la salud numérica de un fragmento de código.

    Realiza análisis estático del AST para detectar patrones de riesgo
    sin ejecutar el código. Útil como dimensión de fitness penalizante.

    Args:
        code: Código fuente Python a analizar.

    Returns:
        NumericalHealth con diagnóstico completo.
    """
    # Graceful degradation: cuando está deshabilitado, devolvemos un estado
    # neutral y estable.
    adaptive_score: Optional[float] = None
    if config is not None and not config.enable_numerical_health:
        return NumericalHealth()
    health = NumericalHealth()

    try:
        tree = ast.parse(code)
    except SyntaxError:
        health.is_stable = False
        health.score = 0.0
        return health

    # ── Detectar patrones de riesgo ─────────────────────────────────
    visitor = _RiskVisitor()
    visitor.visit(tree)

    health.has_nested_loops = visitor.has_nested_loops
    health.has_division = visitor.has_division
    health.has_exponential = visitor.has_exponential

    # ── Estimar stiffness ratio ─────────────────────────────────────
    # Heurística: nested loops con dependencias temporales → stiff
    if visitor.has_nested_loops:
        health.stiffness_ratio = 500.0 + visitor.loop_depth * 250.0
    if visitor.has_exponential:
        health.stiffness_ratio *= 2.0

    # ── Estimar condition number ────────────────────────────────────
    # Heurística: divisiones + operaciones de alta magnitud
    if visitor.has_division:
        health.condition_number = 100.0
        if visitor.has_exponential:
            health.condition_number *= 50.0
        if visitor.has_nested_loops:
            health.condition_number *= 10.0

    # ── Clasificar estabilidad ──────────────────────────────────────
    if (health.stiffness_ratio > NumericalHealth.STIFFNESS_THRESHOLD
            or health.condition_number > NumericalHealth.CONDITION_THRESHOLD):
        health.is_stable = False

    # ── Meta-evaluador: Solver adaptativo (safe numpy) ────────────
    if config is not None and getattr(config, "enable_adaptive_solver", False):
        try:
            import numpy as np  # type: ignore

            # Construir vector de frecuencias de tipos de nodos del AST
            node_types = [type(n).__name__ for n in ast.walk(tree)]
            if node_types:
                unique, counts = np.unique(node_types, return_counts=True)
                probs = counts.astype(float) / max(1.0, float(counts.sum()))
                # "Estabilidad" proxy: entropía baja => más determinismo
                entropy = float(-np.sum(probs * np.log(probs + 1e-12)))
                # Score adicional: entre 0..1 aproximado
                adaptive_score = float(np.exp(-entropy))
                # Combinación conservadora: no sobrepasa el score heurístico si es peor
                health.score = min(health.score, adaptive_score)
                # Si score adaptativo es muy bajo, marcar inestabilidad
                if health.score <= 0.0:
                    health.is_stable = False
                    health.score = 0.0
        except Exception as exc:
            # Caja de arena: no detener la simulación
            logger.warning("Adaptive solver meta-evaluator failed: %r", exc)
            health.is_stable = False
            health.score = 0.0
            return health

    # ── Score normalizado ───────────────────────────────────────────
    # (recalcular tras posibles ajustes arriba)
    health.score = _compute_stability_score(health)
    if adaptive_score is not None:
        health.score = min(health.score, adaptive_score)

    return health


class _RiskVisitor(ast.NodeVisitor):
    """Visitor que detecta patrones de riesgo numérico."""

    def __init__(self):
        self.has_nested_loops = False
        self.has_division = False
        self.has_exponential = False
        self.loop_depth = 0
        self._current_loop_depth = 0

    def visit_For(self, node):
        self._current_loop_depth += 1
        if self._current_loop_depth > 1:
            self.has_nested_loops = True
        self.loop_depth = max(self.loop_depth, self._current_loop_depth)
        self.generic_visit(node)
        self._current_loop_depth -= 1

    def visit_While(self, node):
        self._current_loop_depth += 1
        if self._current_loop_depth > 1:
            self.has_nested_loops = True
        self.loop_depth = max(self.loop_depth, self._current_loop_depth)
        self.generic_visit(node)
        self._current_loop_depth -= 1

    def visit_BinOp(self, node):
        if isinstance(node.op, ast.Div):
            self.has_division = True
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in ("exp", "log", "pow", "math.exp",
                               "math.log", "math.pow", "np.exp"):
                self.has_exponential = True
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in ("exp", "log", "pow"):
                self.has_exponential = True
        self.generic_visit(node)


def _compute_stability_score(health: NumericalHealth) -> float:
    """Calcula score de estabilidad 0.0–1.0."""
    penalty = 0.0

    if health.has_nested_loops:
        penalty += 0.2
    if health.has_division:
        penalty += 0.1
    if health.has_exponential:
        penalty += 0.15
    if health.stiffness_ratio > 100:
        penalty += min(0.3, health.stiffness_ratio / 10000.0)
    if health.condition_number > 10:
        penalty += min(0.25, math.log10(health.condition_number) / 10.0)

    return max(0.0, 1.0 - penalty)