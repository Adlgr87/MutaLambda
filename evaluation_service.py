"""Central evaluation service with cache and lazy pool initialization.

Goals (workflow ML-PERF*):
- Avoid re-evaluating known candidates (source + tests + env key).
- Single evaluation pool shared by islands.
- Lazy process-pool creation on first evaluation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from fitness_vector import FitnessVector
from models import EvalResult
from runners import CandidateRunner, SubprocessRunner, create_runner, stable_code_hash, tests_hash

logger = logging.getLogger("MutaLambda")


def environment_hash() -> str:
    """Hash of evaluation environment (Python + key packages)."""
    payload = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "numpy": _pkg_version("numpy"),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _pkg_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return "unknown"


def evaluation_key(code: str, test_cases: Sequence[dict], *, benchmark_hash: str = "") -> str:
    """Composite key: code + tests + benchmark + environment."""
    parts = [
        stable_code_hash(code),
        tests_hash(list(test_cases)),
        benchmark_hash or "none",
        environment_hash(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _pool_worker(args):
    """Top-level worker for ProcessPoolExecutor (must be picklable)."""
    code, test_cases, timeout_sec, memory_mb, allow_expression_eval, enforce_ast_scan = args
    runner = SubprocessRunner(
        timeout_sec=timeout_sec,
        memory_mb=memory_mb,
        allow_expression_eval=allow_expression_eval,
        enforce_ast_scan=enforce_ast_scan,
    )
    return runner.run(code, test_cases)


@dataclass
class EvaluationService:
    """Central evaluator used by islands and the agent."""

    test_cases: List[dict] = field(default_factory=list)
    timeout_sec: float = 10.0
    memory_mb: int = 256
    max_workers: Optional[int] = None
    runner_mode: str = "subprocess"
    allow_untested: bool = True
    allow_expression_eval: bool = False
    enforce_ast_scan: bool = True
    cache_enabled: bool = True
    benchmark_hash: str = ""

    def __post_init__(self) -> None:
        self._pool: Optional[ProcessPoolExecutor] = None
        self._pool_lock = threading.Lock()
        self._cache: Dict[str, EvalResult] = {}
        self._cache_lock = threading.Lock()
        self._runner: Optional[CandidateRunner] = None
        if os.getenv("MUTALAMBDA_E2E_SERIAL", "0") == "1":
            self.max_workers = 1
        elif self.max_workers is None:
            import multiprocessing

            self.max_workers = min(4, multiprocessing.cpu_count())

    # ── Compatibility with SandboxEvaluator interface ─────────────────────
    @property
    def parallelism(self) -> int:
        return int(self.max_workers or 1)

    def _ensure_tests(self) -> None:
        if not self.test_cases and not self.allow_untested:
            raise ValueError(
                "No test cases configured. Pass test_cases or set allow_untested=True "
                "for development only."
            )

    def _get_runner(self) -> CandidateRunner:
        if self._runner is None:
            self._runner = create_runner(
                self.runner_mode,
                timeout_sec=self.timeout_sec,
                memory_mb=self.memory_mb,
                allow_expression_eval=self.allow_expression_eval,
                enforce_ast_scan=self.enforce_ast_scan,
            )
        return self._runner

    def _ensure_pool(self) -> ProcessPoolExecutor:
        with self._pool_lock:
            if self._pool is None:
                workers = max(1, int(self.max_workers or 1))
                self._pool = ProcessPoolExecutor(max_workers=workers)
                logger.debug("EvaluationService pool started with %d workers", workers)
            return self._pool

    def evaluate_one(self, code: str) -> EvalResult:
        results = self.evaluate_batch([code])
        return results[0]

    def evaluate_batch(self, codes: List[str]) -> List[EvalResult]:
        """Evaluate codes with cache + optional process pool (subprocess mode)."""
        if not codes:
            return []
        self._ensure_tests()

        keys = [
            evaluation_key(code, self.test_cases, benchmark_hash=self.benchmark_hash)
            for code in codes
        ]
        results: List[Optional[EvalResult]] = [None] * len(codes)
        pending_idx: List[int] = []

        if self.cache_enabled:
            with self._cache_lock:
                for i, key in enumerate(keys):
                    cached = self._cache.get(key)
                    if cached is not None:
                        results[i] = cached
                    else:
                        pending_idx.append(i)
        else:
            pending_idx = list(range(len(codes)))

        if not pending_idx:
            return results  # type: ignore[return-value]

        # Container/microvm: sequential via runner (pool worker is subprocess-only).
        if self.runner_mode not in {"subprocess", "local", "dev"}:
            runner = self._get_runner()
            for i in pending_idx:
                results[i] = runner.run(codes[i], self.test_cases)
        elif (self.max_workers or 1) <= 1 or os.getenv("MUTALAMBDA_E2E_SERIAL", "0") == "1":
            runner = SubprocessRunner(
                timeout_sec=self.timeout_sec,
                memory_mb=self.memory_mb,
                allow_expression_eval=self.allow_expression_eval,
                enforce_ast_scan=self.enforce_ast_scan,
            )
            for i in pending_idx:
                results[i] = runner.run(codes[i], self.test_cases)
        else:
            pool = self._ensure_pool()
            args_list = [
                (
                    codes[i],
                    self.test_cases,
                    self.timeout_sec,
                    self.memory_mb,
                    self.allow_expression_eval,
                    self.enforce_ast_scan,
                )
                for i in pending_idx
            ]
            future_map = {
                pool.submit(_pool_worker, args): idx
                for args, idx in zip(args_list, pending_idx)
            }
            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    logger.warning("Eval worker %d raised: %s", idx, exc)
                    results[idx] = EvalResult(
                        fitness=FitnessVector.worst(),
                        passed=False,
                        metrics={"error": str(exc)[:200]},
                        stdout="",
                        stderr=str(exc)[:2000],
                        timed_out=False,
                    )

        if self.cache_enabled:
            with self._cache_lock:
                for i in pending_idx:
                    if results[i] is not None:
                        self._cache[keys[i]] = results[i]  # type: ignore[assignment]

        return results  # type: ignore[return-value]

    def invalidate(self, code: Optional[str] = None) -> None:
        with self._cache_lock:
            if code is None:
                self._cache.clear()
            else:
                key = evaluation_key(code, self.test_cases, benchmark_hash=self.benchmark_hash)
                self._cache.pop(key, None)

    def cache_stats(self) -> Dict[str, int]:
        with self._cache_lock:
            return {"size": len(self._cache)}

    def shutdown(self, wait: bool = True) -> None:
        with self._pool_lock:
            if self._pool is not None:
                self._pool.shutdown(wait=wait)
                self._pool = None
