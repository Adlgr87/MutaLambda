# MutaLambda 2.0

**MutaLambda** is an evolutionary code optimization system that combines LLMs with genetic algorithms (NSGA-II) to automatically improve code performance while maintaining correctness. It supports Python, Rust, and C++ via a Universal AST (UAST) layer for cross-language mutation.

## Why MutaLambda? (vs. OpenEvolve-style frameworks)

Open-source AlphaEvolve clones optimize for *discovery*. MutaLambda optimizes for **trustworthy production code**. The difference is safety and verification at every step:

| Guarantee | MutaLambda | Typical AlphaEvolve-style framework |
|---|---|---|
| **Correctness as a hard gate** — a faster-but-wrong candidate is discarded, never ranked | ✅ | ❌ scalar reward, correctness is just one score |
| **Sandboxed evaluation** with hard timeout & memory limits per candidate | ✅ | ⚠️ varies, often executes in-process |
| **Security mutation filters** (blocks eval/exec/subprocess/OS-call injection) | ✅ | ❌ |
| **Anti-hallucination algebraic verification** (SymPy) + AST math verifier | ✅ | ❌ |
| **Scientific-domain invariants** (energy conservation, mass balance, monotonicity) | ✅ | ❌ |
| **Sequential workflow gates**: build → security → sandbox → tests → perf → decision | ✅ | ❌ |
| **Multi-objective Pareto fitness** (correctness + latency P50/P99 + memory + parsimony) | ✅ NSGA-II | ⚠️ mostly single-objective |
| **Multi-language structural mutation** (Python, Rust, C++, Go via UAST) | ✅ | ⚠️ mostly Python-only |

If you need to *explore* algorithm space, OpenEvolve is a fine tool. If you need to ship an optimized function to production **with evidence that it is still correct**, that is what MutaLambda is built for.

## Architecture

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
├── checkpoint_manager.py     # JSON-based evolution state persistence
├── sandbox.py                # Secure candidate evaluation
├── archive.py                # FAISS semantic cache (RAG)
└── muta_ext/uast/            # Universal AST (multi-language)
    ├── adapters/             # Source → UAST parsers (Python, Rust, C++)
    ├── emitters/             # UAST → source code generators
    └── mutators/             # Structural mutation operators
```

## Key Features

### Core Pipeline
- **Progressive Pipeline**: 5-phase workflow — Discovery → Test Synthesis → Fast Mode → Deep Evolution → Patch
- **3-Objective Fitness**: Correctness (hard gate) + Latency P50 + Memory Peak (Pareto optimization)
- **HFC (Hierarchical Fitness Climbing)**: 3-tier system — Tier1 lab (100), Tier2 factory (50), Tier3 elite (10)

### Genetic Evolution
- **NSGA-II**: Multi-island evolution with ring/mesh/random topology
- **Component Evolution**: Coupling/cohesion metrics, interface-level crossover and mutation
- **Prompt Evolution**: Meta-evolution of LLM system prompts

### Safety & Correctness
- **Mutation Filters**: Regex-based blocking of eval/exec/subprocess/OS calls
- **Anti-Hallucination**: SymPy-based algebraic verification
- **Scientific Mode**: Domain invariants (energy conservation, mass balance, monotonicity)

### Performance Optimization
- **NumPy Optimizer**: Vectorization, einsum, broadcasting mutations
- **ParallelFor Mutator**: Detects reduction patterns in loops and transforms to map/reduce
- **Semantic Caching**: FAISS-based RAG retrieval of past solutions

### Language Support (via UAST)
| Language | Adapter | Emitter | Status |
|----------|---------|---------|--------|
| Python | ✅ | ✅ | Primary |
| Rust | ✅ | ✅ | Supported |
| C++ | ✅ | ✅ | Supported |

## Installation

```bash
git clone https://github.com/Adlgr87/MutaLambda.git
cd MutaLambda
pip install -r requirements.txt
```

## Usage

```bash
# Basic optimization
python muta_lambda.py --optimize my_script.py

# Force fast mode only
python muta_lambda.py --optimize my_script.py --mode fast

# Deep evolution with NSGA-II
python muta_lambda.py --optimize my_script.py --mode deep

# With HFC enabled
python muta_lambda.py --optimize my_script.py --hfc-enabled

# Resume from checkpoint
python muta_lambda.py --resume checkpoints/run_xxx

# Advanced diagnostics (P99, throughput, parsimony)
python muta_lambda.py --optimize my_script.py --advanced-diagnostics
```

## Configuration

Configuration is managed via `config.yaml` with Pydantic validation:

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
4. **Deep Evolution** — NSGA-II with island-based parallel evolution
5. **Patch & Report** — git-style diff + comparative metrics

## Validation Results

| Target | Improvement | Correctness |
|--------|-------------|-------------|
| utility_logic | **3.6x faster** | 100% |
| energy_engine_pure | **2.3x faster** | 100% |
| social_architect_pure | **1.5x faster** | 100% |
| intervention_optimizer | **25.8% simpler** | 100% |

### Self-Evolution (2026-08-19)

MutaLambda optimized **its own hot path** (`nsga2._crowding_distance`) through its production gates: **1.49x gmean speedup** (up to 1.88x on large fronts), exact semantic equivalence verified by a differential oracle — which also **rejected 25 faster-but-incorrect mutants**. See [SELF_EVOLUTION_REPORT.md](SELF_EVOLUTION_REPORT.md).

## Performance Benchmarks (Phase 6 — 2026-08-18)

### System-Level Optimizations

| Optimization | Micro-benchmark | Impact (end-to-end) | Notes |
|------------|----------------|---------------------|-------|
| AST Parse Cache | ~650-1057× on cache hit (0.0377 μs/op vs 39.85 μs/op) | Depends on hit-rate | `lru_cache(maxsize=1024)` on `ast.parse`. Gains appear when population re-evaluates repeated code |
| MsgPack Checkpoints | 4.0× serialization speedup | Notable with frequent checkpoints | 480-individual checkpoint: 766.9 KB / 2.983 ms → 5.4 KB / 0.745 ms (99.3% smaller) |
| NSGA-II Vectorized Dominance | 3.7-4.3× with N≥50 | Real for large populations | Replaces O(N²) Python loop with NumPy vectorization |

> **End-to-end (5 gen × 2 islands × 4 pop): ~1.0× — within measurement noise.**  
> On small workloads, LLM latency dominates. These optimizations matter at scale: large populations, many generations, frequent checkpointing.

**Cache hit-rate instrumentation:**
```python
>>> from runners import report_cache_stats
>>> report_cache_stats()  # called after each run
{'hits': 14382, 'misses': 56, 'hit_rate': 0.9961, 'time_saved_ms': 1035.5}
```

### Test Suite Status
- **443 tests passing** (CI-generated count; 1 deselected: pre-existing flaky `test_hfc_tiers`)
- All optimizations validated against existing test suite

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific module tests
python -m pytest tests/test_component_evolution.py -v
python -m pytest tests/scientific/ -v
```

## License

MutaLambda is licensed under the **Business Source License 1.1** (BUSL-1.1) — see [LICENSE](LICENSE) for details.

- **Free** for personal, academic, and research use, and for internal evaluation (90 days).
- **Commercial / production use requires a commercial license** — contact the author via [GitHub](https://github.com/Adlgr87/MutaLambda).
- Each version automatically converts to **Apache 2.0** on its Change Date (2030-08-19).

> Note: versions published before the license change remain under their original MIT terms.
