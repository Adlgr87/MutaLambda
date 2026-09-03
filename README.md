# MutaLambda — Optimized Multi-Agent Evolutionary System

> **MutaLambda v5.0.0**: Sistema de optimización evolutiva multi-agente con integración GPU, pipeline CI/CD completo, benchmarking científico y 663 tests validados.
> Un framework de alta performance para optimización de código asistida por IA con aceleración hardware.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/Adlgr87/MutaLambda/actions/workflows/mutalambda-optimization-pipeline.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
[![Docker](https://github.com/Adlgr87/MutaLambda/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-61%25-orange)]()
[![GPU Ready](https://img.shields.io/badge/GPU-ready-orange)]()
[![Tag](https://img.shields.io/badge/tag-v5.0.0--phase7--8-blue)]()
[![Status](https://img.shields.io/badge/status-beta-lightgrey)]()
[![Benchmarks](https://img.shields.io/badge/benchmarks-EffiBench-blue)]()

## 🚀 Estado Actual

| Métrica | Valor | Estado | Última verificación |
|---------|-------|--------|---------------------|
| Tests | **663 passed, 6 skipped** | ✅ 669 collected | 2026-09-02 |
| Cobertura | **61%** | 🔄 En progreso (FASE 8) | 2026-09-02 |
| Versión git | **v5.0.0-phase7-8** | ✅ Tag oficial | 2026-08-23 |
| Fases completadas | **FASE 0–7** | ✅ Workflow cerrado | 2026-08-23 |
| Fases pendientes | **FASE 8** (Prometheus/OTel metrics) | 🔄 En progreso | — |
| Repositorio | [github.com/Adlgr87/MutaLambda](https://github.com/Adlgr87/MutaLambda) | Active | — |

## Áreas Vanguardistas

### 1. 🧬 Optimización Evolutiva con NSGA-II
Sistema de evolución multi-objetivo que optimiza código simultáneamente en **calidad, eficiencia y seguridad**. Implementa el algoritmo NSGA-II (Non-dominated Sorting Genetic Algorithm II) con soporte GPU acelerado.

```python
from evolution_engine import EvolutionEngine
engine = EvolutionEngine(config)
result = engine.optimize(generations=50, population_size=100)
```

### 2. 🎮 GPU-Accelerated Evolution (FASE 4-5)
Integración completa de NSGA-II en CUDA via PyTorch con escalado distribuido mediante Ray:
- **gpu_optimizer.py**: NSGA-II en GPU con mixed precision
- **ray_scheduler.py**: Batch processing distribuido en cluster
- **Auto fallback**: Detecta GPU disponible y degradea gracefully a CPU

### 3. 🛡️ UAST-Based Code Intelligence
Parser universal que construye Unified Abstract Syntax Trees para análisis semántico cross-language:
- Soporte nativo: Python, TypeScript, Rust, Go, C/C++
- Mutation engine basado en AST con 4 estrategias de mutación
- Invariant detection para code quality assurance

### 4. 📊 Benchmarking Científico (FASE 6)
Pipeline de benchmarking extendido con:
- `bench_phase6.py`: Evaluación completa multi-generación
- Reportes automatizados con visualización Plotly
- Comparación GPU vs CPU con testing estadístico

### 5. 🔧 Safe Migration Pipeline
Sistema de refactorización automatizada con rollback:
- `migration.py`: Pipeline seguro de transformación de código
- Generación de PRs con cambios validados
- Testing post-migración automático

### 6. 📈 Meta-Evolución
Capa de auto-mejora que evoluciona la configuración del sistema mismo:
- `meta_evolution.py`: Tuning automático de hiperparámetros
- `hyperparameter_evolution.py`: Optimización de estrategia evolutiva

### 7. 🌐 Multi-Agent Orchestration
Arquitectura diseñada para ejecución con múltiples agentes de IA:
- Compatible con OpenHands, Claude Code, y agentes autónomos
- Flujos de trabajo definidos por YAML/JSON
- Integración con sistemas de observabilidad

### 8. 🔬 Research & Reproducibility
Enfoque científico con trazabilidad completa:
- Resultados reproducibles con seeds fijos
- Evolución tracking en JSON
- Validación cross-benchmark

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                    MutaLambda Optimized v2                      │
├─────────────────────────────────────────────────────────────────┤
│  CLI (mutalambda)                                               │
│  ├── init / status / logs / cleanup                            │
│  └── run --config mutation_optimizer.yaml                      │
├─────────────────────────────────────────────────────────────────┤
│  Core Modules                                                   │
│  ├── mutation_engine.py    — ASTMutator, code mutation          │
│  ├── evolution_engine.py   — EvostraNSGA-II optimizer           │
│  ├── meta_evolution.py     — Meta-evolution controller          │
│  ├── hyperparameter_evolution.py — Hyperparameter tuning        │
│  ├── migration.py          — Safe refactoring pipeline          │
│  ├── gpu_optimizer.py      — GPU-accelerated NSGA-II            │
│  ├── ray_scheduler.py      — Distributed batch scheduler        │
│  ├── benchmark_runner.py   — Comprehensive benchmarking         │
│  ├── performance_monitor.py — Real-time monitoring              │
│  └── utils/                  — Logging, metrics, config         │
├─────────────────────────────────────────────────────────────────┤
│  Infrastructure                                                 │
│  ├── tests/                    — 641 tests (unit/integration)   │
│  ├── scripts/                  — deploy, install, monitoring    │
│  ├── docs/                     — Full documentation (22 files)  │
│  └── PLANS/                    — Workflow documentation         │
├─────────────────────────────────────────────────────────────────┤
│  GPU Acceleration (Optional)                                    │
│  ├── NSGA-II on CUDA (gpu_optimizer.py)                        │
│  ├── Ray cluster batch fitness evaluation                      │
│  └── Auto fallback to CPU when no GPU                          │
└─────────────────────────────────────────────────────────────────┘
```

## 🔐 Seguridad y Configuración

- **API keys**: se pasan via variables de entorno, nunca hardcodeadas en el repo. `llm_backend.py` consume `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` (`MUTALAMBDA_OPENROUTER_URL`) o `MISTRAL_API_KEY` según el backend configurado.
- **.gitignore**: incluye patrones `benchmarks/results_*.json` y `benchmarks/output/` para no commitear artefactos de runs ni tokens logs.
- **Auditoría de secretos**: validada con gitleaks (workflow `secret-scan`) → GREEN en rama principal y en el commit de typo-fix `5062a65`.
- Ver detalle en [AGENTS.md](AGENTS.md) → sección `## MutaLambda_github` (cierre comercial + security audit, PR #86 merged).

## Quick Start

```bash
# Clone
git clone https://github.com/Adlgr87/MutaLambda.git
cd MutaLambda

# Install
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Initialize project
mutalambda init --name my_project

# Execute optimization
mutalambda run --config mutation_optimizer.yaml

# GPU mode
CUDA_VISIBLE_DEVICES=0 mutalambda run --config mutation_optimizer_gpu.yaml
```

## Testing

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=muta_lambda --cov-report=html

# E2E only
pytest tests/e2e/ -v

# Stress tests
pytest tests/stress/ -v
```

**Test Results**: `663 passed, 6 skipped` ✅ (669 collected, 2026-09-02)

## 📊 Benchmarking Científico

MutaLambda valida su rendimiento contra benchmarks públicos reconocidos.

### EffiBench Harness (TIER 1)
Pipeline reproducible con el dataset EffiBench (1000 tasks; 891 convertibles a Python).
- **Dataset**: `/tmp/effibench_train.parquet` (pyarrow)
- **Smoke tests (sin API keys)**:
  ```bash
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 20 --baseline-only   # correctness + timing
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 10                   # identity mode (ratio = 1.0)
  ```
- **LLM mode (con Ollama / OpenRouter)**:
  ```bash
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 8 --llm --samples 3 --warmups 1
  ```
- **Métricas**: `ratio_to_canonical` (1.0 = baseline canónico), `%Opt`, `mean_speedup`, `correctness_rate`. Candidate gated por `correctness == 1.0` antes de contar speedup (`benchmarks/SMOKY_TESTS.md`).
- **Status**: ✅ SMOKE PASS validado. Reporte: `benchmarks/results_effibench.json` (gitignored).

> 📌 Los artefactos `*_results.json` están en `.gitignore` (se regeneran en cada run).

## Workflows Completados

| Fase | Descripción | Estado | Archivos clave | Tests |
|------|-------------|--------|----------------|-------|
| FASE 0 | Análisis Inicial | ✅ | Coverage report, architecture analysis | — |
| FASE 1 | Sistema de Pruebas | ✅ | 641 tests, CI pipelines → 663/669 | 663 passed, 6 skipped |
| FASE 2 | Refactorización | ✅ | ASTMutator, migration pipeline | — |
| FASE 3 | Análisis Pre-GPU | ✅ | optimization_workflow.md | — |
| FASE 4 | GPU Pilot (NSGA-II) | ✅ | gpu_optimizer.py, ray_scheduler.py | — |
| FASE 5 | GPU Expansión (Batch) | ✅ | Distributed batch processing | — |
| FASE 6 | Benchmarking Científico | ✅ | bench_phase6.py, cached_parse, msgpack | — |
| FASE 7 | Documentación y Deploy | ✅ | 22 docs, install scripts, CI/CD | — |
| FASE 8 | Metrics Exporter (OTel/Prometheus) | 🔄 En progreso | metrics_exporter.py (parcial) | — |

## Documentation

- [CLI reference](docs/CLI.md)
- [Fitness metrics](docs/FITNESS_METRICS.md)
- [Metrics](docs/METRICS.md)
- [Scientific Optimization Mode](docs/SCIENTIFIC_OPTIMIZATION_MODE.md)
- [Test Execution Protocol](docs/TEST_EXECUTION_PROTOCOL.md)
- [Production checklist](docs/PRODUCTION_CHECKLIST.md)
- [First optimization walkthrough](docs/getting-started/first-optimization.md)
- [Architecture v2](docs/architecture_v2.md)
- [GPU Integration](docs/gpu_integration.md)
- [Testing Guide](docs/testing_guide.md)
- [Performance Report](docs/performance_report.md)
- [Migration Guide](docs/migration_guide.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Deployment Guide](docs/deployment_guide.md)
- [README en español](README_ES.md)

## Roadmap

- [x] FASES 0–7: Pipeline completo con GPU, benchmarking y documentación
- [x] FASE 6: Benchmarking científico (EffiBench smoke + identity validation)
- [ ] FASE 8: Metrics exporter (Prometheus/OTel) para despliegues en producción
- [ ] src-layout packaging migration
- [ ] Fair market comparison: benchmarks vs ShinkaEvolve/OpenEvolve/PyGGI con presupuesto idéntico (ver playbook local)
- [ ] Soporte para más lenguajes (Java, Kotlin, Swift)
- [ ] Integración con plataformas de MLOps (MLflow, Weights & Biases)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Citation

```bibtex
@software{mutalambda2026,
  author = {Adlgr87},
  title = {MutaLambda: Optimized Multi-Agent Evolutionary System},
  year = {2026},
  url = {https://github.com/Adlgr87/MutaLambda},
  version = {5.0.0}
}
```
