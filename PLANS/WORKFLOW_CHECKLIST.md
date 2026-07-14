# MutaLambda remediation — checklist del workflow

Fuente: `MUTALAMBDA_REMEDIATION_WORKFLOW.md`  
Rama: `maintenance/mutalambda-v4` · PR: https://github.com/Adlgr87/MutaLambda/pull/3  

Leyenda: ✅ hecho · 🟡 parcial · ⬜ pendiente · ⏸ diferido (tests finales)

---

## Orden §17 — Bloqueadores

| # | Item | Estado |
|---|------|--------|
| 1 | Runner aislado real | ✅ `runners.py` |
| 2 | Tests obligatorios | ✅ |
| 3 | `step_generation()` | ✅ |
| 4 | CLI funcional | ✅ |
| 5 | Configuración única | 🟡 EvolveConfig unificado; Pydantic full opcional |
| 6 | Checkpoints JSON unificados | ✅ |
| 7 | EvaluationService central | ✅ |
| 8 | Barreras de migración | ✅ |

## Alta prioridad

| # | Item | Estado |
|---|------|--------|
| 9 | Cache + env key | ✅ |
| 10 | Benchmark p50/p95/p99 | ✅ |
| 11 | API fingerprint | ✅ |
| 12 | Differential testing | ✅ |
| 13 | RNG sesión/isla | ✅ |
| 14 | Errores no silenciosos | ✅ IslandFailure |
| 15 | LLM retry/budget | ✅ |

## Prioridad media

| # | Item | Estado |
|---|------|--------|
| 16 | Archive dedupe semántico | ✅ |
| 17 | Bandit de operadores | ✅ select + reward en Island |
| 18 | Lineage indexado | ✅ |
| 19 | Dashboard por eventos | ✅ |
| 20 | HFC/THC/dialectic contrato | ✅ `EngineExtensionAdapter` |

## Prioridad final

| # | Item | Estado |
|---|------|--------|
| 21 | Integración MASSIVE | 🟡 adapter + ejemplos |
| 22 | Auto-documentación élites | ✅ solo best en run artifacts |
| 23 | Micro-hotpaths | ⬜ |
| 24 | Rust/GPU | ⬜ |

## §16 Observabilidad

| Artifact | Estado |
|----------|--------|
| run_manifest.json | ✅ `run_artifacts.py` |
| best_solution.py / .patch | ✅ |
| fitness_history.json | ✅ |
| lineage.json | ✅ |
| benchmark_report.md | ✅ |

## Criterios §18

| Criterio | Estado |
|----------|--------|
| CLI con código+tests | ✅ |
| resume verdadero | ✅ |
| sandbox real (container disponible) | 🟡 default subprocess |
| no promoción sin tests | ✅ |
| p50/p95/p99 reales | ✅ samples>1 |
| fitness normalizado | ✅ |
| sin races migración | ✅ |
| cache + entorno | ✅ |
| LLM replay | ✅ |
| ckpt sin pickle | ✅ |
| E2E en CI | ✅ |
| MASSIVE patch+benchmark | 🟡 |

## Política de pruebas

**Pruebas finales consolidadas al cerrar el workflow** (acordado).  
Este checklist es la fuente de verdad de avance del requerimiento.

## Siguiente (solo si falta del workflow)

1. Pydantic `MutaLambdaConfig` si se exige unicidad estricta (§3 ML-C02)  
2. Container como default recomendado en docs/doctor  
3. MASSIVE: wiring CLI `run --massive-root`  
4. ⏸ Suite de pruebas final  
