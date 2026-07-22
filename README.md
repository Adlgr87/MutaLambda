# MutaLambda: Evolutionary Code Optimization System

<div align="center">

**Validated Performance Improvements through Evolutionary Optimization**

[![Performance](https://img.shields.io/badge/Performance-50--263%25%20speedup-blue)]()
[![Modules](https://img.shields.io/badge/Modules-5%20optimized-orange)]()
[![Correctness](https://img.shields.io/badge/Correctness-149%2F149%20tests-green)]()
[![CLI](https://img.shields.io/badge/CLI-v3.1.0-orange)]()
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success)]()

**English** | **[Español](README_ES.md)**

</div>

---

## 🎯 Overview

MutaLambda is an evolutionary code optimization system that uses Large Language Models (LLMs) to automatically improve performance-critical components of scientific software. The system employs genetic algorithms with AST-based mutations to evolve Python functions for better performance while maintaining correctness.

### Key Achievements

✅ **MASSIVE Framework integration** — 50-263% speedups across 4 scientific modules, 100% correctness
✅ **`_get_fitness()` optimization** — +10.2% speedup validated with 149/149 tests passing
✅ **Interactive CLI** — Full-featured command-line interface with retro animations
✅ **Checkpoint system** — Save and resume evolution runs seamlessly

---

## 📊 Validated Optimizations

### MASSIVE Framework — 50-263% speedups

MutaLambda was successfully applied to the **MASSIVE** cosmological simulation framework, achieving significant performance improvements while maintaining 100% scientific correctness.

| Module | Speedup | Impact |
|--------|---------|--------|
| **utility_logic** | **3.6x faster** | Social pressure calculations |
| **energy_engine_pure** | **2.3x faster** | Thermodynamic energy engine |
| **social_architect_pure** | **1.5x faster** | Polarization analysis |
| **intervention_optimizer** | **25.8% simpler** | Strategy optimization (code reduction) |

**Real-world impact:**
- **35% faster** simulation runtime (10K+ agents)
- **60% faster** large-scale experiments (50K agents)
- **50% faster** real-time analytics

**Statistical rigor:**
- Confidence level: 95%
- P-value: < 0.001 for all improvements
- Effect size: Large (Cohen's d > 0.8)
- Iterations: 1,000 runs per module

**Validation methodology:**
- Numerical equivalence: ε < 1e-10
- Unit tests: 100% pass rate
- Integration testing: Identical simulation results
- Peer review: Domain expert approval

### `_get_fitness()` — +10.2% speedup

**Problem:** The `_get_fitness()` helper function is called O(N²) times during NSGA-II selection. It extracts a `FitnessVector` from an `Individual`, checking if the `.fitness` attribute exists.

**Solution:** Replace `hasattr()` check with `getattr()` using default `None`. This avoids double attribute lookup overhead.

```python
# Before
def _get_fitness(ind: Individual) -> FitnessVector:
    if hasattr(ind, 'fitness') and ind.fitness is not None:
        return ind.fitness
    return FitnessVector(
        correctness=max(0.0, min(1.0, ind.score / 100.0)),
        parsimony=0.5,
    )

# After
def _get_fitness(ind: Individual) -> FitnessVector:
    fitness = getattr(ind, 'fitness', None)
    if fitness is not None:
        return fitness
    return FitnessVector(
        correctness=max(0.0, min(1.0, ind.score / 100.0)),
        parsimony=0.5,
    )
```

**Impact:** ~17 seconds saved per typical evolution run (50 generations, 4 islands, 32 individuals).

**Validation:** 13/13 nsga2 tests, 14/14 fitness_vector tests, 149/149 total tests ✅

---

## 🏗️ Architecture

```
cli.py                       CLI entry point (Click)
└── cli/                     CLI package
    ├── main.py              Main logic: MutaLambdaCLI, InteractiveREPL
    ├── animator.py          Retro animations (ASCII art, progress bars)
    ├── config_manager.py    Configuration management (templates: basic/advanced/research)
    └── checkpoint_manager.py  Checkpoint management (pickle + gzip)

muta_lambda.py               Slim orchestrator — wires all modules together
├── models.py                Data: Individual, FitnessVector, LineageGraph, PromptGenome
├── evolution_engine.py      AST mutations + LLM-guided code generation (ASTMutator, CoreEvolutionEngine)
├── island.py                Island evolution unit (per-island population + protocol workflow)
├── island_evolution.py      Parallel coordinator: IslandPool (thread/process), IslandDiversity
├── migration.py             Inter-island migration bus (ring, fully_connected, mesh topologies)
├── sandbox.py               Hard-limited subprocess evaluation (timeout, memory)
├── archive.py               SolutionArchive (FAISS-backed semantic dedup, optional)
├── nsga2.py                 NSGA-II multi-objective selection (Pareto fronts + crowding distance)
├── fitness_vector.py        6-objective vector: correctness, latency_p50, latency_p99, throughput,
│                                memory_peak_mb, parsimony
├── hfc_tiers.py             HFC tiered speciation: Laboratory → Factory (bacterial clones) → Elite
├── workflow_protocol.py     Protocol-driven gates: build → security → sandbox → tests → perf → decision
├── interpretability.py      3-layer interpretability safeguards for self-evolved code
├── llm_backend.py           LLM adapters: ollama, openai, anthropic, openrouter, mistral
├── prompt_evolver.py        Basic PromptGenome evolution
├── prompt_evolution.py      RichPromptEvolver — 15 mutation operators + crossover + archive-aware
├── config_loader.py         Declarative YAML config loader with validation
├── checkpoint_manager.py    Checkpoint save/resume (pickle + gzip)
└── property_testing.py      Property-based test harness

muta_ext/                    Extensions & advanced subsystems
├── advanced_selection.py    UCB, Thompson Sampling, ε-greedy multi-armed bandit selection
├── dialectic_engine.py      Thesis → Critique → Synthesis pre-sandbox LLM filter
├── pattern_memory.py        Reusable AST pattern memory
├── spatial_topology.py      2D grid (Moore/Von Neumann) structured migration
├── thc_engine.py            Horizontal Code Transfer (fragment extraction + injection)
├── config/
│   └── scientific_extension.py  Scientific extension config
├── diagnostics/
│   ├── evolution_report.py  Shannon entropy, Lyapunov exponent, spectral stability report
│   └── tipping.py           Phase-transition / tipping-point detection
├── evaluation/
│   ├── cache.py             AST-canonical evaluation cache (avoids re-running sandbox)
│   └── numerical_health.py  Numerical stability health checks
├── lineage/
│   └── compression.py       Lineage DAG compression for long runs
└── mutation/
    └── stepper_protocol.py  Composable mutation stepper protocol (Strategy pattern)

tests/
├── benchmarks/              Performance benchmark suite
└── test_*.py                Unit tests (149 total)
```

### Protocol-driven evolution workflow

Every generated candidate moves through one mandatory pipeline before it is
allowed to progress:

```text
select elite parent(s)
  -> generate candidate (AST mutation or LLM prompt)
  -> build gate (parse + compile)
  -> security gate (blocks eval/exec/compile/os.system/subprocess.*)
  -> sandbox evaluation (hard-limited subprocess, timeout + memory)
  -> tests/correctness gate (configurable threshold, default 100%)
  -> performance gate
  -> decision gate (promote / retry / reject)
```

Operational notes:
- each run has a `run_id`; recent per-stage traces exposed in `agent.get_metrics()["protocol"]`
- retryable failures automatically fall back to a safer AST retry
- security gate blocks `eval`, `exec`, `compile`, `__import__`, `os.system`, and `subprocess.*`
- workflow configurable via `config.yaml` under the `workflow:` key

---

## ⚙️ Advanced Features

### HFC — Hierarchical Fair Competition (`hfc_tiers.py`)

Three-tier speciation prevents premature convergence by separating populations by fitness level:

| Tier | Name | Role |
|------|------|------|
| 1 | **Laboratory** | Chaotic exploration — LLM crossover + full AST mutation |
| 2 | **Factory** | Bacterial reproduction (1 → λ clones) with micro-mutators |
| 3 | **Elite** | Static Pareto frontier — validated, promotion-only |

Top-down distillation extracts elite concepts and injects them back into the Laboratory (configurable interval). Promotion from Laboratory → Factory requires 100% correctness by default.

### Convergent Evolution Boost

When multiple islands converge on similar code (cosine similarity ≥ threshold), the system amplifies the score multiplicatively (`score *= 1 + factor × similarity`). Encourages consensus solutions.

### Resurrection — Time-Travel Backtracking

After N stalled generations, the engine revives the best abandoned branch from the lineage DAG and re-enters it into the population. Up to 3 resurrection attempts per run (configurable).

### Cross-Branch Crossover

Individuals separated by ≥ 3 genealogical hops can be crossed over, injecting diversity when the population converges. Probability: 5% per offspring.

### THC — Horizontal Code Transfer (`muta_ext/thc_engine.py`)

Extracts successful AST fragments from high-scoring individuals and injects them into unrelated individuals, analogous to horizontal gene transfer in bacteria.

### Dialectic Engine (`muta_ext/dialectic_engine.py`)

Before sandbox evaluation, candidate code goes through:
1. **Thesis** — proposed mutation
2. **Critique** — LLM identifies correctness / safety issues
3. **Synthesis** — LLM rewrites taking critique into account

Saves sandbox calls by rejecting syntactically invalid candidates early.

### Advanced Selection (`muta_ext/advanced_selection.py`)

Multi-armed bandit strategies for island operator selection:
- **UCB** (Upper Confidence Bound)
- **Thompson Sampling**
- **ε-greedy**

Combines fitness + novelty + entropy + discovery scores.

### Spatial Topology (`muta_ext/spatial_topology.py`)

Arranges islands on a 2D grid. Migration only between geographic neighbors (Moore or Von Neumann neighborhoods), creating spatial diversity gradients.

### Pattern Memory (`muta_ext/pattern_memory.py`)

Stores reusable AST patterns from successful individuals so future mutations can replay proven transformations rather than re-discovering them.

### Evaluation Cache (`muta_ext/evaluation/cache.py`)

Caches fitness results keyed by canonical AST hash (variable-name and whitespace independent). If a mutation produces structurally identical code to a previously evaluated individual, the cached `FitnessVector` is returned without running the sandbox.

---

## 🤖 LLM Backends

MutaLambda supports multiple LLM providers, configured via `llm.backend` in `config.yaml` or the `MUTALAMBDA_*` environment variables:

| Backend | Key | Notes |
|---------|-----|-------|
| **Ollama** | `ollama` | Default — local model server |
| **OpenAI** | `openai` | Requires `OPENAI_API_KEY` |
| **Anthropic** | `anthropic` | Requires `ANTHROPIC_API_KEY` |
| **OpenRouter** | `openrouter` | Requires `OPENROUTER_API_KEY` |
| **Mistral** | `mistral` | Requires `MISTRAL_API_KEY` |

Environment overrides: `MUTALAMBDA_OLLAMA_URL`, `MUTALAMBDA_OPENAI_URL`, `MUTALAMBDA_LLM_TIMEOUT_SEC`, `MUTALAMBDA_LLM_TEMPERATURE`.

### Natural-language mutator generation (OpenAI)

CoreUAST mutator generation is additive and disabled by default:

```yaml
llm:
  enabled: false
  provider: openai
  mutator_model: gpt-4o-mini
  mutator_temperature: 0.1
  mutator_max_tokens: 1400
  mutator_timeout_sec: 60.0
```

Enable it explicitly and run:

```bash
python cli.py generate-mutator "rename total_price to amount in assignment nodes" --lang python --name rename_total_price
python cli.py generate-mutator "rename total_price to amount in assignment nodes" --lang python --dry-run
```

If `llm.enabled` is `false`, current mutation/evolution flows remain unchanged and the command exits with an enablement message.

---

## 📚 Lessons Learned

### 1. Measure Before and After

Never assume an optimization helps — benchmark it. We attempted several optimizations that actually **degraded** performance:

- `dominates()` loop unrolling: **-15.6%** performance (reverted)
- `weighted_sum()` fast path: **-13.4%** performance (reverted)
- Fitness-directed migration: **57.6%** success rate vs ring topology's **92.2%** (reverted)

### 2. Simplicity Beats Complexity

Ring topology (92.2% success) outperformed our gradient-based migration system (57.6%). The simpler algorithm was more effective because:

- Predictable genetic flow
- No overhead from complex selection logic
- Better diversity preservation

### 3. Python Built-ins Are Fast

`zip()`, `all()`, `any()` are implemented in C and often faster than manual alternatives. Our attempts to "optimize" `dominates()` with explicit variable assignments actually added overhead.

### 4. Validation Is Non-Negotiable

Performance measurement without correctness validation produces false positives. We saw AST mutations produce **+97% and +100% speedups** that were actually semantic bugs:

- Off-by-one errors that made functions return early
- Missing individuals in population fronts
- Incorrect dominance relationships

### 5. Small Improvements Compound

A 10.2% speedup in a hot path saves 17 seconds per evolution run. Over 100 runs, that's **28 minutes saved**. Small, validated improvements are worth pursuing.

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/Adlgr87/MutaLambda
cd MutaLambda
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run Tests

```bash
python -m pytest tests/ -v
```

All 149 tests should pass.

### Run CLI

```bash
# View general help
python cli.py --help

# Run evolution with configuration
python cli.py run --config config.yaml --generations 50

# Create configuration from template
python cli.py config create --output config.yaml --template basic

# Resume from checkpoint
python cli.py resume --checkpoint checkpoints/gen_50.json --additional-gens 30

# Interactive mode
python cli.py interactive
```

---

## 🖥️ Command-Line Interface (CLI)

MutaLambda includes a complete CLI with retro animations, configuration management, and checkpoints.

### Available Commands

| Command | Description |
|---------|-------------|
| `run` | Execute complete evolutionary run |
| `resume` | Resume evolution from checkpoint |
| `config create` | Create configuration from template |
| `config validate` | Validate configuration file |
| `config show` | Display configuration summary |
| `stats` | Show statistics from previous runs |
| `evaluate` | Evaluate and summarize results |
| `mutate` | Mutation operations (prompts, operators, hyperparameters) |
| `generate-mutator` | Generate a CoreUAST mutator from natural language |
| `interactive` | Interactive REPL mode |
| `checkpoints` | Manage checkpoints |

### Usage Examples

**Run evolution with retro animations:**
```bash
python cli.py run --config config.yaml --generations 100 --animation retro
```

**Create advanced configuration:**
```bash
python cli.py config create --output advanced.yaml --template advanced
```

**Resume from checkpoint:**
```bash
python cli.py resume --checkpoint checkpoints/checkpoint_0050.json --additional-gens 50
```

**Interactive mode:**
```bash
python cli.py interactive
```

### Configuration Templates

The CLI includes three predefined templates:

- **basic** — Minimal configuration for quick tests (50 generations, 4 islands)
- **advanced** — Production configuration (100 generations, 8 islands, fully_connected)
- **research** — Experimental configuration (200 generations, 12 islands, complete tracking)

### Checkpoint Management

Checkpoints are saved automatically every N generations (configurable):

```bash
# List available checkpoints
python cli.py checkpoints --list

# Clean old checkpoints
python cli.py checkpoints --clean --max-age 7

# Resume from specific checkpoint
python cli.py resume --checkpoint checkpoints/checkpoint_0050.json --additional-gens 30
```

**Complete documentation:** [docs/CLI.md](docs/CLI.md)

---

## 🔬 Methodology

### Optimization Process

1. **Identify hot paths** — Profile code to find functions called frequently
2. **Benchmark baseline** — Measure current performance with statistical rigor
3. **Apply mutations** — Use AST transformations (loop unrolling, variable inlining, etc.)
4. **Validate correctness** — Ensure outputs are identical (ε < 1e-10)
5. **Measure improvement** — Only integrate if speedup is real and validated

### Validation Requirements

- ✅ Numerical equivalence: ε < 1e-10
- ✅ Unit tests: 100% pass rate
- ✅ Integration testing: Identical results
- ✅ Performance improvement: Statistically significant (p < 0.05)

---

## 📖 Documentation

### User Documentation

- **[docs/CLI.md](docs/CLI.md)** — Complete CLI guide: commands, configuration, checkpoints, interactive mode
- **[docs/METRICS.md](docs/METRICS.md)** — Performance metrics, validated benchmarks, and efficiency analysis

### Core Documentation

- **[EMPIRICAL_EVIDENCE.md](EMPIRICAL_EVIDENCE.md)** — Comprehensive report of validated optimizations and failed experiments
- **[PLANS/AUTO_IMPROVEMENT_PLAN.md](PLANS/AUTO_IMPROVEMENT_PLAN.md)** — 6-phase self-improvement plan

### Code Documentation

- **`nsga2.py`** — NSGA-II multi-objective selection with optimized `_get_fitness()`
- **`fitness_vector.py`** — 6-objective fitness: correctness, latency_p50, latency_p99, throughput, memory_peak_mb, parsimony
- **`interpretability.py`** — 3-layer safeguards against "alien code" from recursive self-improvement
- **`workflow_protocol.py`** — Protocol gates, `ProtocolWorkflow`, `ProtocolTrace`, security scanner
- **`hfc_tiers.py`** — HFC three-tier speciation (Laboratory / Factory / Elite)
- **`island_evolution.py`** — Parallel `IslandPool` coordinator with diversity metrics
- **`cli/main.py`** — Main CLI logic with evolutionary core integration

---

## 🎓 Key Insights

### What Works

✅ **Small, targeted optimizations** in hot paths
✅ **`getattr()` instead of `hasattr()`** for attribute access
✅ **Simple algorithms** (ring topology) over complex ones (gradient migration)
✅ **Rigorous validation** before integration
✅ **Honest benchmarking** with before/after measurements

### What Doesn't Work

❌ **Aggressive AST mutations** without semantic validation
❌ **Complex "intelligent" systems** that outperform simple alternatives
❌ **Loop unrolling** in Python (C-level optimizations don't apply)
❌ **Premature optimization** without measurement
❌ **Automatic deployment** of evolved code without human review

---

## 🤝 Contributing

### Adding Optimizations

1. Identify a hot path with profiling
2. Benchmark baseline performance
3. Apply optimization
4. Validate correctness (all tests must pass)
5. Measure improvement (must be statistically significant)
6. Update EMPIRICAL_EVIDENCE.md with results
7. Submit pull request with benchmarks

### Reporting Issues

If you find a performance regression or correctness issue:

1. Run `python -m pytest tests/ -v` to confirm
2. Check EMPIRICAL_EVIDENCE.md for known limitations
3. Open issue with reproduction steps

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **NSGA-II algorithm** — Deb et al., 2002
- **Python AST module** — Standard library
- **Pytest framework** — Testing infrastructure
- **Docker** — Secure sandbox execution
- **Click framework** — CLI infrastructure
- **Rich library** — Terminal UI components

---

## 📊 Project Status

**Version:** 3.1.0 (CLI)
**Last Updated:** 2026-07-12
**Maintainer:** MutaLambda Development Team

### Current Capabilities

✅ **Multi-objective evolution** with NSGA-II selection (6 objectives: correctness, latency_p50, latency_p99, throughput, memory_peak_mb, parsimony)
✅ **Secure sandbox execution** with hard-limited subprocess isolation
✅ **Interactive CLI** with retro animations and checkpoint management
✅ **Validated optimizations** with comprehensive test coverage (149/149 tests)
✅ **Interpretability safeguards** for future self-evolution work
✅ **Checkpoint system** for resuming long evolution runs
✅ **Configuration templates** for different use cases (basic/advanced/research)
✅ **Protocol-driven workflow** with sequential gates (build → security → sandbox → tests → perf)
✅ **HFC tiers** — Laboratory / Factory / Elite speciation (opt-in)
✅ **Convergent Evolution Boost** — score amplification for converging islands
✅ **Resurrection** — time-travel backtracking to revive abandoned lineage branches
✅ **Cross-branch crossover** — diversity injection from genealogically distant individuals
✅ **Multiple LLM backends** — ollama, openai, anthropic, openrouter, mistral
✅ **Dialectic Engine** — thesis/critique/synthesis pre-sandbox filter (opt-in)
✅ **Horizontal Code Transfer (THC)** — fragment extraction and injection (opt-in)
✅ **Evaluation cache** — canonical AST hash cache to skip redundant sandbox calls

### Validated Performance Improvements

| Component | Optimization | Speedup | Status |
|-----------|-------------|---------|--------|
| **MASSIVE Framework** | 4 modules optimized | **50-263%** | ✅ Production |
| `_get_fitness()` | `getattr()` instead of `hasattr()` | **+10.2%** | ✅ Production |
| Ring topology | Simple migration pattern | **92.2% success** | ✅ Production |
| NSGA-II selection | Optimized hot paths | **Validated** | ✅ Production |
### Failed Experiments (Reverted)

❌ Fitness-directed migration (57.6% success vs 92.2% ring)
❌ `dominates()` loop unrolling (-15.6% performance)
❌ `weighted_sum()` fast path (-13.4% performance)
❌ Aggressive AST mutations (semantic bugs)

### Roadmap

- [ ] Integration testing with real-world Python functions
- [ ] Extended benchmark suite for diverse workloads
- [ ] Web dashboard for monitoring evolution runs
- [ ] Distributed evolution across multiple machines

---

## 📈 Metrics Summary

**Total optimizations attempted:** 11
**Validated improvements:** 5 (MASSIVE: 4 modules, Core: 1 function)
**Failed experiments:** 4 (reverted)
**Tests passing:** 149/149 (100%)

**Impact on production runs:**
- MASSIVE: **35-60% faster** simulation runtime
- Core: Saves ~17 seconds per evolution run (50 generations, 4 islands, 32 individuals)
- Over 100 runs: **28 minutes saved**
- Compounds across all future evolution experiments

**Detailed metrics:** [docs/METRICS.md](docs/METRICS.md)

---

<div align="center">

**Built with evolutionary algorithms, validated with empirical evidence.**

[Report Bug](https://github.com/Adlgr87/MutaLambda/issues) · [Request Feature](https://github.com/Adlgr87/MutaLambda/issues)

</div>
