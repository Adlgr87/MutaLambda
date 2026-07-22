# Scientific Optimization Mode

## Overview

Extiende MutaLambda con 3 capacidades Tier 1:

1. **SVL**: Validación científica vía invariantes (hard/soft)
2. **Hot-path**: Profiling cProfile + optimización inter-procedural
3. **Domain Operators**: Mutadores con conciencia numérica

## Activation

```bash
python cli.py run --config config.scientific.yaml
python cli.py run --scientific  # atajo
```

## Pipeline

```
build → security → sandbox → tests → scientific_validation → perf → decision
```

## Configuration

```yaml
scientific:
  enabled: true                     # Master switch
  validation:                       # Fase 1: SVL
    invariants: true
    numerical_stability: true
    conservation_checks: true
    property_based: true
  hotpath:                          # Fase 2: Hot-path
    enabled: true
    profiler: "cprofile"
    min_cumulative_pct: 5.0
  domain_operators:                 # Fase 3: Operadores de dominio
    enabled: true
    strength: 0.3
```

## Invariants

| Invariant | Severity | Description |
|-----------|----------|-------------|
| energy_non_negative | hard | Total energy ≥ -1e-9 |
| mass_conservation | hard | \|Δmass\| < 1e-8 |
| physical_bounds | soft | Quantities in [1e-15, 1e15] |
| monotonicity_trend | soft | Entropy non-decreasing |
| numerical_stability | hard | No NaN/Inf/overflow |

## Domain Operators

| Operator | Description |
|----------|-------------|
| StrengthReductionMutator | x² → x*x, x*2 → x<<1 |
| NumericalStabilityMutator | (a+b)-c → a+(b-c) |
| LoopFusionMutator | Merge adjacent loops |
| LoopFissionMutator | Split loops |
| SafeVectorizationMutator | Loop → np.sum |

## Rollback

```yaml
scientific:
  enabled: false
```

Al desactivar, el workflow vuelve a comportamiento original sin validación científica.