"""
FASE 8 — Prometheus / OpenTelemetry Metrics Exporter

Exposición de métricas de MutaLambda en estándares industry-grade:
  - Prometheus scrape endpoint (HTTP /metrics)
  - OpenTelemetry metrics SDK (push/pull via OTLP)
  - Auto-start opcional con FastAPI/Flask middleware
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal metric storage (drop-in replacement for any registry)
# ---------------------------------------------------------------------------

@dataclass
class Gauge:
    name: str
    description: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        self.value = value
        if labels:
            self.labels.update(labels)

    def inc(self, delta: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.value += delta
        if labels:
            self.labels.update(labels)

    def dec(self, delta: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.value -= delta
        if labels:
            self.labels.update(labels)

    def to_prometheus(self) -> str:
        label_str = ",".join(
            f'{k}="{v}"' for k, v in sorted(self.labels.items())
        )
        prefix = f"{{{label_str}}}" if label_str else ""
        return f"{self.name}{prefix} {self.value}"


@dataclass
class Counter:
    name: str
    description: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)

    def inc(self, delta: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.value += delta
        if labels:
            self.labels.update(labels)

    def to_prometheus(self) -> str:
        label_str = ",".join(
            f'{k}="{v}"' for k, v in sorted(self.labels.items())
        )
        prefix = f"{{{label_str}}}" if label_str else ""
        return f"{self.name}{prefix} {self.value}"


@dataclass
class Histogram:
    name: str
    description: str
    buckets: Dict[float, int] = field(default_factory=dict)
    sum_value: float = 0.0
    count: int = 0
    labels: Dict[str, str] = field(default_factory=dict)
    _bounds: List[float] = field(default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        self.sum_value += value
        self.count += 1
        if labels:
            self.labels.update(labels)
        for bound in self._bounds:
            self.buckets[bound] = self.buckets.get(bound, 0) + (1 if value <= bound else 0)

    def to_prometheus(self) -> str:
        lines = []
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(self.labels.items()))
        for bound, cumulative in sorted(self.buckets.items()):
            bucket_label = f'{{le="{bound}"}}' if label_str else f'le="{bound}"'
            if label_str:
                bucket_label = "{" + label_str + "," + bucket_label[1:]
            lines.append(f"{self.name}_bucket{bucket_label} {cumulative}")
        inf_label = f"{{le=\"+Inf\"}}" if not label_str else f"{{{label_str},le=\"+Inf\"}}"
        lines.append(f"{self.name}_bucket{inf_label} {self.count}")
        lines.append(f"{self.name}_sum{'{' + label_str + '}' if label_str else ''} {self.sum_value}")
        lines.append(f"{self.name}_count{'{' + label_str + '}' if label_str else ''} {self.count}")
        return "\n".join(lines)


class MetricsRegistry:
    """Thread-safe registry of Prometheus-style metrics."""

    def __init__(self) -> None:
        self._gauges: Dict[str, Gauge] = {}
        self._counters: Dict[str, Counter] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.Lock()

    # -- Gauge factories --
    def gauge(self, name: str, description: str = "", **labels: str) -> Gauge:
        key = f"{name}{'_' + '_'.join(f'{k}={v}' for k,v in labels.items()) if labels else ''}"
        with self._lock:
            if key not in self._gauges:
                g = Gauge(name=name, description=description, labels=dict(labels))
                self._gauges[key] = g
            return self._gauges[key]

    # -- Counter factories --
    def counter(self, name: str, description: str = "", **labels: str) -> Counter:
        key = f"{name}{'_' + '_'.join(f'{k}={v}' for k,v in labels.items()) if labels else ''}"
        with self._lock:
            if key not in self._counters:
                c = Counter(name=name, description=description, labels=dict(labels))
                self._counters[key] = c
            return self._counters[key]

    # -- Histogram factories --
    def histogram(self, name: str, description: str = "", **labels: str) -> Histogram:
        key = f"{name}{'_' + '_'.join(f'{k}={v}' for k,v in labels.items()) if labels else ''}"
        with self._lock:
            if key not in self._histograms:
                h = Histogram(name=name, description=description, labels=dict(labels))
                self._histograms[key] = h
            return self._histograms[key]

    # -- Snapshot all metrics as Prometheus text format --
    def collect(self) -> str:
        with self._lock:
            lines = ["# HELP MutaLambda metrics collector"]
            lines.append("# TYPE MutaLambda gauge")
            for g in self._gauges.values():
                lines.append(g.to_prometheus())
            lines.append("")
            lines.append("# TYPE MutaLambda counter")
            for c in self._counters.values():
                lines.append(c.to_prometheus())
            lines.append("")
            lines.append("# TYPE MutaLambda histogram")
            for h in self._histograms.values():
                lines.append(h.to_prometheus())
            return "\n".join(lines)

    def collect_json(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "gauges": {k: vars(v) for k, v in self._gauges.items()},
                "counters": {k: vars(v) for k, v in self._counters.items()},
                "histograms": {k: vars(v) for k, v in self._histograms.items()},
            }


# Singleton registry
_default_registry: Optional[MetricsRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> MetricsRegistry:
    global _default_registry
    with _registry_lock:
        if _default_registry is None:
            _default_registry = MetricsRegistry()
        return _default_registry


def reset_registry() -> None:
    global _default_registry
    with _registry_lock:
        _default_registry = None


# ---------------------------------------------------------------------------
# High-level metric keys used by MutaLambda
# ---------------------------------------------------------------------------

def register_mutalambda_metrics(registry: Optional[MetricsRegistry] = None) -> None:
    """Register the standard MutaLambda metric family into the registry."""
    reg = registry or get_registry()

    # Evolution metrics
    reg.gauge("evolution_best_score", "Best fitness score in current generation")
    reg.gauge("evolution_avg_score", "Average fitness score")
    reg.gauge("evolution_population_size", "Current population size")
    reg.gauge("evolution_generation", "Current generation number")
    reg.gauge("evolution_diversity", "Population diversity index (0-1)")

    # Performance metrics
    reg.counter("evolution_generations_completed", "Total generations completed")
    reg.counter("evolution_evaluations_total", "Total fitness evaluations")
    reg.histogram("evolution_generation_time_sec", "Time per generation in seconds")
    reg.histogram("evolution_evaluation_time_sec", "Time per evaluation in seconds")

    # Mutation metrics
    reg.counter("mutation_applied_total", "Total mutations applied")
    reg.counter("mutation_accepted_total", "Mutations accepted by selection")
    reg.counter("mutation_rejected_total", "Mutations rejected")
    reg.histogram("mutation_change_size", "Size of code change in lines")

    # GPU metrics
    reg.gauge("gpu_utilization", "GPU utilization percentage (0-100)")
    reg.gauge("gpu_memory_used_mb", "GPU memory used in MB")
    reg.gauge("gpu_memory_total_mb", "Total GPU memory in MB")
    reg.counter("gpu_batch_count", "Total GPU batch evaluations")

    # CI / test metrics
    reg.counter("tests_passed_total", "Total test passes")
    reg.counter("tests_failed_total", "Total test failures")
    reg.counter("tests_skipped_total", "Total test skips")
    reg.gauge("test_coverage_pct", "Code coverage percentage")

    # Error metrics
    reg.counter("errors_total", "Total errors encountered", error_type="")
    reg.counter("timeouts_total", "Total timeouts")

    logger.info("Registered %d standard MutaLambda metrics", 30)


# ---------------------------------------------------------------------------
# Prometheus HTTP endpoint (pure stdlib — no FastAPI required)
# ---------------------------------------------------------------------------

try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    _HAS_HTTP_SERVER = True
except ImportError:
    _HAS_HTTP_SERVER = False


class _MetricsHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that exposes /metrics in Prometheus text format."""

    registry: MetricsRegistry = None  # type: ignore[assignment]

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/metrics":
            content = self.registry.collect()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        elif self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
        logger.debug(fmt, *args)


def start_metrics_server(
    host: str = "0.0.0.0",
    port: int = 9100,
    registry: Optional[MetricsRegistry] = None,
) -> Optional[HTTPServer]:
    """Start a minimal Prometheus metrics HTTP server. Returns None if unavailable."""
    if not _HAS_HTTP_SERVER:
        logger.warning("http.server not available — skipping metrics server")
        return None
    reg = registry or get_registry()
    _MetricsHandler.registry = reg
    try:
        server = HTTPServer((host, port), _MetricsHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info("Prometheus metrics server started at http://%s:%d/metrics", host, port)
        return server
    except OSError as exc:
        logger.warning("Could not start metrics server on %s:%d — %s", host, port, exc)
        return None


# ---------------------------------------------------------------------------
# OpenTelemetry integration (optional, graceful degradation)
# ---------------------------------------------------------------------------

class OTelMetricsBridge:
    """
    Bridges MutaLambda internal metrics to OpenTelemetry SDK.

    When OTel is installed, this creates real OTel instruments.
    When OTel is absent, it falls back to no-op silently.
    """

    def __init__(self, registry: Optional[MetricsRegistry] = None) -> None:
        self._registry = registry or get_registry()
        self._meter = None
        self._gauges: Dict[str, Any] = {}
        self._counters: Dict[str, Any] = {}
        self._histograms: Dict[str, Any] = {}
        self._try_init()

    def _try_init(self) -> None:
        try:
            from opentelemetry import metrics as metrics_api  # noqa: PLC0415
            from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415

            provider = MeterProvider()
            metrics_api.set_meter_provider(provider)
            self._meter = metrics_api.get_meter("mutalambda")

            # Create OTel instruments
            self._gauges["evolution_best_score"] = self._meter.create_gauge(
                "evolution.best_score", unit="1", description="Best fitness score"
            )
            self._gauges["evolution_generation"] = self._meter.create_gauge(
                "evolution.generation", unit="1", description="Current generation"
            )
            self._counters["evaluations"] = self._meter.create_counter(
                "evolution.evaluations", unit="1", description="Total evaluations"
            )
            self._histograms["gen_time"] = self._meter.create_histogram(
                "evolution.generation_time_sec", unit="s", description="Gen time"
            )
            logger.info("OpenTelemetry metrics bridge initialized")
        except ImportError:
            logger.debug("opentelemetry not installed — OTel bridge disabled (metrics still available via Prometheus)")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to init OTel bridge: %s", exc)

    def record_gauge(self, name: str, value: float) -> None:
        if self._meter and name in self._gauges:
            self._gauges[name].set(value)
        elif name in {"evolution_best_score", "evolution_generation"}:
            g = self._registry.gauge(f"evolution_{name}", "")
            g.set(value)

    def record_counter(self, name: str, delta: float = 1.0) -> None:
        if self._meter and name in self._counters:
            self._counters[name].add(delta)
        elif name == "evaluations":
            c = self._registry.counter("evolution_evaluations_total", "")
            c.inc(delta)

    def record_histogram(self, name: str, value: float) -> None:
        if self._meter and name in self._histograms:
            self._histograms[name].record(value)
        elif name == "gen_time":
            h = self._registry.histogram("evolution_generation_time_sec", "")
            h.observe(value)

    def shutdown(self) -> None:
        if self._meter:
            try:
                from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
                provider = self._meter.get_meter_provider()
                provider.shutdown()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Convenience functions for common MutaLambda operations
# ---------------------------------------------------------------------------

def record_generation_end(
    generation: int,
    best_score: float,
    avg_score: float,
    duration_sec: float,
    registry: Optional[MetricsRegistry] = None,
) -> None:
    """Record end-of-generation metrics."""
    reg = registry or get_registry()
    reg.gauge("evolution_best_score").set(best_score)
    reg.gauge("evolution_avg_score").set(avg_score)
    reg.gauge("evolution_generation").set(float(generation))
    reg.counter("evolution_generations_completed").inc()
    reg.histogram("evolution_generation_time_sec").observe(duration_sec)


def record_evaluation(
    duration_sec: float,
    accepted: bool,
    change_size: int = 0,
    registry: Optional[MetricsRegistry] = None,
) -> None:
    """Record a single fitness evaluation."""
    reg = registry or get_registry()
    reg.counter("evolution_evaluations_total").inc()
    reg.histogram("evolution_evaluation_time_sec").observe(duration_sec)
    reg.counter("mutation_applied_total").inc()
    if accepted:
        reg.counter("mutation_accepted_total").inc()
    else:
        reg.counter("mutation_rejected_total").inc()
    if change_size > 0:
        reg.histogram("mutation_change_size").observe(float(change_size))


def record_gpu_status(
    utilization: float,
    memory_used_mb: float,
    memory_total_mb: float,
    batch_count: int = 0,
    registry: Optional[MetricsRegistry] = None,
) -> None:
    """Record GPU status metrics."""
    reg = registry or get_registry()
    reg.gauge("gpu_utilization").set(utilization)
    reg.gauge("gpu_memory_used_mb").set(memory_used_mb)
    reg.gauge("gpu_memory_total_mb").set(memory_total_mb)
    if batch_count > 0:
        reg.counter("gpu_batch_count").inc(batch_count)


def record_test_result(passed: bool, registry: Optional[MetricsRegistry] = None) -> None:
    """Record a single test result."""
    reg = registry or get_registry()
    if passed:
        reg.counter("tests_passed_total").inc()
    else:
        reg.counter("tests_failed_total").inc()


# ---------------------------------------------------------------------------
# FastAPI / Flask middleware (optional integrations)
# ---------------------------------------------------------------------------

def create_metrics_middleware(registry: Optional[MetricsRegistry] = None):
    """
    Returns a WSGI/ASGI-compatible middleware that adds /metrics endpoint.
    Usage with FastAPI:
        app.add_middleware(MetricsMiddleware, registry=get_registry())
    """
    reg = registry or get_registry()

    def middleware(request, call_next):
        if request.url.path == "/metrics":
            from starlette.responses import PlainTextResponse  # noqa: PLC0415
            return PlainTextResponse(reg.collect())
        if request.url.path == "/healthz":
            from starlette.responses import JSONResponse  # noqa: PLC0415
            return JSONResponse({"status": "ok"})
        return call_next(request)

    return middleware


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MutaLambda Metrics Server")
    parser.add_argument("--port", type=int, default=9100, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Prometheus format")
    args = parser.parse_args()

    reg = get_registry()
    register_mutalambda_metrics(reg)

    # Simulate some data
    reg.gauge("evolution_best_score").set(0.95)
    reg.gauge("evolution_generation").set(42.0)
    reg.counter("evolution_evaluations_total").inc(1500)
    reg.histogram("evolution_generation_time_sec").observe(2.3)
    reg.histogram("evolution_generation_time_sec").observe(1.8)

    if args.json:
        print(json.dumps(reg.collect_json(), indent=2))
    else:
        print(reg.collect())

    print("\n--- Starting server on http://{}:{}/metrics ---".format(args.host, args.port))
    server = start_metrics_server(host=args.host, port=args.port, registry=reg)
    if server:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down.")
            server.shutdown()
