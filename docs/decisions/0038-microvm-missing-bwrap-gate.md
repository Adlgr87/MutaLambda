# ADR-0038 — MicroVMRunner raises on missing bwrap when enforce_ast_scan=True

## Status: accepted (Fase 3C)

## Context
`runners.py` `MicroVMRunner` only *warned* when `bwrap` was absent, risking
silent fallback to an un-isolated execution path that still honors AST scan
guards but loses namespace-level isolation (network/FS).

## Decision
In `MicroVMRunner.__post_init__`, when `enforce_ast_scan` is True and `bwrap`
binary is unavailable, raise `RuntimeError` (was: warn). Keeps the
`enforce_ast_scan=False` opt-out for dev environments without bwrap.

## Consequences
- Fail-fast: users learn about missing bwrap before launching evolution.
- `--enforce-ast-scan`/`--no-ast-scan` CLI flags now gate the error cleanly.
