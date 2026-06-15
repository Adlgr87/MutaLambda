# 🧬 MutaLambda — Evolutionary Code Synthesis Platform

[![CI](https://github.com/Adlgr87/MutaLambda/actions/workflows/python-package.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Phases](https://img.shields.io/badge/phases-7%2B-orange)
![Tests](https://img.shields.io/badge/tests-74%2B-brightgreen)

**MutaLambda** is a research-grade evolutionary computation platform that emulates Google DeepMind's **AlphaEvolve** paradigm: evolving code through multi-island genetic algorithms, LLM-powered prompt meta-evolution, FAISS-based long-term memory, NSGA-II multi-objective optimization, convergent evolution boosting, and **Linaje Multiversal** — a time-travel backtracking system inspired by 5D chess.

> *"Code that writes itself — guided by evolution, validated by sandbox, curated by Pareto, and blessed by pedigree."*

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
     │                                                         │
     │   ┌─────────────────────────────────────────────────┐   │
     │   │        Fase 6.5–7: ConvergentBoost + Linaje    │   │
     │   │  ┌──────────────────┐  ┌────────────────────┐  │   │
     │   │  │ LineageGraph     │  │ ConvergentBoost    │  │   │
     │   │  │ DAG genealógico  │  │ Consenso entre     │  │   │
     │   │  │ + Pedigree ♜     │  │ islas → +15% score │  │   │
     │   │  └────────┬─────────┘  └────────────────────┘  │   │
     │   │           ▼                                     │   │
     │   │  ┌─────────────────────────────────────────┐    │   │
     │   │  │ ♜ Resurrección de ramas abandonadas    │    │   │
     │   │  │   (time-travel backtracking)            │    │   │
     │   │  │ ✕ Cross-branch crossover (linajes)     │    │   │
     │   │  └─────────────────────────────────────────┘    │   │
     │   └─────────────────────────────────────────────────┘   │
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
6. **Boost** — Cross-island convergent solutions get +15% fitness (consensus mechanism)
7. **Archive** — Novel solutions stored in FAISS index; Novelty Search prevents convergence
8. **Meta-Evolve** — Prompt genomes co-evolve with code; system learns to prompt itself
9. **Track Lineage** — Every individual's pedigree recorded in the LineageGraph DAG
10. **Backtrack** — On stagnation, revive abandoned branches via time-travel resurrection ♜
11. **Checkpoint** — Full RNG state + population + archive + lineage snapshotted

---

## 🧩 Optional Evolutionary Extensions (muta_ext)

MutaLambda ships a **plug‑in package** `muta_ext/` that adds powerful, opt‑in capabilities without touching the core evolution loop. All extensions are disabled by default and can be toggled via the new flags in `EvolveConfig` (e.g. `enable_numerical_health`, `enable_tipping_detection`).

| Module | Purpose | Key API |
|--------|---------|---------|
| `lineage/compression.py` | Differential compression of inactive `LineageGraph` nodes (zlib + optional diff). Reduces RAM usage >60 % on runs with >1 000 individuals. | `LineageCompressor.compress_inactive()`, `decompress_node()` |
| `evaluation/cache.py` | Canonical AST cache keyed by a structural hash (normalised variable names, stripped metadata). Skips sandbox execution for duplicate code. | `CanonicalCache.get()`, `put()`, `stats()` |
| `evaluation/numerical_health.py` | Static analysis of generated code for numerical stability (stiffness, division safety, exponential calls). Adds a `numerical_health` dimension to `FitnessVector`. | `evaluate_numerical_health()` |
| `diagnostics/tipping.py` | Robust MAD‑based detection of tipping points in the fitness time‑series. Emits `TippingEvent` objects with magnitude and severity. | `detect_tipping()` |
| `diagnostics/evolution_report.py` | Computes Shannon entropy, Lyapunov exponent, spectral radius and classifies the evolutionary state (`converging`, `exploring`, `stalled`, `unstable`). Serializable to JSON for the dashboard. | `EvolutionReport.compute()`, `to_dashboard_dict()` |
| `mutation/stepper_protocol.py` | Protocol (`MutationStepper`) for composable mutation steppers. Includes built‑in `ASTStepper` and `CrossBranchStepper`. Allows weighted selection via YAML. | `MutationComposer`, `ASTStepper`, `CrossBranchStepper` |

These modules are imported under `muta_ext` and can be used from the main loop:

```python
from muta_ext.evaluation.cache import CanonicalCache
from muta_ext.diagnostics.evolution_report import EvolutionReport
# …
```

### 📊 Dashboard – Diagnostics Tab

The Streamlit HITL dashboard now features a **Diagnostics** tab that surfaces the new evolutionary metrics:

* **Shannon Entropy** – genetic diversity of the population.
* **Lyapunov Exponent** – rate of divergence/convergence between successive generations.
* **Spectral Radius** – ratio of max/min fitness (captures extreme dispersion).
* **Classification** – automatic label (`converging`, `exploring`, `stalled`, `unstable`).
* **Tipping Events** – table of recent outliers detected by the MAD‑based detector.
* **Lineage Compression Stats** – number of compressed nodes, active nodes and compression ratio.

All of these are rendered in real‑time via `DashboardRenderer` and are stored in `DashboardState` through the new `record_diagnostics` method. The dashboard still offers the classic HITL controls (hint injection, approve/reject) and the original fitness/diversity charts.

---


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
├── muta_ext/                # Optional extensions (opt‑in)
│   ├── lineage/
│   │   └── compression.py
│   ├── evaluation/
│   │   ├── cache.py
│   │   └── numerical_health.py
│   ├── diagnostics/
│   │   ├── tipping.py
│   │   └── evolution_report.py
│   └── mutation/
│       └── stepper_protocol.py
└── tests/                    # 74 pytest + E2E pipeline tests
```

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
# Full pytest suite (74 tests)
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

  convergent_boost:
    enabled: true
    threshold: 0.85
    factor: 0.15

  resurrection:
    enabled: true
    threshold: 8
    max_attempts: 3
    min_score_ratio: 0.3

  cross_branch_crossover:
    enabled: true
    prob: 0.05
    min_distance: 3

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
## 🤝 Convergent Evolution Boost

When multiple islands independently arrive at similar solutions, that's a strong signal of optimality. MutaLambda detects this and reinforces it:

- **Cross-island consensus detection** — cosine similarity via `SolutionArchive` embeddings (or Jaccard fallback)
- **Fitness boosting** — convergent individuals get `score *= (1 + factor × similarity)` (default +15%)
- **Periodic evaluation** — checked every `migration_interval` generations
- **Configurable** — enable/disable, adjust similarity threshold and boost factor

```yaml
convergent_boost:
  enabled: true
  threshold: 0.85    # minimum cosine similarity
  factor: 0.15       # boost multiplier
```

> *Concept adapted from FACTOR Protocols' Consensus Boosting pattern.*

---
## ♜ Linaje Multiversal (Time-Travel Backtracking)

Inspired by **5D chess with multiversal time travel**, this system gives every solution a complete pedigree and the ability to revisit abandoned evolutionary paths.

### 🌳 LineageGraph — The Genealogical DAG

Every individual is registered as a node in a directed acyclic graph with:

| Field | Purpose |
|-------|---------|
| `id` / `parent_ids` | Full ancestry chain (who mutated into whom) |
| `generation` / `island_id` | Spatiotemporal origin |
| `score` / `fitness` | Multi-objective metrics at time of evaluation |
| `code_hash` | Fast deduplication |
| `alive` | Whether this branch is still active |
| `resurrected` | Whether this node was revived via time-travel |

```python
# Query the genealogical tree
ancestors = lineage.get_ancestors(best_individual.id)
distance  = lineage.get_genealogical_distance(ind_a.id, ind_b.id)
```

### ♜ Branch Resurrection (Time Travel)

When evolution stagnates (configurable threshold, default 8 generations without improvement):

1. **Scan abandoned branches** — find nodes with `score > threshold` that were prematurely discarded
2. **Revive the most promising** — apply aggressive 3× mutation with alternative operators
3. **Inject into the weakest island** — the stagnant island gets a fresh genetic injection
4. **Mark as resurrected** — prevents infinite loops

```yaml
resurrection:
  enabled: true
  threshold: 8          # stagnant gens before first attempt
  max_attempts: 3       # max resurrections per run
  min_score_ratio: 0.3  # min score relative to global_best
```

### ✕ Cross-Branch Crossover

Instead of only crossing parents within the same island and generation, MutaLambda can cross parents from **different genealogical lineages**:

- Selects one parent with high `correctness` and another with high `throughput`
- Verifies genealogical distance ≥ `min_distance` (default 3)
- Applies crossover to produce hybrid offspring with both lineages

```yaml
cross_branch_crossover:
  enabled: true
  prob: 0.05            # probability per new child
  min_distance: 3       # minimum genealogical distance
```

> *"En lugar de solo avanzar hacia la mejor solución, puedes retomar ramas muertas si detectas que la evolución se estancó — equivalente a viajar al pasado para explorar otra rama."*

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
| Unit (pytest) | 74 | `pytest tests/ -v` |
| E2E Pipeline | 3 pipelines | `python tests/e2e_tests.py` |

---

## 📜 License

MIT © 2026 Adlgr87