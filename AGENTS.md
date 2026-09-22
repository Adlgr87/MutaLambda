# AGENTS.md — MutaLambda

Conventions and operational notes for anyone (human or agent) working in
this repository.

## Layout

- `mutalambda_core/`, `mutalambda_engines/`, `mutalambda_config/`,
  `mutalambda_security/` — the implementation packages.
- Root-level `.py` modules — services (sandbox, cost ledger, …) plus thin
  backward-compatibility shims that re-export from the packages. New code
  should import from the packages, not the shims.
- `muta_lambda/` — `MutaLambdaAgent` orchestrator. `muta_ext/` — optimizer
  extensions, UAST/UAST v2, scientific layer. `cli/`, `lsp/` — CLI and LSP.
- `tests/` — pytest suite (unit + integration + security + uast + benchmarks).

## Run commands

```bash
uv sync --extra cli --extra uast --extra dev   # single source of truth: uv.lock

uv run pytest tests/ -q                         # full suite
uv run mutalambda --help                        # CLI smoke

python bench_phase6.py                          # micro-benchmarks (parse cache, checkpoints)
python scripts/benchmark_nsga2_cache.py
python scripts/benchmark_checkpoint_serialization.py
```

> `tree_sitter` (extra `uast`) is required for the UAST test modules; with it
> installed the suite collects with 0 errors.

## Testing conventions

- Run tests from the project root.
- The canonical test count is maintained by `scripts/report_test_count.py`
  → `docs/ARTIFACTS/test_count.txt`. Reference that file in docs instead of
  hard-coding numbers.
- The suite is expected to be fully green; do not add `--deselect`
  workarounds — fix the test or the code.
- `conftest.py` has an autouse fixture that resets module-level caches between
  tests (process pools, HFC memoization, metric registry). Preserve it when
  adding new global state.

## Performance notes

- AST parse cache: `code_hash.cached_parse` wraps `ast.parse` with
  `lru_cache(maxsize=4096)`. Hot-path call sites use it for read-only parse
  results; mutating call sites (NodeTransformer pipelines) deepcopy the cached
  tree first. Call `code_hash.clear_ast_cache()` between independent runs if
  memory pressure is a concern.
- Fitness cache must be cleared between runs with different configs.
- Sandbox timeout defaults to 30s; scientific presets may need more.
- Checkpoint serialization: `checkpoint.format` controls output
  ('auto' default, 'json', or 'msgpack'). In 'auto' mode, msgpack
  (zlib-compressed) is used when total individuals > 256
  (MSGPACK_THRESHOLD), otherwise JSON. Existing JSON checkpoints still load
  (backward compatible). `mutalambda migrate-checkpoints --format msgpack`
  re-saves older JSON checkpoints.

## Gotchas

- **Process pools**: always create `ProcessPoolExecutor` with an explicit
  context (`multiprocessing.get_context("forkserver")`, fallback spawn). The
  default `fork` on a multi-threaded process (pytest, island threads, LSP)
  produces dead children → `BrokenProcessPool` →
  "Evolution produced no valid individuals". See
  `mutalambda_core/evaluation_service.py::_make_pool`.
- **GHCR**: the image reference must be 100% lowercase and the workflow needs
  `permissions: packages: write` for GITHUB_TOKEN to push.
- **ProfileMode**: the legacy STRICT/PERMISSIVE values were removed from call
  sites; do not reintroduce them (valid enum: HOTFIX/BALANCED/DEBT/RELEASE).
- **HFC tiering**: `_process_migrations()` in `hfc_tiers.py` deduplicates
  elites by code (`elite.code != ind.code`) and tracks demoted elites in a
  `demoted_ids` set to prevent double-demotion.

## Conventions

- Python 3.10+; use `pathlib.Path` for all filesystem paths.
- CLI output uses `rich`; config validation uses Pydantic.
- Keep dependencies bounded in `pyproject.toml` (upper pins); exact versions
  live in `uv.lock` and CI validates with `uv sync --locked`.
- Root shims are deprecated: prefer package imports in all new code.

## Security model

- `SecurityVisitor` (AST `NodeVisitor`) in `runners.py` blocks the documented
  sandbox-escape class: builtin obfuscation via `getattr(__builtins__,
  chr(...))`, aliased imports, `exec`/`eval` via variables, `subprocess`,
  `__import__`, `importlib`, `pickle`, `ctypes`, network modules.
- `enforce_ast_scan` defaults to **True** across all config layers.
- `mutation_filters.check_no_critical_patterns` is backed by the AST visitor,
  so the regex patterns are not evadible by aliasing.
- `SubprocessRunner` emits a `RuntimeWarning` advising `runner_mode="container"`
  for untrusted code (silence with `MUTALAMBDA_UNSAFE_LOCAL=1`). Container
  mode uses `--network=none`, read-only rootfs, `--cap-drop=ALL`, non-root
  user. `microvm` mode requires bwrap.
- Exec paths in the main process (differential, metrics injector, benchmarks,
  Ray scheduler) go through `secure_exec.py` (AST pre-scan + restricted
  builtins).
- Regression suite: `tests/security/test_sandbox_escapes.py`.

## Dependencies

- Core: numpy, msgpack, pydantic, pyyaml, requests.
- Optional extras: `[uast]` tree-sitter + language packs, `[cli]` click/rich,
  `[scientific]` z3/pandas/…, `[archive]`, `[dashboard]`, `[dev]`.
