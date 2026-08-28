"""Tests for GPU optimizer (FASE 4-5)."""

import pytest
import numpy as np

from gpu_optimizer import GPUOptimizer, GPUConfig, get_gpu_optimizer, reset_gpu_optimizer


class TestGPUConfig:
    def test_defaults(self):
        cfg = GPUConfig()
        assert cfg.enabled is False
        assert cfg.device == 0
        assert cfg.batch_size == 32
        assert cfg.fallback_to_cpu is True

    def test_is_available_disabled(self):
        cfg = GPUConfig(enabled=False)
        assert cfg.is_available is False

    def test_device_str_cpu(self):
        cfg = GPUConfig(enabled=False)
        assert cfg.device_str == "cpu"

    def test_device_str_gpu(self):
        cfg = GPUConfig(enabled=True, device=0)
        # If GPU available, should be cuda:0; otherwise fallback to cpu
        assert cfg.device_str in ("cuda:0", "cpu")


class TestGPUOptimizer:
    def setup_method(self):
        reset_gpu_optimizer()

    def teardown_method(self):
        reset_gpu_optimizer()

    def test_detect_no_torch(self):
        info = GPUOptimizer.detect()
        assert "torch_installed" in info
        assert "cuda_available" in info
        assert "device" in info

    def test_evaluate_population_cpu_fallback(self):
        """When GPU unavailable, should fallback to CPU."""
        opt = GPUOptimizer(GPUConfig(enabled=False))
        pop = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

        def fitness(ind):
            return float(np.sum(ind ** 2))

        scores, stats = opt.evaluate_population_gpu(pop, fitness)
        assert len(scores) == 3
        assert stats["acceleration"] == "none"
        assert stats["method"] in ("cpu", "cpu_fallback")

    def test_evaluate_population_simple(self):
        opt = GPUOptimizer(GPUConfig(enabled=False))
        pop = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])

        def fitness(ind):
            return float(np.dot(ind, ind))

        scores, _ = opt.evaluate_population_gpu(pop, fitness)
        assert np.allclose(scores, [1.0, 1.0, 2.0])

    def test_nsga2_cpu_mode(self):
        opt = GPUOptimizer(GPUConfig(enabled=False))
        pop = np.random.randn(10, 5)

        def fitness(ind):
            return float(np.sum(ind ** 2))

        result = opt.nsga2_gpu(pop, fitness, n_generations=3, population_size=5)
        assert result["generations_completed"] == 3
        assert result["best_score"] < float("inf")
        assert result["gpu_stats"]["acceleration"] == "none"

    def test_singleton(self):
        opt1 = get_gpu_optimizer()
        opt2 = get_gpu_optimizer()
        assert opt1 is opt2

    def test_memory_usage_no_gpu(self):
        opt = GPUOptimizer(GPUConfig(enabled=False))
        mem = opt.get_memory_usage()
        assert mem["gpu_memory_used_mb"] == 0
