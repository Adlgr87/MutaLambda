# MutaLambda - Optimized Architecture v2

> Versión optimizada del sistema MutaLambda con integración GPU, pipeline evolutivo y monitoring completo.

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                      MutaLambda Optimized                       │
├─────────────────────────────────────────────────────────────────┤
│  CLI (mutalambda)                                               │
│  ├── init / status / logs / cleanup                            │
│  └── run --config mutation_optimizer.yaml                      │
├─────────────────────────────────────────────────────────────────┤
│  Core Modules                                                   │
│  ├── mutation_engine.py    — ASTMutator, code mutation          │
│  ├── evolution_engine.py   — EvostraNGA-II optimizer            │
│  ├── meta_evolution.py     — Meta-evolution controller          │
│  ├── hyperparameter_evolution.py — Hyperparameter tuning        │
│  ├── migration.py          — Safe refactoring pipeline          │
│  ├── gpu_optimizer.py      — GPU-accelerated optimization       │
│  ├── ray_scheduler.py      — Distributed batch scheduler        │
│  ├── benchmark_runner.py   — Comprehensive benchmarking         │
│  ├── performance_monitor.py — Real-time monitoring              │
│  └── utils/                  — Logging, metrics, config         │
├─────────────────────────────────────────────────────────────────┤
│  Infrastructure                                                 │
│  ├── tests/                    — 441+ tests (unit/integration)  │
│  ├── scripts/                  — deploy, install, monitoring    │
│  ├── docs/                     — Full documentation             │
│  └── PLANS/                    — Workflow documentation         │
├─────────────────────────────────────────────────────────────────┤
│  GPU Acceleration (Optional)                                    │
│  ├── NSGA-II on CUDA (gpu_optimizer.py)                        │
│  ├── Ray cluster batch fitness evaluation                      │
│  └── Auto fallback to CPU when no GPU                          │
└─────────────────────────────────────────────────────────────────┘
```

## Mejoras respecto a v1

| Aspecto | v1 | v2 (Optimized) |
|---------|----|----------------|
| Tests | ~200 | 441 (+120%) |
| Cobertura | Parcial | >85% |
| GPU | No | NSGA-II + Ray batch |
| Benchmark | Manual | Automático (bench_phase6.py) |
| CI/CD | Básico | Pipeline completo + GPU jobs |
| Documentación | Parcial | Completa (10+ docs) |
| Miggración | Manual | Automatizada con rollback |

## Uso rápido

```bash
# Inicializar proyecto
mutalambda init --name my_project

# Ejecutar optimización (CPU)
mutalambda run --config mutation_optimizer.yaml

# Ejecutar con GPU
CUDA_VISIBLE_DEVICES=0 mutalambda run --config mutation_optimizer_gpu.yaml

# Ejecutar benchmark completo
python bench_phase6.py --num-generations 20 --population-size 50

# Ver estado
mutalambda status
```

## Requisitos

- Python 3.10+
- numpy, scipy, plotly
- Ray + NVIDIA Driver (opcional para GPU)
- Pytest para tests
