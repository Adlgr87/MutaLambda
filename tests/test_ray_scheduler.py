"""Tests for Ray scheduler (FASE 5)."""

import pytest
from unittest.mock import patch, MagicMock

from ray_scheduler import RayScheduler, RayConfig, get_ray_scheduler, reset_ray_scheduler


class TestRayConfig:
    def test_defaults(self):
        cfg = RayConfig()
        assert cfg.address == "auto"
        assert cfg.num_cpus == 4
        assert cfg.num_gpus == 0
        assert cfg.batch_size == 32

    def test_is_available_no_ray(self):
        cfg = RayConfig()
        # Without ray installed, should return False
        with patch.dict("sys.modules", {"ray": None}):
            assert cfg.is_available is False


class TestRayScheduler:
    def setup_method(self):
        reset_ray_scheduler()

    def teardown_method(self):
        reset_ray_scheduler()

    def test_initialize_no_ray(self):
        with patch.dict("sys.modules", {"ray": None}):
            scheduler = RayScheduler()
            assert scheduler.initialize() is False

    def test_evaluate_local_fallback(self):
        """Without Ray, should fall back to local evaluation."""
        scheduler = RayScheduler()
        scheduler._ray_initialized = False

        import numpy as np
        population = np.array([[1.0, 2.0], [3.0, 4.0]])

        def fitness(ind):
            return float(np.sum(ind ** 2))

        result = scheduler.evaluate_batch(population, fitness)
        assert len(result["scores"]) == 2
        assert result["stats"]["method"] == "local"

    def test_evaluate_batch(self):
        scheduler = RayScheduler()
        scheduler._ray_initialized = True

        import numpy as np
        population = np.array([[1.0, 0.0], [0.0, 1.0]])

        def fitness(ind):
            return float(np.sum(ind ** 2))

        result = scheduler.evaluate_batch(population, fitness)
        assert "scores" in result
        assert "stats" in result

    def test_cluster_info_no_ray(self):
        with patch.dict("sys.modules", {"ray": None}):
            scheduler = RayScheduler()
            info = scheduler.get_cluster_info()
            assert info["ray_initialized"] is False

    def test_singleton(self):
        s1 = get_ray_scheduler()
        s2 = get_ray_scheduler()
        assert s1 is s2

    def test_gpu_enabled_false_without_ray(self):
        with patch.dict("sys.modules", {"ray": None}):
            scheduler = RayScheduler()
            assert scheduler.is_gpu_enabled() is False


class TestRaySchedulerWithMock:
    def test_evaluate_with_ray_mock(self):
        """Test Ray evaluation path with mocked Ray."""
        mock_ray = MagicMock()
        mock_ray.is_initialized.return_value = True
        mock_ray.cluster_resources.return_value = {"CPU": 4, "GPU": 1}

        with patch.dict("sys.modules", {"ray": mock_ray}):
            import sys
            sys.modules["ray"] = mock_ray

            scheduler = RayScheduler()
            scheduler._ray_initialized = True

            import numpy as np
            population = np.array([[1.0, 2.0]])

            def fitness(ind):
                return float(np.sum(ind ** 2))

            # Should use local fallback since we can't truly mock Ray tasks
            result = scheduler.evaluate_batch(population, fitness)
            assert len(result["scores"]) == 1
