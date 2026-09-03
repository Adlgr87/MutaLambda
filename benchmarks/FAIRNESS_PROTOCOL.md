# Protocolo de Comparación Justa (Fairness Protocol)

> **Regla maestra:** misma tarea, mismo presupuesto, mismo harness, misma máquina,
> mismo LLM. Si alguna de las cinco cambia, la fila no entra al leaderboard.
> Documento normativo para `PLANS/MARKET_COMPARISON_WORKFLOW.md` y todo harness bajo
> `benchmarks/`.

## 1. Ejes de equidad (presupuestos)

| Eje | Definición | Valor por defecto |
|---|---|---|
| **E1. Presupuesto de evaluaciones** (PRIMARIO) | Nº de ejecuciones de programa (fitness evaluations) que la herramienta puede gastar por tarea | **150** (escala ShinkaEvolve; configurable `--max-evals`) |
| **E2. Presupuesto LLM** | Mismo backend+modelo, mismo tope de tokens por tarea para TODAS las herramientas evolutivas | p. ej. `gemini-2.5-flash` o modelo local Ollama, tope 300k tokens/tarea |
| **E3. Presupuesto wall-clock** (SECUNDARIO, informativo) | Tiempo máximo por tarea; se REPORTA, no se iguala | 30 min/tarea |
| **E4. Medición** | TODO candidato se mide con `EvaluationService` de MutaLambda: samples=7, warmups=2, timeout=10 s, memory cap 512 MB | idéntico para todos |
| **E5. Entorno** | Misma máquina (CPU model + núcleos + RAM registrados), cada herramienta en su venv/Docker propio, seeds fijas {42, 43, 44} (5 recomendado para publicación) | — |

**Justificación del eje primario:** igualar evaluaciones es lo único que hace
comparables a un motor con LLM (1 eval ≈ 1 llamada cara) y uno sin LLM (PyGGI,
evals gratis) sin beneficiar a ninguno. El costo (tokens/USD/llamadas) se registra
para las métricas de eficiencia, no se iguala.

## 2. Métricas objetivas

### 2.1 Calidad del resultado (L1 — eficiencia de código)

| Métrica | Fórmula | Notas |
|---|---|---|
| `correctness` | tests_pasados / total | Solo si = 1.0 computa speedup |
| `ratio_to_canonical` | P50_candidato / P50_canónico | P50 de 7 samples tras 2 warmups |
| `speedup_x` | 1 / ratio_to_canonical | Mediana sobre seeds |
| `%opt` (opt rate) | tareas con ratio ≤ 0.95 / tareas válidas | Umbral: mejora ≥ 5 % |
| `mem_ratio` | peak_mem_candidato / peak_mem_canónico | Reportar siempre |
| `ET% / MP% / MI%` | Estilo EffiBench-X: pass-rate de tiempo / memoria / ambos vs canónico | Adoptar definiciones oficiales de EffiBench-X para comparar con literatura |
| `auc_bsf` | Área bajo curva best-so-far (score vs #evals) | Mide velocidad de convergencia, no solo punto final |

### 2.2 Costo y ejecución (todas las categorías)

| Métrica | Definición |
|---|---|
| `wall_clock_total` | Tiempo total de la herramienta por tarea (excluye medición del harness) |
| `llm_calls`, `tokens_in`, `tokens_out`, `usd` | Contadores por tarea |
| `evals_used` | Evaluaciones realmente gastadas (≤ presupuesto E1) |
| `evals_per_sec` | Throughput del motor |
| `cache_hit_rate` | Hit-rate de fitness cache (introspección propia) |
| `cpu_peak`, `ram_peak` | Uso de recursos del proceso herramienta |

### 2.3 Eficiencia muestral y económica

| Métrica | Fórmula | Significado |
|---|---|---|
| `speedup_per_eval` | speedup_x / evals_used | Qué tan barato logra la mejora |
| `speedup_per_usd` | speedup_x / USD gastado | Costo-eficiencia (solo herramientas con LLM) |

### 2.4 Motor (L3 — pymoo/DEAP)

| Métrica | Setup |
|---|---|
| `gens_per_sec` | NSGA-II con población N ∈ {50, 100, 200, 500} sobre función objetivo sintética fija |
| `evals_per_sec` | Evaluaciones de fitness/seg en el mismo setup |
| `hypervolume` | DTLZ2 (3 objetivos) tras 10k evals, referencia pymoo `get_reference_directions` — comparar MutaLambda vs pymoo NSGA-II vs DEAP NSGA-II |
| `scaling_slope` | Pendiente gens/sec vs N en log-log |

## 3. Protocolo estadístico

1. **Seeds:** mínimo 3 ({42,43,44}), 5 para resultados publicables.
2. **Reporte central:** mediana ± IQR (robusto a outliers de timing).
3. **Significancia:** Mann–Whitney U (`scipy.stats.mannwhitneyu`) entre MutaLambda y
   cada competidor por métrica; declarar "mejor" solo con p < 0.05.
4. **Tamaño de efecto:** Cliff's delta (pequeño ≥0.147, medio ≥0.33, grande ≥0.474).
5. **Empate técnico:** si p ≥ 0.05, reportar "parity" — no ordenar por diferencias no
   significativas.
6. **Outliers:** si el baseline de una tarea falla o el P50 canónico es < 1 ms, la
   tarea se excluye del leaderboard y se lista en `excluded_tasks` con motivo.

## 4. Formato de artefactos (auditable)

```
benchmarks/results/fair/<fecha>/
├── manifest.json          # git SHA, HW (cpu, cores, ram), python, versiones de CADA tool
├── L1_efficiency.json     # por herramienta × tarea × seed: métricas §2.1–2.3 crudas
├── L2_algorithmic.json    # score best-so-far por eval (curvas completas)
├── L3_engine.json         # gens/sec, hypervolume, escalabilidad
├── leaderboard.md         # tablas finales con mediana ± IQR y p-valores
└── excluded_tasks.json    # tareas excluidas + motivo
```

- Escritura **incremental** (tras cada tarea) — patrón ya existente en
  `effibench_harness.py` (sobrevive a timeouts).
- `manifest.json` obligatorio: sin él, la corrida no es citable en
  `EMPIRICAL_EVIDENCE.md`.
- DNF: `{ "status": "DNF", "reason": "...", "install_cmd": "...", "log": "path" }`.

## 5. Reglas de etiquetado del leaderboard

| Tipo de fila | Etiqueta obligatoria | Ejemplo |
|---|---|---|
| Herramienta ejecutada con presupuesto | `tool@version` | `shinka-evolve@0.4.x` |
| LLM una pasada | `llm-oneshot/<model>` | `llm-oneshot/gpt-5-mini` |
| Referencia determinista | `reference/<tech>` | `reference/numba-njit` |
| Número publicado (no ejecutado) | `published/<paper>` — sección separada | `published/alphaevolve-2025` |
| Stub / no disponible | **NO ENTRA** — va a `excluded_tools.md` | ~~copilot (stub)~~ |

## 6. Muestreo determinista de tareas

- EffiBench-Python (convertidas): filtrar por baseline correcto, ordenar por
  `problem_idx`, muestrear con `random.Random(42).sample(...)` → lista de IDs
  congelada en `benchmarks/fair_task_sets.json` (n=50 para desarrollo, n=100 para
  reporte).
- EffiBench-X: usar el split Python oficial sin remuestreo.
- Suite AlphaEvolve: los 9 problemas estándar (P1–P4 de CodeEvolve/AlphaEvolve) con
  sus instancias publicadas.
- Cambiar un task set = bump de versión del JSON (`task_set_version`) para no
  comparar corridas históricas contra sets distintos.
