# AGENTS.md — MutaLambda Workflow Guide

## Overview
MutaLambda is an evolutionary code optimization system. This guide documents
CLI workflows, key modules, and conventions for contributors.

## CLI Commands (muta_lambda)

The CLI entry point is `mutalambda` (or `python -m muta_ext`). Key commands:

```bash
mutalambda init            # Interactive config wizard → config.yaml
mutalambda doctor --fix    # Diagnose & auto-fix configuration issues
mutalambda production file.py          # Run with production preset
mutalambda scientific file.py          # Run with scientific preset (SVL, invariants)
mutalambda dashboard [--text]          # Launch post-run visual dashboard
mutalambda explain checkpoints/run_xxx # Explain evolution decisions from a run
```

### Presets
| Preset    | Use Case              | Key Features                              |
|-----------|-----------------------|-------------------------------------------|
| quick     | Fast feedback         | 20 generations, fast mode only            |
| production| Balanced              | 100 generations, 6 islands, HFC enabled |
| scientific| Data science / NumPy  | SVL active, invariant validation        |

### Config Locations
- `config.yaml` — default user config (gitignore)
- `presets/*.yaml` — built-in preset templates
- `checkpoints/run_*/` — per-run directories with `run_manifest.json`

## Architecture

```
muta_ext/
├── __init__.py          # Optimizer, Analyzer, ExplainableOptimizer
├── __main__.py          # CLI entry point (argparse + rich)
├── muta_ext.py →        # core logic (see below)
cli/
├── config_manager.py    # YAML config load/save/diagnose/fix
├── checkpoint_manager.py# Checkpoint persistence & lineage
└── evolution_engine.py  # NSGA-II + island model
```

### Key Modules
- `cli/config_manager.py` — `ConfigManager.load()`, `diagnostic()`, `apply_fix()`
- `cli/checkpoint_manager.py` — `CheckpointManager` for run artifacts
- `evolution_engine.py` — `EvolutionEngine` with NSGA-II + multi-island

## Testing
Run tests from project root:
```bash
pytest tests/ -v
```
Tests cover config management, checkpoint logic, fitness caching, and
evolution operators. Target: 80%+ coverage.

## Performance Notes
- Fitness cache must be cleared between runs with different configs.
- Sandbox timeout defaults to 30s; scientific presets may need more.
- Checkpoint compression (msgpack) reduces I/O by ~60% vs JSON.

## Conventions
- Python 3.10+; use `pathlib.Path` for all filesystem paths.
- All CLI output uses `rich` for formatting (tables, panels, colors).
- Config validation uses Pydantic models.
- Every refactor must be documented in `EMPIRICAL_EVIDENCE.md` with benchmarks.
