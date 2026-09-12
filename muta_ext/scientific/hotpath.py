"""Hot-path detection usando cProfile."""

from __future__ import annotations
import cProfile
import io
import logging
import pstats
from typing import Any, Callable, List, Optional

from muta_ext.scientific.hotpath_types import HotPath, HotPathResult, ProfileConfig

logger = logging.getLogger("MutaLambda.Scientific.HotPath")


def profile_code(
    entry_point: str,
    workload: Callable[[], Any],
    profiler: str = "cprofile",
    min_cumulative_pct: float = 5.0,
    max_hot_functions: int = 15,
) -> List[HotPath]:
    """Profilea un workload y extrae funciones hot-path.

    Args:
        entry_point: Nombre del punto de entrada
        workload: Callable a ejecutar y medir
        profiler: Profiler a usar ("cprofile" actualmente)
        min_cumulative_pct: Umbral mínimo de porcentaje de tiempo
        max_hot_functions: Máximo número de funciones a retornar

    Returns:
        Lista de HotPath identificadas

    Raises:
        RuntimeError: Si el workload falla o el profiler tiene error
    """
    if profiler == "none":
        return []

    if profiler != "cprofile":
        logger.warning("Unsupported profiler '%s', fallback to cprofile", profiler)

    try:
        prof = cProfile.Profile()
        prof.enable()
        try:
            workload()
        except Exception as exc:
            raise RuntimeError(f"Workload failed: {exc}") from exc
        finally:
            prof.disable()

        stream = io.StringIO()
        stats = pstats.Stats(prof, stream=stream).sort_stats("cumulative")
        stats.print_stats()

        return _parse_cprofile_output(
            stream.getvalue(), entry_point, min_cumulative_pct,
            max_hot_functions, _get_total_time(stats),
        )

    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"cProfile failed: {exc}") from exc


def profile_workload(
    entry_point: str,
    workload: Callable[[], Any],
    config: Optional[ProfileConfig] = None,
) -> HotPathResult:
    """Profilea un workload con configuración completa.

    Args:
        entry_point: Nombre del punto de entrada
        workload: Callable a ejecutar
        config: Configuración de profiling; si None, usa defaults

    Returns:
        HotPathResult con lista de hot-paths o error
    """
    if config is None:
        config = ProfileConfig()
    if not config.enabled:
        return HotPathResult(profiler="none", entry_point=entry_point)

    try:
        hot_paths = profile_code(
            entry_point=entry_point, workload=workload,
            profiler=config.profiler,
            min_cumulative_pct=config.min_cumulative_pct,
            max_hot_functions=config.max_hot_functions,
        )
        total = sum(hp.cumulative_time for hp in hot_paths) if hot_paths else 0.0
        return HotPathResult(
            hot_paths=hot_paths, total_time=total,
            profiler=config.profiler, entry_point=entry_point
        )
    except RuntimeError as exc:
        return HotPathResult(
            profiler=config.profiler, entry_point=entry_point, error=str(exc)
        )


# ── Internal helpers ──────────────────────────────────────────

def _get_total_time(stats: pstats.Stats) -> float:
    """Extrae el tiempo total de ejecución de las estadísticas."""
    return getattr(stats, 'total_tt', 0.0)


def _parse_cprofile_output(
    output: str,
    entry_point: str,
    min_pct: float,
    max_functions: int,
    total_time: float,
) -> List[HotPath]:
    """Parsea la salida de cprofile y extrae HotPath.

    Args:
        output: Salida texto de cprofile
        entry_point: Nombre del punto de entrada
        min_pct: Umbral mínimo de porcentaje
        max_functions: Máximo número de funciones
        total_time: Tiempo total de ejecución

    Returns:
        Lista de HotPath parseadas
    """
    hot_paths: List[HotPath] = []
    lines = output.strip().split("\n")
    data_lines, started = [], False

    # Skip header until function table
    for line in lines:
        if not started and "function" in line and "(" in line:
            started = True
            continue
        if started and line.strip() and not line.startswith("---"):
            data_lines.append(line)
        elif line.startswith("---"):
            break

    for line in data_lines:
        parts = line.strip().split()
        if len(parts) < 6:
            continue
        try:
            ncalls, cumtime = parts[0], float(parts[3])
            location = " ".join(parts[5:])
        except (ValueError, IndexError):
            continue

        if "(" in location and location.endswith(")"):
            func_part = location[location.rindex("(") + 1:location.rindex(")")]
            file_part = location[:location.rindex("(") - 1]
        else:
            func_part, file_part = location, ""

        line_number = 0
        if ":" in file_part:
            try:
                file_part, line_str = file_part.rsplit(":", 1)
                line_number = int(line_str) if line_str.isdigit() else 0
            except ValueError:
                pass

        call_count = 1
        if "/" in str(ncalls):
            try:
                call_count = int(ncalls.split("/")[0])
            except ValueError:
                pass
        elif ncalls.isdigit():
            call_count = int(ncalls)

        pct = (cumtime / total_time * 100) if total_time > 0 else 0.0

        # Skip builtin/python internals
        if func_part.startswith("<"):
            continue

        hot_paths.append(HotPath(
            function_name=func_part, file_path=file_part,
            cumulative_time=cumtime, cumulative_pct=round(pct, 2),
            call_count=call_count, is_entry=(func_part == entry_point),
            line_number=line_number,
        ))

    hot_paths = [hp for hp in hot_paths if hp.cumulative_pct >= min_pct]
    hot_paths.sort(key=lambda hp: hp.cumulative_time, reverse=True)
    return hot_paths[:max_functions]