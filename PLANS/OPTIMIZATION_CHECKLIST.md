# MutaLambda optimization workflow checklist

Source: `PLANS/OPTIMIZATION_WORKFLOW.md`  
PR #4 (FASE 1–3): **MERGED** → `main` (`7d2c73d`)  
Branch FASE 4: `maintenance/mutalambda-opt-fase4`

## FASE 1–3 ✅ (merged)

Ver historial PR #4.

## FASE 4 — Baja

| ID | Item | Estado |
|----|------|--------|
| 4.1 | Tests “redundantes” | ✅ `tests/conftest.py` helpers compartidos; archive vs nsga2 **no** se fusionan (dominios distintos) |
| 4.2 | Documentar métricas | ✅ docstring `FitnessVector` + `docs/FITNESS_METRICS.md` |

## Verificación FASE 4

```bash
pytest tests/ -q
```
