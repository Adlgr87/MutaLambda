## MutaLambda — evolutionary code optimization system

### Phase 6 optimization (completed — 2026-08-18)
- AST parse cache (`cached_parse`, `functools.lru_cache(maxsize=1024)`) — **1,057× faster** on parse-heavy hot paths
- Msgpack checkpoint serialization — threshold lowered from 2000 → 256 individuals; **4.00× faster + 99.3% smaller**
- NSGA-II numpy-vectorized dominance matrix — **3.7-4.3× speedup** for N≥50
- Evaluation key caching — invariant `tests_hash` and `environment_hash` precomputed; **242.7× faster** on key generation
- HFC evaluation volume optimization — factory clones skip re-evaluation, inherit parent fitness (~15-25% predicted)
- HFC offspring batch evaluation (WF#17) — `island.py` two-phase driver runs pre-eval gates (build/security/api) for all offspring first, then a single `evaluate_batch` for all first-attempt codes; retries fall back to individual evaluation. Preserves security-gate ordering (unsafe code never sandboxed).
### Phase 6 Block D — Benchmarks (completed — 2026-08-19)
- `benchmarks/harness.py` D2–D6 harness: 30 targets, 30-rep median + Mann-Whitney U + Holm-Bonferroni + Cliff's delta.
- D.5 speedup evidence (`benchmarks/results/D.5_speedup_evidence.md`): headline `t3_page_rank` **6.63×**, `t1_primes_sieve` **1.57×**, all mutants verified (0 L2 divergence, 1000 differential trials).
- D.6 baseline comparison (`benchmarks/results/D.6_baseline_comparison.md`): real-MutaLambda mutant vs LLM-direct (1-shot) and LLM best-of-5 (ollama `qwen2.5:1.5b`) on `t1_matrix_multiply`, `t1_primes_sieve`, `t3_page_rank`, reusing the harness's own `verify_candidate` (D4 three-layer) + `time_function_code` (30-rep median). Runner: `benchmarks/d6_baseline_runner.py` → `benchmarks/results/D.6_baseline_snapshot.json`. LLM endpoint is wired (`llm_backend.py` ollama backend, `http://localhost:11434`) but the model server was CPU-saturated during the run, so `t3_page_rank` LLM rows are `N/A` (see report).

### Pending / Future proposals (from SWE-Agent analysis)
1. ProtocolWorkflow per-candidate overhead — skip gates for AST-only mutations (~10-20% predicted, Medium risk)
2. Sandbox worker spawn overhead — persistent worker pool (~5-15% predicted, High risk)

Note: HFC cache hit-rate instrumentation (item 3) has been completed via `cache_stats()` / `report_cache_stats()`.

### UAST adapters (lazy registry — 2026-08-19)
- `muta_ext/uast/adapters/__init__.py` is a **lazy registry**: `import muta_ext.uast.adapters` does NOT pull in `tree_sitter_rust`/`cpp`/`go`. Rust/C/C++/Go are loaded on demand via `get_adapter(...)` and module-level `__getattr__`.
- When the `uast` extra is missing, `get_adapter("rust")` raises `ImportError` (never `NameError`) with the hint `pip install 'mutalambda[uast]'`. `from muta_ext.uast.adapters import RustAdapter` stays backward-compatible.
- Tests: `tests/test_uast_disabled_bypass.py` (subprocess-isolated, simulates absent bindings) and `tests/test_smoke_imports.py` (Block A4).

### Run commands
```bash
cd /home/adlg/MutaLambda
python bench_phase6.py            # Phase 6 benchmark
python scripts/benchmark_nsga2_cache.py
python scripts/benchmark_checkpoint_serialization.py
python -m pytest tests/ -q --deselect tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory
```

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
- `os` removed from `_FORBIDDEN_IMPORTS`; `os.path.join`, `os.path.exists`, and other safe `os.path` usages are now allowed while `os.system`, `os.popen`, `os.exec*`, `os.spawn*`, `os.fork`, `os.kill` remain blocked via `_FORBIDDEN_ATTR_CALLS` and alias resolution
- Module aliases resolved: `import os as _o; _o.system(...)` now caught (resolves `_o` → `os` before checking `_FORBIDDEN_ATTR_CALLS`)
- Dangerous from-imports caught: `from os import system` blocked while `from os.path import join` allowed
- SubprocessRunner warns once; ContainerRunner recommended for untrusted code
- Mutation filter consults `SecurityVisitor` to block evasive aliases before execution
- Cache stats instrumentation: `cache_stats()` / `report_cache_stats()` expose hit-rate telemetry
- Security scan instrumentation: `get_security_stats()` exposes call/blocked/allowed/syntax_error counts and per-kind finding rates

## Phase 8 — Sandbox Isolation Hardening C3 (completed)
- `create_runner()` default is now `"container"` (was `"subprocess"`). When no container engine (docker/podman) is on PATH, it gracefully falls back to `SubprocessRunner` with `enforce_ast_scan=True` and emits a `RuntimeWarning` documenting the fallback.
- `SubprocessRunner` now applies hard `resource.setrlimit` bounds **inside the spawned child** via `preexec_fn`:
  - `RLIMIT_CPU` (default 2s soft, +5 hard)
  - `RLIMIT_AS` (256MB default from `memory_mb`)
  - `RLIMIT_NPROC` (128)
  - `RLIMIT_FSIZE` (1MB)
  - Each limit guarded for platforms where `resource.RLIMIT_*` is absent (e.g. Windows/BSD/musl).
- New fields on `SubprocessRunner`: `cpu_limit`, `nproc_limit`, `fsize_mb`; both `SubprocessRunner` and `ContainerRunner` expose a `mode` property.
- RLIMIT instrumentation: `get_rlimit_stats()` exposes `rlimit_hits`, `rlimit_enforced`, `rlimit_unsupported` counters (mirrors `get_security_stats()`).
- `EvaluationService` / `SandboxEvaluator` defaults changed to `runner_mode="container"` (tests that don't need a real engine pass `runner_mode="subprocess"` explicitly). Container remains an optional dependency (no hard docker requirement in core deps).
- Regression suite: `tests/security/test_rlimit_enforcement.py` (12 tests: default-mode resolution, fallback AST-scan forcing, CPU-burn termination, memory ceiling, stats counters).

## Dependencies
- `tree-sitter>=0.21` and language packs moved to `[uast]` optional extra
- Core dependencies: numpy, msgpack, pydantic, pyyaml, requests
- Install with uast support: `pip install -e ".[uast]"`
