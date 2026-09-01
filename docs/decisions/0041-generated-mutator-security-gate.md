# ADR-0041 — `generate-mutator` guarded by `run_all_filters(profile="strict")`

## Status: accepted (Fase 3B)

## Context
`muta_ext/uast/mutators/llm_generator.py` `generate_mutator()` writes LLM-produced
Python into `muta_ext/uast/mutators/generated/` which is later *executed* by the
mutation pipeline. Without pre-write filtering, a hallucinated `os.system`/`eval`/network
call could escape the sandbox.

## Decision
Before writing the generated file, call `run_all_filters(code, profile="strict")`
and reject the write if any forbidden pattern matches. The strict profile is the
same one used by `MicroVMRunner` post-execution, so a filter failure == a would-be
runtime failure → caught one step earlier.

## Consequences
- False-positive risk only for LLM variants that legitimately need e.g. I/O at
  runtime; mitigated by `--allow` escape hatch + explicit override (see
  `mutation_filters.py` profiles).
- Adds ~2ms per generation per mutator (regex over ~150 LOC).
