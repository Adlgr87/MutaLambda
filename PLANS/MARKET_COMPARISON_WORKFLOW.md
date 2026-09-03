# 🔬 WORKFLOW: COMPARATIVA JUSTA DE MERCADO PARA MUTALAMBDA

## 📋 METADATA

| Campo | Valor |
|-------|-------|
| **Proyecto** | MutaLambda |
| **Objetivo** | Generar benchmarks comparativos **serios y auditables** de MutaLambda vs herramientas reales del mercado (ejecución, rendimiento y resultados) y actualizar el proyecto con esos números |
| **Documentos normativos** | `docs/MARKET_COMPARISON_ANALYSIS.md` (con quién comparar) · `benchmarks/FAIRNESS_PROTOCOL.md` (presupuestos y métricas) |
| **Sub-agente** | `.agents/benchmark-comparator.md` |
| **Fecha** | 2026-09-03 |
| **Regla innegociable** | Solo números realmente ejecutados. Sin stubs en el leaderboard. Sin presupuestos asimétricos. |

---

## 🎯 PRINCIPIO RECTOR (léelo antes de cada fase)

> Una comparativa es seria cuando un tercero puede reproducir cada fila del
> leaderboard con: (1) el comando exacto, (2) el `manifest.json` con hardware y
> versiones, y (3) los artefactos crudos por tarea/seed. **Si MutaLambda no corre
> su propio optimizador con presupuesto acotado, el resultado no es un benchmark,
> es marketing.**

Los defectos a corregir primero (ver §0 del análisis): **D1** MutaLambda entra al
leaderboard sin optimizar (`task.seed_code()`), **D2** stubs de
Copilot/CodeWhisperer con ratio 1.0 inventado, **D3** LLM one-shot etiquetados como
herramientas.

---

## ⛔ STOP-GLOBAL: condiciones para NO avanzar de fase

- No pases a la fase siguiente si el **gate** de la fase actual no está en verde.
- Si una herramienta externa no instala/arranca: registra `DNF` con log y sigue con
  las demás — **nunca elimines la fila silenciosamente ni la llenes con supuestos**.
- Si un resultado contradice lo esperado, se reporta igual. El workflow no optimiza
  la narrativa, mide.

---

## ═══════════════════════════════════════════════════════════════════
# FASE 0 — Descubrimiento y baseline del propio estado (½ día)
## ═══════════════════════════════════════════════════════════════════

**Objetivo:** verificar con tus propios ojos (no confiar en docs) el estado actual.

1. Leer `benchmarks/market_comparison_harness.py` completo y confirmar D1–D3.
2. Confirmar que el dataset EffiBench existe: `/tmp/effibench_train.parquet` (si no,
   descargar de `ktd-prime/EffiBench` en HuggingFace — ver `benchmarks/SMOKY_TESTS.md`).
3. Correr el smoke actual y guardar su output como "antes":
   ```bash
   MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/market_comparison_harness.py \
     --smoke --tasks 5 --out benchmarks/results/_fase0_before.json
   ```
4. Detectar la vía canónica para invocar el optimizador real programáticamente:
   `evolve.py` (`MutaLambdaAgent`), `muta_ext` (`Optimizer`), o `cli.py run
   --source X --tests Y -g N --max-evals E`. Anotar firma exacta y cómo pasar
   `max_evals`/budget.

**✅ GATE 0:** (a) lista D1/D2/D3 confirmada con líneas de código citadas; (b) smoke
"antes" guardado; (c) comando de invocación del optimizador real documentado en el
reporte de fase.

---

## ═══════════════════════════════════════════════════════════════════
# FASE 1 — Reparar el harness: MutaLambda real + etiquetas honestas (1–2 días)
## ═══════════════════════════════════════════════════════════════════

**Objetivo:** que la fila `mutalambda` ejecute el optimizador evolutivo real con
presupuesto E1, y que cada fila declare su tipo honesto.

### Tarea 1.1 — Runner real de MutaLambda
Crear `benchmarks/mutalambda_runner.py`:

```python
def mutalambda_optimize(task, max_evals: int, seed: int) -> str:
    """Ejecuta el optimizador real (MutaLambdaAgent/evolve) sobre task.seed_code()
    con max_evals y seed; devuelve el CÓDIGO del mejor individuo (no el score).
    Debe: fijar seed (rng_session), budget de evaluaciones, sin LLM salvo
    --llm explícito, y timeout por tarea."""
```

Puntos críticos:
- Presupuesto de evaluaciones medido por el propio motor (population × generations ≤
  `max_evals`, o el equivalente en HFC). Si el motor no soporta tope de evals,
  agregar el parámetro — es un requisito de equidad, no un feature.
- Contadores: `evals_used`, `wall_clock_total`, `cache_hit_rate` (usar
  `EvaluationEngine.cache_stats()`).
- El fitness de velocidad del motor NO se usa como métrica del leaderboard: el
  ranking se mide después con `EvaluationService` (E4 del protocolo), igual que
  todos los competidores.

### Tarea 1.2 — Registrar el runner en el harness
En `market_comparison_harness.py`:
- Rama `mutalambda`: llamar a `mutalambda_optimize(task, args.max_evals, seed)`.
- CLI nuevo: `--max-evals` (default 150), `--seeds` (default `42,43,44`),
  `--llm-budget` (opcional).
- Renombrar entradas: `copilot`/`codewhisperer` → eliminar del leaderboard o mover a
  sección `excluded_tools.md` (motivo: "no ejecutable sin credenciales; stub no
  representa al producto"). LLM endpoints → claves `llm-oneshot/<model>`.
- Registrar en cada record: `evals_used`, `llm_tokens`, `usd`, `seed`,
  `tool_version`.

### Tarea 1.3 — Tests de honestidad del harness
En `tests/test_market_comparison_harness.py`:
- `test_mutalambda_row_runs_optimizer`: con 1 tarea trivial y `max_evals=10`, la fila
  `mutalambda` produce código ≠ seed_code o registra 0 mejoras — pero **ejecuta el
  motor** (assert sobre `evals_used > 0`).
- `test_no_stub_rows_in_leaderboard`: `print_leaderboard` no acepta entradas con
  `backend=stub`.
- `test_budget_respected`: `evals_used ≤ max_evals`.

**✅ GATE 1:** smoke nuevo en verde con: MutaLambda real (evals_used>0), ≥1
`llm-oneshot` real o marcado DNF, cero stubs, y `pytest tests/test_market_comparison_harness.py` verde.

---

## ═══════════════════════════════════════════════════════════════════
# FASE 2 — Adaptadores de herramientas externas (2–3 días)
## ═══════════════════════════════════════════════════════════════════

**Objetivo:** cada competidor ejecutable expuesto con la MISMA interfaz, en su
propio entorno aislado. Un adaptador por herramienta en `benchmarks/adapters/`:

```python
class ToolAdapter(Protocol):
    name: str          # "shinka-evolve@<ver>"
    kind: str          # "evolutionary" | "gi" | "reference" | "llm-oneshot"
    def setup(self) -> None: ...          # instala/valida su entorno (uv venv o docker)
    def optimize(self, source: str, tests: list, budget: Budget, seed: int) -> ToolResult: ...
    # ToolResult: code | None, evals_used, llm_calls, tokens, usd, wall_clock, status
```

### Tarea 2.1 — PyGGI 2.0 (GI clásico, sin LLM) — empezar por este (más simple)
```bash
git clone https://github.com/coinse/pyggi.git tools/pyggi && cd tools/pyggi
python -m venv .venv && . .venv/bin/activate && pip install -e .
```
Adaptador: preparar repo de tarea (target.py + tests), fitness = tests pasan +
speedup, tope `max_evals`. Registrar `DNF` si su AST toolkit falla con Python 3.12.

### Tarea 2.2 — ShinkaEvolve (rival directo)
```bash
pip install shinka-evolve   # PyPI (Mar 2026: API ShinkaEvolveRunner)
```
- Usar `shinka_run`/Python API con `initial.py` = tarea, `evaluate.py` = tests+timing,
  presupuesto de evals equivalente a E1, mismo LLM backend que MutaLambda cuando se
  corra en modo LLM.
- Documentar en el adaptador la versión exacta (`pip show shinka-evolve`) para
  `manifest.json`.

### Tarea 2.3 — OpenEvolve
```bash
git clone https://github.com/codelion/openevolve.git tools/openevolve
```
- Configurar con el mismo LLM (E2) y `evaluation_budget`; usar su formato de
  `initial_program.py` + evaluator.

### Tarea 2.4 — Referencias deterministas (1 día, alto valor)
`adapters/reference_numba.py`, `adapters/reference_cython.py`, `adapters/reference_mypyc.py`:
transformaciones mecánicas (`@njit` en la función target; build Cython; compilar) que
preservan semántica. Son "upper bounds" contextuales, etiqueta `reference/*`.

### Tarea 2.5 — pymoo / DEAP (para FASE 6)
```bash
pip install pymoo deap
```

**✅ GATE 2:** cada adaptador pasa su smoke: `python -m benchmarks.adapters.<name> --selftest`
(1 tarea trivial, `max_evals=10`, devuelve código y contadores, o `DNF` con log).
Smoke debe correr SIN claves de API (modo local) y, con claves, probar el backend LLM una vez.

---

## ═══════════════════════════════════════════════════════════════════
# FASE 3 — Task sets congelados y métricas EffiBench-X (1 día)
## ═══════════════════════════════════════════════════════════════════

1. **EffiBench-X Python**: clonar `EffiBench/EffiBench-X`, cargar subset Python
   nativo con su sandbox/métricas (ET%, MP%, MI%). Implementar
   `benchmarks/effibench_x_loader.py` espejo de `effibench_loader.py`.
2. **EffiBench-Python (converted)**: filtrar tasks convertidas cuyo baseline pasa
   100% tests; congelar `benchmarks/fair_task_sets.json` (n=50 dev / n=100 reporte,
   `random.Random(42)`, `task_set_version: 1`).
3. **Suite AlphaEvolve**: portar los 9 problemas estándar (CirclePacking n=26/32,
   CirclePackingRect, HexagonPacking n=11/12, MinimizeMaxMinDist (16,2)/(14,3),
   First/SecondAutocorrIneq) como evaluadores Python puros con scoring idéntico al
   publicado (fuentes: paper AlphaEvolve 2025 + CodeEvolve arXiv:2510.14150 que
   re-corrió ShinkaEvolve/OpenEvolve con settings matched).
4. Estandarizar `Budget` dataclass (`max_evals`, `llm_model`, `token_cap`,
   `wall_clock_sec`, `seed`) en `benchmarks/fairness.py` — única fuente de verdad.

**✅ GATE 3:** `python -m benchmarks.fairness --check` valida: task sets cargan,
versiones registradas, y cada task del set pasa su baseline en EvaluationService.

---

## ═══════════════════════════════════════════════════════════════════
# FASE 4 — L1: corrida de eficiencia de código (2–4 días máquina)
## ═══════════════════════════════════════════════════════════════════

**Diseño:** herramientas × tasks(S1+S2) × seeds{42,43,44}, E1=150 evals, E4 idéntico.

Herramientas: `mutalambda`, `pyggi`, `shinka-evolve`, `openevolve`,
`llm-oneshot/<model>`, `reference/numba`, `reference/cython`.

```bash
python -m benchmarks.run_fair --leaderboard L1 --task-set effibench-py-v1 \
  --tools mutalambda pyggi shinka-evolve openevolve llm-oneshot reference \
  --max-evals 150 --seeds 42 43 44 --out benchmarks/results/fair/<fecha>/
```

Reglas de ejecución:
- Escritura incremental por task (patrón existente en `effibench_harness.py`).
- Orden de medición intercalado (canonical, candidato, canonical) para neutralizar
  deriva térmica de la máquina.
- Capturar `evals_used/tokens/usd/wall_clock` por task → `L1_efficiency.json`.
- Si una tool excede wall-clock E3 por task: `status=timeout`, conserva partials.

**✅ GATE 4:** JSON con ≥ 2 herramientas (incluida MutaLambda real) × ≥ 20 tasks × 3
seeds completos; `excluded_tasks.json` y `excluded_tools.md` al día; cero NaNs sin
explicación.

---

## ═══════════════════════════════════════════════════════════════════
# FASE 5 — L2: evolución algorítmica vs ShinkaEvolve/OpenEvolve/EoH (3–5 días)
## ═══════════════════════════════════════════════════════════════════

**Diseño:** suite AlphaEvolve (9 problemas) + EoH suite (OBP/TSP/FSSP ya en
`eoh_suite.py`), mismo LLM (E2), mismo `max_evals`, 3 seeds.

1. Implementar evaluadores MutaLambda de los 9 problemas (FASE 3.3) como
   `presets/bench_alphaevolve/*.py`.
2. Correr MutaLambda, ShinkaEvolve y OpenEvolve con idéntico presupuesto; exportar
   curvas best-so-far completas (score por eval) → `L2_algorithmic.json`.
3. Recopilar números publicados de AlphaEvolve/ThetaEvolve/CodeEvolve sobre la
   misma suite → tabla `published/` SEPARADA del leaderboard (norma §5 del
   protocolo).
4. Métricas: score final (mediana ± IQR), `auc_bsf`, evals hasta alcanzar el score
   publicado de AlphaEvolve (si se alcanza).

**✅ GATE 5:** curvas completas de ≥ 2 herramientas evolutivas en ≥ 6/9 problemas;
tabla `published/*` citada con paper+tabla exactos.

---

## ═══════════════════════════════════════════════════════════════════
# FASE 6 — L3: benchmark de motor vs pymoo/DEAP (1 día)
## ═══════════════════════════════════════════════════════════════════

Script `benchmarks/engine_benchmark.py`:
1. **Throughput:** NSGA-II una generación con N∈{50,100,200,500} — MutaLambda
   (`nsga2.py` numpy path) vs `pymoo.algorithms.moo.nsga2.NSGA2` vs DEAP — misma
   función objetivo sintética, 30 reps, reportar gens/sec y evals/sec.
2. **Calidad:** hypervolume en DTLZ2 (3 obj) tras 10k evals, 3 seeds, con
   `pymoo.indicators.hv`.
3. **Introspección MutaLambda:** `cache_stats()`, mejora con HFC on/off, islas 1 vs 6
   (ablation interna).

**✅ GATE 6:** `L3_engine.json` con las 3 filas y pendientes de escalabilidad; si
pymoo gana en algo, queda en la tabla (es información, no derrota).

---

## ═══════════════════════════════════════════════════════════════════
# FASE 7 — Estadística, leaderboard, actualización del proyecto y PR (1–2 días)
## ═══════════════════════════════════════════════════════════════════

### Tarea 7.1 — Análisis estadístico
`benchmarks/fair_stats.py`: mediana ± IQR por métrica, Mann–Whitney U MutaLambda vs
cada competidor, Cliff's delta, salida a `leaderboard.md` (formato §4 protocolo).

### Tarea 7.2 — Actualizar el proyecto (orden obligatorio)
1. `benchmarks/BENCHMARK_STRATEGY.md` — sustituir la sección "Market comparison" por
   resultado L1/L2/L3 real + enlace a `results/fair/<fecha>/leaderboard.md`.
2. `EMPIRICAL_EVIDENCE.md` — nueva sección "Fair Market Comparison (fecha)" con:
   hipótesis, setup (manifest), tablas, decisiones (ganado/paridad/perdido por
   métrica), comandos de reproducción. Filosofía del archivo: solo lo ejecutado.
3. `README.md` — badge/tabla de comparativa con la fecha y el link; SIN superlativos
   no respaldados ("mejor que X" solo con p<0.05, si no: "parity con X").
4. `AGENTS.md` — registrar la sección "Fair market comparison" con el comando
   canónico de re-ejecución.
5. `docs/METRICS.md` — añadir ET/MP/MI, speedup_per_eval, auc_bsf.
6. CHANGELOG.md — entrada nueva.

### Tarea 7.3 — PR
- Branch `feat/fair-market-comparison`, un commit por fase, body del PR con el
  leaderboard resumido y la tabla DNFs.
- CI debe pasar: `pytest tests/ -q` (incluye tests de FASE 1.3).

**✅ GATE 7 (Definition of Done):**
- [ ] Leaderboard L1 con ≥ 2 competidores REALES ejecutados + MutaLambda real.
- [ ] Cada fila: tool@versión, presupuesto, mediana ± IQR, p-valor vs MutaLambda.
- [ ] L2 con curvas best-so-far de ≥ 2 evolutivos + tabla published/ separada.
- [ ] L3 motor vs pymoo/DEAP.
- [ ] `manifest.json` completo (HW, versiones, git SHA).
- [ ] Cero stubs; DNFs documentados; excluded_tasks con motivo.
- [ ] README/EMPIRICAL_EVIDENCE/BENCHMARK_STRATEGY actualizados con números
      reproducibles (comando + artifacts).
- [ ] Tests de honestidad del harness en verde dentro de CI.

---

## 📎 APÉNDICE A — Matriz de esfuerzo/prioridad (si hay poco tiempo)

| Prioridad | Qué | Por qué |
|---|---|---|
| P0 | FASE 1 (harness honesto) | Sin esto, todo lo demás es decoración |
| P1 | FASE 4 con {mutalambda, pyggi, llm-oneshot, reference/numba} | Comparativa mínima creíble sin LLM budget compartido |
| P2 | FASE 2.2/2.3 + FASE 5 (ShinkaEvolve/OpenEvolve) | Head-to-head contra rivales directos |
| P3 | FASE 6 (pymoo/DEAP) y EffiBench-X | Diferenciación de motor y métricas de literatura |

## 📎 APÉNDICE B — Referencias

- ShinkaEvolve: Sakana AI, arXiv:2509.19349 · github.com/SakanaAI/ShinkaEvolve · PyPI `shinka-evolve`
- OpenEvolve: github.com/codelion/openevolve
- CodeEvolve (matched-settings vs OpenEvolve/ShinkaEvolve): arXiv:2510.14150 · github.com/inter-co/science-codeevolve
- EoH: Liu et al. · github.com/FeiLiu36/EoH
- PyGGI 2.0: github.com/coinse/pyggi (GI sin LLM)
- EffiBench: NeurIPS 2024 · HF `ktd-prime/EffiBench` (Java, conversiones propias)
- EffiBench-X: NeurIPS 2025 · github.com/EffiBench/EffiBench-X · HF `EffiBench/effibench-x`
- PIE: Performance-Improving Edits (dataset C++; síntesis Python etiquetada "PIE-pattern")
- AlphaEvolve suite: Novikov et al. 2025 (+ tabla comparativa re-corrida en CodeEvolve)
