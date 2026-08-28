# Troubleshooting Guide

## Common Issues

### 1. Tests failing after migration

**Symptom:** `ImportError` or test failures

**Solution:**
```bash
# Check Python version
python --version  # Should be 3.10+

# Reinstall dependencies
pip install -e ".[dev]"

# Run with verbose output
pytest -v --tb=long
```

### 2. GPU not detected

**Symptom:** "No GPU available" warnings

**Solution:**
```bash
# Check CUDA
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"

# If False, reinstall with CUDA
pip uninstall torch
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### 3. Ray cluster connection failed

**Symptom:** `ConnectionRefusedError`

**Solution:**
```bash
# Stop existing Ray
ray stop --force

# Start fresh
ray start --head --num-gpus=4

# Verify
ray status
```

### 4. Memory errors with large populations

**Symptom:** `MemoryError` or OOM kills

**Solution:**
```yaml
# Reduce batch size in config
gpu:
  batch_size: 16  # Reduce from 64
```

Or enable memory mapping:
```yaml
storage:
  type: mmap
  path: /tmp/mutalambda_cache
```

### 5. Slow convergence

**Symptom:** Taking too many generations

**Solution:**
```yaml
# Increase population
evolution:
  population_size: 100  # Increase from 50

# Enable GPU
gpu:
  enabled: true
```

### 6. CI pipeline failing

**Symptom:** GitHub Actions failures

**Solution:**
```bash
# Run locally with same environment
pytest tests/ --tb=short

# Check for dependency issues
pip check
```

## Diagnostic Commands

```bash
# Full system status
mutalambda status

# Check GPU availability
python -c "from gpu_optimizer import GPUOptimizer; print(GPUOptimizer.detect())"

# Run diagnostics
python scripts/diagnose.py

# Check test coverage
pytest --cov=muta_lambda --cov-report=term-missing
```

## Log Locations

| Log | Path |
|-----|------|
| Main | `logs/mutalambda.log` |
| Tests | `test-reports/` |
| GPU | `logs/gpu_optimizer.log` |
| Ray | `~/.ray/logs/` |

## Getting Help

1. Check `docs/` for detailed documentation
2. Search GitHub Issues for similar problems
3. Run `mutalambda status` and share output
4. Check `logs/` directory for detailed error messages
