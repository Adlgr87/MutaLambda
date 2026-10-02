# ADR 0042 — Plan de migración a src-layout

**Estado:** Propuesto (NO ejecutado)
**Fecha:** 2026-10-02
**Contexto:** recorrido de escrutinio v5 (limpieza + verificación integral)

---

## 1. Decisión

La reorganización completa a `src/mutalambda/` **se entrega como plan ejecutable,
no se aplica en este cambio**. Las razones son concretas, no de prudencia genérica:

1. **La premisa del plan original está desactualizada.** El objetivo declarado era
   eliminar «~40 módulos sueltos en la raíz» de un layout plano. El repositorio
   **ya hizo esa migración**: existen `mutalambda_core`, `mutalambda_engines`,
   `mutalambda_config`, `mutalambda_security`, `muta_lambda`, `muta_ext`, `cli` y
   `lsp`, y **21 de los 71 módulos raíz son ya shims de compatibilidad** de 14
   líneas que re-exportan con `DeprecationWarning`. Mover otra vez *todo* significa
   una **segunda** capa de shims sobre la primera, con dos niveles de deprecación
   simultáneos sobre la misma API pública.

2. **Superficie de cambio medida** (no estimada):
   - 837 sentencias de import de primer orden a reescribir
   - 158 módulos distintos referenciados
   - 427 ficheros versionados, 349 de ellos `.py`
   - referencias en `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `Dockerfile`,
     6 workflows de CI, `docs/*` y `package.json` de la extensión

3. **Riesgo asimétrico.** El beneficio es de higiene estructural; el coste de un
   error es romper `--resume` (checkpoints serializan rutas de módulo),
   la API pública y los entry points. El mandamiento del encargo es explícito:
   *«La seguridad prima sobre la limpieza»* y *«Prefiere conservar con
   deprecación a romper la API pública»*.

4. **Debe ser un PR propio.** Un cambio mecánico de 800+ imports es irrevisable
   si viaja mezclado con correcciones de comportamiento. Las correcciones de este
   recorrido deben poder revertirse sin arrastrar la reorganización, y viceversa.

**Recomendación:** ejecutar este plan como PR independiente, un commit por fase,
con la batería `scripts/smoke_all.sh` + suite completa verde entre fases.

---

## 2. Estado actual (medido, no asumido)

| Grupo | Nº | Observación |
|---|---|---|
| Módulos raíz `.py` | 71 | de los cuales… |
| …shims de compatibilidad | 21 | ya re-exportan a `mutalambda_*` con `DeprecationWarning` |
| …módulos reales en raíz | 50 | objetivo real de la migración |
| Paquetes existentes | 8 | `cli`, `lsp`, `muta_lambda`, `muta_ext`, `mutalambda_{core,engines,config,security}` |
| Imports de primer orden | 837 | sitios a reescribir |

Los 21 shims ya existentes son: `api_fingerprint`, `archive`, `checkpoint_manager`,
`code_hash`, `component_evolution`, `config_loader`, `constants`, `diagnostics`,
`differential`, `evaluation_service`, `event_bus`, `evolution_engine`, `extensions`,
`fitness_cache`, `fitness_normalize`, `fitness_vector`, `hfc_tiers`,
`island_evolution`, `muta_config`, `mutation_filters`, `nsga2`.

Tras este recorrido **ningún módulo interno los importa** (se verificó con AST y se
migraron los 3 usos restantes: `tests/conftest.py`, `tests/test_nsga2.py`,
`bench_phase6.py`). Son ya puramente externos → su eliminación en la próxima mayor
es segura y verificable.

---

## 3. Estructura objetivo

```
src/mutalambda/
├── __init__.py                 # __version__ + exports públicos estables
├── core/                       # orquestación y configuración
│   ├── orchestrator.py         # ← muta_lambda/agent.py
│   ├── session.py              # ← muta_lambda/session.py
│   ├── progressive_pipeline.py # ← progressive_pipeline.py
│   ├── workflow_protocol.py    # ← workflow_protocol.py
│   ├── config.py               # ← muta_lambda/config.py + mutalambda_config/muta_config.py
│   ├── config_loader.py        # ← mutalambda_config/config_loader.py
│   ├── constants.py            # ← mutalambda_core/constants.py  (ya canónico)
│   ├── models.py               # ← mutalambda_core/models.py
│   ├── logging_setup.py        # ← logging_setup.py
│   └── rng_session.py          # ← rng_session.py
├── evolution/
│   ├── engine.py               # ← mutalambda_core/evolution_engine.py
│   ├── island.py               # ← mutalambda_core/island.py
│   ├── island_pool.py          # ← mutalambda_core/island_evolution.py
│   ├── nsga2.py                # ← mutalambda_engines/nsga2.py
│   ├── hfc_tiers.py            # ← mutalambda_engines/hfc_tiers.py
│   ├── migration.py            # ← migration.py
│   ├── operator_bandit.py      # ← operator_bandit.py
│   ├── prompt_evolution.py     # ← prompt_evolution.py   (RichPromptEvolver)
│   ├── prompt_evolver.py       # ← prompt_evolver.py     (PromptEvolver — NO fusionar, §5)
│   ├── component_evolution.py  # ← mutalambda_core/component_evolution.py
│   └── thc_engine.py           # ← muta_ext/thc_engine.py
├── evaluation/
│   ├── service.py              # ← mutalambda_core/evaluation_service.py
│   ├── runners.py              # ← runners.py
│   ├── sandbox.py              # ← sandbox.py
│   ├── secure_exec.py          # ← secure_exec.py
│   ├── tiered_evaluator.py     # ← mutalambda_engines/tiered_evaluator.py
│   ├── fitness_vector.py       # ← mutalambda_engines/fitness_vector.py
│   ├── fitness_normalize.py    # ← mutalambda_engines/fitness_normalize.py
│   ├── fitness_cache.py        # ← mutalambda_engines/fitness_cache.py
│   ├── comparison.py           # ← comparison.py
│   ├── mutation_filters.py     # ← mutalambda_core/mutation_filters.py
│   ├── property_testing.py     # ← property_testing.py
│   ├── ast_math_verifier.py    # ← ast_math_verifier.py
│   ├── differential.py         # ← mutalambda_core/differential.py
│   └── api_fingerprint.py      # ← mutalambda_security/api_fingerprint.py
├── uast/                       # ← muta_ext/uast/   (v1, congelado)
├── uast2/                      # ← muta_ext/uast2/  (v2, motor mutable)
├── scientific/                 # ← muta_ext/scientific/ + muta_ext/config/
├── persistence/
│   ├── checkpoint_manager.py   # ← mutalambda_config/checkpoint_manager.py
│   ├── archive.py              # ← mutalambda_engines/archive.py
│   ├── pareto_archive.py       # ← pareto_archive.py
│   ├── run_artifacts.py        # ← run_artifacts.py
│   └── code_hash.py            # ← mutalambda_core/code_hash.py
├── infra/
│   ├── llm_backend.py  event_bus.py  extensions.py  massive_adapter.py
│   ├── hotspot_profiler.py  numpy_optimizer.py  gpu_optimizer.py
│   ├── ray_scheduler.py  benchmarking.py  interpretability.py
│   ├── trace_compressor.py  metrics_exporter.py  performance_monitor.py
│   ├── telemetry.py  cost_ledger.py  economic_gate.py  optimization_flags.py
│   └── diagnostics.py          # ← mutalambda_security/diagnostics.py
└── interfaces/
    ├── cli/                    # ← cli/ + mutalambda_cli.py (como cli/__main__.py)
    ├── dashboard/
    │   ├── live.py             # ← dashboard.py
    │   └── runs.py             # ← dashboard_run.py
    └── lsp/                    # ← lsp/server.py
editors/vscode/                 # ← lsp/extensions/vscode/
editors/neovim/                 # ← lsp/extensions/neovim/
tests/                          # espeja src/mutalambda/
benchmarks/, bench_*.py         # → tools/benchmarks/ (NO empaquetar)
```

---

## 4. Fases (un commit por fase, verificación entre cada una)

### Fase 0 — Preparatoria (ya hecha en este recorrido)
- [x] Ningún módulo interno importa los 21 shims raíz.
- [x] `constants.py` es la única fuente de los defaults (test de deriva).
- [x] Batería de humo repetible: `scripts/smoke_all.sh`.
- [x] Línea base de tests registrada: **1125 passed / 22 skipped / 0 failed**.

### Fase 1 — Esqueleto
`mkdir -p src/mutalambda/{core,evolution,evaluation,persistence,infra,interfaces}`
+ `__init__.py` en cada uno. Sin mover nada. Suite debe seguir verde.

### Fase 2 — Mover con `git mv` (preserva historial)
Un `git mv` por subpaquete, en el orden de *menor* a *mayor* fan-in medido:
`persistence` → `infra` → `evaluation` → `evolution` → `core` → `interfaces` →
`uast`/`uast2`. Mover las hojas primero minimiza los imports rotos simultáneos.

### Fase 3 — Codemod de imports
Script con `libcst` (preserva formato/comentarios, a diferencia de un regex):

```python
# tools/codemod_imports.py
RENAMES = {
    "mutalambda_core.models":            "mutalambda.core.models",
    "mutalambda_core.evolution_engine":  "mutalambda.evolution.engine",
    "mutalambda_core.island_evolution":  "mutalambda.evolution.island_pool",
    "mutalambda_engines.fitness_vector": "mutalambda.evaluation.fitness_vector",
    "mutalambda_config.muta_config":     "mutalambda.core.config",
    "muta_ext.uast":                     "mutalambda.uast",
    "muta_ext.uast2":                    "mutalambda.uast2",
    "muta_lambda":                       "mutalambda.core.orchestrator",
    "runners":                           "mutalambda.evaluation.runners",
    # ... tabla completa: 158 entradas, una por módulo
}
```
Verificación: `ast.parse` de los 349 ficheros + resolución de **todos** los
`ImportFrom` contra los módulos existentes. Cero imports no resolubles antes de
hacer commit.

### Fase 4 — Shims de compatibilidad
En cada ruta antigua (71 raíz + 8 paquetes), un módulo de 14 líneas idéntico al
patrón ya usado en el repo:

```python
"""Backward-compatibility shim: moved to mutalambda.<nueva.ruta>."""
import warnings
warnings.warn(
    "<viejo> has moved to mutalambda.<nuevo>. Please update your import path.",
    DeprecationWarning, stacklevel=2,
)
from mutalambda.<nuevo> import *  # noqa: F401,F403
```

Los 21 shims que ya existen se **re-apuntan** a la nueva ruta (no se anidan).

### Fase 5 — Empaquetado
```toml
[tool.setuptools]
package-dir = {"" = "src"}
[tool.setuptools.packages.find]
where = ["src"]
[project.scripts]
mutalambda = "mutalambda.interfaces.cli:cli"
```
Se elimina la lista `py-modules` de 71 entradas y la lista `packages` de 27.
⚠️ Los shims raíz deben seguir instalándose → `py-modules` reducido solo a ellos,
o `src/_compat/` con los shims y un `.pth`. **Decisión pendiente del autor.**

### Fase 6 — Referencias externas
`README.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `docs/**`, `Dockerfile`,
`.dockerignore`, `run_tests.sh`, `scripts/*.sh`, los 6 workflows de
`.github/workflows/`, `[tool.coverage.run] source`, y
`lsp/extensions/vscode/extension.js` (ruta `server.py` → `editors/vscode` ya no
está a `../../server.py`: pasa a depender de `mutalambda.server.path` o de
`python -m mutalambda.interfaces.lsp`).

### Fase 7 — Verificación final obligatoria
```bash
python -m venv /tmp/v && /tmp/v/bin/pip install -e ".[cli,dashboard,uast,dev]"
/tmp/v/bin/python .audit/import_all.py        # 88/88 módulos
/tmp/v/bin/python -m pytest -q -m "not e2e"   # >= 1125 passed, 0 failed
./scripts/smoke_all.sh /tmp/v/bin/python       # ALL GREEN
/tmp/v/bin/python -c "import runners, nsga2, dashboard"  # shims aún funcionan
```
Si cualquiera falla → `git revert` de la fase y reporte.

---

## 5. Riesgos específicos identificados

| Riesgo | Mitigación |
|---|---|
| `--resume` roto: los checkpoints msgpack guardan estado de objetos cuya ruta de módulo cambia | `CheckpointData` es un dataclass de tipos primitivos (verificado: el round-trip json+msgpack conserva los 18 campos). No hay `pickle` de clases → bajo riesgo. **Verificar con un checkpoint real pre-migración.** |
| Doble deprecación (shim→shim) | Fase 4 re-apunta los 21 shims existentes a la ruta final; no se anidan. |
| `evolve.py` (38k) y `mutalambda_cli.py` (43k) son monolitos en la raíz | Moverlos tal cual en Fase 2; **no** trocearlos en el mismo PR. |
| Benchmarks (`bench_*.py`, `benchmarks/`) hoy se empaquetan vía `py-modules` | Mover a `tools/` y **sacarlos del paquete**: no son API pública. Reduce el wheel. |
| `muta_ext.uast` vs `uast2` parecen duplicados | **NO lo son** (ver informe §4). v1 congelado + v2 mutable, con `convert.py` entre ambos y un modo `shadow` que los compara. Se mueven como dos subpaquetes hermanos. |

---

## 6. Tabla ruta antigua → ruta nueva (resumen)

La tabla completa (158 entradas) se genera mecánicamente con:

```bash
python - <<'EOF'
import ast, pathlib
# ... recorre src/, emite CSV viejo,nuevo
EOF
```

Se adjunta como entrada del codemod en Fase 3; no se transcribe aquí para
evitar que diverja del script, que es la fuente de verdad.
