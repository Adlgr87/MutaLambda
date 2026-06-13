# 🧬 MutaLambda — Evolutionary Code Synthesis Platform

[![CI](https://github.com/Adlgr87/MutaLambda/actions/workflows/python-package.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**MutaLambda** is a research-grade evolutionary computation platform that emulates Google DeepMind's **AlphaEvolve** paradigm: evolving code through multi-island genetic algorithms, LLM-powered prompt meta-evolution, FAISS-based long-term memory, and NSGA-II multi-objective optimization.

> *"Code that writes itself — guided by evolution, validated by sandbox, curated by Pareto."*

---

## 🧠 How MutaLambda Works

```
                    ┌──────────────────────────────────────────┐
                    │         CONFIG (YAML / CLI)              │
                    └──────────────┬───────────────────────────┘
                                   │
     ┌─────────────────────────────▼──────────────────────────────┐
     │                 MutaLambdaAgent (Orchestrator)              │
     │                                                            │
     │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
     │  │ Island 0 │  │ Island 1 │  │ Island 2 │  │ Island 3 │  │
     │  │ ┌──────┐ │  │ ┌──────┐ │  │ ┌──────┐ │  │ ┌──────┐ │  │
     │  │ │ Pop  │ │  │ │ Pop  │ │  │ │ Pop  │ │  │ │ Pop  │ │  │
     │  │ └──┬───┘ │  │ └──┬───┘ │  │ └──┬───┘ │  │ └──┬───┘ │  │
     │  └────┼─────┘  └────┼─────┘  └────┼─────┘  └────┼─────┘  │
     │       │   MigrationBus (ring/mesh/random)   │            │
     │       └──────────────┬──────────────────────┘            │
     │                      ▼                                   │
     │            ┌──────────────────┐                          │
     │            │ IslandPool       │  ← Thread-parallel       │
     │            │  evaluate_batch  │                          │
     │            └────────┬─────────┘                          │
     │                     ▼                                    │
     │   ┌─────────────────────────────────────────────┐        │
     │   │           SandboxEvaluator                  │        │
     │   │  ┌─────────┐ ┌─────────┐ ┌─────────┐       │        │
     │   │  │ Worker 0│ │ Worker 1│ │ Worker N│       │        │
     │   │  │ subproc │ │ subproc │ │ subproc │       │        │
     │   │  └────┬────┘ └────┬────┘ └────┬────┘       │        │
     │   └───────┼───────────┼───────────┼────────────┘        │
     │           ▼           ▼           ▼                      │
     │    ┌──────────────────────────────────────────┐         │
     │    │       FitnessVector (6-dim)              │         │
     │    │  correctness │ p50 │ p99 │ thru │ mem │  │         │
     │    │                     parsimony            │         │
     │    └────────────────────┬─────────────────────┘         │
     │                         ▼                               │
     │              ┌──────────────────────┐                   │
     │              │  NSGA-II Selection   │                   │
     │              │  Non-dominated sort  │                   │
     │              │  + Crowding distance │                   │
     │              └──────────┬───────────┘                   │
     │                         ▼                               │
     │              ┌──────────────────────┐                   │
     │              │  Mutation / Crossover│                   │
     │              │  LLM + AST (13 ops)  │                   │
     │              └──────────────────────┘                   │
     └─────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
          ┌──────────────────┐         ┌──────────────────┐
          │  SolutionArchive │         │  PromptEvolver   │
          │  FAISS + MiniLM  │         │  15 mutation ops │
          │  Novelty Search  │         │  Crossover       │
          │  Curriculum Learn│         │  Archive-aware   │
          └──────────────────┘         └──────────────────┘
                    │                             │
                    └──────────────┬──────────────┘
                                   ▼
                         ┌──────────────────┐
                         │   Checkpoint     │
                         │   RNG + State    │
                         │   Resume         │
                         └──────────────────┘
```

### The Evolution Cycle

1. **Initialize** — N semi-isolated islands seeded with code variants
2. **Evaluate** — Sandbox executes each individual; extracts 6-dim fitness vector
3. **Select** — NSGA-II non-dominated sorting preserves Pareto frontier
4. **Mutate** — LLM creative mutation + AST-guaranteed structural mutation
5. **Migrate** — Top individuals migrate between islands via configurable topology
6. **Archive** — Novel solutions stored in FAISS index; Novelty Search prevents convergence
7. **Meta-Evolve** — Prompt genomes co-evolve with code; system learns to prompt itself
8. **Checkpoint** — Full RNG state + population + archive snapshotted for reproducibility

---

## 📦 Architecture

```
MutaLambda/
├── muta_lambda.py            # Core orchestrator (MutaLambdaAgent, Island, MigrationBus)
├── fitness_vector.py         # 6-dim multi-objective fitness + Pareto dominance
├── nsga2.py                  # NSGA-II: non-dominated sort + crowding distance
├── island_evolution.py       # IslandPool: thread-parallel island evolution
├── prompt_evolution.py       # RichPromptEvolver: 15 ops + crossover + archive-aware
├── config_loader.py          # YAML config loader + schema validation
├── checkpoint_manager.py     # Full RNG-aware checkpointing + resume
├── property_testing.py       # Hypothesis + Z3 formal verification
├── dashboard.py              # Streamlit HITL dashboard
├── config.yaml               # Reference declarative configuration
├── app.py                    # HuggingFace model wrapper (optional)
├── document_intelligence.py  # MASSIVE parameter extraction (auxiliary)
└── tests/                    # 54 pytest + E2E pipeline tests
```

---

## 🚀 Quick Start

### Requirements
- Python 3.10+
- (Optional) FAISS + sentence-transformers for SolutionArchive
- (Optional) Streamlit for HITL dashboard
- (Optional) Z3 + Hypothesis for formal verification

### Install

```bash
git clone https://github.com/Adlgr87/MutaLambda.git
cd MutaLambda
pip install -r requirements.txt
```

### Run a demo evolution

```bash
# 4 islands, 20 generations, mesh topology, with NSGA-II
python muta_lambda.py --islands 4 --generations 20 --topology mesh --pop-size 6

# From YAML config
python muta_lambda.py --config config.yaml

# Resume from checkpoint
python muta_lambda.py --resume checkpoints/chk_gen0010
```

### Run tests

```bash
# Full pytest suite (54 tests)
pytest tests/ -v

# Embedded integration tests
python muta_lambda.py --test

# End-to-end pipeline test
python tests/e2e_tests.py
```

---

## ⚙️ Configuration

All parameters externalized via YAML (`config.yaml`):

```yaml
evolution:
  num_islands: 4
  generations: 50
  topology: ring          # ring | mesh | fully_connected | random
  early_stop_patience: 15
  novelty_alpha: 0.15

population:
  size: 8
  top_k: 3
  migration_interval: 10
  migrants_per_island: 2

sandbox:
  timeout_sec: 10.0
  max_workers: 4

archive:
  enabled: true
  max_size: 10000

prompt_evolution:
  enabled: true
  pop_size: 6

checkpoint:
  interval: 10
  dir: checkpoints
```

---

## 🧬 Multi-Objective Fitness

MutaLambda optimizes **six objectives simultaneously** via Pareto dominance:

| Objective | Direction | Meaning |
|-----------|-----------|---------|
| `correctness` | ↑ | Fraction of tests passed (0–1) |
| `latency_p50` | ↓ | Median execution time (seconds) |
| `latency_p99` | ↓ | P99 execution time (seconds) |
| `throughput` | ↑ | Operations per second |
| `memory_peak_mb` | ↓ | Peak RSS memory (MiB) |
| `parsimony` | ↑ | 1 / (1 + cyclomatic_complexity / KB) |

NSGA-II selection preserves the Pareto frontier while maintaining diversity via crowding distance.

---

## 🏝️ Multi-Island Evolution

- **N islands** evolve semi-independently in parallel threads
- **Differentiated seeding** — Island 0 gets original code; islands 1..N get progressively mutated variants
- **MigrationBus** — Configurable topology (ring, mesh, fully_connected, random)
- **Diversity tracking** — Intra-island and cross-island uniqueness metrics

---

## 📚 SolutionArchive (Long-Term Memory)

- **FAISS IndexFlatIP** — Cosine-similarity search over MiniLM embeddings
- **Novelty Search** — Rewards structural distance from archive (not just fitness)
- **Curriculum Learning** — k-means sampling of diverse solutions
- **Persistence** — Save/load archive to disk for experiment continuity

---

## 🧠 Prompt Meta-Evolution

Prompts are genomes that co-evolve with code:

- **15 mutation operators** — Word swap, constraint add/remove, instruction rephrase, few-shot evolution
- **Uniform crossover** — Combine system prompts, instructions, temperature, and few-shot examples
- **Archive-aware** — Draws diverse few-shot examples from SolutionArchive
- **PromptFitness** — Quality (50%) + Diversity (30%) + Consistency (20%)

---

## 🛡️ Sandbox & Safety

- **Subprocess isolation** — Every individual executes in a separate process
- **Resource tracking** — Peak RSS memory via `resource.getrusage()`
- **Timeout protection** — Configurable per-evaluation timeout
- **Graceful degradation** — All failures → penalized FitnessVector, never engine crash
- **ProcessPoolExecutor** — Massive parallel evaluation

---

## 💾 Reproducibility

```bash
# Run with fixed seed
python muta_lambda.py --config config.yaml

# Checkpoints capture:
#   - Random + numpy RNG state
#   - Island populations + scores
#   - SolutionArchive (FAISS index + metadata)
#   - PromptEvolver state
#   - Config SHA256 hash + git commit hash
```

---

## 📊 HITL Dashboard

```bash
streamlit run dashboard.py
```

- Real-time fitness/diversity/Pareto charts
- Per-island score tracking
- Expert hint injection into random islands
- Variant approval/rejection before costly evaluation

---

## 🔬 Property-Based Testing

```python
from property_testing import infer_property_strategies, run_property_tests

# Auto-generate Hypothesis strategies from function signatures
strategies = infer_property_strategies(code)

# Z3 formal verification of algorithmic invariants
from property_testing import verify_invariant_z3
holds, counterexample = verify_invariant_z3(code, "result >= 0")
```

---

## 🔮 API

```python
from muta_lambda import MutaLambdaAgent, EvolveConfig

config = EvolveConfig(
    num_islands=4,
    generations=100,
    topology="mesh",
    seed_codes=["def solution(x): return x + 1"],
)

agent = MutaLambdaAgent(config=config, test_cases=[
    {"function": "solution", "args": [1], "expected": 2},
    {"function": "solution", "args": [5], "expected": 6},
])

best = agent.run(task="Optimize a simple arithmetic function")
print(best.code)
print(agent.get_metrics())
```

---

## 🧪 Testing

| Suite | Tests | Command |
|-------|-------|---------|
| Unit (pytest) | 54 | `pytest tests/ -v` |
| Embedded | 14 | `python muta_lambda.py --test` |
| E2E Pipeline | 3 pipelines | `python tests/e2e_tests.py` |

---

## 📜 License

MIT © 2026 Adlgr87