# Contributing to MutaLambda

MutaLambda is a modular evolutionary code-synthesis platform. Contributions should keep the core engine lightweight, deterministic by default, and compatible with optional integrations.

## Development phases

The project is organized around these implementation phases:

1. **Phase 1 — Multi-objective fitness and NSGA-II**
   - `FitnessVector`
   - Pareto ranking
   - Crowding distance
   - Multi-objective selection

2. **Phase 2 — Multi-island evolution**
   - `Island`
   - `IslandPool`
   - Ring/mesh/fully connected/random migration topologies
   - Cross-island diversity metrics

3. **Phase 3 — Long-term memory and novelty search**
   - `SolutionArchive`
   - FAISS index
   - Sentence-transformer embeddings
   - Novelty-aware scoring

4. **Phase 4 — Prompt meta-evolution**
   - `PromptGenome`
   - `PromptEvolver`
   - `RichPromptEvolver`
   - Archive-aware prompt mutation and crossover

5. **Phase 5 — Configuration, checkpoints, and reproducibility**
   - `config.yaml`
   - `config_loader.py`
   - `checkpoint_manager.py`
   - RNG seeding and resume workflows

6. **Phase 6 — Human-in-the-loop dashboard and convergence controls**
   - Console dashboard hooks
   - Early-stop monitor
   - HITL hint injection
   - Convergent Boost

7. **Phase 6.5 — Convergent Evolution Boost**
   - Cross-island consensus
   - Fitness boosting for convergent high-similarity islands
   - Controlled novelty preservation

8. **Phase 7 — Linaje Multiversal**
   - `LineageGraph`
   - Genealogical distance
   - Abandoned-branch detection
   - Resurrection of dormant branches
   - Cross-branch crossover

9. **Phase 7+ — Optional lineage compression and diagnostics**
   - `muta_ext/lineage/compression.py`
   - Evolution reports
   - Numerical health checks
   - Tipping-point analysis

## Refactoring conventions

The monolithic orchestrator has been split into focused modules:

- [`muta_lambda.py`](muta_lambda.py:1) — slim compatibility orchestrator and CLI.
- [`models.py`](models.py:1) — shared dataclasses and `LineageGraph`.
- [`llm_backend.py`](llm_backend.py:1) — LLM adapters.
- [`evolution_engine.py`](evolution_engine.py:1) — AST mutation and LLM mutation contracts.
- [`island.py`](island.py:1) — island-local evolution.
- [`migration.py`](migration.py:1) — migration bus.
- [`sandbox.py`](sandbox.py:1) — hard-limited subprocess evaluation.
- [`archive.py`](archive.py:1) — solution archive.
- [`prompt_evolver.py`](prompt_evolver.py:1) — basic prompt evolution.
- [`prompt_evolution.py`](prompt_evolution.py:1) — rich prompt meta-evolution.

Rules:

1. Do not add heavy optional dependencies to the core import path.
2. Keep `muta_lambda.py` as a compatibility layer for existing imports.
3. Prefer small modules with single responsibilities.
4. Preserve backward-compatible names when moving code.
5. Add tests for behavior changes, not only for new modules.
6. Avoid cycles: extension modules may import core modules, but core modules should not import optional extensions directly.

## Running tests

```bash
python -m pytest -q
python tests/e2e_tests.py --fast
python muta_lambda.py --test
```

For focused checks:

```bash
python -m pytest tests/test_lineage.py tests/test_lineage_compression.py
python -m pytest tests/test_solution_archive.py
python -m pytest tests/test_convergent_boost.py
```

## Reproducible benchmark

Use the benchmark script to measure mean and standard deviation across repeated evolution runs:

```bash
python benchmark_reproducible.py --runs 10 --generations 50 --islands 4 --pop-size 8
```

Recommended CI smoke test:

```bash
python benchmark_reproducible.py --runs 2 --generations 1 --islands 2 --pop-size 4 --timeout 1.0
```

The output is JSON and includes:

- mean best score
- standard deviation of best score
- mean elapsed time
- standard deviation of elapsed time
- parseable-rate
- per-run details

## Optional dependencies

Core runtime dependencies are listed in `requirements.txt`.

Optional archive dependencies:

```bash
python -m pip install faiss-cpu sentence-transformers
```

Optional legacy Inferless/HuggingFace dependencies:

```bash
python -m pip install huggingface_hub transformers torch
```

Optional document-processing dependencies:

```bash
python -m pip install pdfplumber pandas openpyxl pillow
```

## Pull request checklist

Before opening a PR:

- [ ] Run `python -m pytest -q`.
- [ ] Run `python tests/e2e_tests.py --fast`.
- [ ] Run `python muta_lambda.py --test`.
- [ ] Add or update tests for changed behavior.
- [ ] Keep optional integrations out of the core import path.
- [ ] Update documentation when adding a new phase, module, CLI flag, or config option.
- [ ] Avoid committing generated checkpoints, logs, or large fixture data.
