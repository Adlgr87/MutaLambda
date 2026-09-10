# Migration Guide

## Overview

MutaLambda v2 introduces breaking changes from v1. This guide covers migration paths.

## Breaking Changes

| Change | v1 | v2 | Migration |
|--------|----|----|-----------|
| Config format | JSON | YAML | Use migration script |
| CLI entry point | `mutalambda.py` | `__main__.py` | Update references |
| Test structure | Flat | Organized | Update pytest configs |
| GPU support | None | Optional | Add GPU config |

## Migration Steps

### 1. Backup current configuration

```bash
cp config.json config.v1.backup.json
```

### 2. Run migration script

```bash
python migration.py --input config.v1.backup.json --output config.yaml
```

### 3. Update imports

```python
# Old
from muta_lambda.mutation_engine import ASTMutator

# New
from muta_lambda.core.mutation_engine import ASTMutator
```

### 4. Update CI/CD

Add GPU jobs if needed:
```yaml
- name: GPU Tests
  uses: ./.github/workflows/mutalambda-pr-gate.yml
  with:
    gpu: true
```

### 5. Run full test suite

```bash
pytest tests/ -v
```

### 6. Verify E2E

```bash
python -m muta_lambda.main --config config.yaml --dry-run
```

## Rollback

If issues occur:
```bash
python migration.py --rollback --backup config.v1.backup.json
```

## GPU Migration

If adding GPU support:
1. Install CUDA drivers
2. Add `gpu.enabled: true` to config
3. Run `python -c "from gpu_optimizer import GPUOptimizer; print(GPUOptimizer.detect())"`
4. Start Ray cluster if using distributed mode

## Support

- Issues: GitHub Issues
- Docs: `docs/` directory
- Chat: [Discord/Slack]

---

## UAST v2 — activación opt-in (sin romper nada)

El motor UAST v2 (`muta_ext/uast2/`) convive con el motor legacy
(`muta_ext/uast/`, congelado). **No hay migración obligatoria**: el valor por
defecto sigue siendo `legacy` y el pipeline evolutivo, los checkpoints y la API
pública no cambian.

### 1. Verificar paridad antes de activar

```bash
python mutalambda_cli.py uast2 check examples        # exit 0 = sin diferencias
python mutalambda_cli.py uast2 check examples --json # informe + métricas uast2.*
```

### 2. Activar el motor v2

```yaml
# config.yaml
uast:
  engine: v2
  verify: true    # verificación + rollback atómico tras cada nanopass
  shadow: true    # opcional: sigue comparando con legacy y registra diffs
```

o por CLI, sin tocar el fichero:

```bash
python mutalambda_cli.py run --config config.yaml --uast-engine v2 --uast-verify
```

### 3. Comprobar el resultado

```bash
pytest tests/uast2 -q          # 247 tests del motor v2
python bench_uast2.py --reps 3 # puertas de rendimiento (exit 1 si falla alguna)
python bench_uast2.py --reps 3 --phase6   # sin regresión en el pipeline completo
```

### 4. Rollback

```yaml
uast:
  engine: legacy   # una sola bandera: el sistema vuelve al motor original
```

No hay datos que reconvertir: los checkpoints siguen en el mismo formato msgpack
(solo se añade un campo opcional `engine` cuando el motor activo es `v2`), y los
convertidores `legacy_to_v2()` / `v2_to_legacy()` permiten seguir usando
adaptadores, emisores, mutadores y validadores legacy desde el motor nuevo.

### 5. Uso puntual sin cambiar la bandera

```bash
python mutalambda_cli.py uast2 parse examples/target.py            # ver el UAST v2
python mutalambda_cli.py uast2 mutate examples/target.py --seed 42 # mutar y emitir
```

Guía completa: [docs/uast2.md](uast2.md).
