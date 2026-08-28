# Testing Guide

## Test Suite Overview

MutaLambda has 441+ tests organized into 5 categories:

| Category | Files | Tests | Purpose |
|----------|-------|-------|---------|
| Unit | tests/unit/ | ~150 | Module-level functionality |
| Integration | tests/integration/ | ~100 | Cross-module interactions |
| Stress | tests/stress/ | ~50 | Large-scale performance |
| Ablation | tests/ablation/ | ~40 | Feature contribution |
| E2E | tests/e2e/ | ~101 | Full pipeline validation |

## Running Tests

### All tests
```bash
pytest tests/ -v
```

### By category
```bash
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/stress/ -v
pytest tests/ablation/ -v
pytest tests/e2e/ -v
```

### With coverage
```bash
pytest tests/ --cov=muta_lambda --cov-report=html
```

### Fast feedback (critical path)
```bash
pytest tests/unit/test_ast_mutator.py tests/e2e/test_end_to_end.py -v
```

## Writing New Tests

### Unit test template
```python
import pytest
from muta_lambda.core.mutation_engine import ASTMutator

class TestASTMutator:
    def test_expression_mutation(self):
        code = "x = 1 + 2"
        mutator = ASTMutator()
        result = mutator.mutate(code, strategy="expression")
        assert result != code
```

### Integration test template
```python
def test_evolution_pipeline():
    engine = EvolutionEngine(config)
    result = engine.run(generations=5)
    assert result.final_population is not None
```

### Stress test template
```python
@pytest.mark.stress
def test_large_population():
    engine = EvolutionEngine(config, population_size=500)
    result = engine.run(generations=10)
    assert len(result.final_population) == 500
```

## CI Integration

Tests run automatically on:
- Push to main
- Pull requests
- Scheduled daily runs

See `.github/workflows/mutalambda-optimization-pipeline.yml` for details.

## Performance Benchmarks

Run the full benchmark suite:
```bash
python bench_phase6.py --num-generations 20 --population-size 50
```

Results are saved to `PHASE6_BENCHMARK_REPORT.md`.
