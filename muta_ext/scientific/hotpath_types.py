"""Data types para hot-path profiling y mutación inter-procedural."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class HotPath:
    """Representa una función identificada como hot-path.

    Attributes:
        function_name: Nombre de la función
        file_path: Archivo donde está definida
        cumulative_time: Tiempo acumulado en segundos
        cumulative_pct: Porcentaje del tiempo total
        call_count: Número de llamadas
        is_entry: Si es el punto de entrada
        line_number: Línea donde se llama
        is_hotpath: Flag (siempre True, para extensibilidad)
    """
    function_name: str
    file_path: str
    cumulative_time: float
    cumulative_pct: float
    call_count: int = 1
    is_entry: bool = False
    line_number: int = 0
    is_hotpath: bool = True


@dataclass
class HotPathResult:
    """Resultado del profiling de un workload."""
    hot_paths: List[HotPath] = field(default_factory=list)
    total_time: float = 0.0
    profiler: str = "cprofile"
    entry_point: str = ""
    error: Optional[str] = None

    @property
    def has_hot_paths(self) -> bool:
        """Indica si se encontraron hot-paths."""
        return len(self.hot_paths) > 0

    @property
    def top_function(self) -> Optional[HotPath]:
        """Retorna la función más lenta, si existe."""
        return self.hot_paths[0] if self.hot_paths else None

    def filter_by_threshold(self, min_pct: float = 5.0) -> "HotPathResult":
        """Filtra hot-paths por porcentaje acumulativo mínimo."""
        filtered = [hp for hp in self.hot_paths if hp.cumulative_pct >= min_pct]
        return HotPathResult(
            hot_paths=filtered, total_time=self.total_time,
            profiler=self.profiler, entry_point=self.entry_point
        )


@dataclass
class ProfileConfig:
    """Configuración para el profiling de hot-paths."""
    enabled: bool = True
    profiler: str = "cprofile"
    min_cumulative_pct: float = 5.0
    max_hot_functions: int = 15
    interprocedural_prob: float = 0.25
    max_functions_per_mutation: int = 3
    depth: int = 1