# Plan de benchmarks publicables para MutaLambda

**Versión:** 1.0 · **Fecha:** 2026-09-04  
**Objetivo:** demostrar la calidad de las soluciones producidas por MutaLambda, no solamente la velocidad del motor evolutivo.

## 1. Qué debe demostrar MutaLambda

MutaLambda no es principalmente un compilador ni un modelo de generación de código. Es un **optimizador evolutivo asistido por agentes** que transforma una implementación existente y selecciona candidatos con varias señales. Por eso el resultado comercial debe responder, en este orden:

1. **¿Conserva el comportamiento?**
2. **¿Mejora la calidad de la solución?** (rendimiento, memoria, robustez y, cuando aplique, calidad numérica)
3. **¿Encuentra soluciones mejores que un baseline razonable?**
4. **¿Lo hace con un coste y tiempo aceptables?**

Un único `speedup` no prueba calidad: una implementación incorrecta puede parecer infinitamente rápida. La regla de publicación es: **ningún speedup se cuenta si no pasa el conjunto público y un conjunto oculto o generado fuera de muestra**.

## 2. Suite recomendada por prioridad

| Prioridad | Benchmark público | Encaje con MutaLambda | Métrica principal | Decisión |
|---|---|---|---|---|
| P0 | **EffiBench** | Optimización de implementaciones Python con referencia canónica | `ratio_to_canonical`, `correctness`, `opt_pct` | Mantener; ejecutar el dataset completo o declarar explícitamente el subconjunto |
| P0 | **PIE (Performance-Improving Edits)** | Ediciones que mejoran rendimiento en código competitivo | `%Opt`, speedup y corrección | Integrar los datos originales; el conjunto sintético actual solo es smoke test |
| P0 | **HumanEval+ y MBPP+** | Control de regresión funcional en Python | pass@1 / pass@k y tasa de regresión | Usar como prueba de preservación, no como prueba única de optimización |
| P1 | **LiveCodeBench** | Problemas recientes y menos expuestos a contaminación | pass@1, tests pasados y coste | Validar que la mejora generaliza a tareas fuera del conjunto de evolución |
| P1 | **DS-1000** | Código de ciencia de datos con NumPy/Pandas/SciPy | exactitud, tests y rendimiento | Muy buen diferenciador para calidad científica y casos reales |
| P1 | **SWE-bench Verified** | Cambios multiarchivo en repositorios reales | resolve rate y regresiones | Solo si se ofrece un modo de reparación de repositorio; no presentarlo como prueba directa del optimizador de funciones |
| P2 | **EoH / problemas de optimización combinatoria** | Encaja con la búsqueda evolutiva de heurísticas | gap al óptimo, factibilidad y coste | Mantener como demostración de descubrimiento de algoritmos; añadir instancias estándar y óptimos verificables |
| P2 | **pyperformance + PolyBench** | Micro y kernels numéricos | P50/P95, memoria, speedup | Benchmark de ingeniería del motor, no evidencia suficiente de calidad del resultado |

### Fuentes y versiones que deben congelarse

- EffiBench: registrar URL/commit, versión del dataset y licencia en cada reporte.
- PIE: usar el dataset y protocolo publicados; el archivo actual `benchmarks/pie_harness.py` contiene tareas representativas sintéticas y **no debe llamarse resultado PIE completo**.
- HumanEval+: <https://github.com/openai/human-eval> (usar la fuente oficial de HumanEval y el protocolo HumanEval+ de EvalPlus: <https://github.com/evalplus/evalplus>).
- MBPP+: <https://github.com/google-research/google-research/tree/master/mbpp> y EvalPlus.
- LiveCodeBench: <https://github.com/LiveCodeBench/LiveCodeBench>.
- DS-1000: <https://github.com/xlang-ai/DS-1000>.
- SWE-bench: <https://github.com/SWE-bench/SWE-bench>.
- PolyBench: <https://github.com/llvm-test-suite/polybench>.

> Nota: los nombres, commits, licencias y splits deben quedar en `metadata` del artefacto. No copiar datasets grandes al repositorio.

## 3. Protocolo experimental que sí es publicable

### Condiciones

- Congelar commit de MutaLambda, Python, OS, CPU/GPU, CUDA, dependencias, modelo y prompt.
- Semillas separadas para selección de tareas, evolución y evaluación.
- Separar `train/evolution`, `validation` y `test`; el test no puede entrar en prompts, memoria, cache semántica ni selección de hiperparámetros.
- Comparar exactamente el mismo presupuesto: tiempo de pared, número de evaluaciones, tokens/API, temperatura y número de intentos.
- Repetir cada configuración al menos 5 veces; informar mediana, media, desviación estándar e intervalo de confianza bootstrap del 95%.
- Ejecutar warm-up y medir P50/P95, memoria pico, energía si está disponible y coste monetario.

### Baselines mínimos

1. Implementación original/canónica sin cambios.
2. Compilador/intérprete y optimizaciones estándar (por ejemplo, CPython y `-O3` cuando aplique).
3. LLM directo con **el mismo modelo, prompt, presupuesto y tests**, sin evolución.
4. MutaLambda sin cada componente importante: sin memoria semántica, sin selección multiobjetivo, sin verificación reforzada y sin evolución de prompts.
5. Mejor resultado humano/oficial del dataset cuando exista.

No comparar contra “GitHub Copilot (stub)” o “CodeWhisperer (stub)” como si fueran productos reales. Si no existe una API pública reproducible, deben aparecer como `not_run`, nunca como un baseline con score 1.0.

## 4. Métricas: calidad primero

### Gate de corrección

- `functional_pass_rate`: proporción de tests pasados.
- `hidden_pass_rate`: proporción en tests ocultos/holdout.
- `regression_rate`: porcentaje de tareas donde el candidato rompe un caso que el baseline resolvía.
- `semantic_equivalence_rate`: equivalencia diferencial + propiedades/invariantes.
- Reportar intervalos binomiales; no redondear 100% cuando el número de casos sea pequeño.

### Calidad de solución

- `speedup = baseline_p50 / candidate_p50` solo con `correctness == 1.0`.
- `ratio_to_baseline = candidate_p50 / baseline_p50`.
- `memory_reduction_pct` y `p95_speedup`.
- Para optimización combinatoria: `feasibility_rate`, `optimality_gap`, `best_known_gap` y coste de evaluación.
- Para científica/numérica: error absoluto/relativo, conservación de invariantes y estabilidad; la tolerancia debe estar definida antes de ejecutar.
- `quality_score`: no mezclar en una cifra opaca. Publicar siempre el vector original (corrección, latencia, memoria, robustez y complejidad) y, si se usa un agregado, publicar pesos y análisis de sensibilidad.

### Descubrimiento y fiabilidad

- `improvement_rate`: tareas mejoradas tras el gate.
- `median_validated_speedup`: mediana entre mejoras válidas; acompañar de distribución.
- `time_to_first_valid_improvement`.
- `reproducibility_rate`: ejecuciones que repiten la conclusión bajo otra semilla.
- Coste por mejora válida y porcentaje de candidatos rechazados por corrección.

## 5. Comparación justa con el mercado

MutaLambda debe compararse como **sistema**, no como si fuese un modelo. La comparación recomendada tiene tres capas:

- **Motor:** MutaLambda frente a búsqueda local, mutación aleatoria y optimización estándar.
- **Agente/modelo:** mismo modelo subyacente con y sin MutaLambda.
- **Producto:** herramientas comerciales solo mediante una interfaz y presupuesto equivalentes, con fecha, versión y método de captura documentados.

La tabla comercial debe contener `tool`, `version/date`, `model`, `prompt`, `attempts`, `budget`, `tasks`, `pass_rate`, `validated_improvement_rate`, `median_speedup`, `cost`, `wall_time` y `raw_artifact_url`. Un score publicado por el proveedor es contexto, no una medición head-to-head.

## 6. Correcciones necesarias al estado actual

- El smoke test de EffiBench verifica la tubería, no demuestra rendimiento.
- La estrategia actual llama “PIE” a un conjunto que el propio harness describe como sintético: debe etiquetarse `PIE-representative` hasta incorporar los datos originales.
- `run_full_suite.py` usa una ruta fija (`/home/adlg/MutaLambda`) para Git; debe usar el root detectado desde el archivo o `Path.cwd()` antes de publicar reportes.
- El valor de cache `0.996` es un placeholder documentado en código; no debe figurar como medición de una ejecución real.
- `copilot_stub` y `codewhisperer_stub` devuelven la solución canónica; deben quedar fuera de rankings y marcarse `stub/not_run`.
- Los resultados existentes en `BENCHMARK_STRATEGY.md` deben distinguir `validated live`, `smoke`, `synthetic` y `reported/unverified`.

## 7. Paquete de evidencia para una release

Cada release de benchmark debe publicar:

```text
benchmark_manifest.json       # versiones, commits, hardware, seeds, licencia
results_raw.jsonl             # una fila por tarea y repetición
results_summary.json          # agregados y CI
baseline_config.json          # prompts, presupuesto y parámetros
ablations.json                # componentes activados/desactivados
reproduce.sh                  # comandos exactos, sin secretos
README.md                     # limitaciones y resultados
```

El README comercial debe mostrar primero: **corrección, regresiones, mejora validada y distribución**. El speedup medio sin estos datos no debe ser el titular.

## 8. Primer experimento aconsejado

Para obtener una cifra sólida rápidamente:

1. HumanEval+ y MBPP+: 164/974 tareas, split fijo, 5 repeticiones.
2. Para cada tarea, conservar la implementación original y producir una transformación MutaLambda con presupuesto fijo.
3. Validar con tests públicos más tests EvalPlus fuera del prompt.
4. Medir calidad funcional, regresiones, P50/P95 y memoria.
5. Repetir con el mismo modelo sin evolución y con búsqueda aleatoria.
6. Publicar el manifiesto y los artefactos crudos; no publicar solo el promedio.

Esto prueba la tesis central de MutaLambda: **mejores resultados preservando el comportamiento**, mientras EffiBench/PIE/pyperformance aportan después la evidencia específica de rendimiento.
