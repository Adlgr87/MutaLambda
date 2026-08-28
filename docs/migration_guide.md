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
