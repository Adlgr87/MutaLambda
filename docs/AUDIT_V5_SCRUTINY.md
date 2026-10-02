# Recorrido de escrutinio, limpieza y verificación — MutaLambda v5

**Rama:** `arena/01a0fbac-mutalambda`
**Commit base:** `3141a99`
**Fecha:** 2026-10-02
**Método:** línea base primero → lotes pequeños → verificación entre lotes → commit atómico.

---

## 0. Corrección de premisas del encargo

El encargo describía un repositorio que ya no existe. Se verificó contra el código real
antes de tocar nada:

| Premisa del encargo | Realidad medida |
|---|---|
| «v4.0.0 declarada» | `pyproject.toml` → **5.0.0** |
| «~40 módulos sueltos en la raíz, layout plano» | Migración **ya hecha**: 8 paquetes y **21 de los 71 módulos raíz son shims** con `DeprecationWarning` |
| «`dashboard.py` hace `append(best_score)` sin definir `best_score`» | **Ya corregido**; `record_generation` puebla `island_bests` y `diversity` correctamente |
| «umbral msgpack 2000 vs 256» | Solo existe **256**, coherente con su comentario. Sin deriva |
| «`island.py` vs `island_evolution.py` duplicados» | **No lo son**: `Island` (entidad) vs `IslandPool` (coordinador paralelo) |
| «`tests/uast/` y `tests/uast2/` duplicados» | **No lo son**: prueban `muta_ext.uast` (v1) y `muta_ext.uast2` (v2), motores distintos |
| «`dashboard_run.py` launcher de 2 líneas» | Es una **app Streamlit distinta** (inspector post-mortem), 135 líneas |
| «`app.py`, `muta_lambda.py` entry points» | **No existen**. Único entry point: `mutalambda_cli:cli` |
| «`index.js` de ~106 bytes, ¿basura?» | **Confirmado basura** → eliminado (ver §3) |
| «falta `pandas` en `[dashboard]`» | **Confirmado** → corregido |

---

## 1. Línea base vs final

| Métrica | ANTES (`3141a99`) | DESPUÉS | Δ |
|---|---|---|---|
| Ficheros versionados | 426 | 427 | +1 |
| Ficheros `.py` | 347 | 349 | +2 (−1 borrado, +3 tests) |
| LOC `.py` total | 73 786 | 74 510 | +724 |
| LOC producción (sin `tests/`) | 57 716 | 57 940 | +224 |
| LOC tests | 16 070 | 16 570 | +500 |
| **Tests recolectados** | 1123 | 1177 | **+54** |
| **Tests pasando** (`-m "not e2e"`) | **1070 ✅ / 1 ❌** | **1125 ✅ / 0 ❌** | **+55, −1 fallo** |
| Tests skipped | 22 | 22 | = |
| Módulos que importan (`py-modules`+`packages`) | 89/89 | 88/88 | −1 (paquete vacío borrado) |
| ruff clase `F` (bugs reales) | 452 | 151 | **−301** |
| · F401 imports sin usar | 372 | 79 | −293 |
| · F811 redefiniciones | 7 | 4 | −3 |
| Errores de colección pytest | 0* | 0 | = |
| Sentencias medidas por coverage | 10 617 | 15 811 | **+5194** (4 paquetes antes invisibles) |
| Cobertura global | 60 % (parcial) | **64 %** (real) | medida honesta |

\* requiere los extras `uast` instalados; sin ellos la base daba 6 errores de colección.

**Verificación final (entorno limpio, `python -m venv` + `pip install -e ".[cli,dashboard,uast,dev]"`):**

```
pip install -e .            → OK (exit 0)
mutalambda --version        → MutaLambda, version 5.0.0   (desde fuera del repo)
import_all.py               → OK=88 FAIL=0
pytest -q -m "not e2e"      → 1125 passed, 22 skipped, 0 failed
smoke_all.sh                → ALL GREEN
```

---

## 2. Desperfectos corregidos (categoría A)

| # | Ubicación | Qué estaba mal | Corrección |
|---|---|---|---|
| A1 | `muta_ext/uast/mutators/scientific/loop_transforms.py`, `vectorization.py` | `name = "loop_fusion"` (atributo) y `def name(self): return self.name` (método) se **tapaban mutuamente**: el método ganaba, y devolvía **el propio método ligado**, no el identificador. Afectaba a `LoopFusionMutator`, `LoopFissionMutator`, `SafeVectorizationMutator` | Patrón `_name` + `return self._name`, igual que los dos mutadores que sí funcionaban. Test de regresión sobre los 5 |
| A2 | `lsp/server.py::main()` | `asyncio.sleep(0.1)` fuera de un event loop: solo construye una corrutina nunca esperada → **bucle a 100 % CPU** y `RuntimeWarning` | `time.sleep(0.1)` + manejo de `KeyboardInterrupt` |
| A3 | `lsp/server.py::_handle_initialize` | Anunciaba `codeActionProvider`, `inlayHintProvider`, `hoverProvider`, `completionProvider` **sin handler**: cualquier cliente que los invocara **se colgaba para siempre** | Handlers mínimos conformes + respuesta `null` genérica a cualquier *request* desconocida |
| A4 | `lsp/server.py::_run_server`/`_send` | Solo hablaba JSON por líneas; **todo cliente LSP real usa `Content-Length`** → ningún editor podía completar `initialize` | Lectura que acepta ambos formatos; escritura con framing LSP por defecto (`--framing line` conserva el antiguo) |
| A5 | `lsp/server.py::_handle_message` | `except json.JSONDecodeError: pass` — tramas corruptas desaparecían sin rastro | Se registran con `log.warning` |
| A6 | `runners.py` | `from dataclasses import dataclass` **duplicado** (líneas 26 y 67); `import math` sin uso | Eliminados. Los re-exports `compare_values`/`stable_code_hash` se **conservan** con `# noqa` y comentario (ver §4) |
| A7 | `muta_ext/uast/adapters/go_adapter.py` | Atributo de clase `language = "go"` siempre tapado por la `@property language` | Atributo muerto eliminado, comentario explicativo |
| A8 | `cli/entrypoints.py:253` | `agent_kwargs = {"config": config}` construido y **nunca usado** | Eliminado |
| A9 | `mutalambda_core/component_evolution.py:322` | Bucle `for … if … pass` completamente no-op + `extracted_code` sin usar | Sustituido por un comentario que explica la intención real |
| A10 | `llm_backend._estimate_tokens` | Test auto-contradictorio: exigía `_estimate_tokens("") == 1` cuando el código (correctamente) devuelve 0 | Se corrigió el **test**, no el código: facturar un token fantasma a una completion vacía sería un error de coste. Docstring aclarado |
| A11 | `dashboard_run.py` | `import streamlit as st` y después `if st is None: raise ImportError` — rama **inalcanzable** | `try/except ImportError` real con mensaje útil |
| A12 | `dashboard_run.py` | Renderizaba la página **en tiempo de import**; `st.stop()` (cuando no hay runs) hacía que `import dashboard_run` **reventara**. Detectado por la verificación en entorno limpio, no por la suite | Cuerpo movido a `main()` bajo `if __name__ == "__main__"`. `streamlit run` se comporta igual (Streamlit ejecuta como `__main__`) |
| A13 | `tests/conftest.py`, `tests/test_nsga2.py`, `bench_phase6.py` | Importaban los shims raíz deprecados → la propia suite emitía `DeprecationWarning` | Migrados a las rutas canónicas |

### Deriva docstring ↔ código corregida

| Ubicación | Decía | Realidad |
|---|---|---|
| `mutalambda_cli.py` | `python cli.py run …` | El fichero es `mutalambda_cli.py` y el comando instalado es `mutalambda` |
| `dashboard.py` | «`dashboard_run.py` is the launcher» | Es un inspector post-mortem independiente |
| `dashboard_run.py` | «Run `muta_lambda quick …`» | El comando es `mutalambda quick` |
| `mutalambda_config/muta_config.py` | «`llm.enabled`: Dead field - has NO effect» | **Sí tiene efecto**: gatea `mutalambda generate-mutator` (`cli/main.py:794`) |
| `dashboard.py::DashboardState` | «Thread-safe accumulators» | No tenía ningún lock → se **implementó** la promesa (ver §6) |

---

## 3. Registro de eliminaciones

| Elemento | Cat. | Ubicación | Evidencia de cero referencias | Commit |
|---|---|---|---|---|
| Paquete `muta_ext/uast/emitter/` | C | `muta_ext/uast/emitter/__init__.py` | **(1)** Grep en `.py/.js/.json/.md/.toml/.yml`: única referencia era su propia entrada en `pyproject packages`. **(2)** No es API pública: `__all__ = []`, cero nombres públicos (`dir()` → solo `annotations`). **(3)** Ningún test lo usa; todos usan `emitters` (plural). **(4)** No aparece en checkpoints/artifacts/FAISS. **(5)** Post-borrado: 88/88 imports, suite verde. **(6)** Lote propio | `chore(C/D)` |
| `lsp/extensions/vscode/index.js` | C | extensión VSCode | **(1)** Grep global: cero referencias; `package.json main` apuntaba a `./dist/extension.js`. **(2)** No es entry point resoluble por nadie. **(3)** Sin tests. **(4)** N/A. **(5)** La extensión no podía cargar ni antes ni después; ahora sí. **(6)** Lote propio | `fix(E.3)` |
| 286 imports sin usar en 113 ficheros | D | repo | Clasificador `.audit/safe_f401.py`: se acepta un hallazgo **solo si** el módulo no define `__all__`, no es `__init__.py`, nadie hace `from X import *` sobre él y **nadie** hace `from <módulo> import <nombre>`. 66 hallazgos que fallaron algún criterio → intactos | `chore(C/D)` |
| Entrada `"muta_ext.uast.emitter"` | D | `pyproject.toml` | Acompaña al borrado del paquete | `chore(C/D)` |
| Variables muertas: `agent_kwargs`, `extracted_code`, `exc` | D | `cli/entrypoints.py`, `mutalambda_core/component_evolution.py` | ruff F841 + inspección manual | `fix(A)` |
| `import math`, `from dataclasses import dataclass` (dup.) | D | `runners.py` | `math` solo se usa dentro de una plantilla de harness que tiene su propio `import math` | `fix(A)` |
| Script `compile: tsc -p ./` | D | `lsp/.../package.json` | Sin ficheros `.ts` ni `tsconfig.json` en el repo: nunca pudo ejecutarse | `fix(E.3)` |

**Basura de categoría D ya controlada:** `__pycache__/`, `.pytest_cache/`, `checkpoints/`,
`reports/`, `*.egg-info/` existen en el árbol de trabajo pero **ninguno está versionado**
(`git ls-files` limpio) y `.gitignore` ya los cubría. Se añadió solo `.audit/`.

---

## 4. Candidatos descartados — `[MANTENER — en uso]`

Lo que parecía basura pero tenía una referencia que obliga a conservarlo:

| Elemento | Por qué parecía muerto | Por qué se mantiene |
|---|---|---|
| `runners.py` → `compare_values`, `stable_code_hash`, `COMPARATORS`, `register_predicate` | ruff F401: importados y nunca usados en `runners.py` | **`sandbox.py:35` hace `from runners import compare_values, stable_code_hash`**. Son re-exports deliberados. Marcados con `# noqa: F401` y comentario |
| Los 21 shims raíz (`nsga2.py`, `archive.py`, `constants.py`, …) | Ningún módulo interno los importa ya | **API pública**: están en `py-modules`, documentados en `README`/`AGENTS.md`/`Dockerfile`. Se conservan con `DeprecationWarning` hasta la próxima mayor |
| `prompt_evolution.py` vs `prompt_evolver.py` | Ambos en `py-modules`, nombres casi idénticos | **Clases distintas y ambas vivas**: `RichPromptEvolver` (fitness multi-objetivo, 400 líneas) y `PromptEvolver` (fitness = score, 95 líneas, usado por `muta_lambda/__init__`). Fusionarlas es un cambio de algoritmo, fuera de alcance |
| `island.py` vs `island_evolution.py` | Nombres solapados | `Island` (entidad, población local) vs `IslandPool`/`IslandSnapshot`/`IslandDiversity` (coordinador con barreras). Responsabilidades disjuntas |
| `tests/uast/` vs `tests/uast2/` | Dos directorios de tests UAST | Prueban **motores distintos**: `muta_ext.uast` (v1 congelado) y `muta_ext.uast2` (v2 arena/mutable). Cero solapamiento de módulo bajo prueba. Consolidarlos perdería cobertura |
| `dashboard.py` vs `dashboard_run.py` | Dos apps Streamlit | HITL en vivo vs inspector post-mortem. Sin solapamiento funcional. Docstrings corregidos para que no vuelva a confundir |
| `test_remediation_v4{,_tranche2,3,4}.py` | Sospecha de casos repetidos | Revisados: tranches disjuntos (v4 base, EventBus/CommandQueue, migración, workflow). Ningún test duplicado |
| `_compare` inline en el harness de `runners.py` vs `comparison.compare_values` | Lógica de comparación duplicada | **Duplicación necesaria**: el harness se ejecuta en el proceso hijo del sandbox, sin acceso a los paquetes del proyecto. Ver deuda D2 en §7 |
| `muta_ext/uast/config/*.yaml` (4 plantillas) | Cero referencias en todo el repo | **RESUELTO**: no son basura — los 4 handlers y los 14 mutadores que nombran existen. Lo que no existe es un *loader*. Movidas a `examples/configs/uast/` con un README que documenta qué se consume de verdad (3 claves de 48). Ver §7 D3 |
| `LLMSection.enabled` | Comentado en el código como «dead field» | **Falso**: `cli/main.py:794` gatea `generate-mutator` con él. Se corrigió el comentario |

---

## 5. Duplicados consolidados

| Par antiguo | Canónico | Sitios reemplazados |
|---|---|---|
| Defaults de evolución repetidos en **4** sitios (`constants.py`, `config_loader._DEFAULTS`, Pydantic `Field(...)`, `EvolveConfig`) | **`mutalambda_core/constants.py`** | 16 constantes × 3 consumidores = **49 literales** sustituidos por la constante canónica. Nada cambió de valor (verificado imprimiendo las 4 capas antes/después) |
| `name`/`_name` en mutadores científicos (2 patrones distintos para lo mismo) | patrón `_name` + `def name()` | 3 clases alineadas con las otras 2 |

Antes de este cambio, `constants.py` declaraba 10 constantes `DEFAULT_*` de las que
**solo `MIN_POPULATION_SIZE` era leída por alguien**. Era documentación que fingía
ser código. Ahora es la fuente real, y
`tests/test_config_single_source.py` (29 tests) impide que vuelvan a divergir.

---

## 6. Conexiones verificadas y reparadas (categoría E)

### E.1 CLI → core ✅
Los **23** subcomandos (`run`, `resume`, `config`, `stats`, `evaluate`, `mutate`,
`checkpoints`, `migrate-checkpoints`, `interactive`, `quick`, `production`,
`scientific`, `numpy`, `doctor`, `tutorial`, `dashboard`, `init`, `recommend`,
`compare`, `explain-run`, `examples`, `generate-mutator`, `uast2`) responden a
`--help` y mapean a una función real. **Sin subcomandos duplicados.**
Nota: el encargo mencionaba `--dashboard`/`--mode`/`--hfc-enabled` como flags del grupo;
en realidad `dashboard` es un subcomando y `--mode` vive en `cli/entrypoints.py`
(entrada alternativa por `argparse`). Todo coherente.

### E.2 Dashboard ↔ motor — **ESTABA ROTO, REPARADO** 🔧
Hallazgo principal del recorrido:

> `dashboard.integrate_hitl()` se suscribe a `GenerationCompleted` y lee
> `payload["diversity"]`, `payload["island_scores"]`, `payload["pareto_size"]`.
> **El agente nunca publicaba ninguna de las tres.** El payload real era
> `{generation, best_score, combined_best_score, should_stop, snapshots, extension_metrics}`.
> Consecuencia: `DashboardState.diversity`, `.island_bests` y `.pareto_size` quedaban
> **permanentemente vacíos** y las pestañas Diversity / Islands / Pareto no pintaban
> nada en ninguna ejecución. Ningún test lo detectaba.

Reparado en `muta_lambda/agent.py`: el payload incluye ahora las tres claves,
tomadas de datos que ya se calculaban (`cross_diversity`, `island_snapshots`,
y el `pareto_frontier_size` de NSGA-II cacheado en `_last_pareto_size` para no
pagar un sort extra por generación).

Además:
- `DashboardState` prometía ser *thread-safe* y no tenía ni un lock, con el hilo de
  evolución escribiendo y el hilo de Streamlit leyendo → `RLock` en todas las
  mutaciones + `snapshot()` consistente para que el renderer no itere un `deque`
  mientras se le hace `append`.
- `approved_variants`/`rejected_variants` se escribían directamente desde el
  renderer → `record_review()` bajo lock.
- `[dashboard]` extra **sin pandas**, usado en los 4 gráficos → añadido.
- `agent.get_metrics()` → `_render_advanced_metrics` lee `advanced_selection`,
  `thc`, `dialectic`, `spatial`: claves verificadas contra los emisores. ✅

Blindado por `tests/test_dashboard_wiring.py` (11 tests), incluido un test AST que
**falla si se vuelve a quitar cualquiera de las tres claves** (verificado quitándolas).

### E.3 LSP ↔ extensión VSCode ↔ core — **ESTABA ROTO, REPARADO** 🔧
Toda la cadena era inoperante:

| Eslabón | Estado antes | Ahora |
|---|---|---|
| `package.json main` | `./dist/extension.js` — `dist/` nunca se generaba (script `tsc` sin fuentes `.ts` ni `tsconfig.json`) | `./extension.js` |
| `extension.js` | `module.exports = function(context)` — VS Code necesita `activate`/`deactivate` | Exporta `{ activate, deactivate }` |
| Comandos | `mutalambda.optimize/explain/analyzeProject` declarados en `contributes.commands`, **ninguno registrado** → «command not found» | Los 3 registrados |
| Arranque del servidor | `require.resolve('./server.js')` — fichero inexistente; el servidor es Python | Lanza `lsp/server.py` con el intérprete configurable |
| Protocolo | Servidor en JSON por líneas; clientes en `Content-Length` | Framing LSP; lectura compatible con ambos |
| Capacidades | 4 anunciadas sin handler → cliente colgado | Handlers mínimos conformes |
| Versión | `4.0.0` vs proyecto `5.0.0` | Sincronizada (y asertada por test) |
| `index.js` | Re-export huérfano | Eliminado |

Blindado por `tests/test_lsp_extension_contract.py` (12 tests) y un handshake real
contra un subproceso.

### E.4 Configuración ✅
Jerarquía canónica establecida y verificada:
`constants.py` (valores) → `config_loader.py` (YAML→dict con defaults) →
`muta_config.py` (Pydantic, validación) → `EvolveConfig` (runtime).
Los 6 YAML distribuidos cargan, validan y convierten. 29 tests de deriva.

### E.5 Persistencia ✅
Round-trip `save_full_checkpoint` → `load_checkpoint` verificado en **json y
msgpack**, asertando que **los 18 campos** de `CheckpointData` sobreviven.
Ningún campo renombrado ni eliminado en este trabajo → `--resume` intacto.

---

## 7. Pendientes y recomendaciones (requieren decisión del autor)

### Deuda detectada, NO tocada

**D0 — `[tool.coverage.run] source` omitía los 4 paquetes `mutalambda_*` y `lsp`.** *(CORREGIDO)*
La puerta de cobertura medía 10 617 sentencias de 15 811: el motor de evolución,
el modelo de configuración, el formato de checkpoint y el servidor LSP eran
**invisibles** y reportaban un 60 % saludable sobre dos tercios del código. Ahora
se listan los 8 paquetes de primer orden; `benchmarks/` se excluye explícitamente.

**D1 — `benchmarks/` y `bench_*.py` se empaquetan como API pública.**
`bench_cost_ledger`, `bench_headroom_fase{1,2,3}`, `bench_phase6`, `bench_uast2`,
`benchmark_runner` están en `py-modules`: viajan en el wheel de todos los usuarios.
No son API. Recomendado moverlos a `tools/` y sacarlos del paquete (Fase 2 del ADR 0042).

**D2 — Divergencia semántica de comparadores (riesgo de corrección).**
`comparison.compare_values` **lanza `ValueError`** ante un comparador desconocido;
la copia inline `_compare` del harness de sandbox hace `return got == expected`
(silencioso). Un `comparison:` mal escrito en un fichero de tests se rechaza en
*differential testing* pero se acepta como `equal` en la evaluación en sandbox.
Además al harness le falta `predicate_registered`.
**No corregido**: alinear los comportamientos puede empezar a hacer fallar runs que
hoy pasan. Decisión de producto.

**D3 — Las 4 plantillas YAML de UAST.** *(RESUELTO: reubicadas, no borradas)*
Triaje aplicado: **(a)** YAML válido → las 4 pasan. **(b)** campos presentes en el
schema Pydantic actual → **las 4 fallan**: ninguna de las 48 claves valida contra
`MutaLambdaConfig`, porque usan el vocabulario plano pre-v5 (`generations`,
`population_size`, `islands`) que hoy vive seccionado (`evolution.generations`,
`population.size`, …). **(c)** ¿presets con sentido? → **sí**: los 4 handlers que
nombran existen y los 14 mutadores que listan existen.

No son basura: son **bocetos de diseño precisos sin loader**. Lo único que un
handler consume de verdad son 3 claves (`compile_timeout_sec`, `run_timeout_sec`,
`sanitizers`, leídas por `CppHandler`/`RustHandler`):

| Fichero | Claves | Consumibles |
|---|---|---|
| `cpp_template.yaml` | 17 | 3 |
| `rust_template.yaml` | 14 | 3 |
| `python_uast_template.yaml` | 9 | 0 |
| `go_config.yaml` | 8 | 0 |

Estaban en el peor sitio posible: dentro del paquete (parecían config de runtime)
pero **sin entrada en `packages`** (nunca se instalaban) y sin nadie que las
leyera. Movidas con `git mv` a `examples/configs/uast/` + README que documenta la
tabla de arriba, la traducción plano→seccionado y las dos piezas que faltarían
para convertirlas en presets reales. Quedan en un extremo claro: ejemplos
documentados, no configuración.

**D4 — 38 variables locales sin usar (`F841`) y 311 `except Exception` ciegos.**
Fuera de los 5 corregidos, las demás están en `benchmarks/`, `muta_ext/__main__.py`
y harnesses. Los `except` ciegos requieren revisar caso por caso si tragan errores
reales — en particular en `evaluation_service` con `forkserver`, donde un fallo del
proceso hijo debe propagarse. No auditado en profundidad.

**D5 — `evolve.py` (38 KB) y `mutalambda_cli.py` (43 KB) son monolitos.**
Trocearlos es un refactor estructural, no limpieza. Debe ir después del ADR 0042.

**D6 — Reorganización src-layout.** Ver `docs/decisions/0042-src-layout-migration-plan.md`:
plan completo en 7 fases, con la superficie medida (837 imports, 158 módulos) y los
riesgos. **Entregado como plan, no ejecutado** — justificación en §1 del ADR.

### No tocado por mandato explícito
`LICENSE`, `COMMERCIAL.md`, licencias, `docs/`, `README*`, `AGENTS.md`, `CLAUDE.md`,
`CONTRIBUTING.md` (solo se añadieron dos documentos nuevos en `docs/`).
Ningún algoritmo (NSGA-II, mutadores, evaluación) fue reescrito.

---

## 8. Commits

| Commit | Lote | Tests después |
|---|---|---|
| `deea2c0` | `fix(A)` — 13 desperfectos de corrección + deriva de docstrings | 1073 ✅ / 0 ❌ |
| `—` | `fix(E)` — dashboard ↔ motor reconectado, locks, pandas | 1084 ✅ / 0 ❌ |
| `—` | `fix(E.3)` — cadena LSP ↔ VSCode reparada, `index.js` borrado | 1096 ✅ / 0 ❌ |
| `—` | `chore(C/D)` — paquete muerto + 286 imports | 1096 ✅ / 0 ❌ |
| `—` | `refactor(5)` — fuente única de defaults + bounds | 1125 ✅ / 0 ❌ |
| `—` | `fix(E)` — `dashboard_run` importable + batería de humo | 1125 ✅ / 0 ❌ |

Cada lote es revertible por separado (`git revert <sha>`).

## 9. Cómo reproducir la verificación

```bash
python -m venv .venv
.venv/bin/pip install -e ".[cli,dashboard,uast,dev]"
.venv/bin/python -m pytest -q -m "not e2e"   # 1125 passed, 22 skipped, 0 failed
./.audit/smoke_all.sh .venv/bin/python       # SMOKE: ALL GREEN
```
