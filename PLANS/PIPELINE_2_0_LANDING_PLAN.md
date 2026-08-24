# Plan de Aterrizaje — MutaLambda 2.0 Workflow Empresarial/Científico

**Fecha:** 2026-08-24
**Estado:** IMPLEMENTADO (FASE 0–2 completadas) — ver criterios de aceptación por fase
**Origen:** Workflow propuesto "MutaLambda Optimization Pipeline" (6 fases: baseline → UAST → evolve → verify → benchmark → explain/publish)

## Estado de aceptación (criterios de las fases 0–2)

| Fase | Criterio de aceptación | Estado | Evidencia |
|---|---|---|---|
| FASE 0 | `actionlint` sin errores en ambos workflows; PR-gate corre en < 10 min; pipeline deshabilitada hasta FASE 3 | ✅ COMPLETADO | `.github/workflows/mutalambda-pr-gate.yml` + `mutalambda-optimization-pipeline.yml` validados con `actionlint` |
| FASE 1 | Cada fase apunta a un comando que existe y corre localmente; dry-run manual fases 1, 4, 5, 6 | ✅ COMPLETADO | `universal_parser.py`, `benchmarking.py`, `ast_math_verifier.py`, `property_testing.py`, `comparison.py`, `interpretability.py` cableados |
| FASE 2 | 5 CLIs con tests unitarios (`tests/test_pipeline_scripts.py`) y smoke E2E local | ✅ COMPLETADO | `universal_parser.py`, `invariant_detector.py`, `evolve.py`, `regression_gate.py`, `certify.py` — 37 tests passing; smoke E2E verificado |
| FASE 3 | Corrida completa de la pipeline por `workflow_dispatch` sobre kernel fixture (mes 3) | 🚧 PENDIENTE | Workflows creados; pendiente ejecución en CI |
| FASE 4 | Habilitar `schedule` semanal sobre kernels reales tras 3 corridas verdes | 🚧 PENDIENTE | `schedule` intencionalmente omitido hasta validar FASE 3 |

---

## 0. Diagnóstico de partida (evidencia en el repo)

| Elemento del workflow propuesto | Estado real en el repo |
|---|---|
| `mutalambda/benchmark.py` | ❌ No existe. Existe `benchmarking.py`, `bench_phase6.py`, `benchmarks/run_full_suite.py` |
| `mutalambda/universal_parser.py` | ❌ No existe. Existe `muta_ext/uast/adapters/` con parseo Python/Rust/C++ |
| `mutalambda/invariant_detector.py` | ❌ No existe |
| `mutalambda/evolve.py` | ❌ No existe. Existen `evolution_engine.py`, `hfc_tiers.py`, `checkpoint_manager.py` |
| `mutalambda/ast_math_verifier.py` | ✅ Existe (en raíz, no en `mutalambda/`) |
| `mutalambda/property_testing.py` | ✅ Existe (en raíz) |
| `mutalambda/smt_verify.py` | ❌ No existe (marcado no-bloqueante en el diseño, aceptable) |
| `mutalambda/certify.py` | ❌ No existe |
| `mutalambda/regression_gate.py` | ❌ No existe. Existe `muta_ext/ci_integration.py` con detección de regresiones (pero con medición dummy) |
| `mutalambda/interpretability.py` | ✅ Existe (en raíz) |
| Directorios `src/`, `kernels/`, `mutalambda/` | ❌ Ninguno existe — el fingerprint del job `baseline` fallaría |
| YAML del workflow | ❌ Roto: `steps:\`, entidades HTML (`&amp;`), fases 3–4 duplicadas, truncado al final |
| Islas "THC" vía matrix | ⚠️ 4 jobs independientes sin migración real; la migración de `hfc_tiers.py` es intra-proceso |
| Cache FAISS | ⚠️ Key basada en `github.sha` → nunca se reutiliza semánticamente |

**Conclusión:** el workflow es una especificación norte. ~70% de los scripts invocados no existen y la sintaxis YAML es inválida.

---

## 1. Principios del plan

1. **No se ejecuta nada de la pipeline hasta que la Fase 0 (YAML válido) pase `actionlint`/`yamllint` en seco.**
2. **Dividir para no bloquear:** un gate ligero por PR (segundos) y la pipeline pesada solo bajo `workflow_dispatch`/schedule.
3. **Reutilizar antes que crear:** cada fase del workflow se mapea primero a módulos existentes; solo se crea código nuevo donde no hay equivalente.
4. **Cada fase tiene criterio de aceptación medible** antes de pasar a la siguiente.
5. **Los paths del workflow se adaptan al repo real** (módulos en raíz), no se crea un paquete `mutalambda/` artificial.

---

## 2. Paquetes de trabajo — CÓMO / CUÁNDO / DÓNDE

### FASE 0 — Reparación sintáctica y división del workflow
**Cuándo:** Día 1–2 (prerrequisito de todo lo demás).

| Qué | Dónde | Cómo |
|---|---|---|
| Workflow ligero de PR | `.github/workflows/mutalambda-pr-gate.yml` | Nuevo archivo: lint + tests + smoke CLI (reutiliza la base de `python-package.yml`). Sin evolución, sin gate de mejora. |
| Pipeline pesada | `.github/workflows/mutalambda-optimization-pipeline.yml` | Nuevo archivo: solo `workflow_dispatch` + `schedule` semanal. Contiene las 6 fases del diseño. |
| Limpieza del texto propuesto | ambos archivos | Eliminar fases duplicadas/truncadas; convertir entidades HTML; arreglar `steps:\`; añadir `\` en las continuaciones de línea partidas (`--classes`, `--properties`, `--sections`). |
| Validación | CI local | `actionlint` + `yamllint` como paso de verificación antes del primer commit de workflows. |

**Criterio de aceptación:** `actionlint` sin errores; el PR-gate corre en < 10 min en un PR de prueba; la pipeline pesada es parseable y queda deshabilitada (`workflow_dispatch` únicamente) hasta la Fase 3.

---

### FASE 1 — Cableado de fases del workflow a módulos existentes
**Cuándo:** Semana 1 (días 3–7).

| Fase del workflow | Módulo real a usar | Dónde está | Qué ajustar |
|---|---|---|---|
| Fase 1 (fingerprint) | `code_hash.py` + `api_fingerprint.py` | raíz | Reemplazar `find src kernels` (directorios inexistentes) por fingerprint sobre los paths reales del repo; salida JSON en vez de solo sha256. |
| Fase 1 (baseline) | `benchmarking.py` + `benchmarks/run_full_suite.py` | raíz, `benchmarks/` | Añadir modo `--mode baseline --output reports/baseline.json` si falta; definir subconjunto rápido (< 15 min) para CI. |
| Fase 3 (evolución) | `evolution_engine.py` + `hfc_tiers.py` + `checkpoint_manager.py` | raíz | Envolver en un CLI único (ver Fase 2) en vez de invocar 3 módulos. |
| Fase 4 (verificación) | `ast_math_verifier.py` + `property_testing.py` | raíz | Alinear flags del workflow con los CLI reales; documentar el contrato `invariants.lock`. |
| Fase 5 (comparación) | `comparison.py` + `benchmarking.py` | raíz | Añadir test Mann-Whitney U (scipy) y salida `comparison.json` con campos que el gate consumirá. |
| Fase 6 (explicabilidad) | `interpretability.py` | raíz | Añadir export SARIF y resumen markdown para el comentario de PR. |

**Criterio de aceptación:** cada fase del workflow apunta a un comando que existe y corre localmente; dry-run manual de las fases 1, 4, 5 y 6 con fixtures.

---

### FASE 2 — Módulos faltantes (los 5 imprescindibles)
**Cuándo:** Semana 2 (días 8–14). Cada uno como script en la raíz (convención del repo), delgado sobre el motor existente:

| Módulo nuevo | Dónde | Cómo (sobre qué se construye) | Esfuerzo |
|---|---|---|---|
| `universal_parser.py` | raíz | Wrapper CLI de `muta_ext/uast/adapters.get_adapter()` → emite `uast.json`. Soporte inicial: python, rust, cpp (los 3 con adapter+emitter). | S |
| `invariant_detector.py` | raíz | Análisis estático sobre CoreUAST: constantes físicas (dict de valores CODATA), identidades matemáticas (registry), precisión numérica (tolerancias por tipo), propiedades criptográficas (solo detección de patrones, marcado best-effort). Salida: `invariants.lock` versionado (JSON + hash). | M |
| `evolve.py` | raíz | CLI unificador: recibe `--uast --profile --fitness --constraints --generations --population --hfc-tiers --checkpoint-every`; orquesta `evolution_engine` + `hfc_tiers` + `checkpoint_manager`. Perfiles: `enterprise` (latencia/memoria), `scientific` (estabilidad numérica + velocidad), `gpu` (placeholder documentado). | M |
| `regression_gate.py` | raíz | Consume `comparison.json`, aplica `--min-improvement-pct` / `--max-regression-pct`, exit code 0/1. **Ojo:** en la pipeline pesada se mantiene estricto; en el PR-gate solo anota, nunca bloquea. | S |
| `certify.py` | raíz | Genera certificado JSON: hashes de baseline/optimizado, invariantes verificados, seed, config, firma (si `--sign`: HMAC con secret de CI, NO claves asimétricas en esta fase). | S |

**Explícitamente fuera de alcance (Fase 4+):** `smt_verify.py` (Z3) — el diseño original ya lo marca `continue-on-error`; se implementa solo cuando el detector de invariantes produzca fórmulas cerradas verificables.

**Criterio de aceptación:** los 5 CLIs tienen tests unitarios (`tests/test_pipeline_scripts.py`) y un smoke E2E local: parse → detect → evolve (2 gen, pop 10) → verify → gate, sobre una función fixture.

---

### FASE 3 — Corregir la mecánica distribuida (islas, artefactos, caché)
**Cuándo:** Semana 3 (días 15–21).

| Problema | Solución | Dónde |
|---|---|---|
| Islas sin migración real | **Decisión: islas intra-job.** Un solo job `evolve` ejecuta `evolve.py --islands 4` con migración real vía `hfc_tiers` (intra-proceso). El matrix de GitHub se elimina — no aporta migración y cuadruplica costo. | `evolve.py` + workflow |
| Artefactos desconectados | Contrato explícito de artefactos: `uast-invariants` (fase 2) descargado en fases 3 y 4; `baseline-<hash>` descargado en fase 5; paso nuevo `select-best` tras la evolución que produce `.mutalambda/checkpoints/best/`. | workflow, sección de artifacts |
| Caché FAISS inútil (key = sha del commit) | Key = hash del contenido de las fuentes parseadas + versión del schema UAST: `mutalambda-uast-{{ hashFiles('...') }}-v1`. | workflow, `env.CACHE_KEY` |
| Webhook puede marcar fallido el job | `continue-on-error: true` + guarda `if: env.MUTALAMBDA_WEBHOOK_URL != ''`. | fase 6 del workflow |
| Auto-tag con colisión | Tag `optimized-${{ github.run_id }}` + anotación del %; `git push --no-verify` con check de existencia previa. | fase 6 del workflow |
| Métricas de energía | `energy_est` se declara **estimación proxy** (operaciones × costo modelo) en la doc; `energy_joules_per_op` solo se reporta en runners/self-hosted con RAPL, nunca en ubuntu-latest. | doc + `benchmarking.py` |

**Criterio de aceptación:** corrida completa de la pipeline por `workflow_dispatch` sobre un kernel fixture de `examples/`, con todos los artefactos subidos y el certificado generado.

---

### FASE 4 — Endurecimiento y habilitación
**Cuándo:** Semana 4+ (condicional a que la Fase 3 pase 3 corridas verdes consecutivas).

- Habilitar `schedule` semanal (domingo 02:00 UTC) sobre los kernels reales del repo.
- `retention-days: 90` para certificados/baselines (compliance), 7 días para checkpoints.
- Documentar el protocolo de falsos positivos del gate (runbook en `docs/`).
- Opcional: `smt_verify.py` con Z3 para identidades algebraicas simples.

---

## 3. Análisis: ¿expandir a más lenguajes/funciones por sector?

### 3.1 Estado actual verificado en el repo

| Lenguaje | Adapter | Emitter | Handler | Tests | Madurez |
|---|---|---|---|---|---|
| Python | ✅ | ✅ | ✅ | ✅ suite completa | **Alta** |
| Rust | ✅ tree-sitter | ✅ | ✅ (compila y prueba) | ✅ `test_rust_adapter.py` | **Media-alta** |
| C++ | ✅ tree-sitter | ✅ | ✅ (compila y prueba) | ✅ `test_cpp_adapter.py` | **Media-alta** |
| Go | — (handler + tests) | ❓ | ✅ `go_handler.py` | ✅ `test_go_support.py` | **Media-baja** |
| Java / C# / Fortran / CUDA / C | ❌ | ❌ | ❌ | ❌ | Nula |

### 3.2 Análisis por sector objetivo

**🏦 Financiero (trading, riesgo, pricing)**
- *Lenguajes:* C++ y Rust (hot paths), Python como origen a transpilar (research quant → producción). Java en plataformas de riesgo de bancos.
- *Invariante crítico:* **exactitud numérica no negociable** — un optimizador que cambia redondeo IEEE-754 o reordena operaciones flotantes puede violar compliance (MiFID II, Basel). El `invariant_detector` necesita una clase `financial_precision` (no solo `numerical_precision`): orden de sumas, modo de redondeo, uso de decimal vs float.
- *Funciones de alto valor:* bucles de pricing/montecarlo (vectorización, SoA), cero asignaciones en hot path, eliminación de dispatch virtual.
- *Veredicto:* **Prioridad ALTA y es el fit natural del repo** — Python→C++/Rust ya está 80% construido. Requiere tests de bit-exactness antes de habilitar el modo estricto.

**🔬 Científico (HPC, simulación)**
- *Lenguajes:* C++ (ya soportado), CUDA/GPU, Fortran (código legado masivo), Julia.
- *Invariante crítico:* leyes de conservación (energía, masa) y estabilidad numérica — el workflow ya contempla `physical_constants` y el repo tiene `muta_ext/scientific/` y `parallel_for_mutator` (paralelización de bucles ya pensada para esto).
- *Veredicto:* **Prioridad ALTA.** CUDA en Fase 2 de expansión: optimizar kernels GPU manualmente es carísimo y el ROI de automatizarlo es el mayor de todos los sectores. Fortran: demanda real pero parser/emitter costosos; posponer hasta tener evidencia de usuarios.

**🏭 Industrial (manufactura, embebido, automotriz)**
- *Lenguajes:* **C** (no C++) es el dominante en embebido/automotriz.
- *Invariante crítico:* no solo latencia media sino **WCET** (worst-case execution time) y cero asignación dinámica en rutas críticas; cumplimiento MISRA en automotriz.
- *Veredicto:* **Prioridad MEDIA-ALTA y barata** — un adapter C se deriva casi gratis del de C++ (gramáticas tree-sitter hermanas, mismo emitter con flags `-std`). Añadir métrica `wcet_estimate` (análisis de peor ruta, no estadística).

**🏢 Corporativo (microservicios, plataformas)**
- *Lenguajes:* Java, C#, Go (handler ya existe), TypeScript/Node.
- *Problema estructural:* la fitness es difícil de medir bien en JVM/CLR (JIT, GC) — exige protocolo de warmup y benchmarks estabilizados, o se generan falsas regresiones. Go ya está parcialmente soportado pero su cuello de botella típico es concurrencia/I/O, no cómputo puro, donde MutaLambda aporta menos.
- *Veredicto:* **Prioridad MEDIA-BAJA.** Consolidar Go (completar emitter si falta) antes que Java/C#. TypeScript solo tendría sentido con métrica de cold-start serverless, nicho estrecho.

### 3.3 Recomendación priorizada

| Ola | Cuándo | Lenguajes | Sector | Justificación |
|---|---|---|---|---|
| **Ola 1** | Tras Fase 3 (mes 2) | Consolidar C++ y Rust + bit-exactness para float | Financiero + Científico | Ya existe ~80%; mayor ROI inmediato |
| **Ola 2** | Mes 2–3 | **C** (derivado del adapter C++) + métrica WCET | Industrial | Costo bajo, mercado enorme (automotriz/embebido) |
| **Ola 3** | Mes 3–4 | CUDA (kernels GPU) + perfil `gpu` del workflow | Científico | Mayor valor por dólar automatizado; perfila hardware self-hosted |
| **Ola 4** | Mes 4+ | Go (completar) y evaluar Java con protocolo JIT-aware | Corporativo/Financiero | Solo si hay demanda concreta; medir calidad de fitness primero |
| **No hacer** | — | Fortran, TypeScript, C#, Julia (por ahora) | — | Costo de parser/emitter sin demanda validada |

### 3.4 Condición transversal para cualquier lenguaje nuevo

Un lenguaje solo entra cuando cumple las **4 puertas** (lección del `ci_integration.py` actual, que tiene medición dummy):
1. Adapter + emitter con tests que compilan y ejecutan código emitido.
2. Medición de fitness **real** (no stubs) reproducible con coeficiente de variación < 5%.
3. Clase de invariantes específica del sector registrada en `invariant_detector`.
4. Al menos 3 benchmarks de referencia del sector con resultados publicables (evita el problema de auditoría que el propio README admite hoy).

---

## 4. Riesgos del plan

| Riesgo | Mitigación |
|---|---|
| La pipeline pesada consume muchos minutos de CI (4 islas × 120 min) | Islas intra-job (Fase 3) + `workflow_dispatch` exclusivo hasta Fase 4 |
| Falsos positivos del gate de regresión bloquean desarrollo | Gate estricto solo en la pipeline; PR-gate nunca bloquea por mejora |
| `invariant_detector` incompleto da falsa sensación de seguridad | Documentar cobertura real por clase de invariante; Z3 queda explícitamente fuera hasta madurar |
| Bit-exactness flotante imposible con reorden de operaciones | Clase `financial_precision` que prohíbe mutaciones de reorden aritmético en perfil financiero |

---

## 5. Resumen ejecutivo

- **Cómo:** reparar YAML → dividir en 2 workflows → cablear fases a módulos existentes → crear 5 CLIs delgados → corregir islas/artefactos/caché → habilitar.
- **Cuándo:** ~4 semanas hasta la primera corrida completa verde (Fase 0: 2 días; Fase 1: semana 1; Fase 2: semana 2; Fase 3: semana 3; Fase 4: semana 4+). Expansión de lenguajes: mes 2 en adelante, por olas.
- **Dónde:** workflows en `.github/workflows/` (2 archivos nuevos, ninguno de los existentes se toca), CLIs nuevos en la raíz siguiendo la convención del repo, nada dentro de un paquete `mutalambda/` artificial.
- **Expansión multi-lenguaje:** sí conviene, pero priorizada — C++/Rust (financiero+científico) primero, C industrial segundo, CUDA tercero; Java/C#/Go corporativos solo con demanda validada. Todo lenguaje nuevo pasa por las 4 puertas de calidad para no repetir el error de la medición dummy actual.
