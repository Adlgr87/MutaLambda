<div align="center">

<img src="assets/MutaLambda_Logo.png" alt="MutaLambda logo" width="220"/>

# MutaLambda

**Evolutionary code optimization: LLMs + genetic algorithms (NSGA-II) that make your Python, Rust and C++ faster without breaking it.**

[![CI](https://github.com/Adlgr87/MutaLambda/actions/workflows/python-package.yml/badge.svg?branch=main)](https://github.com/Adlgr87/MutaLambda/actions/workflows/python-package.yml)
[![Optimization Pipeline](https://github.com/Adlgr87/MutaLambda/actions/workflows/mutalambda-optimization-pipeline.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions/workflows/mutalambda-optimization-pipeline.yml)
[![Docker Image](https://github.com/Adlgr87/MutaLambda/actions/workflows/docker-image.yml/badge.svg?branch=main)](https://github.com/Adlgr87/MutaLambda/actions/workflows/docker-image.yml)
[![Docker pulls](https://img.shields.io/badge/ghcr.io-adlgr87%2Fmutalambda-blue)](https://github.com/Adlgr87?tab=packages&q=mutalambda)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-4.0.0-green.svg)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey.svg)](#license)

</div>

---

MutaLambda combines an LLM with NSGA-II multi-island evolution to automatically optimize code while a **hard correctness gate** guarantees behavior is preserved. Everything runs through a sandboxed evaluation service with fork-safe process pools, msgpack checkpoints and reproducible run artifacts.

## Why MutaLambda / Differentiators

| | Profilers + manual tuning | Pure LLM "optimize this" tools | **MutaLambda** |
|---|---|---|---|
| Search strategy | Human-driven | Single-shot generation | Multi-island NSGA-II Pareto search |
| Correctness guarantee | Manual test review | Hope | Hard gate + property-based testing |
| Cross-language | Manual porting | Usually one language | UAST layer: Python, Rust, C++ |
| Reproducibility | Ad-hoc | None | Run artifacts + msgpack checkpoints |
| Safety | Code review only | Often executes raw output | Regex gates + sandboxed pool eval |

### Cutting-edge capabilities

- 🧬 **Multi-island NSGA-II evolution** — Pareto optimization over latency P50 and memory peak with correctness as hard gate; ring / mesh / random / fully-connected migration topologies.
- ⛰️ **HFC (Hierarchical Fitness Climbing)** — three tiers (lab → factory → elite) with bacterial clones; cheap candidates climb or get pruned early.
- 🌉 **UAST cross-language mutations** — language-agnostic AST layer with adapters/emitters for Python, Rust and C++, enabling structural mutations portable across languages.
- 🔁 **THC (Horizontal Code Transfer)** — cross-island candidate sharing via `HorizontalTransferEngine`, so good genetic material propagates between islands instead of staying local.
- 🧠 **Prompt evolution** — the LLM system prompts themselves evolve via meta-evolution (`prompt_evolution.py`).
- 🧪 **Anti-hallucination verification** — SymPy-based algebraic checks plus Scientific Mode domain invariants (energy conservation, mass balance, monotonicity).
- 🚀 **Engineering at scale** — AST parse cache (~1000× on hit), vectorized NSGA-II dominance (3.7–4.3× at N≥50), msgpack checkpoints (99.3% smaller), FAISS semantic cache, persistent worker pools.

### Validated results

Internal targets from the author's MASSIVE framework (see honesty note below):

| Target | Improvement | Correctness |
|--------|-------------|-------------|
| utility_logic | **3.6× faster** | ✅ tests passed |
| energy_engine_pure | **2.3× faster** | ✅ tests passed |
| social_architect_pure | **1.5× faster** | ✅ tests passed |
| intervention_optimizer | **25.8% simpler** | ✅ tests passed |

> [!IMPORTANT]
> **Honesty note:** these targets are internal modules, not standard public benchmarks (Rosetta / HumanEval-Plus / MBPP-Exec). They have not been reproduced on unseen codebases and before/after diffs are not published here, so these numbers cannot be independently audited from this repository. "Correctness" means the author's own test targets passed. The Phase-6 micro-benchmarks show real gains at scale; end-to-end speedup on small workloads is ~1.0× because LLM latency dominates.

## Architecture Overview

```
                    ┌─────────────────────────────┐
   CLI/API ───────▶ │  Progressive Pipeline       │
                    │  (5 phases)                 │
                    └──────────┬──────────────────┘
                               │
        ┌──────────────────────┼─────────────────────┐
        ▼                      ▼                     ▼
┌───────────────┐    ┌───────────────────┐  ┌──────────────┐
│ Discovery &   │    │ Test Synthesis    │  │ Fast Mode    │
│ Hotspots      │    │ (Hypothesis)      │  │ (5 variants) │
└───────────────┘    └───────────────────┘  └──────┬───────┘
                                                   │
                            ┌──────────────────────▼──────────────┐
                            │ Deep Evolution                      │
                            │  Multi-island NSGA-II               │
                            │  ├ HFC tiers + bacterial clones     │
                            │  ├ THC horizontal transfer          │
                            │  └ Prompt evolution                 │
                            └──────────────────┬──────────────────┘
                                               │
                            ┌───────────────────▼─────────────────┐
                            │ Sandboxed Evaluation Service        │
                            │  correctness gate → latency/mem     │
                            │  fork-safe pools · FAISS cache      │
                            └──────────────────┬──────────────────┘
                                               │
                            ┌───────────────────▼─────────────────┐
                            │ Patch & Report                      │
                            │  git-style diff · run artifacts     │
                            └─────────────────────────────────────┘
```

<details>
<summary><strong>Module map</strong></summary>

```
MutaLambda/
├── muta_lambda.py            # Main orchestrator + CLI entrypoint
├── progressive_pipeline.py   # 5-phase workflow orchestration
├── evolution_engine.py       # AST mutation operators & CoreEvolutionEngine
├── island.py                 # Island evolution unit (NSGA-II)
├── fitness_vector.py         # 3-objective Pareto fitness
├── mutation_filters.py       # Security/correctness gates
├── component_evolution.py    # Coupling/cohesion analysis
├── hfc_tiers.py              # Hierarchical Fitness Climbing (Tier 1/2/3)
├── config_loader.py          # YAML → Pydantic config loader
├── checkpoint_manager.py     # Msgpack-based evolution state persistence
├── sandbox.py                # Secure candidate evaluation
├── archive.py                # FAISS semantic cache (RAG)
└── muta_ext/uast/            # Universal AST (multi-language)
    ├── adapters/             # Source → UAST parsers (Python, Rust, C++)
    ├── emitters/             # UAST → source code generators
    ├── mutators/             # Structural mutation operators
    └── thc_engine.py         # Horizontal Code Transfer (cross-island sharing)
```

</details>

## Installation

### From source

```bash
git clone https://github.com/Adlgr87/MutaLambda.git
cd MutaLambda
pip install -r requirements.txt
```

### Optional extras

```bash
pip install -e ".[uast]"   # tree-sitter based UAST support (Rust/C++)
```

### Docker (published image)

```bash
docker pull ghcr.io/adlgr87/mutalambda:latest
docker run --rm ghcr.io/adlgr87/mutalambda:latest --version

# Optimize a file from your current directory:
# mount it read-write into the container's /workspace
docker run --rm -v "$(pwd)":/workspace ghcr.io/adlgr87/mutalambda:latest examples
```

The image is hardened: non-root user, read-only-rootfs compatible, OCI labels. Published to GHCR on every push to `main` as `ghcr.io/adlgr87/mutalambda:{version,latest}`.

## Quick Start

```bash
mutalambda --help                          # packaged CLI (or: python muta_lambda.py --help)

python muta_lambda.py --optimize my_script.py                # auto pipeline
python muta_lambda.py --optimize my_script.py --mode fast    # fast mode only
python muta_lambda.py --optimize my_script.py --mode deep    # full NSGA-II evolution
python muta_lambda.py --optimize my_script.py --hfc-enabled  # HFC leagues enabled
python muta_lambda.py --resume checkpoints/run_xxx           # resume from checkpoint
python muta_lambda.py --dashboard                            # HITL console dashboard
```

Or use the packaged CLI with presets and helpers:

```bash
mutalambda quick file.py       # fast feedback preset
mutalambda production file.py  # balanced preset (100 gen, 6 islands, HFC on)
mutalambda scientific file.py  # SVL + domain-invariant verification
mutalambda doctor              # validate environment, LLM backend, runner
mutalambda interactive         # REPL-style session
mutalambda tutorial            # guided step-by-step walkthrough
```

Full reference: [docs/CLI.md](docs/CLI.md) · Guided walkthrough: [docs/getting-started/first-optimization.md](docs/getting-started/first-optimization.md)

## Pipeline CLI Modules

> **Status:** FASES 0–2 of the 2.0 pipeline implemented (2026-08-24). FASE 3+ pending CI validation.

The optimization pipeline is composed of independent CLI modules that chain together via GitHub Actions artifacts:

| Module | Usage | Description |
|--------|-------|-------------|
| `universal_parser.py` | `python universal_parser.py examples/target.py -o uast.json` | CLI wrapper over UAST adapters (Python, Rust, C++) → CoreUAST JSON |
| `invariant_detector.py` | `python invariant_detector.py uast.json -o invariants.lock` | Static analyzer: CODATA constants, math identities, numeric tolerances, crypto patterns |
| `evolve.py` | `python evolve.py --uast uast.json --profile scientific --generations 50` | Unified orchestrator: AST mutation + HFC tiers + checkpoints. Profiles: `enterprise`, `scientific`, `gpu` |
| `regression_gate.py` | `python regression_gate.py comparison.json --max-regression 2` | Gate with configurable thresholds. PR-gate mode is non-blocking (annotate only) |
| `certify.py` | `python certify.py --baseline baseline.json --optimized optimized.json --invariants invariants.lock --sign` | Generates `certificate.json` with content hashes + optional HMAC signature |

### Artifact Wire Contracts

See [docs/pipeline.md](docs/pipeline.md) for full JSON schemas. Key artifacts:

- **`uast.json`** — flat node list with `type`, `name`, `start_line`, `end_line`, `children`
- **`invariants.lock`** — versioned JSON with `content_hash`, `constants`, `identities`, `tolerances`, `crypto_patterns`
- **`comparison.json`** — baseline vs optimized metrics with Mann-Whitney U test results
- **`certificate.json`** — signed binding of baseline_hash, optimized_hash, invariants_hash, seed, config_hash

### GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `python-package.yml` | push/PR | Lightweight CI: lint + tests + CLI smoke |
| `mutalambda-pr-gate.yml` | PR on main | Fast gate (<10 min): flake8 + black + pytest + CLI smoke |
| `mutalambda-optimization-pipeline.yml` | `workflow_dispatch` only | Full 6-phase pipeline: fingerprint → baseline → evolve → verify → compare → explain/publish |

## Configuration

Configuration lives in `config.yaml` with Pydantic validation:

```yaml
evolution:
  islands: 4
  generations: 100
  topology: ring

population:
  size: 50
  elite: 10
  migration_interval: 10

sandbox:
  timeout: 30
  workers: 4

llm:
  backend: ollama
  model: codestral

uast:
  enabled: false
  languages: [python, rust, cpp]
```

## Pipeline Stages

1. **Discovery & Hotspots** — profiling + top-3 function extraction
2. **Test Synthesis** — auto-generate Hypothesis strategies
3. **Fast Mode** — LLM generates 5 optimized variants, parallel sandbox eval
4. **Deep Evolution** — NSGA-II multi-island with HFC + THC
5. **Patch & Report** — git-style diff + comparative metrics + run artifacts

## Language Support (via UAST)

| Language | Adapter | Emitter | Status |
|----------|---------|---------|--------|
| Python | ✅ | ✅ | Primary |
| Rust | ✅ | ✅ | Supported |
| C++ | ✅ | ✅ | Supported |

## Testing

```bash
python -m pytest tests/ -v
```

Current status: **531 test functions** (canonical count via `scripts/report_test_count.py`, incluye 7 con errores de colección por dependencia opcional `tree_sitter` en entornos locales). CI green across Python 3.10/3.11/3.12 plus Docker build/test/push. See [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md) for the production-readiness audit.

> **Note:** Tests require `pytest` (`pip install pytest`). Run with `python -m pytest tests/ -v` or use the bundled CLI: `mutalambda test`.

## Documentation

- [CLI reference](docs/CLI.md)
- [Fitness metrics](docs/FITNESS_METRICS.md)
- [Metrics](docs/METRICS.md)
- [Scientific Optimization Mode](docs/SCIENTIFIC_OPTIMIZATION_MODE.md)
- [Test Execution Protocol](docs/TEST_EXECUTION_PROTOCOL.md)
- [Production checklist](docs/PRODUCTION_CHECKLIST.md)
- [First optimization walkthrough](docs/getting-started/first-optimization.md)
- [Architecture v2](docs/architecture_v2.md)
- [GPU Integration](docs/gpu_integration.md)
- [Testing Guide](docs/testing_guide.md)
- [Performance Report](docs/performance_report.md)
- [Migration Guide](docs/migration_guide.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Deployment Guide](docs/deployment_guide.md)
- [README en español](README_ES.md)

## Roadmap

- [x] FASES 0–2: Pipeline CLI modules (universal_parser, invariant_detector, evolve, regression_gate, certify)
- [x] FASES 0–2: GitHub Actions workflows (PR gate + optimization pipeline)
- [x] FASE 3: Pre-GPU analysis and optimization workflow
- [x] FASE 4: GPU Integration - Pilot Phase (NSGA-II on CUDA)
- [x] FASE 5: GPU Integration - Expansion (Ray batch processing)
- [x] FASE 6: Complete Testing & Benchmarking (bench_phase6.py, 441+ tests)
- [x] FASE 7: Documentation & Deploy (full docs suite, install scripts, CI/CD)
- [ ] FASE 8: Metrics exporter (Prometheus/OTel) for long-running service deployments
- [ ] src-layout packaging migration (eliminates py-modules maintenance class of bugs)
- [ ] Independent reproduction of validated results on public benchmarks

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

> **Commercial availability:** MutaLambda is currently evaluating a dual-license model
> (open-core). Future releases may be distributed under a commercial license for
> business use. See [COMMERCIAL.md](COMMERCIAL.md) for details.

---

*This README was substantially rewritten by OpenHands (AI agent) as part of the production-readiness workflow.*
