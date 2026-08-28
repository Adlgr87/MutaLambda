"""
GPU-Accelerated NSGA-II Optimizer for MutaLambda.

Uses PyTorch CUDA tensors for parallel population evaluation.
Auto-fallback to CPU when no GPU is available.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False
    torch = None  # type: ignore


@dataclass
class GPUConfig:
    """Configuration for GPU-accelerated optimization."""
    enabled: bool = False
    device: int = 0
    batch_size: int = 32
    mixed_precision: bool = False
    fallback_to_cpu: bool = True

    @property
    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if not _HAS_TORCH:
            return self.fallback_to_cpu
        return torch.cuda.is_available()

    @property
    def device_str(self) -> str:
        if not self.is_available or not _HAS_TORCH:
            return "cpu"
        return f"cuda:{self.device}"


class GPUOptimizer:
    """
    NSGA-II optimizer accelerated with GPU (PyTorch CUDA).

    Features:
    - Parallel fitness evaluation on GPU tensors
    - Auto fallback to CPU when GPU unavailable
    - Mixed precision support for memory efficiency
    - Batch processing for large populations
    """

    def __init__(self, config: Optional[GPUConfig] = None) -> None:
        self.config = config or GPUConfig()
        self._device: str = "cpu"
        self._torch_available = _HAS_TORCH
        self._batch_stats: Dict[str, float] = {}

    @staticmethod
    def detect() -> Dict[str, Any]:
        """Detect GPU availability and return status."""
        status = {
            "torch_installed": _HAS_TORCH,
            "cuda_available": False,
            "gpu_count": 0,
            "device": "cpu",
            "memory_total_mb": 0,
            "memory_used_mb": 0,
        }
        if not _HAS_TORCH:
            logger.info("PyTorch not installed — GPU mode disabled")
            return status

        if torch.cuda.is_available():
            status["cuda_available"] = True
            status["gpu_count"] = torch.cuda.device_count()
            status["device"] = f"cuda:0"
            status["memory_total_mb"] = torch.cuda.get_device_properties(0).total_mem / 1024**2
            status["memory_used_mb"] = torch.cuda.memory_allocated(0) / 1024**2
            logger.info(
                "GPU detected: %d device(s), %.1f MB total",
                status["gpu_count"],
                status["memory_total_mb"],
            )
        else:
            logger.info("No GPU detected — running in CPU mode")

        return status

    def _get_device(self) -> str:
        """Get the appropriate device string."""
        if self.config.is_available and self._torch_available:
            try:
                return f"cuda:{self.config.device}"
            except Exception:
                if self.config.fallback_to_cpu:
                    logger.warning("GPU device %d unavailable, falling back to CPU", self.config.device)
                    return "cpu"
                raise
        return "cpu"

    def _ensure_torch(self) -> bool:
        """Check torch is available and return status."""
        if not self._torch_available:
            logger.warning("PyTorch not installed — GPU optimization disabled")
            return False
        return True

    def evaluate_population_gpu(
        self,
        population: np.ndarray,
        fitness_fn,
        batch_size: Optional[int] = None,
    ) -> Tuple[np.ndarray, Dict[str, float]]:
        """
        Evaluate population fitness using GPU acceleration.

        Args:
            population: Array of shape (n_individuals, n_features)
            fitness_fn: Function that evaluates a single individual
            batch_size: Override config batch size

        Returns:
            (fitness_scores, gpu_stats)
        """
        if not self._ensure_torch():
            # Fallback to CPU evaluation
            scores = np.array([fitness_fn(ind) for ind in population])
            return scores, {"acceleration": "none", "method": "cpu_fallback"}

        device = self._get_device()
        bs = batch_size or self.config.batch_size
        n = len(population)
        scores = np.zeros(n)
        stats = {
            "acceleration": "gpu" if device.startswith("cuda") else "cpu",
            "method": device,
            "batch_size": bs,
            "total_individuals": n,
            "batches": 0,
            "eval_time_sec": 0.0,
        }

        start = time.perf_counter()

        # Process in batches
        for start_idx in range(0, n, bs):
            end_idx = min(start_idx + bs, n)
            batch = population[start_idx:end_idx]

            if device.startswith("cuda") and len(batch) > 0:
                # Convert to GPU tensor
                try:
                    tensor = torch.tensor(batch, dtype=torch.float32, device=device)
                    if self.config.mixed_precision:
                        with torch.cuda.amp.autocast():
                            result = self._evaluate_batch_gpu(tensor, fitness_fn)
                    else:
                        result = self._evaluate_batch_gpu(tensor, fitness_fn)
                    # Move results back to CPU
                    scores[start_idx:end_idx] = result.cpu().numpy()
                except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
                    logger.warning("GPU OOM or error, falling back to CPU for batch %d-%d: %s",
                                   start_idx, end_idx, e)
                    for i in range(start_idx, end_idx):
                        scores[i] = fitness_fn(batch[i - start_idx])
            else:
                for i, ind in enumerate(batch):
                    scores[start_idx + i] = fitness_fn(ind)

            stats["batches"] += 1

        elapsed = time.perf_counter() - start
        stats["eval_time_sec"] = elapsed
        stats["throughput"] = n / elapsed if elapsed > 0 else 0.0

        # Update GPU memory stats
        if device.startswith("cuda") and _HAS_TORCH:
            stats["gpu_memory_used_mb"] = torch.cuda.memory_allocated(device) / 1024**2
            stats["gpu_memory_reserved_mb"] = torch.cuda.memory_reserved(device) / 1024**2

        logger.info(
            "GPU eval: %d individuals in %.3fs (%.1f/s) on %s",
            n, elapsed, stats["throughput"], device,
        )

        self._batch_stats = stats
        return scores, stats

    def _evaluate_batch_gpu(self, tensor: "torch.Tensor", fitness_fn) -> "torch.Tensor":  # noqa: F821
        """Evaluate a batch of individuals on GPU."""
        # Apply fitness function to tensor batch
        # This is where GPU parallelism happens
        try:
            result = fitness_fn(tensor)
            if isinstance(result, torch.Tensor):
                return result
            return torch.tensor(result, device=tensor.device)
        except Exception:
            # If fitness_fn doesn't support tensors, fall back to list
            cpu_list = tensor.cpu().numpy().tolist()
            return torch.tensor(
                [fitness_fn(ind) for ind in cpu_list],
                device=tensor.device,
            )

    def nsga2_gpu(
        self,
        individuals: np.ndarray,
        fitness_fn,
        n_generations: int = 10,
        population_size: int = 50,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.9,
    ) -> Dict[str, Any]:
        """
        Run NSGA-II optimization with GPU acceleration.

        Returns dict with results and GPU stats.
        """
        result = {
            "best_individual": None,
            "best_score": float("inf"),
            "all_scores": [],
            "gpu_stats": {},
            "generations_completed": 0,
        }

        if not self._ensure_torch():
            logger.info("Running NSGA-II in CPU-only mode (no PyTorch)")
            return self._nsga2_cpu(individuals, fitness_fn, n_generations, population_size,
                                   mutation_rate, crossover_rate, result)

        device = self._get_device()
        logger.info("Starting NSGA-II on %s with %d generations, pop=%d",
                     device, n_generations, population_size)

        start_time = time.perf_counter()
        current_pop = individuals[:population_size] if len(individuals) >= population_size else individuals

        for gen in range(n_generations):
            gen_start = time.perf_counter()

            # GPU-accelerated evaluation
            scores, gpu_stats = self.evaluate_population_gpu(current_pop, fitness_fn)
            result["all_scores"].append(float(np.min(scores)))

            if np.min(scores) < result["best_score"]:
                result["best_score"] = float(np.min(scores))
                result["best_individual"] = current_pop[np.argmin(scores)].copy()

            # Selection, crossover, mutation (simplified NSGA-II)
            current_pop = self._next_generation(
                current_pop, scores, mutation_rate, crossover_rate
            )

            gen_time = time.perf_counter() - gen_start
            result["generations_completed"] = gen + 1

            if gen % 5 == 0:
                logger.info("Gen %d/%d — best: %.4f — %.3fs",
                            gen, n_generations, result["best_score"], gen_time)

        total_time = time.perf_counter() - start_time
        result["gpu_stats"] = {
            **gpu_stats,
            "total_time_sec": total_time,
            "gens_per_sec": n_generations / total_time if total_time > 0 else 0,
        }

        return result

    def _nsga2_cpu(
        self,
        individuals: np.ndarray,
        fitness_fn,
        n_generations: int,
        population_size: int,
        mutation_rate: float,
        crossover_rate: float,
        result: Dict,
    ) -> Dict:
        """Fallback CPU NSGA-II when GPU unavailable."""
        current_pop = individuals[:population_size]
        result["gpu_stats"] = {"acceleration": "none", "method": "cpu"}

        for gen in range(n_generations):
            scores = np.array([fitness_fn(ind) for ind in current_pop])
            result["all_scores"].append(float(np.min(scores)))
            if np.min(scores) < result["best_score"]:
                result["best_score"] = float(np.min(scores))
                result["best_individual"] = current_pop[np.argmin(scores)].copy()
            current_pop = self._next_generation(current_pop, scores, mutation_rate, crossover_rate)

        result["generations_completed"] = n_generations
        return result

    def _next_generation(
        self,
        population: np.ndarray,
        scores: np.ndarray,
        mutation_rate: float,
        crossover_rate: float,
    ) -> np.ndarray:
        """Simple genetic operation: tournament selection + crossover + mutation."""
        n, dim = population.shape
        offspring = np.zeros_like(population)

        for i in range(n):
            # Tournament selection
            idx1, idx2 = np.random.choice(n, 2, replace=False)
            parent = population[idx1] if scores[idx1] < scores[idx2] else population[idx2]

            # Crossover
            if np.random.random() < crossover_rate:
                idx3 = np.random.choice(n)
                mask = np.random.random(dim) < 0.5
                child = np.where(mask, parent, population[idx3])
            else:
                child = parent.copy()

            # Mutation
            if np.random.random() < mutation_rate:
                child += np.random.randn(dim) * 0.1

            offspring[i] = child

        return offspring

    def get_memory_usage(self) -> Dict[str, float]:
        """Get current GPU memory usage."""
        if not self._torch_available or not torch.cuda.is_available():
            return {"gpu_memory_used_mb": 0, "gpu_memory_reserved_mb": 0}

        return {
            "gpu_memory_used_mb": torch.cuda.memory_allocated(self.config.device) / 1024**2,
            "gpu_memory_reserved_mb": torch.cuda.memory_reserved(self.config.device) / 1024**2,
            "gpu_memory_max_mb": torch.cuda.max_memory_allocated(self.config.device) / 1024**2,
        }


# Module-level convenience
_default_optimizer: Optional[GPUOptimizer] = None


def get_gpu_optimizer(config: Optional[GPUConfig] = None) -> GPUOptimizer:
    """Get or create the default GPU optimizer singleton."""
    global _default_optimizer
    if _default_optimizer is None:
        _default_optimizer = GPUOptimizer(config)
    return _default_optimizer


def reset_gpu_optimizer() -> None:
    """Reset the singleton (for testing)."""
    global _default_optimizer
    _default_optimizer = None
