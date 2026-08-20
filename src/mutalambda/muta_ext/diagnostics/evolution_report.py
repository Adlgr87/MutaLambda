"""
Evolutionary Diagnostic Report
===============================

Reporte de diagnóstico evolutivo que incluye métricas de convergencia,
diversidad y estabilidad. Diseñado para serialización JSON y consumo
desde el dashboard Streamlit.

Métricas
--------
- Shannon entropy: diversidad genética de la población
- Lyapunov exponent: tasa de divergencia entre generaciones consecutivas
- Spectral stability: estabilidad de la distribución de fitness
- Classification: converging / exploring / stalled / unstable

Usage
-----
    report = EvolutionReport.compute(
        fitness_history=agent._fitness_history,
        generation=gen,
        diversity=cross_diversity,
    )
    dashboard_dict = report.to_dashboard_dict()
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import math
import logging

logger = logging.getLogger(__name__)


@dataclass
class EvolutionReport:
    """Reporte completo de diagnóstico evolutivo para una generación.

    Attributes
    ----------
    generation : int
        Generación actual.
    shannon_entropy : float
        Entropía de Shannon de la distribución de fitness (bits).
        Alta = alta diversidad. Baja = convergencia.
    lyapunov_exponent : float
        Exponente de Lyapunov aproximado. Positivo = divergencia,
        negativo = convergencia, ~0 = exploración estable.
    spectral_radius : float
        Radio espectral de la matriz de fitness (max eigenvalue ratio).
    diversity_score : float
        Puntuación de diversidad normalizada 0.0–1.0.
    stability_classification : str
        "converging", "exploring", "stalled", "unstable".
    mean_fitness : float
        Fitness promedio de la población.
    best_fitness : float
        Mejor fitness de la generación.
    fitness_std : float
        Desviación estándar del fitness.
    """

    generation: int = 0
    shannon_entropy: float = 0.0
    lyapunov_exponent: float = 0.0
    spectral_radius: float = 0.0
    diversity_score: float = 0.0
    stability_classification: str = "exploring"
    mean_fitness: float = 0.0
    best_fitness: float = 0.0
    fitness_std: float = 0.0
    metadata: Dict = field(default_factory=dict)

    @classmethod
    def compute(
        cls,
        fitness_history: List[float],
        generation: int,
        diversity: float = 0.0,
        population_scores: Optional[List[float]] = None,
    ) -> "EvolutionReport":
        """Calcula el reporte de diagnóstico para la generación actual.

        Args:
            fitness_history: Serie temporal de mejor fitness por generación.
            generation: Generación actual.
            diversity: Diversidad entre islas (0.0–1.0).
            population_scores: Scores de todos los individuos (opcional).

        Returns:
            EvolutionReport con todas las métricas calculadas.
        """
        report = cls(generation=generation)
        report.diversity_score = diversity
        report.metadata = {"population_size": len(population_scores or [])}

        # ── Mean / Best / Std de fitness ────────────────────────────
        if population_scores:
            report.mean_fitness = sum(population_scores) / len(population_scores)
            report.best_fitness = max(population_scores)
            report.fitness_std = _std(population_scores, report.mean_fitness)

        # ── Shannon entropy ─────────────────────────────────────────
        report.shannon_entropy = _shannon_entropy(population_scores or [])

        # ── Lyapunov exponent ───────────────────────────────────────
        report.lyapunov_exponent = _lyapunov_approx(fitness_history)

        # ── Spectral radius ─────────────────────────────────────────
        report.spectral_radius = _spectral_radius(population_scores or [])

        # ── Classification ──────────────────────────────────────────
        report.stability_classification = _classify(
            report.lyapunov_exponent,
            report.shannon_entropy,
            report.diversity_score,
            fitness_history,
        )

        return report

    def to_dashboard_dict(self) -> Dict:
        """Serializa el reporte para consumo del dashboard Streamlit.

        Garantiza campos serializables a JSON y graceful degradation:
        si módulos científicos están apagados, devuelve defaults vacíos
        sin lanzar KeyError.
        """
        # Safe metadata (optional extensions)
        cache_stats = self.metadata.get("cache_stats", {}) if isinstance(self.metadata, dict) else {}
        compression_stats = (
            self.metadata.get("lineage_compression", {})
            if isinstance(self.metadata, dict)
            else {}
        )
        tipping_alerts = (
            self.metadata.get("tipping_alerts", [])
            if isinstance(self.metadata, dict)
            else []
        )

        # Keep stable top-level fields for the dashboard
        return {
            "generation": self.generation,
            "shannon_entropy": round(self.shannon_entropy, 4),
            "lyapunov_exponent": round(self.lyapunov_exponent, 4),
            "spectral_radius": round(self.spectral_radius, 4),
            "diversity_score": round(self.diversity_score, 4),
            "classification": self.stability_classification,
            "mean_fitness": round(self.mean_fitness, 4),
            "best_fitness": round(self.best_fitness, 4),
            "fitness_std": round(self.fitness_std, 4),
            # Optional extension fields (defaults safe)
            "cache_stats": cache_stats,
            "lineage_compression": compression_stats,
            "tipping_alerts": tipping_alerts,
        }


# ── Internal helpers ────────────────────────────────────────────────────────


def _shannon_entropy(scores: List[float]) -> float:
    """Entropía de Shannon de una distribución de scores.

    Normaliza scores a una distribución de probabilidad y calcula
    H = -Σ p_i × log₂(p_i). Alta entropía = alta diversidad.
    """
    if not scores or len(scores) < 2:
        return 0.0

    # Shift para manejar scores negativos
    min_score = min(scores)
    shifted = [s - min_score + 1e-9 for s in scores]
    total = sum(shifted)
    if total == 0:
        return 0.0

    probs = [s / total for s in shifted]
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)
    return max(0.0, entropy)


def _lyapunov_approx(fitness_history: List[float]) -> float:
    """Exponente de Lyapunov aproximado.

    λ ≈ (1/N) Σ log(|δf_i / δf_{i-1}|)
    donde δf_i = fitness_i - fitness_{i-1}.

    λ > 0: divergencia (exploración caótica)
    λ < 0: convergencia (estabilización)
    λ ≈ 0: exploración estable
    """
    if len(fitness_history) < 3:
        return 0.0

    diffs = []
    for i in range(1, len(fitness_history)):
        diff = abs(fitness_history[i] - fitness_history[i - 1])
        if diff > 0:
            diffs.append(diff)

    if len(diffs) < 2:
        return 0.0

    lyap_sum = 0.0
    count = 0
    for i in range(1, len(diffs)):
        if diffs[i - 1] > 0 and diffs[i] > 0:
            ratio = diffs[i] / diffs[i - 1]
            lyap_sum += math.log(ratio)
            count += 1

    return lyap_sum / count if count > 0 else 0.0


def _spectral_radius(scores: List[float]) -> float:
    """Radio espectral: ratio entre max y min score (no negativo).

    Valores altos indican dispersión extrema en la población.
    """
    if not scores or len(scores) < 2:
        return 0.0

    abs_scores = [abs(s) for s in scores]
    max_abs = max(abs_scores)
    min_abs = min(abs_scores)

    if min_abs < 1e-9:
        return float("inf") if max_abs > 0 else 0.0
    return max_abs / min_abs


def _std(values: List[float], mean: float) -> float:
    """Desviación estándar poblacional."""
    if len(values) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _classify(
    lyapunov: float,
    entropy: float,
    diversity: float,
    fitness_history: List[float],
) -> str:
    """Clasifica el estado evolutivo actual.

    Returns:
        "converging": fitness mejorando consistentemente, entropía bajando
        "exploring": diversidad alta, exploración activa
        "stalled": sin mejora por varias generaciones
        "unstable": divergencia caótica (lyapunov > 0.5)
    """
    if lyapunov > 0.5:
        return "unstable"

    # Detectar estancamiento
    if len(fitness_history) >= 5:
        recent = fitness_history[-5:]
        if max(recent) - min(recent) < 0.01 * abs(max(recent)):
            return "stalled"

    if entropy < 0.5 and lyapunov < -0.1:
        return "converging"

    if diversity > 0.3 and entropy > 1.0:
        return "exploring"

    return "exploring"