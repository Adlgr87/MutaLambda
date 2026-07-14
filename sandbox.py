"""Sandbox evaluation for generated Python code.

Remediation notes
-----------------
- Security boundary is the CandidateRunner (subprocess/container), not AST alone.
- SandboxEvaluator remains the public interface used by islands and tests.
- Internally it delegates to EvaluationService (cache + lazy pool).
"""

from __future__ import annotations

import atexit
import logging
import multiprocessing
import os
from typing import Dict, List, Optional

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

# Re-exports for backward compatibility / external imports.
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
        enforce_ast_scan: bool = False,
        cache_enabled: bool = True,
        benchmark_warmups: int = 0,
        benchmark_samples: int = 1,
        benchmark_operations_per_case: int = 1,
    ):
        self.test_cases = test_cases
        self.timeout_sec = timeout_sec
        self.memory_mb = memory_mb
        self.allow_untested = allow_untested
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
