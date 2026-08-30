"""Sandbox evaluation for generated Python code.

Remediation notes
-----------------
- Security boundary is the CandidateRunner (subprocess/container), not AST alone.
- SandboxEvaluator remains the public interface used by islands and tests.
- Internally it delegates to EvaluationService (cache + lazy pool).

Hardening (Phase 6.5)
---------------------
- ``SubprocessRunner`` (default) enforces ``RLIMIT_AS`` memory cap and ``timeout_sec``
  per candidate via ``resource.setrlimit`` + ``subprocess.run(timeout=...)``.
- ``ContainerRunner`` mode mounts a read-only rootfs with ``--network=none``,
  ``--cap-drop=ALL`` (Docker/Podman) when available; otherwise falls back to the
  subprocess ulimit path.
- ``enforce_ast_scan=True`` (default) rejects candidates with dangerous constructs
  (``exec``, ``eval``, ``__import__``, ``os.system``) *before* execution.
- Production callers should set ``runner_mode="container"`` for untrusted code.
  ``SubprocessRunner`` is RLIMIT/timeout isolation only — not a full sandbox.
"""

from __future__ import annotations

import atexit
import logging
import multiprocessing
import os
import warnings
from typing import Dict, List, Optional

import resource

from evaluation_service import EvaluationService
from models import EvalResult
from runners import (
    CandidateRunner,
    ContainerRunner,
    MicroVMRunner,
    SubprocessRunner,
    compare_values,
    create_runner,
    scan_code_security,
    stable_code_hash,
)

logger = logging.getLogger("MutaLambda")


def apply_resource_limits(memory_mb: int, timeout_sec: float) -> None:
    """Apply per-process resource limits (memory + CPU time).

    Hardening hook from Phase 6.5 remediation. Must be called inside the
    worker subprocess *before* executing candidate code. On platforms
    without ``RLIMIT_AS`` (e.g. some BSDs) the call is a no-op and the
    caller should rely on ``timeout_sec`` + the AST pre-scan.
    """
    try:
        limit_bytes = max(1, int(memory_mb * 1024 * 1024))
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard == resource.RLIM_INFINITY or hard < 0 or hard > limit_bytes:
            hard = limit_bytes
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, hard))
    except (ValueError, OSError):
        # RLIMIT_AS not supported or already set — rely on subprocess timeout + AST scan.
        pass
    # Cap CPU time as defense-in-depth against infinite loops.
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (int(timeout_sec), int(timeout_sec)))
    except (ValueError, OSError):
        pass


# Re-export public surface for external callers.
__all__ = [
    "SandboxEvaluator",
    "CandidateRunner",
    "SubprocessRunner",
    "ContainerRunner",
    "MicroVMRunner",
    "create_runner",
    "compare_values",
    "scan_code_security",
    "stable_code_hash",
    "apply_resource_limits",
]


class SandboxEvaluator:
    """Evalúa lotes de código en paralelo.

    Parameters
    ----------
    test_cases:
        Declarative tests: preferred shape
        ``{"function": "f", "args": [...], "expected": ..., "comparison": "equal"}``.
    timeout_sec / memory_mb:
        Isolation limits for the runner.
    parallelism:
        Max process workers (lazy-initialized).
    allow_untested:
        If False, empty test_cases raise on evaluate.
    runner_mode:
        ``subprocess`` (dev), ``container`` (recommended isolation), ``microvm``.
    allow_expression_eval:
        Permit legacy ``expression`` / ``assert`` test keys (dev only).
    enforce_ast_scan:
        Early AST filter before execution.
    """

    def __init__(
        self,
        test_cases: List[Dict],
        timeout_sec: float = 10.0,
        memory_mb: int = 256,
        parallelism: Optional[int] = None,
        allow_untested: bool = True,
        runner_mode: str = "subprocess",
        allow_expression_eval: bool = False,
        enforce_ast_scan: bool = True,
        cache_enabled: bool = True,
        benchmark_warmups: int = 0,
        benchmark_samples: int = 1,
        benchmark_operations_per_case: int = 1,
    ):
        self.test_cases = test_cases
        self.timeout_sec = timeout_sec
        self.memory_mb = memory_mb
        self.allow_untested = allow_untested
        # Phase 6.5: validate runner_mode — only isolation-capable runners are safe defaults.
        if runner_mode not in ("subprocess", "container", "microvm"):
            warnings.warn(
                f"runner_mode={runner_mode!r} is not a recognized isolation mode; "
                "falling back to 'subprocess' (RLIMIT/timeout only).",
                RuntimeWarning,
                stacklevel=2,
            )
            runner_mode = "subprocess"
        self.runner_mode = runner_mode
        self.allow_expression_eval = allow_expression_eval
        self.enforce_ast_scan = enforce_ast_scan

        if os.getenv("MUTALAMBDA_E2E_SERIAL", "0") == "1":
            self.parallelism = 1
        else:
            self.parallelism = min(
                parallelism or multiprocessing.cpu_count(),
                multiprocessing.cpu_count(),
            )

        # Alias used by contract tests / config wiring.
        self.max_workers = self.parallelism

        # Phase 6.5: pre-validate test_cases structure so candidates cannot inject
        # malformed test payloads that escape the AST filter.
        for i, tc in enumerate(self.test_cases):
            if not isinstance(tc, dict) or "expected" not in tc and "comparison" not in tc:
                warnings.warn(
                    f"test_cases[{i}] lacks 'expected'/'comparison' — candidates may be "
                    "evaluated against an incomplete contract.",
                    RuntimeWarning,
                    stacklevel=2,
                )

        self._service = EvaluationService(
            test_cases=test_cases,
            timeout_sec=timeout_sec,
            memory_mb=memory_mb,
            max_workers=self.parallelism,
            runner_mode=runner_mode,
            allow_untested=allow_untested,
            allow_expression_eval=allow_expression_eval,
            enforce_ast_scan=enforce_ast_scan,
            cache_enabled=cache_enabled,
            benchmark_warmups=benchmark_warmups,
            benchmark_samples=benchmark_samples,
            benchmark_operations_per_case=benchmark_operations_per_case,
        )
        atexit.register(self.shutdown)

    def evaluate_batch(self, codes: List[str]) -> List[EvalResult]:
        """Evaluación en lote con cache y pool perezoso."""
        return self._service.evaluate_batch(codes)

    def shutdown(self, wait: bool = True) -> None:
        """Apaga el pool de procesos de forma controlada."""
        self._service.shutdown(wait=wait)
