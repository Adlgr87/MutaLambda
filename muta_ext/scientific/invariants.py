"""Scientific invariants para la Scientific Validation Layer (SVL).

Proporciona verificaciones de integridad científica para código evolutivo.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import math


@dataclass(frozen=True)
class ScientificInvariant:
    """Representa un invariante científico a validar.

    Attributes:
        name: Identificador único del invariante
        description: Descripción legible por humanos
        check: Función que recibe (result_dict, context) y retorna bool
        severity: "hard" (falla rechaza candidato) o "soft" (penaliza pero permite continuar)
    """
    name: str
    description: str
    check: Callable[[Dict[str, Any], Dict[str, Any]], bool]
    severity: str = "hard"  # hard | soft


# ── Checks base ──────────────────────────────────────────────

def check_energy_non_negative(result: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Verifica que la energía total no sea negativa."""
    energy = result.get("total_energy", result.get("energy", None))
    if energy is None:
        return True
    return float(energy) >= -1e-9


def check_mass_conservation(result: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Verifica conservación de masa (|Δmass| < 1e-8)."""
    delta = result.get("mass_delta", result.get("mass_change", None))
    if delta is None:
        return True
    return abs(float(delta)) < 1e-8


def check_bounds_physical(result: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Verifica que cantidades físicas estén en rangos razonables."""
    BOUNDS = (1e-15, 1e15)
    phys_keys = {"temperature", "pressure", "velocity", "density", "position", "momentum"}
    for key, value in result.items():
        if key in phys_keys or any(pk in key.lower() for pk in phys_keys):
            try:
                v = float(value)
                if not (BOUNDS[0] <= v <= BOUNDS[1]):
                    return False
            except (ValueError, TypeError):
                continue
    return True


def check_monotonicity(result: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Verifica tendencias monotónicas en trayectorias (entropy no decrece)."""
    trajectory = result.get("trajectory", result.get("history", None))
    if not trajectory or not isinstance(trajectory, list) or len(trajectory) < 2:
        return True
    for field_name in ("entropy", "cumulative_energy", "total_mass"):
        values = []
        for step in trajectory:
            if isinstance(step, dict):
                v = step.get(field_name, None)
                if v is not None:
                    values.append(float(v))
        if len(values) >= 2:
            for i in range(1, len(values)):
                if values[i] < values[i - 1] - 1e-6:
                    return False
    return True


def check_numerical_stability(result: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Verifica ausencia de NaN, Inf o overflow numérico."""
    for key, value in result.items():
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return False
            if abs(value) > 1e20:
                return False
        elif isinstance(value, int) and abs(value) > 1e20:
            return False
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, float):
                    if math.isnan(item) or math.isinf(item):
                        return False
                    if abs(item) > 1e20:
                        return False
    return True


# ── Registro de invariantes base ─────────────────────────────

BASE_INVARIANTS: List[ScientificInvariant] = [
    ScientificInvariant("energy_non_negative", "Total energy >= -1e-9",
                        check_energy_non_negative, "hard"),
    ScientificInvariant("mass_conservation", "Mass change < 1e-8",
                        check_mass_conservation, "hard"),
    ScientificInvariant("physical_bounds", "Quantities in [1e-15, 1e15]",
                        check_bounds_physical, "soft"),
    ScientificInvariant("monotonicity_trend", "Entropy non-decreasing",
                        check_monotonicity, "soft"),
    ScientificInvariant("numerical_stability", "No NaN/Inf/overflow",
                        check_numerical_stability, "hard"),
]


def filter_invariants(
    invariants: Optional[List[ScientificInvariant]] = None,
    severity: Optional[str] = None,
    names: Optional[List[str]] = None,
) -> List[ScientificInvariant]:
    """Filtra invariantes por severidad o nombre.

    Args:
        invariants: Lista base; si None, usa BASE_INVARIANTS
        severity: "hard" o "soft" para filtrar por severidad
        names: Lista de nombres para filtrar

    Returns:
        Lista filtrada de invariantes
    """
    source = invariants if invariants is not None else BASE_INVARIANTS
    result = list(source)
    if severity:
        result = [inv for inv in result if inv.severity == severity]
    if names:
        name_set = set(names)
        result = [inv for inv in result if inv.name in name_set]
    return result