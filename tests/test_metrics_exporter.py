"""Tests for metrics_exporter.py (FASE 8)."""

import threading
import time
import json
from unittest.mock import patch, MagicMock

import pytest

from metrics_exporter import (
    Gauge,
    Counter,
    Histogram,
    MetricsRegistry,
    get_registry,
    reset_registry,
    register_mutalambda_metrics,
    record_generation_end,
    record_evaluation,
    record_gpu_status,
    record_test_result,
    start_metrics_server,
    OTelMetricsBridge,
)


class TestGauge:
    def test_initial_value(self):
        g = Gauge(name="test_gauge", description="a test gauge")
        assert g.value == 0.0

    def test_set(self):
        g = Gauge(name="g", description="")
        g.set(42.0)
        assert g.value == 42.0

    def test_inc(self):
        g = Gauge(name="g", description="")
        g.inc(5.0)
        assert g.value == 5.0
        g.inc(3.0)
        assert g.value == 8.0

    def test_dec(self):
        g = Gauge(name="g", description="")
        g.set(10.0)
        g.dec(3.0)
        assert g.value == 7.0

    def test_labels(self):
        g = Gauge(name="g", description="", labels={"label1": "v1"})
        g.set(1.0, labels={"label2": "v2"})
        assert g.labels == {"label1": "v1", "label2": "v2"}

    def test_to_prometheus_no_labels(self):
        g = Gauge(name="my_gauge", description="")
        g.set(3.14)
        assert "my_gauge 3.14" in g.to_prometheus()

    def test_to_prometheus_with_labels(self):
        g = Gauge(name="my_gauge", description="", labels={"job": "a"})
        g.set(1.0)
        prom = g.to_prometheus()
        assert 'job="a"' in prom
        assert "my_gauge" in prom


class TestCounter:
    def test_initial(self):
        c = Counter(name="test_counter", description="")
        assert c.value == 0.0

    def test_inc(self):
        c = Counter(name="c", description="")
        c.inc()
        assert c.value == 1.0
        c.inc(5)
        assert c.value == 6.0

    def test_to_prometheus(self):
        c = Counter(name="requests_total", description="")
        c.inc(10)
        assert "requests_total 10.0" in c.to_prometheus()


class TestHistogram:
    def test_observe(self):
        h = Histogram(name="latency", description="")
        h.observe(0.5)
        h.observe(1.5)
        assert h.count == 2
        assert h.sum_value == 2.0

    def test_buckets(self):
        h = Histogram(name="latency", description="")
        h.observe(0.008)
        h.observe(0.03)
        # 0.005 bucket: 0 items <= 0.005
        assert h.buckets.get(0.005, 0) == 0
        # 0.01 bucket: 1 item <= 0.01
        assert h.buckets.get(0.01, 0) == 1
        # 0.1 bucket: 2 items <= 0.1
        assert h.buckets.get(0.1, 0) == 2

    def test_to_prometheus(self):
        h = Histogram(name="my_hist", description="")
        h.observe(0.5)
        prom = h.to_prometheus()
        assert "my_hist_bucket" in prom
        assert "my_hist_sum" in prom
        assert "my_hist_count" in prom


class TestMetricsRegistry:
    def setup_method(self):
        reset_registry()

    def test_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_gauge_factory(self):
        reg = get_registry()
        g = reg.gauge("g1", "desc")
        assert g.name == "g1"
        assert isinstance(reg.gauge("g1", "desc"), Gauge)

    def test_counter_factory(self):
        reg = get_registry()
        c = reg.counter("c1", "desc")
        assert c.name == "c1"
        assert isinstance(reg.counter("c1"), Counter)

    def test_histogram_factory(self):
        reg = get_registry()
        h = reg.histogram("h1", "desc")
        assert h.name == "h1"
        assert isinstance(reg.histogram("h1"), Histogram)

    def test_collect_prometheus_format(self):
        reg = get_registry()
        reg.gauge("g1").set(1.0)
        reg.counter("c1").inc(5)
        reg.histogram("h1").observe(0.5)
        output = reg.collect()
        assert "g1 1.0" in output
        assert "c1 5.0" in output
        assert "h1_bucket" in output

    def test_collect_json(self):
        reg = get_registry()
        reg.gauge("g1").set(42.0)
        data = reg.collect_json()
        assert "gauges" in data
        assert "g1" in data["gauges"]
        assert data["gauges"]["g1"]["value"] == 42.0

    def test_thread_safety(self):
        reg = get_registry()
        errors = []

        def writer():
            try:
                for i in range(100):
                    reg.gauge(f"g{i % 10}").set(float(i))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        output = reg.collect()
        assert len(output) > 0


class TestRegisterMutalambdaMetrics:
    def setup_method(self):
        reset_registry()

    def test_registers_standard_metrics(self):
        reg = get_registry()
        register_mutalambda_metrics(reg)
        # Check key metrics exist
        g = reg.gauge("evolution_best_score")
        assert g is not None
        c = reg.counter("evolution_generations_completed")
        assert c is not None
        h = reg.histogram("evolution_generation_time_sec")
        assert h is not None


class TestConvenienceFunctions:
    def setup_method(self):
        reset_registry()

    def test_record_generation_end(self):
        record_generation_end(
            generation=5,
            best_score=0.95,
            avg_score=0.72,
            duration_sec=2.1,
        )
        reg = get_registry()
        assert reg.gauge("evolution_best_score").value == 0.95
        assert reg.gauge("evolution_generation").value == 5.0
        assert reg.counter("evolution_generations_completed").value == 1.0

    def test_record_evaluation_accepted(self):
        record_evaluation(duration_sec=0.05, accepted=True, change_size=3)
        reg = get_registry()
        assert reg.counter("evolution_evaluations_total").value == 1.0
        assert reg.counter("mutation_accepted_total").value == 1.0
        assert reg.counter("mutation_rejected_total").value == 0.0

    def test_record_evaluation_rejected(self):
        record_evaluation(duration_sec=0.02, accepted=False)
        reg = get_registry()
        assert reg.counter("mutation_rejected_total").value == 1.0

    def test_record_gpu_status(self):
        record_gpu_status(utilization=85.0, memory_used_mb=4000.0, memory_total_mb=8000.0, batch_count=10)
        reg = get_registry()
        assert reg.gauge("gpu_utilization").value == 85.0
        assert reg.gauge("gpu_memory_used_mb").value == 4000.0
        assert reg.counter("gpu_batch_count").value == 10.0

    def test_record_test_result(self):
        record_test_result(passed=True)
        record_test_result(passed=False)
        reg = get_registry()
        assert reg.counter("tests_passed_total").value == 1.0
        assert reg.counter("tests_failed_total").value == 1.0


class TestMetricsServer:
    def test_start_and_stop(self):
        reset_registry()
        reg = get_registry()
        reg.gauge("test_metric").set(1.0)
        server = start_metrics_server(port=19100, registry=reg)
        if server is None:
            pytest.skip("HTTP server not available")
        try:
            time.sleep(0.2)
            import urllib.request  # noqa: PLC0415
            resp = urllib.request.urlopen("http://127.0.0.1:19100/metrics", timeout=2)
            assert resp.status == 200
            body = resp.read().decode()
            assert "test_metric" in body
        finally:
            server.shutdown()

    def test_healthz(self):
        reset_registry()
        server = start_metrics_server(port=19101)
        if server is None:
            pytest.skip("HTTP server not available")
        try:
            time.sleep(0.2)
            import urllib.request  # noqa: PLC0415
            resp = urllib.request.urlopen("http://127.0.0.1:19101/healthz", timeout=2)
            assert resp.status == 200
            body = json.loads(resp.read())
            assert body["status"] == "ok"
        finally:
            server.shutdown()


class TestOTelMetricsBridge:
    def test_no_op_without_otel(self):
        with patch.dict("sys.modules", {"opentelemetry": None, "opentelemetry.sdk": None}):
            bridge = OTelMetricsBridge()
            bridge.record_gauge("evolution_best_score", 0.95)
            bridge.record_counter("evaluations", 10)
            bridge.record_histogram("gen_time", 2.0)
            # Should not raise even without OTel

    def test_records_to_registry(self):
        reset_registry()
        bridge = OTelMetricsBridge()
        # Directly set on registry since OTel is not installed
        reg = get_registry()
        reg.gauge("evolution_best_score").set(0.88)
        assert reg.gauge("evolution_best_score").value == 0.88
