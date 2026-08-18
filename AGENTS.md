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
- AST parse cache: `code_hash.cached_parse` wraps `ast.parse` with an
  `lru_cache(maxsize=1024)`. Hot path call sites in `evolution_engine.py`,
  `island.py`, and `hfc_tiers.py` use it for read-only parse results; mutating
  call sites (NodeTransformer pipelines) deepcopy the cached tree first. Call
  `code_hash.clear_ast_cache()` between independent runs if memory pressure
  is a concern.
- Fitness cache must be cleared between runs with different configs.
- Sandbox timeout defaults to 30s; scientific presets may need more.
- Checkpoint serialization: `checkpoint.format` controls output ('auto' default,
  'json', or 'msgpack'). In 'auto' mode, msgpack (zlib-compressed) is used when
  total individuals > 256 (MSGPACK_THRESHOLD), otherwise JSON. msgpack reduces
  I/O by ~60-95% vs JSON for large populations. Existing JSON checkpoints still
  load (backward compatible). Use `mutalambda migrate-checkpoints --format msgpack`
  to re-save older JSON checkpoints as msgpack.
- HFC tiering: `_process_migrations()` in `hfc_tiers.py` handles elite
  deduplication with code-based comparison (`elite.code != ind.code`) to
  distinguish individuals with same ID but different code. Demoted elites are
  tracked via `demoted_ids` set to prevent double-demotion when a challenger
  dominates multiple individuals.

## Conventions
- Python 3.10+; use `pathlib.Path` for all filesystem paths.
- All CLI output uses `rich` for formatting (tables, panels, colors).
- Config validation uses Pydantic models.
- Every refactor must be documented in `EMPIRICAL_EVIDENCE.md` with benchmarks.
