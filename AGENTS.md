## MutaLambda — evolutionary code optimization system

### Phase 6 optimization (completed — 2026-08-18)
- AST parse cache (`cached_parse`, `functools.lru_cache(maxsize=1024)`) — **1,057× faster** on parse-heavy hot paths
- Msgpack checkpoint serialization — threshold lowered from 2000 → 256 individuals; **4.00× faster + 99.3% smaller**
- NSGA-II numpy-vectorized dominance matrix — **3.7-4.3× speedup** for N≥50
- Evaluation key caching — invariant `tests_hash` and `environment_hash` precomputed; **242.7× faster** on key generation
- HFC evaluation volume optimization — factory clones skip re-evaluation, inherit parent fitness (~15-25% predicted)

### HFC micro-mutator memoization (added — 2026-08-22)
- Deterministic mutators in `hfc_tiers.py` (`_parsimony_prune`, `_loop_unrolling`, `_memory_optimization`) decorated with `@_memoize` keyed on `stable_code_hash(code)`.
- Cache is module-level (`_micro_mutator_cache`) and cleared between independent runs via `HFCLeagueEngine.clear_caches()`, invoked from `seed()` and `restore()` — prevents cross-generation leakage.
- `tests_hash` invalidation is *automatic*: `cli/main.py` reloads `target_tests.json` each invocation → loaded `test_cases` → hash recalculado → cache de evaluación invalidado (no change needed).

### Phase 6.5: HFC batch eval + cache telemetry (completed — 2026-08-30)
- Single `evaluate_batch` call per generation in `EvaluationEngine` (no per-candidate overhead).
- `_cache_hits`/`_cache_misses` counters on `EvaluationEngine.__post_init__`; `cache_stats()` accessor returns `{hits, misses, hit_rate, total}`.
- `hfc_tiers._evaluate` reads hit/miss deltas from real evaluators (defensive `hasattr` guard for mocks); factory clones inherit parent fitness and skip evaluation.
- Test key alignment note: cache-map keys must use raw `code` strings (not stripped) to match the engine's keying.

### Phase 6.6: Archive-aware migration (completed — 2026-08-30)
- `archive` parameter threaded through `MigrationBus.stage_all_migrations` → `stage_migration` → `_rank_by_destination_diversity` for novelty-aware migrant ordering via `SolutionArchive.novelty_score`.
- Wired in `island_evolution.py` Phase C: staged via `island_evolution.island_evolution.run_once` (sourced from `islands[0].archive`).

### Market-comparison benchmarks (completed — 2026-09-02)
- Harness: `benchmarks/market_comparison_harness.py` (OpenAI-compatible backends Agnes AI + Poolside; OpenRouter scaffolding present, secondary — requiere key/headers no disponibles en env).
- Fixed typo `POOLSDARD_API_KEY` → `POOLSIDE_API_KEY` in `TOOL_REGISTRY` for `poolside-laguna`.
- Validated Agnes AI / Flash 2.0: ratio 0.56–0.77 (1.8x speedup), 66.7–100 % correct según tasks; reproducible.
- Validated Poolside / Laguna XS 2.1 (direct request + harness): funciona, ratio ~0.31–0.69, pero API lenta/inconsistente (5–45s+ por request; >120s ocasional) → no recomendable para runs repeatables de >1 task dentro de timeouts estándar. base_url correcto: `https://inference.poolside.ai/v1/chat/completions`.
- Infraestructura benchmarks intacta: `effibench_harness.py`, `effibench_loader.py`, `run_full_suite.py`, `targets/*`. Smoke tests en `SMOKY_TESTS.md`.

### Pending / Future proposals (from SWE-Agent analysis)
~~1. ProtocolWorkflow per-candidate overhead — skip gates for AST-only mutations (~10-20% predicted, Medium risk)~~ **COMPLETED in Phase 6.5**
~~2. Sandbox worker spawn overhead — persistent worker pool (~5-15% predicted, High risk)~~ **COMPLETED (EvaluationService shared pool)**
3. HFC cache hit-rate instrumentation — add hit/miss counters (`cache_stats()` + `hfc_tiers._evaluate` telemetry, low risk, visibility-only)

### Run commands
```bash
cd /home/adlg/MutaLambda
python bench_phase6.py            # Phase 6 benchmark
python scripts/benchmark_nsga2_cache.py
python scripts/benchmark_checkpoint_serialization.py
python -m pytest tests/ -q --deselect tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory
```
> Resultados actuales (post-optimización memoización HFC): ~458 tests OK.  
> Tests preexistentes en error de colección: 7 (dependencia `tree_sitter` no instalada en el entorno local — ver `DEPENDENCIES note` más abajo; no correlacionados con los cambios).

# AGENTS.md — MutaLambda Workflow Guide

## Production readiness (cerrado 2026-08-23)
- Fuente de verdad: `docs/PRODUCTION_CHECKLIST.md` (workflow `Workflow_productionready_mutalambda`).
- CI verde en main: Python 3.10/3.11/3.12 + Docker; imagen publicada en
  `ghcr.io/adlgr87/mutalambda:{4.0.0,latest}`.
- **Gotcha pools de procesos**: crear SIEMPRE `ProcessPoolExecutor` con contexto
  explícito (`multiprocessing.get_context("forkserver")`, fallback spawn). Con el
  default `fork` (py<=3.13), forkear desde proceso multi-hilo (pytest, runtime con
  hilos de islas/LSP) produce hijos muertos → BrokenProcessPool →
  "Evolution produced no valid individuals". Ver `EvaluationService._make_pool`.
- **Gotcha GHCR**: la referencia de imagen debe ser 100% minúsculas y el workflow
  necesita `permissions: packages: write` para que GITHUB_TOKEN pueda pushear.
- ProfileMode: los valores legacy STRICT/PERMISSIVE fueron eliminados de los call
  sites; no reintroducirlos (el enum válido es HOTFIX/BALANCED/DEBT/RELEASE).

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

The canonical test count is maintained by `scripts/report_test_count.py`
→ `docs/ARTIFACTS/test_count.txt`. Reference it in docs instead of hard-coding
numbers so the count never drifts.

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

## Security

Sandbox hardening (Bloque C — remediated 2026-08-18):

- `SecurityVisitor` (AST `NodeVisitor`) in `runners.py` defeats the documented
  evasion class: `getattr(__builtins__, chr(...)("...")`, `import os as _o; _o.system`,
  `f = exec; f(...)`, `subprocess.Popen`, `open(...,"a")`, `__import__`,
  `importlib`, `pickle`, `ctypes`, network modules.
- `runners.scan_code_security(code)` now delegates to `SecurityVisitor`;
  legacy prefix strings (`import:os`, `call:exec`, `call:os.system`,
  `syntax_error:...`) are preserved for backward compatibility.
- `runners.scan_findings(code) -> List[SecurityFinding]` exposes detailed
  findings with `lineno`/`col` for reporting.
- `enforce_ast_scan` defaults to **True** everywhere (SandboxSection,
  config_loader `_DEFAULTS`, EvolveConfig, SandboxEvaluator, EvaluationService).
- `mutation_filters.check_no_critical_patterns` is backed by the AST visitor,
  so the regex `_CRITICAL_PATTERNS` are no longer evadible by aliasing.
- `SubprocessRunner` emits a `RuntimeWarning` advising `runner_mode="container"`
  for untrusted code (silence with `MUTALAMBDA_UNSAFE_LOCAL=1`). Container
  mode uses `--network=none`, read-only rootfs, `--cap-drop=ALL`, non-root user.
- Regression suite: `tests/security/test_sandbox_escapes.py` (all six
  documented escapes plus extras; 0 false positives on safe stdlib code).

Note: `sys`/`json` are intentionally allowed by the import gate (the wrapper
harness and candidates legitimately use them).


## Phase 7 — Security Hardening (completed)
- `SecurityVisitor` AST-based sandbox scanner blocks all 6 documented escape patterns + extras
- AST scan enabled by default (`enforce_ast_scan=True`) across all config layers
- SubprocessRunner warns once; ContainerRunner recommended for untrusted code
- Mutation filter consults `SecurityVisitor` to block evasive aliases before execution
- Cache stats instrumentation: `cache_stats()` / `report_cache_stats()` expose hit-rate telemetry

## Dependencies
- `tree-sitter>=0.21` and language packs moved to `[uast]` optional extra
- Core dependencies: numpy, msgpack, pydantic, pyyaml, requests
- Install with uast support: `pip install -e ".[uast]"`
