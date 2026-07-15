# MutaLambda optimization workflow checklist

Source: `PLANS/OPTIMIZATION_WORKFLOW.md`  
Branch: `maintenance/mutalambda-opt-v1` · PR: https://github.com/Adlgr87/MutaLambda/pull/4  

## FASE 1 — Críticas ✅

| ID | Item | Estado |
|----|------|--------|
| 1.1–1.3 | hash único, CheckpointData, bare except | ✅ |

## FASE 2 — Alta ✅ / 🟡

| ID | Item | Estado |
|----|------|--------|
| 2.1–2.6 | RNG streams, comparison, logging, sys.path, config, MicroVM | ✅ |
| 2.7 | except genéricos high-traffic | 🟡 selectivo |

## FASE 3 — Media

| ID | Item | Estado |
|----|------|--------|
| 3.1 | `__init__.py` útiles | ✅ `muta_ext/*` con `__all__` + lazy root |
| 3.2 | Legacy clean | ✅ documentado; `inferless` kept via `app.py`; `document_intelligence` unused-by-core |
| 3.3 | Naming Fake→Mock | ✅ tests only |
| 3.4 | Consolidar config | ✅ ya `MutaLambdaConfig` + `config.yaml`; repomix tooling retained |
| 3.5 | Constantes | ✅ `constants.py` ampliado + uso en IslandConfig |

## FASE 4 — Baja

⬜ consolidar tests redundantes / métricas docs — opcional

## Verificación

```text
pytest tests/ -q  → 189 passed
```
