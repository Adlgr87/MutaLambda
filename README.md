# MutaLambda: Evolutionary Code Optimization System

<div align="center">

**Validated Performance Improvements through Evolutionary Optimization**

[![Performance](https://img.shields.io/badge/Performance-50--263%25%20speedup-blue)]()
[![Modules](https://img.shields.io/badge/Modules-5%20optimized-orange)]()
[![Correctness](https://img.shields.io/badge/Correctness-147%2F147%20tests-green)]()
[![CLI](https://img.shields.io/badge/CLI-v3.1.0-orange)]()
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success)]()

**English** | **[Español](README_ES.md)**

</div>

---

## 🎯 Overview

MutaLambda is an evolutionary code optimization system that uses Large Language Models (LLMs) to automatically improve performance-critical components of scientific software. The system employs genetic algorithms with AST-based mutations to evolve Python functions for better performance while maintaining correctness.

### Key Achievements

✅ **MASSIVE Framework integration** — 50-263% speedups across 4 scientific modules, 100% correctness
✅ **`_get_fitness()` optimization** — +10.2% speedup validated with 147/147 tests passing
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

**Validation:** 13/13 nsga2 tests, 14/14 fitness_vector tests, 147/147 total tests ✅

---

## 🏗️ Architecture

```
cli.py                   CLI entry point (Click)
├── cli/                 CLI package
│   ├── main.py          Main logic: MutaLambdaCLI, InteractiveREPL
│   ├── animator.py      Retro animations (ASCII art, progress bars)
│   ├── config_manager.py  Configuration management (templates: basic/advanced/research)
│   └── checkpoint_manager.py  Checkpoint management (pickle + gzip)

muta_lambda.py           Core: Multi-Objective Evolution (v3.1)
├── models.py            Data: Individual, FitnessVector, EvoStats
├── island.py            Evolution: AST mutations + NSGA-II selection
├── sandbox.py           Secure evaluation (Docker)
├── nsga2.py             Multi-objective selection (Pareto + Crowding)
├── fitness_vector.py    6D vector: correctness, latency, memory, parsimony
├── interpretability.py  Interpretability safeguards (3 layers)
├── meta_evolution.py    Hyperparameter auto-tuning
└── mutation_operators.py  Genetic operators (crossover, mutation)

evolution_engine.py      Main evolution engine
├── pattern_memory.py    AST pattern memory
├── tipping_points.py    Phase transition detection
└── thc_engine.py        Horizontal Code Transfer

muta_ext/                Scientific extensions
├── migration.py         Inter-island migration bus
├── lineage_graph.py     Complete genealogy (DAG)
├── convergence.py       Multi-scale monitoring
├── early_stop_monitor.py  Stopping criteria
├── hfc.py               Hierarchical Fair Competition (HFC)
├── spatial_topology.py  Spatial topology (grid)
├── advanced_selection.py  UCB, Thompson Sampling, ε-greedy
├── prompt_evolver.py    Prompt evolution
└── benchmarking/        Robust benchmarking system
```

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

All 147 tests should pass.

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
- **`fitness_vector.py`** — 6-dimensional fitness vector for Pareto optimization
- **`interpretability.py`** — 3-layer safeguards against "alien code" from recursive self-improvement
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
**Last Updated:** 2026-06-29
**Maintainer:** MutaLambda Development Team

### Current Capabilities

✅ **Multi-objective evolution** with NSGA-II selection
✅ **Secure sandbox execution** with Docker isolation
✅ **Interactive CLI** with retro animations and checkpoint management
✅ **Validated optimizations** with comprehensive test coverage (147/147 tests)
✅ **Interpretability safeguards** for future self-evolution work
✅ **Checkpoint system** for resuming long evolution runs
✅ **Configuration templates** for different use cases (basic/advanced/research)

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
**Tests passing:** 147/147 (100%)

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
