# MutaLambda

**MutaLambda** is a research platform for evolutionary code synthesis. It evolves Python code through isolated populations, sandbox evaluation, multi-objective selection, lineage tracking, long-term memory, prompt evolution, and optional Evolution Upgrade v2.0 modules.

The project is not a production code-generation service. It is a modular experiment bench for asking a practical question:

> Can code candidates improve over time while preserving traceable ancestry, measurable diversity, and reproducible experiment state?

Current verified local status:

| Metric | Value |
|---|---:|
| Test suite result | `147 passed` |
| Test warnings | `2` FAISS/SWIG deprecation warnings |
| Test files | `17` |
| Core runtime language | Python 3.10+ |
| Fitness objectives | `6` |
| Built-in island topologies | `ring`, `mesh`, `fully_connected`, `random`, `spatial_grid` |
| Main v2.0 extension modules | `5` |
| Optional archive backend | FAISS + sentence-transformers |
| Default v2.0 behavior | Disabled unless enabled in config |

Last verified command:

```bash
pytest -q
```

Result:

```text
147 passed, 2 warnings
```

---

## What It Does

MutaLambda starts with one or more seed programs, mutates them, evaluates them in a sandbox, selects the best and most diverse candidates, migrates individuals between islands, records their genealogy, and optionally stores useful solutions or patterns for later reuse.

The default loop is:

```text
Initialize
  -> Evaluate in Sandbox
  -> Compute FitnessVector
  -> Select with NSGA-II
  -> Mutate / Crossover
  -> Migrate between Islands
  -> Archive / Track Lineage / Checkpoint
```

With Evolution Upgrade v2.0 enabled, the loop can add:

```text
Mutate
  -> Dialectic Critique
  -> Evaluate
  -> Entropy + Discovery Selection
  -> Horizontal Code Transfer
  -> Spatial Migration
  -> Pattern Memory
```

---

## Design Values

| Value | How the project implements it | Current honesty |
|---|---|---|
| Safety first | Generated code runs through `SandboxEvaluator`, not direct in-process execution. | Sandbox is useful but not a complete security boundary against every possible hostile program. |
| Reproducibility | Checkpoints save populations, RNG state, lineage, prompt state, HFC state, metrics, and config hash. | Exact reproducibility still depends on LLM determinism and environment stability. |
| Modularity | Optional features live mostly in `muta_ext/` and are controlled by `config.yaml`. | Some orchestration hooks still live in `muta_lambda.py` and `island.py`. |
| Measurability | Fitness, diversity, lineage, entropy, THC, dialectic, HFC, and archive metrics are exposed. | Some metrics are proxies, not definitive scientific proof. |
| Lineage over leaderboard-only evolution | `LineageGraph` records ancestry and supports branch resurrection and discovery scoring. | Long-run lineage scaling needs more benchmark data. |
| Graceful degradation | Optional FAISS, sentence-transformers, Streamlit, and scientific helpers degrade when unavailable. | Optional paths need more integration testing across environments. |

---

## Architecture Map

```text
MutaLambdaAgent
  |-- Islands
  |     |-- population of Individual
  |     |-- local evaluation
  |     |-- mutation / crossover
  |
  |-- IslandPool
  |     |-- parallel generation execution
  |
  |-- MigrationBus
  |     |-- topology-aware migration
  |     |-- optional spatial topology
  |
  |-- SandboxEvaluator
  |     |-- subprocess execution
  |     |-- timeout / memory / stdout / stderr
  |
  |-- FitnessVector
  |     |-- correctness
  |     |-- latency_p50
  |     |-- latency_p99
  |     |-- throughput
  |     |-- memory_peak_mb
  |     |-- parsimony
  |
  |-- NSGA-II
  |     |-- non-dominated sorting
  |     |-- crowding distance
  |
  |-- LineageGraph
  |     |-- ancestors
  |     |-- abandoned branches
  |     |-- hybrid THC lineage
  |
  |-- Optional systems
        |-- SolutionArchive
        |-- PromptEvolver / RichPromptEvolver
        |-- HFCLeagueEngine
        |-- Evolution Upgrade v2.0 engines
        |-- Dashboard / HITL
        |-- CheckpointManager
```

---

## Main Components

| Component | File | Role | Stage |
|---|---|---|---|
| Main orchestrator | [`muta_lambda.py`](muta_lambda.py) | Builds the agent, runs generations, applies global features, exposes metrics. | Core, active |
| Island evolution | [`island.py`](island.py) | Evaluates, selects, mutates, and reproduces one local population. | Core, active |
| Parallel island pool | [`island_evolution.py`](island_evolution.py) | Runs islands concurrently and records island snapshots. | Core, usable |
| Migration | [`migration.py`](migration.py) | Moves candidates between islands by topology. | Core, usable |
| Data model | [`models.py`](models.py) | `Individual`, `LineageNode`, `LineageGraph`, `EvalResult`, configs. | Core, active |
| Fitness | [`fitness_vector.py`](fitness_vector.py) | Six-objective fitness and scalar fallback. | Core, tested |
| NSGA-II | [`nsga2.py`](nsga2.py) | Pareto selection and crowding distance. | Core, tested |
| Sandbox | [`sandbox.py`](sandbox.py) | Subprocess evaluator with timeout and metrics. | Core, active |
| LLM backend | [`llm_backend.py`](llm_backend.py) | Ollama, OpenAI, Anthropic, OpenRouter, Mistral, local CLI adapters. | Usable, provider-dependent |
| Prompt evolution | [`prompt_evolver.py`](prompt_evolver.py), [`prompt_evolution.py`](prompt_evolution.py) | Evolves prompts as genomes. | Experimental |
| Semantic archive | [`archive.py`](archive.py) | FAISS-backed long-term memory and novelty scoring. | Optional |
| Checkpoints | [`checkpoint_manager.py`](checkpoint_manager.py) | Save/resume state and reproducibility metadata. | Usable |
| HFC tiers | [`hfc_tiers.py`](hfc_tiers.py) | Hierarchical Fair Competition style tiered evolution. | Experimental |
| Dashboard | [`dashboard.py`](dashboard.py) | Streamlit HITL and advanced metrics view. | Experimental UI |
| Property helpers | [`property_testing.py`](property_testing.py) | Hypothesis/Z3-style helper checks. | Research helper |
| Legacy adapter | [`legacy/`](legacy) | Inferless/document workflows kept outside core path. | Legacy |

---

## Evolution Upgrade v2.0

The v2.0 layer is opt-in. It is designed to extend MutaLambda's identity around lineage, branch resurrection, diversity, and reusable knowledge. It does not replace the base engine.

| Module | File | What it adds | Metrics |
|---|---|---|---|
| Advanced Selection | [`muta_ext/advanced_selection.py`](muta_ext/advanced_selection.py) | Combines fitness, novelty, entropy, and Discovery Score. | `population_entropy`, `discovery_score_avg`, `entropy_gain_per_gen` |
| THC | [`muta_ext/thc_engine.py`](muta_ext/thc_engine.py) | Transfers reusable AST fragments between individuals and records hybrid ancestry. | `thc_transfer_rate`, `fragment_survival_gens`, `hybrid_lineage_depth` |
| Dialectic Engine | [`muta_ext/dialectic_engine.py`](muta_ext/dialectic_engine.py) | Adds thesis -> critique -> synthesis before sandbox evaluation. | `critique_rejection_rate`, `sandbox_calls_saved` |
| Spatial Topology | [`muta_ext/spatial_topology.py`](muta_ext/spatial_topology.py) | Uses 2D local neighborhoods for migration and local diversity. | `cluster_count`, `local_diversity_index`, `spatial_migration_success` |
| Pattern Memory | [`muta_ext/pattern_memory.py`](muta_ext/pattern_memory.py) | Stores success patterns instead of only full individuals. | Pattern count and per-pattern success rate |

Important limitation: v2.0 is implemented and tested at unit/integration level, but it still needs long benchmark runs to prove when it improves convergence, diversity, or compute efficiency. The code is ready for experiments; the scientific claims are not final.

Enable it in [`config.yaml`](config.yaml):

```yaml
advanced_selection:
  enabled: true
  fitness_weight: 1.0
  novelty_weight: 0.15
  entropy_weight: 0.20
  discovery_weight: 0.35

thc:
  enabled: true
  max_transfers_per_generation: 1
  min_donor_score: 0.0
  validate_in_sandbox: true

dialectic:
  enabled: true
  critique_intensity: medium

spatial:
  enabled: true
  neighborhood: moore

pattern_memory:
  enabled: true
```

---

## Discovery Score

Discovery Score is the most identity-specific part of v2.0. It asks:

> Did this branch produce improved descendants later?

Instead of selecting only by immediate score, MutaLambda can value a candidate that historically acts as an ancestor of later improvements.

Current implementation:

```text
Discovery Score = descendant improvement ratio + normalized descendant gain
```

Measured from:

- `LineageGraph.nodes`
- parent/child edges
- descendant scores

Current caveat: this score is strongest after enough lineage history exists. Early generations may have little or no descendant information, so discovery values can start near zero.

---

## Fitness Model

`FitnessVector` tracks six objectives:

| Objective | Direction | Meaning |
|---|---:|---|
| `correctness` | higher | Fraction of test cases passed, from `0.0` to `1.0`. |
| `latency_p50` | lower | Median execution time. |
| `latency_p99` | lower | Tail execution time. |
| `throughput` | higher | Estimated operations per second. |
| `memory_peak_mb` | lower | Peak resident memory. |
| `parsimony` | higher | Bias toward smaller/simpler code. |

Correctness is a hard gate in scalar fallback ranking. A partially correct candidate should not beat a fully correct one just because it is faster.

---

## Metrics You Can Inspect

`agent.get_metrics()` returns runtime telemetry. Main fields include:

| Metric | Meaning |
|---|---|
| `total_generations` | Number of completed generations. |
| `total_time_sec` | Sum of generation durations. |
| `avg_generation_time_sec` | Average generation duration. |
| `best_score_history` | Best scalar score per generation. |
| `archive_size` | Number of archived solutions when archive is enabled. |
| `num_islands` | Active island count. |
| `hfc_enabled` | Whether HFC tier mode is active. |
| `hfc_stats` | Tier counts and HFC telemetry when enabled. |
| `stagnant_generations` | Early-stop stagnation counter. |
| `cross_island_diversity` | Token/Jaccard-style cross-island diversity estimate. |
| `parallel_generations` | Generations executed through `IslandPool`. |
| `advanced_selection` | Entropy and Discovery Score telemetry. |
| `thc` | Horizontal transfer telemetry. |
| `dialectic` | Critique/synthesis telemetry. |
| `spatial` | Spatial neighborhood telemetry. |
| `pattern_memory_size` | Number of stored pattern records. |

Dashboard support:

- Fitness trend
- Diversity trend
- Per-island scores
- Pareto frontier size
- HITL hint injection
- Advanced v2.0 metrics

---

## Configuration

Most behavior is configured from [`config.yaml`](config.yaml). Important sections:

| Section | Purpose |
|---|---|
| `evolution` | Island count, generations, topology, novelty, early stop, resurrection, convergent boost. |
| `population` | Population size, elite count, migration interval, migrants per island. |
| `sandbox` | Evaluation timeout and worker count. |
| `hfc` | Optional tiered evolution. |
| `archive` | Optional FAISS memory. |
| `prompt_evolution` | Prompt population and elite fraction. |
| `checkpoint` | Save interval and checkpoint directory. |
| `llm` | Backend, model, timeout, temperature. |
| `reproducibility` | RNG seed and git commit tracking. |
| `advanced_selection` | v2.0 selection weights. |
| `thc` | Horizontal transfer behavior. |
| `dialectic` | Critique/synthesis behavior. |
| `spatial` | Local migration topology. |
| `pattern_memory` | Reusable pattern storage. |

---

## LLM Providers

Supported backend names:

| Backend | Notes |
|---|---|
| `ollama` | Good local default if Ollama is running. |
| `openai` | Requires `OPENAI_API_KEY`. |
| `anthropic` | Requires `ANTHROPIC_API_KEY`. |
| `openrouter` | Requires `OPENROUTER_API_KEY`. |
| `mistral` | Requires `MISTRAL_API_KEY`. |
| `microsoft_cpp` | Local CLI adapter. |
| `huggingface_cli` | Local CLI adapter. |

Honest status: the abstraction works, but provider behavior varies. Prompt formatting, token limits, retry policy, latency, and determinism are not identical across providers.

---

## Checkpointing and Reproducibility

Checkpoints save:

- best score and code
- all island populations
- island generation counters
- archive snapshot path
- prompt population and metrics
- HFC tier state
- lineage DAG
- v2.0 metrics
- pattern memory
- Python `random` state
- NumPy RNG state
- config hash
- git commit hash when available

Resume:

```bash
python muta_lambda.py --resume checkpoints/chk_gen0010
```

Honest status: checkpointing is practical and tested, but exact reproduction with external LLM APIs is not guaranteed. Deterministic local stubs are much easier to reproduce.

---

## Testing

Run:

```bash
pytest -q
```

Current verified result:

```text
147 passed, 2 warnings
```

Test coverage areas:

| Test file | Covers |
|---|---|
| [`tests/test_config.py`](tests/test_config.py) | YAML defaults, validation, `EvolveConfig`. |
| [`tests/test_fitness_vector.py`](tests/test_fitness_vector.py) | Fitness scalarization and Pareto behavior. |
| [`tests/test_nsga2.py`](tests/test_nsga2.py) | Non-dominated sort and NSGA-II selection. |
| [`tests/test_lineage.py`](tests/test_lineage.py) | DAG recording, ancestry, resurrection candidates. |
| [`tests/test_lineage_compression.py`](tests/test_lineage_compression.py) | Optional lineage compression. |
| [`tests/test_convergent_boost.py`](tests/test_convergent_boost.py) | Cross-island convergence boosting. |
| [`tests/test_prompt_evolution.py`](tests/test_prompt_evolution.py) | Prompt evolution behavior. |
| [`tests/test_llm_backend.py`](tests/test_llm_backend.py) | Backend resolution and adapter behavior. |
| [`tests/test_hfc_tiers.py`](tests/test_hfc_tiers.py) | HFC tier transitions and state. |
| [`tests/test_property_testing.py`](tests/test_property_testing.py) | Property-testing helpers. |
| [`tests/test_solution_archive.py`](tests/test_solution_archive.py) | Archive behavior. |
| [`tests/test_scientific_extension.py`](tests/test_scientific_extension.py) | Optional scientific extension config. |
| [`tests/test_evolution_upgrade_v2.py`](tests/test_evolution_upgrade_v2.py) | v2.0 modules: advanced selection, THC, dialectic, spatial, pattern memory, checkpoint metrics. |
| [`tests/benchmarks/test_evolution_upgrade_benchmark_matrix.py`](tests/benchmarks/test_evolution_upgrade_benchmark_matrix.py) | Benchmark matrix smoke definitions. |
| [`tests/e2e_tests.py`](tests/e2e_tests.py) | End-to-end smoke tests. |

What tests do not prove yet:

- They do not prove v2.0 improves every task.
- They do not benchmark large-scale convergence.
- They do not prove external LLM determinism.
- They do not prove sandbox security against adversarial code.

---

## Benchmark Plan

The benchmark matrix is defined, but full empirical results are still pending.

Required variants:

| Variant | Purpose |
|---|---|
| `base` | Baseline MutaLambda. |
| `base_plus_thc` | Measure fragment reuse effects. |
| `base_plus_advanced_selection` | Measure entropy/discovery selection. |
| `base_plus_dialectic` | Measure sandbox call savings and quality effect. |
| `full_v2` | Measure combined system behavior. |

Required global metrics:

| Metric | Meaning |
|---|---|
| `best_fitness` | Best observed solution quality. |
| `convergence_speed` | Generations or time to target quality. |
| `fragment_reuse_ratio` | How often transferred fragments survive. |
| `lineage_depth_max` | Maximum genealogical depth. |
| `sandbox_efficiency` | Useful evaluations per sandbox call. |
| `cpu_time_per_gain` | Compute cost per unit of improvement. |

Current status: benchmark definitions exist as smoke tests. Long-run benchmark data is not yet included in the repo.

---

## What Works Well Today

- The modular architecture is significantly cleaner than a single-file prototype.
- The base evolutionary loop runs and is covered by tests.
- NSGA-II and multi-objective fitness are implemented.
- Sandbox evaluation is integrated with pass/fail and timing metrics.
- Lineage tracking, ancestry queries, abandoned branch search, and resurrection are implemented.
- Checkpointing covers the major runtime state.
- v2.0 modules are implemented as opt-in extensions.
- Dashboard exposes core and advanced metrics.
- Optional dependencies degrade without stopping the whole project.
- The full local test suite currently passes.

---

## What Is Still Rough

- The project is still a research scaffold, not a polished product.
- Long-run benchmark evidence is still missing.
- v2.0 weights are reasonable defaults, not tuned scientific constants.
- The Discovery Score needs enough history before it becomes meaningful.
- THC uses AST-level function/class transfer; deeper semantic compatibility is still limited.
- The Dialectic Engine can save sandbox calls, but it depends heavily on LLM critique quality.
- The surrogate model described in the original vision is not yet a trained RandomForest/GP; current advanced selection uses deterministic entropy and lineage heuristics.
- Streamlit HITL is useful, but not production hardened.
- FAISS archive requires optional dependencies and can be heavy for small machines.
- Process-based island parallelism can be fragile with non-pickleable LLM callables.
- Memory metrics are OS-dependent approximations.
- Legacy files are still present for compatibility.

---

## Installation

Minimal:

```bash
pip install -r requirements.txt
```

Optional semantic archive:

```bash
pip install faiss-cpu sentence-transformers
```

Optional dashboard:

```bash
pip install streamlit pandas
streamlit run dashboard.py
```

---

## Minimal API Example

```python
from muta_lambda import EvolveConfig, MutaLambdaAgent

config = EvolveConfig(
    num_islands=4,
    generations=50,
    seed_codes=["def solution(x):\n    return x + 1\n"],
    archive_solutions=False,
    prompt_evolution=False,
)

agent = MutaLambdaAgent(
    config=config,
    test_cases=[
        {"function": "solution", "args": [1], "expected": 2},
        {"function": "solution", "args": [5], "expected": 6},
    ],
)

best = agent.run(task="Optimize a simple arithmetic function")
print(best.code)
print(agent.get_metrics())
```

---

## Repository Utilities

This repository includes [`repomix.config.json`](repomix.config.json) and [`.repomixignore`](.repomixignore) for packaging the source into a readable Markdown bundle:

```bash
repomix --config repomix.config.json
```

---

## Contributing

Development principles:

1. Keep new experiments modular and opt-in.
2. Add objective metrics when adding behavior.
3. Prefer graceful degradation over hard optional imports.
4. Write tests for stabilized behavior.
5. Preserve lineage and checkpoint compatibility.
6. Be honest about what is proven, experimental, or incomplete.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for more project notes.

---

## License

MIT © 2026 Adlgr87
