# Release Notes v2.1.0 — FASE 8: Metrics Exporter

## Summary
Adds Prometheus and OpenTelemetry metrics export for long-running service deployments.

## New Files
- `metrics_exporter.py` — Full metrics system with Prometheus registry and OTel bridge
- `tests/test_metrics_exporter.py` — 22 unit tests
- `tests/integration/test_metrics_integration.py` — 5 integration tests
- `docs/FASE8_METRICS_EXPORTER.md` — Documentation

## New Metrics (30+ standard metrics)
- Evolution: best_score, avg_score, generation, diversity, evaluations, generation_time
- Mutation: applied, accepted, rejected, change_size
- GPU: utilization, memory_used, memory_total, batch_count
- Tests: passed, failed, skipped, coverage
- Errors: total (by type), timeouts

## New Endpoints
- `GET /metrics` — Prometheus text format (port 9100)
- `GET /healthz` — Health check

## Backward Compatibility
- Fully backward compatible — metrics are opt-in via `start_metrics_server()`
- OTel integration is optional (graceful degradation when not installed)
- No breaking changes to existing APIs

## Testing
```
pytest tests/test_metrics_exporter.py tests/integration/test_metrics_integration.py -v
# All tests pass
```

## Usage
```python
from metrics_exporter import get_registry, register_mutalambda_metrics, start_metrics_server

reg = get_registry()
register_mutalambda_metrics(reg)
server = start_metrics_server(port=9100)
```
