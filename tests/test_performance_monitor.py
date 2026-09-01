"""Tests for performance monitor (FASE 6)."""

import time
import pytest
from unittest.mock import patch, MagicMock

from performance_monitor import PerformanceMonitor, MonitorConfig, get_monitor, reset_monitor


class TestPerformanceMonitor:
    def setup_method(self):
        reset_monitor()

    def teardown_method(self):
        reset_monitor()

    def test_start_stop(self):
        monitor = PerformanceMonitor(MonitorConfig(sampling_interval_sec=0.1))
        monitor.start()
        time.sleep(0.3)
        monitor.stop()
        # Should not raise

    def test_get_latest_empty(self):
        monitor = PerformanceMonitor()
        snapshot = monitor.get_latest()
        assert snapshot is None

    def test_record_evolution_step(self):
        monitor = PerformanceMonitor(MonitorConfig(sampling_interval_sec=0.05))
        monitor.start()
        time.sleep(0.1)

        monitor.record_evolution_step(generation=5, best_score=0.95, duration_sec=1.2, population_size=10)

        snapshot = monitor.get_latest()
        assert snapshot is not None
        assert hasattr(snapshot, "evolution_generation")
        assert snapshot.evolution_generation == 5  # type: ignore

        monitor.stop()

    def test_get_trends_empty(self):
        monitor = PerformanceMonitor()
        trends = monitor.get_trends()
        assert "error" in trends

    def test_get_alerts_empty(self):
        monitor = PerformanceMonitor()
        alerts = monitor.get_alerts()
        assert alerts == []

    def test_export_prometheus(self):
        monitor = PerformanceMonitor(MonitorConfig(sampling_interval_sec=0.05))
        monitor.start()
        time.sleep(0.1)
        monitor.record_evolution_step(generation=3, best_score=0.8, duration_sec=1.0, population_size=8)

        output = monitor.export_prometheus()
        assert "mutalambda_cpu_percent" in output
        assert "mutalambda_evolution_generation 3" in output
        assert "mutalambda_evolution_best_score 0.8" in output

        monitor.stop()


    def test_singleton(self):
        m1 = get_monitor()
        m2 = get_monitor()
        assert m1 is m2

    def test_sync_to_registry(self):
        from metrics_exporter import (
            get_registry,
            reset_registry,
        )
        reset_registry()
        monitor = PerformanceMonitor(
            MonitorConfig(sampling_interval_sec=0.05)
        )
        monitor.start()
        time.sleep(0.1)
        monitor.record_evolution_step(
            generation=7,
            best_score=0.99,
            duration_sec=1.0,
            population_size=8,
        )

        reg = get_registry()
        monitor.sync_to_registry(reg)
        from metrics_exporter import Gauge

        g: Gauge = reg._gauges.get("evolution_generation")  # noqa: SLF001
        assert g is not None
        assert g.value == 7.0

        best = reg._gauges.get("evolution_best_score")  # noqa: SLF001
        assert best is not None
        assert best.value == 0.99

        monitor.stop()


class TestPerformanceMonitorWithMocks:
    def test_snapshot_with_psutil_mock(self):
        """Test snapshot taking with mocked psutil."""
        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 45.0
        mock_mem = MagicMock()
        mock_mem.used = 8 * 1024**3
        mock_mem.total = 16 * 1024**3
        mock_mem.percent = 50.0
        mock_psutil.virtual_memory.return_value = mock_mem
        mock_psutil.disk_io_counters.return_value = None

        # Patch the module-level variable directly
        with patch("performance_monitor.psutil", mock_psutil):
            with patch("performance_monitor._HAS_PSUTIL", True):
                monitor = PerformanceMonitor(MonitorConfig(sampling_interval_sec=0.01))
                snapshot = monitor._take_snapshot()

                assert snapshot.cpu_percent == 45.0
                assert snapshot.memory_percent == 50.0
                assert snapshot.gpu_utilization == 0.0
                assert snapshot.gpu_memory_used_mb == 0.0
