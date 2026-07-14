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
