"""Unified telemetry for MutaLambda FASE 1+ runs.

Captures latency, memory (peak traced) and optional GPU counters around an
arbitrary callable, producing a :class:`TelemetrySnapshot` that the FASE 6
benchmark pipeline persists alongside benchmark results.

Thin wrapper (kept under 200 lines per the repo's refactor policy) — no
external deps beyond stdlib so it never degrades a failing run into a hard
import error.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class TelemetrySnapshot:
    elapsed_sec: float
    mem_peak_mb: float
    mem_traced_mb: float
    run_id: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "elapsed_sec": round(self.elapsed_sec, 6),
            "mem_peak_mb": round(self.mem_peak_mb, 3),
            "mem_traced_mb": round(self.mem_traced_mb, 3),
            "run_id": self.run_id,
            "tags": dict(self.tags),
            "extra": dict(self.extra),
        }


def _try_gpu_allocated_mb() -> Optional[float]:
    """Return GPU memory allocated (MB) if torch+cuda is available, else None."""
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / (1024 * 1024)
    except Exception:
        pass
    return None


@contextlib.contextmanager
def trace_telemetry(
    run_id: str = "",
    tags: Optional[Dict[str, str]] = None,
) -> Any:
    """Context manager yielding a dict you can mutate with ``extra`` fields.

    Example::

        with trace_telemetry("r1", {"phase": "ablation"}) as t:
            do_work()
        print(t["snapshot"].to_dict())
    """
    tracemalloc.start()
    start = time.perf_counter()
    gpu0 = _try_gpu_allocated_mb()
    holder: Dict[str, Any] = {"snapshot": None, "extra": {}}
    try:
        yield holder
    finally:
        elapsed = time.perf_counter() - start
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        gpu1 = _try_gpu_allocated_mb()
        holder["snapshot"] = TelemetrySnapshot(
            elapsed_sec=elapsed,
            mem_peak_mb=peak / (1024 * 1024),
            mem_traced_mb=cur / (1024 * 1024),
            run_id=run_id,
            tags=dict(tags or {}),
            extra={
                "gpu_allocated_mb_start": gpu0,
                "gpu_allocated_mb_end": gpu1,
            },
        )


def measure(
    fn: Callable[[], Any],
    run_id: str = "",
    tags: Optional[Dict[str, str]] = None,
) -> TelemetrySnapshot:
    """Run ``fn`` under the telemetry context and return the snapshot."""
    with trace_telemetry(run_id=run_id, tags=tags) as t:
        fn()
    snap = t["snapshot"]
    assert snap is not None
    return snap


def is_ci() -> bool:
    return os.environ.get("CI", "").lower() in {"1", "true", "yes"} or bool(
        os.environ.get("GITHUB_ACTIONS")
    )


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
