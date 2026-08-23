<div align="center">

<img src="assets/MutaLambda_Logo.png" alt="MutaLambda logo" width="220"/>

# MutaLambda

**Evolutionary code optimization: LLMs + genetic algorithms (NSGA-II) that make your Python, Rust and C++ faster without breaking it.**

[![CI](https://github.com/Adlgr87/MutaLambda/actions/workflows/python-package.yml/badge.svg?branch=main)](https://github.com/Adlgr87/MutaLambda/actions/workflows/python-package.yml)
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

### Public benchmarks (`bench/`)

The table above is being replaced by numbers a stranger can re-derive. `bench/` is an
auditable harness that runs MutaLambda against public benchmarks and actively tries to
catch itself cheating — see **[docs/BENCHMARKS.md](docs/BENCHMARKS.md)** for the full
methodology.

| Tier | Suite | Settles |
|---|---|---|
| 1 | `effibench` | ratio to the human canonical solution (EffiBench's 3.12× finding) |
| 1 | `pie` | %Opt and speedup on C++ pairs already compiled at `-O3` |
| 1 | `polybench` | numerical kernels — where vectorisation shows up or does not |
| 2 | `effibench-plus` | optimize the code **without breaking the physics** (invariants) |
| 2 | `rosetta` | does a Python-side optimization survive emission to Rust/C++? |
| 3 | `eoh` | heuristic discovery quality per dollar (bin packing, circle packing) |

```bash
python -m bench.runner list                                    # suites + status
python -m bench.runner run --suite smoke --optimizer baseline  # harness self-test
python -m bench.runner run --suite effibench --optimizer mutalambda:deep \
    --repeats 5 --out results/ --include-diffs
```

What makes a result publishable here:

- **Held-out tests** the optimizer never sees decide whether a speedup counts.
- **Integrity gates** reject hardcoded answer tables, no-op entrypoints, forbidden
  imports and clock tampering; every finding is printed with its reason.
- **A measured noise floor**: the harness times identical code against itself and
  refuses to count wins below that band.
- **Interleaved A/B measurement**, N repeats, mean ± std, plus token and USD cost.
- **Ablations** (`--ablation no_hfc`, `no_thc`, `no_prompt_evolution`, …) so a gain
  can be attributed to a component instead of asserted.

> Current status: the harness and its gates are tested (43 tests, CI-guarded) and the
> download-free suites run today. Dataset-backed suites need a local fetch
> (`scripts/fetch_bench_datasets.py`); no benchmark data is committed. **No public
> benchmark result is claimed yet** — the numbers go here when they exist.

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

Current status: **521 tests passing**, CI green across Python 3.10/3.11/3.12 plus Docker build/test/push. See [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md) for the production-readiness audit.

## Documentation

- [CLI reference](docs/CLI.md)
- [Fitness metrics](docs/FITNESS_METRICS.md)
- [Metrics](docs/METRICS.md)
- [Scientific Optimization Mode](docs/SCIENTIFIC_OPTIMIZATION_MODE.md)
- [Test Execution Protocol](docs/TEST_EXECUTION_PROTOCOL.md)
- [Production checklist](docs/PRODUCTION_CHECKLIST.md)
- [First optimization walkthrough](docs/getting-started/first-optimization.md)
- [README en español](README_ES.md)

## Roadmap

- [ ] src-layout packaging migration (eliminates py-modules maintenance class of bugs)
- [ ] Metrics exporter (Prometheus/OTel) for long-running service deployments
- [ ] Independent reproduction of validated results on public benchmarks

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

> **Commercial availability:** MutaLambda is currently evaluating a dual-license model
> (open-core). Future releases may be distributed under a commercial license for
> business use. See [COMMERCIAL.md](COMMERCIAL.md) for details.

---

*This README was substantially rewritten by OpenHands (AI agent) as part of the production-readiness workflow.*
