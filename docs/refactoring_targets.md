# MutaLambda — Technical Debt & Refactoring Targets

Generated: 2026-08-28 (FASE 0 — static analysis of the working tree)

## Method

Static AST scan of the modules listed in `.workflow` scope (the PDF's "Fase 0"
targets: `evolution_engine.py`, `island.py`, `sandbox.py` plus the modules that
import them). A function/class is flagged when its AST span exceeds **200 lines**.

## Priority-ordered target list

### 🔴 P0 — orchestrator (split first, biggest leverage)

| Module | Span (lines) | Kind | Why it blocks |
|---|---|---|---|
| `muta_lambda.py:406 MutaLambdaAgent.__init__` | 256 | `__init__` | Holds config parsing, RNG wiring, thread/futures/pools, archive hooks and protocol wiring in one constructor — blocks testability and parallel init. |
| `muta_lambda.py:403 MutaLambdaAgent` | 974 | class | Whole orchestrator; `run`, `step_generation`, `shutdown` all inline. This is the spine of the system and the natural seam for the FASE 1 `ValidationGates` / `TwoPhaseValidation` split. |
| `muta_lambda.py:936 step_generation` | 252 | method | Mixes island scheduling, protocol tracing, migration and checkpoint triggers. |

> **Recommended first split** (matches PDF §2.3 "Separación de Responsabilidades"):
> extract `CandidateGenerator`, `FitnessEvaluator`, `SelectionEngine`,
> `MigrationManager` as standalone collaborators injected by `MutaLambdaAgent`.

### 🟠 P1 — evolution core

| Module | Span | Kind |
|---|---|---|
| `island.py:31 Island` | 757 | class | Largest single class; owns island loop, fitness, selection, migration and protocol logic. |
| `hfc_tiers.py:121 HFCLeagueEngine` | 722 | class | HFC league engine + tier selection + match scheduling in one class. |
| `evolution_engine.py:240 CoreEvolutionEngine` | 248 | class | Core AST mutation driver. |
| `evolution_engine.py:17 ASTMutator` | 209 | class | The one hot function (`_complexity_score`, §baseline) lives here. |

### 🟡 P2 — supporting large classes

| Module | Span | Kind |
|---|---|---|
| `component_evolution.py:253 ModuleExtractor` | 221 | class |
| `island_evolution.py:80 IslandPool` | 233 | class | Pool of islands + topology routing in one class. |
| `evaluation_service.py:85 EvaluationService` | 320 | class | Process-pool eval loop + security gate wiring. |
| `checkpoint_manager.py` | — | module | Imports `muta_lambda` (see circular-deps below). |

## Circular import dependencies

Bidirectional import edges detected (A imports B **and** B imports A):

| Pair | Typical direction |
|---|---|
| `checkpoint_manager ↔ muta_lambda` | `checkpoint_manager` re-imports `muta_lambda` symbols at runtime; suggests runtime-late binding / import-cycle. |
| `muta_config ↔ muta_lambda` | config loader depends on agent defaults. |
| `muta_lambda ↔ nsga2` | nsga2 calls back into the orchestrator for selection. |
| `muta_lambda ↔ progressive_pipeline` | pipeline re-exports agent. |
| `muta_lambda ↔ prompt_evolution` | prompt evolution re-imports agent config. |

These are **latent** (they don't crash because imports are deferred), but they are
the kind of coupling that the PDF's FASE 2 §2.4 "Validación Incremental" gate is
designed to break. Each is a candidate for an interface shim (`Protocol`/`abc`).

## Hot-path redundancy (from cProfile)

- `sandbox.py:shutdown` → `evaluation_service.py:shutdown` → `concurrent.futures` pool
  join: ~5 s of teardown `time.sleep`/`select.poll` on every run (see baseline report).
  Not a refactor target per se, but it is the dominant waste the optimizer must
  eliminate or move off the hot path.

## Refactor sequencing (maps to PDF FASE 2)

1. **2.1 OperatorFusion**: collapse the duplicated `run_all_filters` / `_filter_mutant`
   call sites in `mutation_filters.py` and the duplicate `fitness_vector` normalize
   paths in `fitness_normalize.py` / `fitness_vector.py`.
2. **2.2 Long-function split**: apply to the P0 `__init__` (256) and `step_generation` (252)
   first; then `Island` (757) and `HFCLeagueEngine` (722).
3. **2.3 SRP**: inject `CandidateGenerator / FitnessEvaluator / SelectionEngine /
   MigrationManager` into `MutaLambdaAgent`, breaking the 5 circular edges above.
4. **2.4 Incremental validation**: after each split, re-run the smoke chain
   (`test_full_smoke_chain`) and confirm numeric parity (ε < 1e-10 vs this baseline).

## Success criteria (carried from PDF §2)

- [ ] Every function in the listed modules ≤ 200 lines after refactor.
- [ ] Redundancy reduced ≥ 30 % (measured by dedup of `run_all_filters` + selection
      code paths; TBD after refactor diff).
- [ ] All 5 circular import pairs reduced to one-directional or removed.
- [ ] `524 passed, 5 skipped` test baseline preserved (plus new FASE 1 tests added).
