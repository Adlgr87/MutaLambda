"""
Evolutionary Tipping Point Detection
=====================================

Detección robusta de puntos de inflexión (tipping points) en series
temporales de fitness evolutivo. Basado en MAD (Median Absolute Deviation)
para ser resistente a outliers.

Cuando se detecta un tipping point, se registra el evento con metadata
(generación, operador activo, islas involucradas) para alimentar el
sistema de resurrección de ramas y ajustar tasas de mutación.

Algorithm
---------
1. Ventana deslizante de tamaño W sobre la serie de fitness.
2. Para cada punto, calcular MAD de la ventana.
3. Si la desviación del punto respecto a la mediana > n_deviations × MAD,
   se marca como tipping point.
4. Agrupar puntos consecutivos en eventos únicos.

Reference
---------
Iglewicz, B. & Hoaglin, D. "How to Detect and Handle Outliers." ASQC, 1993.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
import logging

from muta_ext.config.scientific_extension import EvolutionaryExtensionConfig

logger = logging.getLogger(__name__)


@dataclass
class TippingEvent:
    """Evento de tipping point detectado.

    Attributes
    ----------
    generation : int
        Generación donde ocurrió el tipping.
    fitness_before : float
        Fitness promedio antes del tipping.
    fitness_after : float
        Fitness promedio después del tipping.
    magnitude : float
        Magnitud del cambio (MAD ratios).
    severity : str
        "low", "medium", "high", "critical".
    metadata : dict
        Información contextual (operadores, islas, etc.).
    """

    generation: int
    fitness_before: float
    fitness_after: float
    magnitude: float
    severity: str = "medium"
    metadata: Dict = field(default_factory=dict)


def mad(data: List[float]) -> float:
    """Median Absolute Deviation (robusto a outliers).

    Args:
        data: Lista de valores numéricos.

    Returns:
        MAD = median(|x_i - median(x)|).
    """
    if len(data) < 2:
        return 0.0

    data_sorted = sorted(data)
    n = len(data_sorted)
    median = data_sorted[n // 2] if n % 2 == 1 else (
        data_sorted[n // 2 - 1] + data_sorted[n // 2]
    ) / 2.0

    abs_devs = sorted(abs(x - median) for x in data)
    n_dev = len(abs_devs)
    mad_val = abs_devs[n_dev // 2] if n_dev % 2 == 1 else (
        abs_devs[n_dev // 2 - 1] + abs_devs[n_dev // 2]
    ) / 2.0

    return mad_val


def detect_tipping(
    fitness_series: List[float],
    window: int = 5,
    n_deviations: float = 3.0,
    min_magnitude: float = 0.5,
    metadata_builder: Optional[Callable[[int], Dict]] = None,
    default_metadata: Optional[Dict] = None,
    config: Optional[EvolutionaryExtensionConfig] = None,
) -> List[TippingEvent]:
    """Detecta tipping points en una serie temporal de fitness.

    Args:
        fitness_series: Lista de valores de fitness (uno por generación).
        window: Tamaño de ventana para MAD. Default=5.
        n_deviations: Número de desviaciones MAD para considerar outlier.
            Default=3.0 (conservador).
        min_magnitude: Magnitud mínima para registrar evento. Default=0.5.
        metadata_builder: Función opcional que construye metadata dado el
            índice central de evento (generación).
        default_metadata: Metadata base a aplicar a cada evento.
        config: Configuración opt-in. Si se especifica y
            enable_tipping_detection=False, se devuelve [].

    Returns:
        Lista de TippingEvent ordenados por generación.
    """
    # Graceful degradation: cuando está deshabilitado, no emitimos eventos.
    if config is not None and not config.enable_tipping_detection:
        return []

    if len(fitness_series) < window:
        return []

    events: List[TippingEvent] = []
    tipping_indices: List[int] = []

    import time

    base_metadata: Dict = default_metadata.copy() if default_metadata else {}

    # Default metadata required by manifest when an anomaly is detected.
    # Local-only (safe) enrichment; never changes global resurrección logic.
    def _default_metadata_builder(gen: int) -> Dict:
        try:
            return {
                "detector": "MAD",
                "deviation": float("nan"),  # overwritten per-event when possible
                "timestamp": time.time(),
            }
        except Exception:
            return {
                "detector": "MAD",
                "deviation": 0.0,
                "timestamp": time.time(),
            }

    metadata_builder_effective = (
        metadata_builder if metadata_builder is not None else _default_metadata_builder
    )

    for i in range(len(fitness_series)):
        # Ventana centrada en i
        start = max(0, i - window // 2)
        end = min(len(fitness_series), i + window // 2 + 1)
        window_data = fitness_series[start:end]

        if len(window_data) < 3:
            continue

        m = mad(window_data)
        if m == 0.0:
            # Fallback: usar diferencia absoluta respecto a la mediana
            data_sorted = sorted(window_data)
            median = data_sorted[len(data_sorted) // 2]
            abs_dev = abs(fitness_series[i] - median)
            if abs_dev > abs(median) * 0.2 and abs(median) > 1e-9:
                tipping_indices.append(i)
            continue

        data_sorted = sorted(window_data)
        median = data_sorted[len(data_sorted) // 2]
        deviation = abs(fitness_series[i] - median) / m

        if deviation > n_deviations:
            tipping_indices.append(i)

    if not tipping_indices:
        return []

    # ── Agrupar índices consecutivos en eventos ─────────────────────
    groups: List[List[int]] = []
    current_group = [tipping_indices[0]]

    for idx in tipping_indices[1:]:
        if idx - current_group[-1] <= 1:
            current_group.append(idx)
        else:
            groups.append(current_group)
            current_group = [idx]
    groups.append(current_group)

    # ── Crear eventos ───────────────────────────────────────────────
    for group in groups:
        gen = group[len(group) // 2]  # generación central del grupo

        # Fitness antes y después (promedios)
        before = fitness_series[:gen]
        after = fitness_series[gen:]

        avg_before = sum(before) / len(before) if before else 0.0
        avg_after = sum(after) / len(after) if after else 0.0

        # Magnitud del tipping
        m = mad(fitness_series[max(0, gen - window) : gen + window])
        magnitude = 0.0 if m == 0.0 else abs(avg_after - avg_before) / m

        if magnitude < min_magnitude:
            continue

        # Severidad
        if magnitude > 5.0:
            severity = "critical"
        elif magnitude > 3.0:
            severity = "high"
        elif magnitude > 1.5:
            severity = "medium"
        else:
            severity = "low"

        meta = dict(base_metadata)

        # Inyección local de metadata (MAD) con graceful degradation
        try:
            extra = metadata_builder_effective(gen) or {}
            meta.update(extra)
        except Exception:
            # Metadata es opcional; no debe romper la detección.
            pass

        # Rellenar deviation real si existe el campo requerido
        if "deviation" in meta:
            try:
                meta["deviation"] = float(magnitude)
            except Exception:
                pass

        events.append(
            TippingEvent(
                generation=gen,
                fitness_before=round(avg_before, 4),
                fitness_after=round(avg_after, 4),
                magnitude=round(magnitude, 2),
                severity=severity,
                metadata=meta,
            )
        )

    return events
