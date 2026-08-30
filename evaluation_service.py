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
import multiprocessing
import os
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from benchmarking import BenchmarkConfig, BenchmarkResult, percentiles_from_samples
from fitness_vector import FitnessVector
from models import EvalResult
from code_hash import stable_code_hash
from runners import CandidateRunner, SubprocessRunner, create_runner, tests_hash

logger = logging.getLogger("MutaLambda")


# ── Persistent process pool across EvaluationService instances ─────────────────
# A shared pool keyed by (workers, timeout, memory, enforce_ast_scan) avoids
# re-spawning processes when multiple EvolutionEngine instances are created
# across runs (e.g. island threads, checkpoints, agent sessions). The pool is
# reference-counted and torn down only when the last client releases it.
_POOL_REGISTRY: Dict[tuple, "ProcessPoolExecutor"] = {}
_POOL_REGISTRY_LOCK = threading.Lock()
_POOL_REF_COUNTS: Dict[tuple, int] = {}


def _pool_key(
    workers: int,
    timeout_sec: float,
    memory_mb: int,
    enforce_ast_scan: bool,
    allow_expression_eval: bool,
) -> tuple:
    return (workers, timeout_sec, memory_mb, enforce_ast_scan, allow_expression_eval)


def _acquire_shared_pool(key: tuple) -> ProcessPoolExecutor:
    """Get or create a persistent process pool, incrementing the reference count."""
    with _POOL_REGISTRY_LOCK:
        pool = _POOL_REGISTRY.get(key)
        if pool is None:
            ctx = None
            if "forkserver" in multiprocessing.get_all_start_methods():
                try:
                    ctx = multiprocessing.get_context("forkserver")
                except ValueError:
                    ctx = None
            pool = ProcessPoolExecutor(max_workers=key[0], mp_context=ctx) if ctx else ProcessPoolExecutor(max_workers=key[0])
            _POOL_REGISTRY[key] = pool
            _POOL_REF_COUNTS[key] = 0
            logger.debug("Shared pool created for key=%s", key)
        _POOL_REF_COUNTS[key] += 1
        return pool


def _release_shared_pool(key: tuple) -> None:
    """Decrement ref count; shut down pool when last client releases it."""
    with _POOL_REGISTRY_LOCK:
        if key in _POOL_REF_COUNTS:
            _POOL_REF_COUNTS[key] -= 1
            if _POOL_REF_COUNTS[key] <= 0:
                pool = _POOL_REGISTRY.pop(key, None)
                _POOL_REF_COUNTS.pop(key, None)
                if pool is not None:
                    try:
                        pool.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        pool.shutdown(wait=False)
                    logger.debug("Shared pool shut down (last release) for key=%s", key)


def shutdown_all_pools() -> None:
    """Tear down every persistent pool (used at interpreter shutdown or tests)."""
    with _POOL_REGISTRY_LOCK:
        for key, pool in list(_POOL_REGISTRY.items()):
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                try:
                    pool.shutdown(wait=False)
                except Exception:
                    pass
        _POOL_REGISTRY.clear()
        _POOL_REF_COUNTS.clear()


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
        from importlib.metadata import PackageNotFoundError, version

        return version(name)
    except PackageNotFoundError:
        return "unknown"
    except Exception:
        return "unknown"


def evaluation_key(code: str, test_cases: Sequence[dict], *,
                   benchmark_hash: str = "",
                   _tests_hash: Optional[str] = None,
                   _env_hash: Optional[str] = None) -> str:
    """Composite key: code + tests + benchmark + environment.

    Args:
        _tests_hash: Precomputed tests_hash (caller may cache invariant value).
        _env_hash: Precomputed environment_hash (caller may cache invariant value).
    """
    parts = [
        stable_code_hash(code),
        _tests_hash if _tests_hash is not None else tests_hash(list(test_cases)),
        benchmark_hash or "none",
        _env_hash if _env_hash is not None else environment_hash(),
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
    benchmark_warmups: int = 0
    benchmark_samples: int = 1
    benchmark_operations_per_case: int = 1

    def __post_init__(self) -> None:
        self._pool: Optional[ProcessPoolExecutor] = None
        self._pool_lock = threading.Lock()
        self._pool_key: Optional[tuple] = None  # tracks key for shared pool release
        self._serial_fallback: Optional[ThreadPoolExecutor] = None
        self._cache: Dict[str, EvalResult] = {}
        self._cache_lock = threading.Lock()
        self._runner: Optional[CandidateRunner] = None
        # Cache telemetry: distinguish true cache hits from fresh evaluations.
        self._cache_hits = 0
        self._cache_misses = 0
        # Cache invariant hashes once — tests_hash + environment_hash do not
        # change during the life of an EvaluationService instance. Without this,
        # evaluation_key() recomputes json.dumps(test_cases) + environment_hash
        # for *every* candidate (O(N) redundant serializations per generation).
        self._tests_hash = tests_hash(self.test_cases)
        self._env_hash = environment_hash()
        if os.getenv("MUTALAMBDA_E2E_SERIAL", "0") == "1":
            self.max_workers = 1
        elif self.max_workers is None:
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

    def _make_pool(self, workers: int) -> ProcessPoolExecutor:
        """Create a process pool using a start method safe for threaded parents.

        The pytest process (and the agent runtime in general) is multi-threaded
        (island threads, LSP server threads from earlier tests, ...). With the
        Linux default ``fork`` start method (Python <= 3.13), forking a
        multi-threaded parent can produce dead/broken children — observed in
        CI as BrokenProcessPool right after unrelated tests left threads
        behind, which cascaded into "Evolution produced no valid individuals".

        ``forkserver`` forks workers from a clean single-threaded server
        process instead; ``spawn`` is the portable fallback (and the default
        on Windows/macOS, where forkserver does not exist).
        """
        ctx = None
        if "forkserver" in multiprocessing.get_all_start_methods():
            try:
                ctx = multiprocessing.get_context("forkserver")
            except ValueError:  # pragma: no cover - defensive
                ctx = None
        if ctx is not None:
            return ProcessPoolExecutor(max_workers=workers, mp_context=ctx)
        return ProcessPoolExecutor(max_workers=workers)

    def _ensure_pool(self) -> ProcessPoolExecutor:
        with self._pool_lock:
            if self._pool is None:
                workers = max(1, int(self.max_workers or 1))
                # Use persistent shared pool to avoid re-spawning workers.
                self._pool_key = _pool_key(
                    workers, self.timeout_sec, self.memory_mb,
                    self.enforce_ast_scan, self.allow_expression_eval,
                )
                self._pool = _acquire_shared_pool(self._pool_key)
                logger.debug("EvaluationService pool started with %d workers (shared)", workers)
            return self._pool

    def _get_ready_pool(self):
        """Return an executor whose workers are guaranteed to be up.

        ``ProcessPoolExecutor`` spawns its worker processes lazily on the
        first ``submit()``. When island threads issue concurrent first-submits,
        the bootstrap can race and die, surfacing as BrokenProcessPool /
        ConnectionResetError. Warming one worker while holding ``_pool_lock``
        serializes that bootstrap exactly once; later calls take the fast path
        (workers already alive).
        """
        if self._serial_fallback is not None:
            return self._serial_fallback
        with self._pool_lock:
            if self._serial_fallback is not None:
                return self._serial_fallback
            if self._pool is None:
                workers = max(1, int(self.max_workers or 1))
                # Use persistent shared pool to avoid re-spawning workers.
                self._pool_key = _pool_key(
                    workers, self.timeout_sec, self.memory_mb,
                    self.enforce_ast_scan, self.allow_expression_eval,
                )
                self._pool = _acquire_shared_pool(self._pool_key)
                logger.debug("EvaluationService pool started with %d workers (shared)", workers)
            try:
                # The first submit bootstraps the forkserver and its first
                # worker; performing it under the lock removes the race.
                self._pool.submit(int, 0).result(timeout=60.0)
            except Exception as exc:
                logger.warning(
                    "Process pool unavailable (%s); falling back to serial evaluation", exc
                )
                # Release our ref to the shared pool so it can be garbage collected.
                if self._pool_key is not None:
                    _release_shared_pool(self._pool_key)
                self._pool = None
                self._pool_key = None
                executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval-serial")
                self._serial_fallback = executor
                return executor
            return self._pool

    def shutdown_pool(self) -> None:
        """Release the shared pool reference (pool persists for other clients)."""
        with self._pool_lock:
            pool = getattr(self, "_pool", None)
            pool_key = getattr(self, "_pool_key", None)
            # Only release the shared pool ref; don't shut it down so other
            # EvaluationService instances can keep using it.
            if pool is not None and pool_key is not None:
                _release_shared_pool(pool_key)
            self._pool = None
            self._pool_key = None

    def shutdown(self, wait: bool = True) -> None:
        """Release shared pool reference. Pool persists if other clients exist."""
        self.shutdown_pool()
        fallback = getattr(self, "_serial_fallback", None)
        if fallback is not None:
            fallback.shutdown(wait=wait)
            self._serial_fallback = None

    def evaluate_one(self, code: str) -> EvalResult:
        results = self.evaluate_batch([code])
        return results[0]

    def evaluate_batch(self, codes: List[str]) -> List[EvalResult]:
        """Evaluate codes with cache + optional process pool (subprocess mode)."""
        if not codes:
            return []
        self._ensure_tests()

        keys = [
            evaluation_key(
                code, self.test_cases,
                benchmark_hash=self.benchmark_hash,
                _tests_hash=self._tests_hash,
                _env_hash=self._env_hash,
            )
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
                        self._cache_hits += 1
                    else:
                        pending_idx.append(i)
                        self._cache_misses += 1
        else:
            pending_idx = list(range(len(codes)))
            self._cache_misses += len(codes)

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
            pool = self._get_ready_pool()
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

        # Optional multi-sample latency refinement (ML-F04).
        if self.benchmark_samples > 1:
            for i in pending_idx:
                if results[i] is not None and results[i].passed:
                    results[i] = self._refine_with_benchmark(codes[i], results[i])  # type: ignore[index]

        if self.cache_enabled:
            with self._cache_lock:
                for i in pending_idx:
                    if results[i] is not None:
                        self._cache[keys[i]] = results[i]  # type: ignore[assignment]

        return results  # type: ignore[return-value]

    def _refine_with_benchmark(self, code: str, base: EvalResult) -> EvalResult:
        """Re-run samples for real p50/p95/p99 when configured."""
        samples_sec: List[float] = []
        cfg = BenchmarkConfig(
            warmups=self.benchmark_warmups,
            samples=self.benchmark_samples,
            operations_per_case=max(1, self.benchmark_operations_per_case),
        )
        # Warmups + samples via the primary runner (correctness already known).
        runner = self._get_runner()
        try:
            for _ in range(cfg.warmups):
                runner.run(code, self.test_cases)
            for _ in range(cfg.samples):
                r = runner.run(code, self.test_cases)
                samples_sec.append(float(r.metrics.get("latency", r.fitness.latency_p50)))
        except Exception as exc:
            logger.debug("benchmark refine failed: %s", exc)
            return base

        if not samples_sec:
            return base

        stats = percentiles_from_samples(samples_sec)
        br = BenchmarkResult(
            samples_sec=samples_sec,
            warmups=cfg.warmups,
            operations_per_case=cfg.operations_per_case,
        )
        fitness = FitnessVector(
            correctness=base.fitness.correctness,
            latency_p50=stats["p50"],
            latency_p99=stats["p99"],
            throughput=br.throughput_ops_per_sec if br.throughput_ops_per_sec > 0 else base.fitness.throughput,
            memory_peak_mb=base.fitness.memory_peak_mb,
            parsimony=base.fitness.parsimony,
        )
        metrics = dict(base.metrics)
        metrics.update(
            {
                "latency": stats["p50"],
                "latency_p50": stats["p50"],
                "latency_p95": br.p95,
                "latency_p99": stats["p99"],
                "latency_mean": stats["mean"],
                "latency_samples": float(len(samples_sec)),
                "throughput": fitness.throughput,
            }
        )
        return EvalResult(
            fitness=fitness,
            passed=base.passed,
            metrics=metrics,
            stdout=base.stdout,
            stderr=base.stderr,
            timed_out=base.timed_out,
        )

    def invalidate(self, code: Optional[str] = None) -> None:
        with self._cache_lock:
            if code is None:
                self._cache.clear()
            else:
                key = evaluation_key(
                    code, self.test_cases,
                    benchmark_hash=self.benchmark_hash,
                    _tests_hash=self._tests_hash,
                    _env_hash=self._env_hash,
                )
                self._cache.pop(key, None)

    def cache_stats(self) -> Dict[str, int]:
        """Snapshot of cache hit/miss counters (PDF fix a: HFC telemetry)."""
        with self._cache_lock:
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "size": len(self._cache),
            }
