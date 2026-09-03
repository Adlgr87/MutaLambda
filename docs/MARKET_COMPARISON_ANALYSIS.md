# MutaLambda — Análisis del Mercado para Comparativa Justa

> **Propósito:** definir CON QUÉ herramientas comparar MutaLambda, POR QUÉ cada una
> es (o no) una comparación justa, y QUÉ papel juega en el leaderboard.
> Fecha: 2026-09-03 · Estado: análisis base para `PLANS/MARKET_COMPARISON_WORKFLOW.md`

MutaLambda es un **optimizador evolutivo de código** (NSGA-II + islas + HFC + LLM
opcional) que transforma una función correcta en una equivalente más rápida, validada
por tests. Por tanto, la comparación justa se hace contra herramientas cuyo **contrato
es idéntico**: misma entrada (código fuente correcto + suite de tests), misma salida
(código equivalente más rápido), mismo presupuesto de evaluación.

---

## 0. Diagnóstico: por qué la comparativa actual NO es seria

El harness actual (`benchmarks/market_comparison_harness.py`) tiene tres defectos
que invalidan el leaderboard ante cualquier revisor técnico:

| # | Defecto | Evidencia en código | Consecuencia |
|---|---------|---------------------|--------------|
| D1 | **MutaLambda no corre su optimizador**: la entrada `mutalambda` usa `candidate_code = task.seed_code()` (identidad) | rama `else` de `run_tool()` | El "MutaLambda (Phase 6)" del leaderboard es el baseline disfrazado |
| D2 | **Los competidores son stubs**: `copilot_stub`/`codewhisperer_stub` devuelven el código canónico del prompt | `TOOL_REGISTRY: "backend": "stub"` | Ratio 1.0 inventado para productos que nunca ejecutamos |
| D3 | **Los LLM por API están mal etiquetados**: un endpoint de chat (Agnes, Poolside, OpenRouter) es un *LLM one-shot*, no una herramienta de optimización | `TOOL_REGISTRY: "type": "llm"` | Compara manzanas con naranjas: 1 llamada vs un loop evolutivo |

**Regla de oro que sale de este diagnóstico:** un competidor solo entra al
leaderboard si **realmente se ejecuta, con presupuesto acotado y medido por el mismo
harness** (`EvaluationService` de MutaLambda). Lo que no corre, se reporta como
referencia publicada (cita), nunca como fila del leaderboard.

---

## 1. Panorama 2025–2026 de herramientas comparables

### Categoría A — Competidores directos head-to-head (evolución de programas con LLM)

Estos sistemas hacen EXACTAMENTE lo que MutaLambda: parte de un programa que pasa
tests, lo mutan (con LLM) durante N evaluaciones y devuelven el mejor. Son la
comparación central.

| Herramienta | Repositorio / install | Por qué es comparación justa | Presupuesto natural |
|---|---|---|---|
| **ShinkaEvolve** (Sakana AI, 2025) | `pip install shinka-evolve` · github.com/SakanaAI/ShinkaEvolve · arXiv:2509.19349 | Open-source en PyPI, evolución de programas con islas+archivo (misma arquitectura que MutaLambda), reclama SOTA en sample-efficiency (~150 evals). Es el rival directo y medible | # de evaluaciones de programa |
| **OpenEvolve** (codelion) | github.com/codelion/openevolve | Réplica open-source de AlphaEvolve, ejecutable con cualquier LLM. Benchmark público: suite AlphaEvolve (circle packing, MinimizeMaxMinDist, autocorrelación) | # de evaluaciones + tokens LLM |
| **CodeEvolve** (inter-co, arXiv:2510.14150) | github.com/inter-co/science-codeevolve | Agente evolutivo con islas; **ya re-corrió OpenEvolve y ShinkaEvolve bajo settings matched** — metodología que copiamos | # evaluaciones + costo USD |
| **EoH** (FeiLiu36/EoH) | github.com/FeiLiu36/EoH | Evolution of Heuristics; MutaLambda ya tiene `eoh_suite.py` con sus problemas (OBP, TSP, FSSP) → comparación directa con sus números publicados | # LLM calls |

### Categoría B — Genetic Improvement clásico (baseline "sin IA generativa")

| Herramienta | Repositorio | Papel en la comparativa |
|---|---|---|
| **PyGGI 2.0** (coinse) | github.com/coinse/pyggi | GI puro: mutaciones AST/línea sin LLM, fitness = tests + speedup. Contrato idéntico al de MutaLambda. Demuestra si el motor LLM/evolutivo de MutaLambda aporta valor sobre mutación clásica |
| **Py2Cy** (SOLAR-group, opcional) | github.com/SOLAR-group/Py2Cy | GI Python→Cython (speedup hasta 18× reportado en su paper). Interesante como baseline de la familia GI con compilación |

### Categoría C — Referencias deterministas (techo honesto, no "herramientas rivales")

No son optimizadores evolutivos, pero **deben aparecer** porque resuelven el mismo
contrato (semántica preservada, menos tiempo) y marcan el techo que MutaLambda debe
contextualizar:

| Referencia | Papel |
|---|---|
| **Numba** `@njit` | Upper bound de compilación JIT en Python puro (a menudo 10–100×) |
| **Cython** / **mypyc** | Upper bound de compilación estática (requiere anotar tipos) |
| **LLM one-shot** (GPT/Claude/Gemini vía API, 1 sola llamada) | Ablación clave: ¿la evolución de MutaLambda mejora sobre una pasada del mismo LLM? Reutiliza los endpoints ya integrados (OpenRouter/Agnes) pero **etiquetados como `llm-oneshot/<model>`**, no como productos |

### Categoría D — Nivel MOTOR (rendimiento de ejecución del motor, no del resultado)

Para las métricas de **ejecución/rendimiento interno** (que es donde MutaLambda
diferencia: NSGA-II vectorizado, caches, HFC), comparar contra frameworks de
referencia del dominio:

| Framework | Métrica comparable |
|---|---|
| **pymoo** (NSGA-II de referencia) | generaciones/seg, escalabilidad N∈{50,100,200,500}, hypervolume en DTLZ2 |
| **DEAP** | evaluaciones/seg, overhead por generación |

### Categoría E — Cerrados: solo comparación informada (NO leaderboard)

| Sistema | Tratamiento |
|---|---|
| AlphaEvolve (DeepMind), ThetaEvolve, FunSearch | Citar números publicados de la suite AlphaEvolve como línea de referencia externa. Nunca como fila propia del leaderboard: no se pueden ejecutar ni presupuestar |

---

## 2. Matriz herramienta × benchmark (qué corre contra qué)

| Suite | MutaLambda | ShinkaEvolve | OpenEvolve | PyGGI | Numba/Cython | LLM one-shot | pymoo/DEAP |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| S1. EffiBench-Python (convertidas, ver §3) | ✅ | — | ✅ | ✅ | ✅ | ✅ | — |
| S2. EffiBench-X (subset Python) | ✅ | — | ✅ | ✅ | ✅ | ✅ | — |
| S3. PIE-pattern (sintético, etiquetado) | ✅ | — | ✅ | ✅ | ✅ | ✅ | — |
| S4. Suite AlphaEvolve (circle packing, etc.) | ✅ | ✅ | ✅ | — | — | ✅ | — |
| S5. EoH suite (OBP/TSP/FSSP) | ✅ | ✅ | ✅ | — | — | ✅ | — |
| S6. Motor: DTLZ2 + escalabilidad | ✅ | — | — | — | — | — | ✅ |
| S7. pyperformance + PolyBench | ✅ | — | — | — | ✅ | — | — |

"—" = no aplica por diseño (p. ej. PyGGI no optimiza discovery matemático; pymoo no
optimiza código fuente). Esta matriz ES la honestidad de la comparativa: cada
herramienta compite donde su contrato aplica.

## 3. Nota crítica sobre EffiBench

- El EffiBench original (NeurIPS'24) es **Java**; MutaLambda usa conversiones
  automáticas Java→Python (`bench_public/he_convert.py`, ~891 convertibles). Es
  válido pero **debe etiquetarse** `EffiBench-Python (converted, he_convert)` y
  excluir tasks cuya conversión no pasa el baseline.
- **EffiBench-X** (NeurIPS'25; github.com/EffiBench/EffiBench-X, HF
  `EffiBench/effibench-x`) trae subset Python nativo, sandbox Docker y métricas
  estandarizadas (**ET%, MP%, MI%, Pass@1**). Adoptarlo: da métricas comparables con
  literatura 2025-2026 y neutraliza la crítica de contaminación del dataset Java.

---

## 4. Qué NO hacer (errores que invalidan la comparativa)

1. **No stubs en el leaderboard.** Copilot/CodeWhisperer salen o se mueven a una
   sección "no ejecutable — referencia cualitativa".
2. **No presupuestos asimétricos.** Prohibido darle a MutaLambda 500 evaluaciones y
   al rival 20 (o viceversa). El eje primario es presupuesto de evaluaciones idéntico
   + mismo LLM backend para todos los evolutivos (ver `FAIRNESS_PROTOCOL.md`).
3. **No medir con harness distintos.** TODOS los candidatos (de cualquier
   herramienta) se miden con `EvaluationService` de MutaLambda: mismos samples,
   warmups, timeout, y la misma máquina.
4. **No speedup sin correctness.** Un candidato solo computa ratio si pasa el 100 %
   de tests; en caso contrario cuenta como inválido para %opt.
5. **No números sin dispersión.** Mínimo 3 seeds (5 recomendado), mediana ± IQR,
   Mann–Whitney U para declarar "mejor que".
6. **No fabricar DNFs a favor.** Si una herramienta no instala/corre, se reporta
   `DNF (motivo, comando ejecutado)` — no se elimina silenciosamente.

## 5. Conclusión ejecutiva

La comparativa seria se estructura en **tres leaderboards separados**, cada uno con
su métrica:

1. **L1 — Eficiencia de código** (S1–S3): MutaLambda vs ShinkaEvolve/OpenEvolve vs
   PyGGI vs LLM one-shot vs Numba/Cython. Métricas: speedup P50, %opt, ET/MP/MI,
   costo por speedup.
2. **L2 — Evolución algorítmica** (S4–S5): MutaLambda vs ShinkaEvolve vs OpenEvolve
   vs EoH (números publicados como contexto). Métrica: score del problema con
   presupuesto igual de evals, curva best-so-far.
3. **L3 — Motor** (S6): MutaLambda NSGA-II/HFC vs pymoo/DEAP. Métricas: gens/sec,
   evals/sec, escalabilidad, hypervolume.

El detalle operativo (presupuestos, fórmulas, estadística, gates) está en
`benchmarks/FAIRNESS_PROTOCOL.md` y el plan ejecutable por fases en
`PLANS/MARKET_COMPARISON_WORKFLOW.md`.
