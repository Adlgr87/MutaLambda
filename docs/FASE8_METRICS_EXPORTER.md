# FASE 8 — Metrics Exporter (Prometheus / OpenTelemetry)

## Objetivo
Expose MutaLambda metrics through industry-standard protocols for long-running
service deployments and observability integrations.

## Implementado

### Archivos
| Archivo | Líneas | Descripción |
|---------|--------|-------------|
| `metrics_exporter.py` | ~500 | Prometheus registry + OTel bridge + HTTP server |
| `tests/test_metrics_exporter.py` | ~290 | Unit tests para Gauge, Counter, Histogram, Registry |
| `tests/integration/test_metrics_integration.py` | ~100 | Integration tests con evolution pipeline |

### Métricas expuestas

#### Evolution
- `evolution_best_score` (gauge) — Mejor fitness score
- `evolution_avg_score` (gauge) — Score promedio
- `evolution_generation` (gauge) — Generación actual
- `evolution_diversity` (gauge) — Diversidad poblacional
- `evolution_generations_completed` (counter) — Generaciones completadas
- `evolution_evaluations_total` (counter) — Evaluaciones totales
- `evolution_generation_time_sec` (histogram) — Tiempo por generación
- `evolution_evaluation_time_sec` (histogram) — Tiempo por evaluación

#### Mutation
- `mutation_applied_total` (counter)
- `mutation_accepted_total` (counter)
- `mutation_rejected_total` (counter)
- `mutation_change_size` (histogram)

#### GPU
- `gpu_utilization` (gauge)
- `gpu_memory_used_mb` (gauge)
- `gpu_memory_total_mb` (gauge)
- `gpu_batch_count` (counter)

#### Tests
- `tests_passed_total` (counter)
- `tests_failed_total` (counter)
- `tests_skipped_total` (counter)
- `test_coverage_pct` (gauge)

#### Errors
- `errors_total` (counter, label: error_type)
- `timeouts_total` (counter)

### APIs

```python
from metrics_exporter import (
    get_registry,
    register_mutalambda_metrics,
    record_generation_end,
    record_evaluation,
    record_gpu_status,
    record_test_result,
    start_metrics_server,
    OTelMetricsBridge,
)

# Init
reg = get_registry()
register_mutalambda_metrics(reg)

# Record
record_generation_end(generation=5, best_score=0.95, avg_score=0.72, duration_sec=2.1)
record_evaluation(duration_sec=0.05, accepted=True, change_size=3)
record_gpu_status(utilization=85.0, memory_used_mb=4000.0, memory_total_mb=8000.0)
record_test_result(passed=True)

# Prometheus endpoint
server = start_metrics_server(host="0.0.0.0", port=9100)

# OpenTelemetry (optional)
otel = OTelMetricsBridge(reg)
otel.record_gauge("evolution_best_score", 0.95)
otel.shutdown()
```

### Endpoint Prometheus

```
GET http://localhost:9100/metrics
Content-Type: text/plain; version=0.0.4

# HELP evolution_best_score Best fitness score in current generation
# TYPE evolution_best_score gauge
evolution_best_score 0.95
...
```

## Uso en producción

### Docker
```yaml
services:
  mutalambda:
    image: mutalambda:latest
    ports:
      - "9100:9100"  # Prometheus metrics
    environment:
      - METRICS_PORT=9100
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
```

### Kubernetes
```yaml
apiVersion: v1
kind: Service
metadata:
  name: mutalambda-metrics
spec:
  selector:
    app: mutalambda
  ports:
    - port: 9100
      targetPort: 9100
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mutalambda
spec:
  selector:
    matchLabels:
      app: mutalambda
  endpoints:
    - port: metrics
      path: /metrics
      interval: 15s
```

## Estado
- ✅ Implementado
- ✅ Tests: unitarios + integración
- ✅ Prometheus endpoint
- ✅ OpenTelemetry bridge (optional)
- ✅ Documentación

## Próximos pasos
- [ ] ConfigMap para configuración de scraping
- [ ] Alertas Prometheus (Alertmanager)
- [ ] Grafana dashboard JSON
- [ ] Dashboards para K8s operator
