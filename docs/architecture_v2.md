# Architecture v2 - Detailed Design

## Overview

MutaLambda v2 is a complete redesign of the original MutaLambda system with:

1. **GPU-accelerated optimization** - NSGA-II running on CUDA
2. **Distributed batch processing** - Ray cluster for fitness evaluation
3. **Comprehensive testing** - 441+ tests across all modules
4. **Automated migration** - Safe refactoring with rollback
5. **Full observability** - Real-time monitoring and benchmarking

## Module Responsibilities

### mutation_engine.py
Handles AST-based code mutation. Supports multiple mutation strategies:
- Expression mutation
- Statement mutation
- Control flow mutation
- Type mutation

### evolution_engine.py
Core evolutionary algorithm engine using NSGA-II:
- Population management
- Non-dominated sorting
- Crowding distance calculation
- Genetic operators (crossover, mutation)

### gpu_optimizer.py
GPU-accelerated optimization:
- NSGA-II on CUDA via PyTorch
- Batch fitness evaluation on GPU
- Auto fallback to CPU when GPU unavailable

### ray_scheduler.py
Distributed execution:
- Task scheduling across Ray workers
- Fault tolerance with task retries
- Dynamic resource allocation

### benchmark_runner.py
Comprehensive benchmarking:
- Phase 6 extended benchmark
- GPU vs CPU comparison
- Statistical significance testing
- Performance reporting

### performance_monitor.py
Real-time monitoring:
- Resource utilization tracking
- Bottleneck detection
- Alerting on degradation
- Metrics export

## Data Flow

```
Input Code → AST Parser → Mutation Engine → Fitness Evaluation
                                              ↓
                    ← Evolution Engine ← Population
                                              ↓
                    ← GPU/Ray Scheduler ← Batch Processing
                                              ↓
                    ← Migration Pipeline ← Safe Refactoring
                                              ↓
                    ← Benchmark Runner ← Performance Report
```

## Configuration

All configuration is managed through YAML files:

```yaml
# mutation_optimizer.yaml
evolution:
  algorithm: nsga2
  population_size: 50
  generations: 20

optimization:
  objective: min_error
  constraints:
    max_time: 3600
    min_coverage: 0.8

gpu:
  enabled: true
  device: 0
  batch_size: 32
```

## Testing Strategy

- **Unit tests**: Individual module functionality
- **Integration tests**: Module interactions
- **Stress tests**: Large-scale execution
- **Ablation tests**: Feature contribution analysis
- **E2E tests**: Full pipeline validation

## Deployment

See `scripts/deploy.sh` and `.github/workflows/` for CI/CD pipelines.
