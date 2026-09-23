# Changelog

All notable changes to MutaLambda are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.1.0] — 2026-09-23

### Added
- **Keccak f1600 optimization integration**: Evolutionary optimization of
  `keccak_f1600` hot-path kernel from Bot_Crowdintel, achieving **1.3156×
  speedup** (+31.6%) via in-situ ρ+π rotation rewrite with `shift==0` guard.
  NSGA-II 3 islands × 14 generations × 50 individuals; KAT verified under
  g++ 13.3.0 and clang++ 22.1.8. See
  [benchmarks/MUTALAMBDA_KEECCAK_BENCHMARKS.md](benchmarks/MUTALAMBDA_KEECCAK_BENCHMARKS.md)
  and [benchmarks/targets/keccak256_optimized.hpp](benchmarks/targets/keccak256_optimized.hpp).

## [5.0.0] — 2026-09-22

### Added
- **UAST v2 mutation engine** (opt-in, `uast.engine: v2`): in-situ mutation over a
  language-neutral AST with verified nanopasses, atomic rollback, incremental
  Merkle hashing and shadow-mode parity checking against the legacy engine.
  See [docs/uast2.md](docs/uast2.md).
- **Cost-optimization layer** ("Headroom"): trace compression, AST stubs,
  structured LLM output, economic gating and Pareto warm-start. Every lever is
  individually toggleable via `config/optimization.yaml` or
  `MUTALAMBDA_OPT_*` environment variables; all levers are off by default.
- **Scientific Validation Layer (SVL)**: opt-in gate (`--scientific`) with
  hard/soft invariant checking, plus `--hotpath` profiling integration.
  See [docs/SCIENTIFIC_OPTIMIZATION_MODE.md](docs/SCIENTIFIC_OPTIMIZATION_MODE.md).
- **Metrics exporter**: Prometheus registry, `/metrics` and `/healthz`
  endpoints, optional OpenTelemetry bridge (opt-in).
  See [docs/metrics-exporter.md](docs/metrics-exporter.md).
- **Package layout**: core implementation organized into `mutalambda_core`,
  `mutalambda_engines`, `mutalambda_config` and `mutalambda_security` packages,
  with thin backward-compatibility shims at the repository root.
- **Packaging fix**: all packages and root modules are now declared in
  `pyproject.toml`, so the distributed wheel is complete and importable after
  `pip install` (previously installed copies were broken).
- CLI: `config.scientific.yaml` template, `--scientific`/`--hotpath` flags.

### Changed
- Root-level modules that moved into the `mutalambda_*` packages are now
  deprecation shims; new code should import from the packages directly.
- `docs/FASE8_METRICS_EXPORTER.md` renamed to `docs/metrics-exporter.md`.

### Removed
- Stale duplicate copies of `models`, `island` and `tiered_evaluator` that
  remained at the repository root after the package reorganization.
- The unused `workflow/` package.
- Process artifacts, applied patches, chat exports and superseded reports
  that no longer described the current state of the code.

### Fixed
- HFC league: laboratory offspring were never evaluated — the "unscored"
  filter still looked for the pre-unification `-inf` sentinel while
  `Individual.score` uses `-1.0` as the "not yet evaluated" value. Cache
  hit/miss telemetry now reflects real evaluations.
- Undefined `Any` reference in `migration.py` (flake8 F821).
- Docker image metadata: version and license label now match the project
  (BSL-1.1).

## [4.0.0]

- Baseline of the evolutionary multi-island optimizer with NSGA-II, GPU
  acceleration, sandboxed evaluation and the LLM-backed mutation pipeline.
- Last release under the MIT license; versions after 4.0.0 are published
  under BSL-1.1 (see [COMMERCIAL.md](COMMERCIAL.md)).

## [2.1.0]

- Prometheus/OpenTelemetry metrics export (superseded and expanded in 5.0.0).
