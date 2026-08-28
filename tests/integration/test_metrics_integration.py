"""FASE 8 — Integration test for metrics exporter with evolution pipeline."""

import time

import pytest

from metrics_exporter import (
    MetricsRegistry,
    get_registry,
    reset_registry,
    register_mutalambda_metrics,
    record_generation_end,
    record_evaluation,
    record_gpu_status,
    start_metrics_server,
)


class TestMetricsIntegration:
    """Integration between metrics exporter and core MutaLambda components."""

    def setup_method(self):
        reset_registry()

    def test_evolution_records_metrics(self):
        """Recording evolution steps should produce measurable metrics."""
        reg = get_registry()
        register_mutalambda_metrics(reg)

        for gen in range(3):
            record_generation_end(
                generation=gen,
                best_score=0.5 + gen * 0.1,
                avg_score=0.3 + gen * 0.05,
                duration_sec=1.5,
                registry=reg,
            )
            record_evaluation(
                duration_sec=0.05,
                accepted=True,
                change_size=2,
                registry=reg,
            )

        assert reg.gauge("evolution_generation").value == 2.0
        assert reg.gauge("evolution_best_score").value == 0.7
        assert reg.counter("evolution_generations_completed").value == 3.0
        assert reg.counter("evolution_evaluations_total").value == 3.0

    def test_metrics_collectible_after_evolution(self):
        """Metrics should be collectible in Prometheus format after evolution."""
        reg = get_registry()
        register_mutalambda_metrics(reg)

        record_generation_end(
            generation=10,
            best_score=0.95,
            avg_score=0.8,
            duration_sec=2.0,
            registry=reg,
        )

        output = reg.collect()
        assert "evolution_best_score 0.95" in output
        assert "evolution_generation 10.0" in output
        assert "evolution_generations_completed 1.0" in output

    def test_gpu_metrics_during_optimization(self):
        """GPU metrics should be recordable during optimization."""
        reg = get_registry()
        register_mutalambda_metrics(reg)

        record_gpu_status(
            utilization=92.0,
            memory_used_mb=6500.0,
            memory_total_mb=8000.0,
            batch_count=100,
            registry=reg,
        )

        assert reg.gauge("gpu_utilization").value == 92.0
        assert reg.gauge("gpu_memory_used_mb").value == 6500.0
        assert reg.counter("gpu_batch_count").value == 100.0

    def test_test_result_metrics(self):
        """Test results should be tracked."""
        from metrics_exporter import record_test_result

        reg = get_registry()
        for _ in range(5):
            record_test_result(passed=True, registry=reg)
        record_test_result(passed=False, registry=reg)

        assert reg.counter("tests_passed_total").value == 5.0
        assert reg.counter("tests_failed_total").value == 1.0

    def test_full_pipeline_metrics(self):
        """Simulate a full optimization pipeline and verify all metric families."""
        reg = get_registry()
        register_mutalambda_metrics(reg)

        # Simulate 5 generations
        for gen in range(5):
            record_generation_end(
                generation=gen,
                best_score=0.6 + gen * 0.05,
                avg_score=0.4 + gen * 0.03,
                duration_sec=1.0 + gen * 0.1,
                registry=reg,
            )
            for _ in range(10):  # 10 evaluations per generation
                record_evaluation(
                    duration_sec=0.05,
                    accepted=(gen + _) % 3 != 0,
                    change_size=1 + (_ % 3),
                    registry=reg,
                )

        # Verify all metric families
        output = reg.collect()
        assert "evolution_generation 4.0" in output
        assert "evolution_evaluations_total 50.0" in output
        assert "mutation_applied_total 50.0" in output
        assert "mutation_accepted_total" in output
        assert "mutation_rejected_total" in output

    def test_metrics_server_integration(self):
        """End-to-end: server serves correct metrics."""
        reg = get_registry()
        register_mutalambda_metrics(reg)
        record_generation_end(
            generation=1, best_score=0.9, avg_score=0.7, duration_sec=1.0, registry=reg
        )

        server = start_metrics_server(port=19102, registry=reg)
        if server is None:
            pytest.skip("HTTP server not available")
        try:
            import urllib.request  # noqa: PLC0415
            time.sleep(0.2)
            resp = urllib.request.urlopen("http://127.0.0.1:19102/metrics", timeout=2)
            assert resp.status == 200
            body = resp.read().decode()
            assert "evolution_best_score 0.9" in body
        finally:
            server.shutdown()
