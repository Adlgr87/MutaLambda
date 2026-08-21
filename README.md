# MutaLambda 2.0

**MutaLambda** is an evolutionary code optimization system that combines LLMs with genetic algorithms (NSGA-II) to automatically improve code performance while maintaining correctness. It supports Python, Rust, and C++ via a Universal AST (UAST) layer for cross-language mutation.

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
├── `checkpoint_manager.py`   # Msgpack-based evolution state persistence
├── sandbox.py                # Secure candidate evaluation
├── archive.py                # FAISS semantic cache (RAG)
└── muta_ext/uast/            # Universal AST (multi-language)
    ├── adapters/             # Source → UAST parsers (Python, Rust, C++)
    ├── emitters/             # UAST → source code generators
    ├── mutators/             # Structural mutation operators
    └── thc_engine.py         # Horizontal Code Transfer (cross-island sharing)

## Key Features

### Core Pipeline
- **Progressive Pipeline**: 5-phase workflow — Discovery → Test Synthesis → Fast Mode → Deep Evolution → Patch
- **3-Objective Fitness**: Correctness (hard gate) + Latency P50 + Memory Peak (Pareto optimization)
- **HFC (Hierarchical Fitness Climbing)**: 3-tier system — Tier1 lab (100), Tier2 factory (50), Tier3 elite (10)
- **THC (Horizontal Code Transfer)**: Cross-island candidate sharing via `HorizontalTransferEngine` in `muta_ext/thc_engine.py`

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
- **Semantic Caching**: FAISS-based RAG retrieval with hit/miss counters
- **AST Parse Cache**: LRU cache (`maxsize=1024`) on `ast.parse` — up to ~1000× speedup on cache hit
- **Persistent Worker Pool**: Process pool pre-imports heavy modules via `_worker_init()`, avoiding per-task reimport overhead
- **AST-Only Fast-Path**: Skips `build_gate` and `security_gate` for AST mutations that operate purely on structural transforms

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

# Diagnostics for P99, throughput, and parsimony (not active objectives)
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

> **Scope caveat (read before citing these numbers).** The targets above are
> the author's *internal* modules from the MASSIVE framework, not standard
> public benchmarks such as Rosetta, HumanEval-Plus, or MBPP-Exec. They have
> **not** been reproduced on hostile/unseen codebases, and the specific
> before/after diffs are **not published** in this repository — so the 3.6×
> on `utility_logic` cannot be independently audited here (it may reflect a
> trivial loop bottleneck rather than a subtle transformation). "100%
> correctness" means the author's own test targets passed; it is not a claim
> about correctness on an external benchmark suite.

## Performance Benchmarks (Phase 6 — 2026-08-18)

### System-Level Optimizations

| Optimization | Micro-benchmark | Impact (end-to-end) | Notes |
|------------|----------------|---------------------|-------|
| AST Parse Cache | ~650-1057× on cache hit (0.0377 μs/op vs 39.85 μs/op) | Depends on hit-rate | `lru_cache(maxsize=1024)` on `ast.parse`. Gains appear when population re-evaluates repeated code |
| MsgPack Checkpoints | 4.0× serialization speedup | Notable with frequent checkpoints | 480-individual checkpoint: 766.9 KB / 2.983 ms → 5.4 KB / 0.745 ms (99.3% smaller) |
| NSGA-II Vectorized Dominance | 3.7-4.3× with N≥50 | Real for large populations | Replaces O(N²) Python loop with NumPy vectorization |

> **End-to-end (5 gen × 2 islands × 4 pop): ~1.0× — within measurement noise.**  
> On small workloads, LLM latency dominates. These optimizations matter at scale:
> large populations, many generations, frequent checkpointing.
>
> **The headline here is the infrastructure, not a magic end-to-end speedup.**
> The micro-benchmarks above (parse cache, msgpack checkpoints, vectorized
> NSGA-II dominance) show real gains at scale, but the whole-pipeline speedup
> on a small workload is ~1.0×. Any report of a large end-to-end number on a
> toy workload should be treated as noise.

**Cache stats API** (via `EvaluationService.cache_stats()`):
```python
>>> from evaluation_service import EvaluationService
>>> svc = EvaluationService()
>>> svc.cache_stats()
{'size': 50234, 'hits': 14382, 'misses': 56, 'hit_rate': 0.9961}
```

### Test Suite Status
- **603 tests passing** (1 deselected: pre-existing flaky `test_hfc_tiers`)
- All optimizations validated against existing test suite

## Testing

```bash
python -m pytest tests/ -v --deselect tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory
```

## License

MIT License
