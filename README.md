# MutaLambda: Evolutionary Code Optimization System

<div align="center">

**Validated Performance Improvements through Evolutionary Optimization**

[![Performance](https://img.shields.io/badge/Performance-+10.2%25%20speedup-blue)]()
[![Correctness](https://img.shields.io/badge/Correctness-147%2F147%20tests-green)]()
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success)]()

</div>

---

## 🎯 Overview

MutaLambda is an evolutionary code optimization system that uses Large Language Models (LLMs) to automatically improve performance-critical components of scientific software. The system employs genetic algorithms with AST-based mutations to evolve Python functions for better performance while maintaining correctness.

### Key Achievement

✅ **`_get_fitness()` optimization** — +10.2% speedup validated with 147/147 tests passing

---

## 📊 Validated Optimization

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
muta_lambda.py         Núcleo: Multi-Objective Evolution (v3.1)
├── models.py          Datos: Individual, FitnessVector, EvoStats
├── island.py          Evolución: mutaciones AST + selección NSGA-II
├── sandbox.py         Evaluación segura (Docker)
├── nsga2.py           Selección multi-objetivo (Pareto + Crowding)
├── fitness_vector.py  Vector 6D: correctness, latency, memory, parsimony
├── interpretability.py Salvaguardas de interpretabilidad (3 capas)
├── meta_evolution.py  Auto-ajuste de hiperparámetros
└── mutation_operators.py  Operadores genéticos (crossover, mutación)

evolution_engine.py    Motor principal de evolución
├── pattern_memory.py  Memoria de patrones AST
├── tipping_points.py  Detección de transiciones de fase
└── thc_engine.py      Transferencia Horizontal de Código

muta_ext/              Extensiones científicas
├── migration.py       Bus de migración entre islas
├── lineage_graph.py   Genealogía completa (DAG)
├── convergence.py     Monitoreo multi-escala
├── early_stop_monitor.py  Criterios de parada
├── hfc.py             Competencia jerárquica (HFC)
├── spatial_topology.py  Topología espacial (grid)
├── advanced_selection.py  UCB, Thompson Sampling, ε-greedy
├── prompt_evolver.py  Evolución de prompts
└── benchmarking/      Sistema de benchmarking robusto
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

### Core Documentation

- **[EMPIRICAL_EVIDENCE.md](EMPIRICAL_EVIDENCE.md)** — Comprehensive report of optimization attempts, including validated improvements and honest assessment of failed experiments
- **[PLANS/AUTO_IMPROVEMENT_PLAN.md](PLANS/AUTO_IMPROVEMENT_PLAN.md)** — Original 6-phase self-improvement plan

### Code Documentation

- **`nsga2.py`** — NSGA-II multi-objective selection with optimized `_get_fitness()`
- **`fitness_vector.py`** — 6-dimensional fitness vector for Pareto optimization
- **`interpretability.py`** — 3-layer safeguards against "alien code" from recursive self-improvement

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

---

## 📊 Project Status

**Version:** 3.1 (Hot-Path Optimization)  
**Date:** 2026-06-29  
**Status:** Production Ready  
**Tests:** 147/147 passing ✅  
**Validated Optimization:** `_get_fitness()` +10.2% speedup

---

<div align="center">

**Built with evolutionary algorithms, validated with empirical evidence.**

[Report Bug](https://github.com/Adlgr87/MutaLambda/issues) · [Request Feature](https://github.com/Adlgr87/MutaLambda/issues)

</div>
