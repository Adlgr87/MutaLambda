"""
Ray-based Distributed Batch Scheduler for MutaLambda.

Schedules fitness evaluations across a Ray cluster for parallel processing.
Auto-fallback to local multiprocessing when Ray is unavailable.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import ray
    _HAS_RAY = True
except ImportError:
    _HAS_RAY = False
    ray = None  # type: ignore


@dataclass
class RayConfig:
    """Configuration for Ray distributed scheduling."""
    address: str = "auto"
    num_cpus: int = 4
    num_gpus: int = 0
    max_retries: int = 3
    batch_size: int = 32
    timeout_seconds: int = 600
    retry_interval: int = 30
    auto_init: bool = True

    @property
    def is_available(self) -> bool:
        if not _HAS_RAY:
            return False
        try:
            return ray.is_initialized()
        except Exception:
            return False


class RayScheduler:
    """
    Distributed batch scheduler using Ray for fitness evaluation.

    Features:
    - Parallel fitness evaluation across Ray workers
    - Automatic task retry on failure
    - Graceful fallback to local execution
    - Resource-aware scheduling
    """

    def __init__(self, config: Optional[RayConfig] = None) -> None:
        self.config = config or RayConfig()
        self._ray_initialized = False
        self._stats: Dict[str, Any] = {}

    def initialize(self) -> bool:
        """Initialize Ray cluster connection."""
        if not _HAS_RAY:
            logger.warning("Ray not installed — using local execution")
            return False

        if ray.is_initialized():
            self._ray_initialized = True
            logger.info("Ray already initialized")
            return True

        try:
            ray.init(
                address=self.config.address,
                num_cpus=self.config.num_cpus,
                num_gpus=self.config.num_gpus,
                ignore_reinit_error=True,
                logging_level=logging.WARNING,
            )
            self._ray_initialized = True
            logger.info(
                "Ray initialized: %d CPUs, %d GPUs",
                self.config.num_cpus,
                self.config.num_gpus,
            )
            return True
        except Exception as exc:
            logger.warning("Ray initialization failed: %s — falling back to local", exc)
            return False

    def shutdown(self) -> None:
        """Shutdown Ray cluster."""
        if self._ray_initialized and _HAS_RAY:
            try:
                ray.shutdown()
                self._ray_initialized = False
                logger.info("Ray cluster shut down")
            except Exception:
                pass

    def _make_eval_task(self, fitness_fn: Callable) -> Callable:
        """Create a Ray remote function for fitness evaluation."""
        if not self._ray_initialized or not _HAS_RAY:
            # Return a regular function that evaluates locally
            @ray.remote  # type: ignore
            def _local_eval(individual: np.ndarray, fn: Callable) -> float:
                return fn(individual)
            return _local_eval  # type: ignore

        @ray.remote(num_cpus=1, num_gpus=self.config.num_gpus / max(self.config.num_cpus, 1))
        def _ray_eval(individual: np.ndarray, fn_pickle: bytes, idx: int) -> Dict:
            import pickle  # noqa: PLC0415
            fn = pickle.loads(fn_pickle)
            start = time.perf_counter()
            score = fn(individual)
            elapsed = time.perf_counter() - start
            return {"index": idx, "score": score, "elapsed": elapsed}

        return _ray_eval  # type: ignore

    def evaluate_batch(
        self,
        individuals: np.ndarray,
        fitness_fn: Callable,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a batch of individuals using Ray or local fallback.

        Args:
            individuals: Array of shape (n, features)
            fitness_fn: Fitness evaluation function
            batch_size: Override config batch size

        Returns:
            Dict with scores and timing stats
        """
        bs = batch_size or self.config.batch_size
        n = len(individuals)
        scores = np.zeros(n)
        stats = {
            "method": "ray" if self._ray_initialized else "local",
            "total_individuals": n,
            "batches": 0,
            "eval_time_sec": 0.0,
            "throughput": 0.0,
        }

        start = time.perf_counter()

        if self._ray_initialized and _HAS_RAY:
            try:
                scores, stats = self._evaluate_ray(individuals, fitness_fn, bs, stats)
            except Exception as exc:
                logger.warning("Ray batch eval failed (%s), falling back to local", exc)
                self._ray_initialized = False
                scores, stats = self._evaluate_local(individuals, fitness_fn, stats)
        else:
            scores, stats = self._evaluate_local(individuals, fitness_fn, stats)

        elapsed = time.perf_counter() - start
        stats["eval_time_sec"] = elapsed
        stats["throughput"] = n / elapsed if elapsed > 0 else 0.0

        logger.info(
            "Evaluated %d individuals in %.3fs (%.1f/s) via %s",
            n, elapsed, stats["throughput"], stats["method"],
        )

        self._stats = stats
        return {"scores": scores, "stats": stats}

    def _evaluate_ray(
        self,
        individuals: np.ndarray,
        fitness_fn: Callable,
        batch_size: int,
        stats: Dict,
    ) -> tuple:
        """Evaluate using Ray remote functions."""
        import pickle as _pickle  # noqa: PLC0415

        n = len(individuals)
        scores = np.zeros(n)

        for start_idx in range(0, n, batch_size):
            end_idx = min(start_idx + batch_size, n)
            batch = individuals[start_idx:end_idx]

            # Submit batch tasks
            futures = []
            for i, ind in enumerate(batch):
                future = self._make_eval_task(fitness_fn).remote(
                    ind, _pickle.dumps(fitness_fn), start_idx + i
                )
                futures.append(future)

            # Wait for results with retry
            for attempt in range(self.config.max_retries):
                try:
                    ready, _ = ray.wait(futures, num_returns=len(futures),
                                        timeout=self.config.retry_interval)
                    if len(ready) == len(futures):
                        results = ray.get(ready)
                        for r in results:
                            scores[r["index"]] = r["score"]
                        break
                except Exception:
                    if attempt == self.config.max_retries - 1:
                        raise
                    time.sleep(self.config.retry_interval)

            stats["batches"] += 1

        return scores, stats

    def _evaluate_local(
        self,
        individuals: np.ndarray,
        fitness_fn: Callable,
        stats: Dict,
    ) -> tuple:
        """Evaluate locally (fallback)."""
        n = len(individuals)
        scores = np.array([fitness_fn(ind) for ind in individuals])
        stats["batches"] = 1
        return scores, stats

    def get_cluster_info(self) -> Dict[str, Any]:
        """Get Ray cluster information."""
        info: Dict[str, Any] = {
            "ray_initialized": self._ray_initialized,
            "num_cpus": 0,
            "num_gpus": 0,
            "num_nodes": 0,
        }

        if not self._ray_initialized or not _HAS_RAY:
            return info

        try:
            cluster_resources = ray.cluster_resources()
            info["num_cpus"] = cluster_resources.get("CPU", 0)
            info["num_gpus"] = cluster_resources.get("GPU", 0)
            info["num_nodes"] = cluster_resources.get("node:localhost", 0)
        except Exception:
            pass

        return info

    def is_gpu_enabled(self) -> bool:
        """Check if GPU acceleration is available via Ray."""
        if not self._ray_initialized or not _HAS_RAY:
            return False
        info = self.get_cluster_info()
        return info.get("num_gpus", 0) > 0


# Module-level convenience
_default_scheduler: Optional[RayScheduler] = None


def get_ray_scheduler(config: Optional[RayConfig] = None) -> RayScheduler:
    """Get or create the default Ray scheduler singleton."""
    global _default_scheduler
    if _default_scheduler is None:
        _default_scheduler = RayScheduler(config)
    return _default_scheduler


def reset_ray_scheduler() -> None:
    """Reset the singleton (for testing)."""
    global _default_scheduler
    _default_scheduler = None
