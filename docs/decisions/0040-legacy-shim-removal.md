# ADR-0040 — Remove legacy app.py / document_intelligence.py / inferless_wrapper.py

## Status: accepted (Fase 1B — Legacy Janitor)

## Context
`app.py` (12-line shim) re-exported `InferlessPythonModel` from
`legacy/inferless_wrapper.py`. `legacy/document_intelligence.py` (690 lines of
unrelated MASSIVE code) was only referenced by a self-import whose module path
did not match the file location (dead code). No active MutaLambda runtime code,
tests, CLI, Dockerfile, or CI workflows import `app` or `document_intelligence`
outside the deleted files themselves (verified via `rg`).

## Decision
Delete all three files (`app.py`, `legacy/inferless_wrapper.py`,
`legacy/document_intelligence.py`) with `git rm`. PDF Fase 1B conditions are
satisfied: the only remaining references are historical descriptions in
`docs/architecture_inventory.md` and the draft `REPO_ANALYSIS.md`.

## Consequences
- Repo loses the legacy Inferless entrypoint; prior Inferless deployers must pin
  the old release. No active clients were detected.
- `legacy/README.md` policy ("do not add new features here, prefer muta_ext/")
  remains valid and unchanged.
- Smaller import graph → faster `mutalambda` CLI cold start.
