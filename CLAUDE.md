# CLAUDE.md — MutaLambda

Behavioral guidelines for work on this repository. Prefer caution over speed for non-trivial changes.

## 1. Think Before Coding

- State assumptions explicitly. If uncertain, ask.
- Present multiple interpretations instead of silently picking one.
- Prefer the simpler approach when it solves the request.
- Stop and name confusion rather than guessing across component boundaries.

## 2. Simplicity First

- No features beyond the request.
- No abstractions for single-use code.
- No speculative configurability.
- If a change can be 50 lines instead of 200, keep it small.

## 3. Surgical Changes

- Touch only what the task requires.
- Match existing style.
- Do not delete unrelated dead code unless asked.
- Clean up only unused symbols **your** change introduced.

## 4. Goal-Driven Execution

Transform work into verifiable goals:

1. Step → verify: check
2. Step → verify: check

For multi-step remediation, follow `PLANS/` and the remediation workflow slices.

## MutaLambda conventions

- Prefer declarative tests: `function` / `args` / `expected` / `comparison`.
- Do not treat the AST scanner as a security boundary; use `CandidateRunner` (`subprocess` | `container`).
- Shared generation API: `MutaLambdaAgent.step_generation()` (CLI/dashboard/core).
- Checkpoints must be JSON (optionally gzip). Never pickle.
- Empty `test_cases` is development-only (`allow_untested` / `--allow-untested`).
- Use `stable_code_hash` (SHA-256), never `hash(code)` for lineage/cache keys.
- Build: `pip install -e ".[cli,dev]"` or `pip install -r requirements.txt`
- Test: `pytest tests/` · E2E: `MUTALAMBDA_E2E_SERIAL=1 python tests/e2e_tests.py --fast`
- CLI: `python cli.py run --source examples/target.py --tests examples/target_tests.json -g 5`

## Security

- No force-push / history rewrite unless the user explicitly requests it.
- Do not commit secrets. Prefer env vars for LLM keys.
- `privacy.allow_external_llm` defaults to false; keep cloud LLM off unless requested.

## Remediación v4

Branch: `maintenance/mutalambda-v4`

Priority order: seguridad → ejecución correcta → evaluación correcta → rendimiento → reproducibilidad → extensiones → MASSIVE.

### MASSIVE (proyecto externo)

https://github.com/Adlgr87/MASSIVE is a **separate** simulation project that
historically motivated MutaLambda. Do not import MASSIVE into core. Optimize
pure functions via `MassiveTargetAdapter(source_file=..., tests_file=...)`.

### Config unificada

```python
from muta_config import MutaLambdaConfig
evolve = MutaLambdaConfig.from_yaml("config.yaml").to_evolve_config()
```

`sandbox.runner=container` is recommended for untrusted code when Docker/Podman is available.

## SWE-Agent Integration Protocol

When working with SWE-Agent or performance-analyzer sub-agents:

1. **Run profiler first**: `python scripts/swe_agent_profiler.py --module nsga2 --iterations 500`
2. **Proposals must include**: metric baseline, code suggestion, risk level, confidence interval
3. **Validate with min 3 runs**: use `scripts/benchmark_runner.py` for statistical rigor
4. **Update EMPIRICAL_EVIDENCE.md**: every accepted/rejected proposal documented
5. **Backward compatibility**: all refactors must preserve existing test suite (355 tests)

### Profiling Hotspots

Key hotspots identified via SWE-Agent profiling:
- **NSGA-II**: O(N²) dominance checks, `_get_fitness()` calls
- **Sandbox**: subprocess spawn overhead, JSON serialization
- **Checkpoint manager**: JSON serialization, file I/O
- **Evolution engine**: AST node copying (`copy.deepcopy`), tree traversal

