# MutaLambda 2.0: Evolutionary Code Optimization System

<div align="center">

**AI-Powered Code Optimization with Progressive Pipeline**

[![Performance](https://img.shields.io/badge/Performance-50--263%25%20speedup-blue)]()
[![Tests](https://img.shields.io/badge/Correctness-189%2B%20tests-green)]()
[![Version](https://img.shields.io/badge/Version-2.0.0-orange)]()
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success)]()

**English** | **[Español](README_ES.md)**

</div>

---

## 🎯 What is MutaLambda?

MutaLambda is an **evolutionary code optimization system** that combines LLMs with genetic algorithms to automatically improve Python code performance while maintaining correctness.

### Key Features (v2.0)

- **Progressive Pipeline**: Discovery → Test Synthesis → Fast Mode → Deep Evolution → Patch
- **3-Objective Fitness**: Correctness, Latency P50, Memory Peak (simplified from 6)
- **NumPy Optimizer**: Targeted mutations for vectorization, einsum, broadcasting
- **Anti-Hallucination**: SymPy-based algebraic verification before sandbox
- **Semantic Caching**: RAG-powered pattern retrieval from FAISS archive
- **Complexity Gate**: Auto-detects trivial functions, skips unnecessary evolution
- **Advanced Diagnostics**: P99, throughput, parsimony (opt-in via `--advanced-diagnostics`)

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/Adlgr87/MutaLambda.git
cd MutaLambda
pip install -r requirements.txt
```

### Basic Usage

```bash
# Run progressive optimization on a script
python muta_lambda.py --optimize my_script.py

# Force fast mode only (no deep evolution)
python muta_lambda.py --optimize my_script.py --mode fast

# Deep evolution with NSGA-II fallback
python muta_lambda.py --optimize my_script.py --mode deep

# Enable advanced diagnostics
python mutaLambda.py --optimize my_script.py --advanced-diagnostics
```

### Example

```python
# target.py
def compute_sum(n):
    total = 0
    for i in range(n):
        total += i
    return total
```

```bash
$ python muta_lambda.py --optimize target.py

🧬 MutaLambda 2.0 — Progressive Optimization Pipeline
   Target: target.py
   Mode: auto

============================================================
MUTALAMBDA 2.0 — OPTIMIZATION REPORT
============================================================
Success: True
Phase reached: fast_mode
Duration: 2.34s

Fitness:
  Correctness: 100.0%
  Latency P50: 0.05ms (from 12.30ms)
  Memory Peak: 24.1MB

Hotspots found: 1
  • compute_sum [CRITICAL]
============================================================
```

---

## 🔄 Progressive Pipeline (v2.0)

```
[INPUT: script.py + --optimize]
   │
   ▼
[FASE 0: Discovery & Hotspots]
   ├─> cProfile/sys.monitoring profiling
   ├─> Extract Top 3 functions (>80% cost)
   └─> Semantic translation report
   │
   ▼
[FASE 1: Test Synthesis]
   ├─> Scan for existing tests (pytest/unittest)
   ├─> Auto-generate Hypothesis strategies from type hints
   └─> Validate baseline correctness
   │
   ▼
[FASE 2: Fast Mode (default)]
   ├─> LLM generates 5 optimized variants
   ├─> Parallel sandbox evaluation
   └─> Success? → Skip to FASE 4
   │
   ▼
[FASE 3: Deep Evolution (--deep)]
   ├─> NSGA-II with 3 objectives
   ├─> Island-based parallel evolution
   └─> Budget-based termination
   │
   ▼
[FASE 4: Patch & Report]
   ├─> Git-style diff generation
   ├─> Apply patch to source
   └─> Comparative metrics table
```

---

## 📊 Fitness Objectives (Simplified)

MutaLambda 2.0 uses **3 core objectives** for stronger selective pressure:

| Objective | Direction | Description |
|-----------|-----------|-------------|
| **Correctness** | ↑ Higher better | Fraction of tests passed (hard gate) |
| **Latency P50** | ↓ Lower better | Median execution time (ms) |
| **Memory Peak** | ↓ Lower better | Peak memory usage (MB) |

Advanced metrics (P99, throughput, parsimony) available via `--advanced-diagnostics`.

---

## 🛠️ Architecture

```
muta_lambda.py          # Main orchestrator + CLI
├── progressive_pipeline.py   # v2.0 workflow
├── fitness_vector.py         # 3-objective fitness
├── hotspot_profiler.py       # Discovery phase
├── test_synthesizer.py       # Auto test generation
├── numpy_optimizer.py        # NumPy-specific mutations
├── ast_math_verifier.py      # Anti-hallucination
├── diagnostics.py            # Advanced metrics
├── evolution_engine.py       # AST mutations
├── island_evolution.py       # NSGA-II islands
├── archive.py                # FAISS semantic cache
├── sandbox.py                # Secure evaluation
└── workflow_protocol.py      # Complexity gates
```

---

## 📈 Validated Results

| Module | Speedup | Correctness |
|--------|---------|-------------|
| utility_logic | **3.6x faster** | 100% |
| energy_engine_pure | **2.3x faster** | 100% |
| social_architect_pure | **1.5x faster** | 100% |
| intervention_optimizer | **25.8% simpler** | 100% |

---

## 🔧 Configuration

```bash
# Use custom config
python muta_lambda.py --config my_config.yaml

# Resume from checkpoint
python muta_lambda.py --resume checkpoints/run_xxx

# Enable HFC (Hierarchical Fitness Climbing)
python muta_lambda.py --hfc-enabled
```

---

## 📚 Documentation

- [Fitness Metrics](docs/FITNESS_METRICS.md) — 3-objective fitness reference
- [CLI Guide](docs/CLI.md) — Command-line interface
- [Test Protocol](docs/TEST_EXECUTION_PROTOCOL.md) — Testing guide
- [Scientific Mode](docs/SCIENTIFIC_OPTIMIZATION_MODE.md) — Scientific computing

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📄 License

MIT License — see LICENSE file for details.

---

<div align="center">

**MutaLambda 2.0** — Evolving code, intelligently.

⭐ Star us on GitHub!

</div>
