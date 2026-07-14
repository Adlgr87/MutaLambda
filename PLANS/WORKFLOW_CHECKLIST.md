# MutaLambda remediation — checklist del workflow

Fuente: `MUTALAMBDA_REMEDIATION_WORKFLOW.md`  
Rama: `maintenance/mutalambda-v4` · PR: https://github.com/Adlgr87/MutaLambda/pull/3  

Leyenda: ✅ hecho · 🟡 parcial · ⬜ fuera de camino base

**Cierre de verificación:** ver `PLANS/WORKFLOW_CLOSEOUT.md` (189 pytest passed, E2E OK).

---

## Orden §17 — Bloqueadores

| # | Item | Estado |
|---|------|--------|
| 1 | Runner aislado real | ✅ |
| 2 | Tests obligatorios | ✅ |
| 3 | `step_generation()` | ✅ |
| 4 | CLI funcional | ✅ |
| 5 | Configuración única | ✅ `MutaLambdaConfig` |
| 6 | Checkpoints JSON unificados | ✅ |
| 7 | EvaluationService central | ✅ |
| 8 | Barreras de migración | ✅ |

## Alta prioridad

| # | Item | Estado |
|---|------|--------|
| 9–15 | Cache, benchmarks, API fingerprint, differential, RNG, errores, LLM policy | ✅ |

## Prioridad media

| # | Item | Estado |
|---|------|--------|
| 16–20 | Archive dedupe, bandit, lineage, EventBus, extension contract | ✅ |

## Prioridad final

| # | Item | Estado |
|---|------|--------|
| 21 | MASSIVE como target externo vía adapter | ✅ |
| 22 | Auto-doc élites | ✅ |
| 23 | Micro-hotpaths | ⬜ opcional post-cierre |
| 24 | Rust/GPU | ⬜ experimental futuro |

## §16 Observabilidad · §18 criterios

Cubiertos (detalle en WORKFLOW_CLOSEOUT.md). Suite de pruebas finales **ejecutada**.

## MASSIVE

https://github.com/Adlgr87/MASSIVE — proyecto **separado**. No se importa en el core.
