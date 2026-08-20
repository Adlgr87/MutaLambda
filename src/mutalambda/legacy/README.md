# Legacy adapters (archived in-tree)

This directory holds **optional, frozen entrypoints** that are not part of the
main evolution path.

| File | Status | Notes |
|------|--------|--------|
| `inferless_wrapper.py` | **kept** | Still imported by root `app.py` for old Inferless deployments |
| `document_intelligence.py` | **unused by core** | No imports from MutaLambda runtime; retained for historical MASSIVE doc workflows only |

## Policy (optimization FIX 3.2)

- Do **not** add new features here.
- Prefer `muta_ext/` and top-level modules for active code.
- Before deleting `document_intelligence.py`, confirm no external fork depends on it.
- New deployments should use `cli.py` / `MutaLambdaAgent`, not Inferless.

```python
# Preferred modern entrypoints
from muta_lambda import MutaLambdaAgent, EvolveConfig
from muta_config import MutaLambdaConfig
```
