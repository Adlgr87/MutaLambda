# MutaLambda — Production Readiness Checklist

> Workflow: `Workflow_productionready_mutalambda` · Ejecutado: 2026-08-22, actualizado 2026-08-23
> Repositorio: https://github.com/Adlgr87/MutaLambda (local sincronizado con `origin/main` @ `a0a6179`)
> Entorno: Python 3.14.7 · Linux (kernel 7.1.9-200.fc44.x86_64)

## Resumen ejecutivo

| Área | Estado | Nota |
|------|--------|------|
| Tests | ✅ PASS | 521 passed / 0 failed; causa raíz del flakiness deep-mode **resuelta** (pool fork-safe, commit `caf94e2`); **CI verde** en Python 3.10/3.11/3.12 |
| Benchmarks | ✅ PASS | Los 3 benchmarks dentro de umbrales |
| Packaging (wheel/sdist) | ✅ FIXED | Wheel roto corregido; verificado end-to-end en venv limpio |
| Docker | ✅ COMPLETADO | Imagen endurecida publicada en GHCR (`ghcr.io/adlgr87/mutalambda:{4.0.0,latest}`), CI verde |
| Seguridad / Sandbox | ✅ OK | RLIMIT_AS + timeouts + AST SecurityVisitor; modo container recomendado |
| Observabilidad | ✅ OK | Logging jerárquico centralizado; run_artifacts con environment_hash |
| API/CLI estabilidad | ✅ FIXED | Entry point roto corregido (`mutalambda_cli:cli`) |

**Veredicto:** apto para producción tras resolver los gaps listados en la sección final.

---

## 1. Tests

Comando:
```bash
python -m pytest tests/ -q -p no:cacheprovider --color=no
```

Resultado: **521 passed, 4 warnings in ~33-44s** (run B; runs A/C con 1 fallo intermitente).

### Flakiness deep-mode — RESUELTO (2026-08-23)
Dos tests deep-mode fallaban de forma **intermitente** en CI:
- `tests/test_progressive_pipeline.py::TestDeepPhase::test_runs_real_engine`
- `tests/test_progressive_pipeline.py::TestEndToEnd::test_full_run_deep_mode`

Síntoma: `phase_reached='exhausted'`, `variants_evaluated=0`, fallo en <1s con
`RuntimeError("Evolution produced no valid individuals.")`.

**Causa raíz confirmada**: el pool de evaluación se creaba sin contexto de
multiprocessing explícito. En CI (Linux + Python ≤3.13) eso es `fork`; forkear desde
el proceso pytest **multi-hilo** (hilos de islas + hilos LSP de tests previos) puede
producir hijos muertos → `BrokenProcessPool` → todos los candidatos marcados broken →
0 individuos válidos. El log de CI lo confirmaba literalmente
("multi-threaded, use of fork() may lead to deadlocks...").

**Fix aplicado** (`caf94e2`, `EvaluationService._make_pool`): pool creado con
contexto explícito `forkserver` (fallback `spawn` donde no existe). Warm-up del pool
bajo lock retenido (commit `49962c0`). Los markers `@pytest.mark.flaky(reruns=2)` y el
timeout de 120s se mantienen como defensa en profundidad.

Verificación: 521 passed ×3 runs locales; CI verde 3.10/3.11/3.12 (run `32621842111`).

## 2. Benchmarks

Todos PASS (umbrales internos respetados):

| Benchmark | Resultado clave |
|-----------|----------------|
| `bench_phase6.py` | Parse cache **1103× speedup**; msgpack checkpoint 4× más rápido, tamaño 99.3% del JSON |
| `scripts/benchmark_nsga2_cache.py` | pop=200, mean `non_dominated_sort` **4.04 ms** |
| `scripts/benchmark_checkpoint_serialization.py` | msgpack **7.3× más rápido**, payload **96.1% menor** |

Los números son reproducibles vía `environment_hash()` (deps+versiones) y git commit
grabados por `run_artifacts.write_run_artifacts`.

## 3. Empaquetado (wheel / sdist) — FIXES CRÍTICOS

### Hallazgo principal
El wheel publicado estaba **roto**: `[tool.setuptools] py-modules` estaba desactualizado
y omitía 10+ módulos importados transitivamente desde `muta_lambda`
(`mutation_filters`, `progressive_pipeline`, `component_evolution`, `ast_math_verifier`,
`hotspot_profiler`, `numpy_optimizer`, `test_synthesizer`, `diagnostics`,
`dashboard_run`, `nsga2`). El CLI instalado moría con `ModuleNotFoundError`.

### Correcciones aplicadas
1. **pyproject.toml** — `py-modules` completado con todos los módulos faltantes.
2. **Colisión de nombres cli** — el paquete `cli/` sombreaba al módulo raíz `cli.py`
   (el grupo click real). El entry point `cli:cli` era insatisfacible. Se renombró:
   `git mv cli.py mutalambda_cli.py`, entry point actualizado a
   `mutalambda = "mutalambda_cli:cli"`, y el smoke-test de CI
   (`.github/workflows/python-package.yml`) ahora usa `python mutalambda_cli.py`.
3. Reconstrucción: `python -m build` → exit 0.

### Verificación end-to-end (venv limpio, wheel instalado)
```bash
mutalambda --help            # exit 0, grupos visibles
mutalambda config create --output /tmp/ml-test.yaml --template basic   # exit 0
mutalambda config validate --path /tmp/ml-test.yaml                    # exit 0
```

Artefactos regenerados en `dist/`:
- `mutalambda-4.0.0-py3-none-any.whl`
- `mutalambda-4.0.0.tar.gz`

> Nota: mantener `[tool.setuptools] py-modules` en sync es frágil; considerar migrar a
> auto-descubrimiento (`packages find`) con estructura `src/` como mejora estructural.

## 4. Docker

**COMPLETADO (2026-08-22)**: imagen de producción multi-stage validada end-to-end.

- `Dockerfile` multi-stage (`python:3.12-slim` builder → runtime), extras
  `cli,uast,scientific` instalados en venv aislado; el extra `archive`
  (faiss/sentence-transformers → torch) queda opcional fuera por defecto.
- Endurecida: usuario no-root `mutalambda` (uid/gid 10001), compatible con rootfs
  read-only (`HOME=/tmp`), labels OCI, `.dockerignore` de contexto mínimo (~635 MB final).
- Workflow `.github/workflows/docker-image.yml`: build con cache GHA, smoke tests
  endurecidos (`--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--read-only`,
  `--network=none`) y push a GHCR (`ghcr.io/adlgr87/mutalambda:{version,latest}`)
  únicamente en push a `main`.
- **PUBLICADO (2026-08-23)**: imagen visible en
  `ghcr.io/adlgr87/mutalambda:4.0.0` y `:latest`. Fixes habilitantes del workflow:
  referencia de imagen forzada a minúsculas (GHCR rechaza mayúsculas) y permiso
  `packages: write` para el `GITHUB_TOKEN` (sin él el push devolvía
  "denied: installation not allowed to Create organization package").
- Fixes habilitantes: versión CLI single-source desde `pyproject.toml` (antes hardcodeada
  3.1.0 vs 4.0.0 real) y `CheckpointManager.__init__` tolerante a filesystem read-only.
- Validado localmente: `docker build` ✓ y smokes `--version` / `examples` ✓ bajo sandbox
  endurecido como usuario sin privilegios.

## 5. Seguridad

| Check | Resultado |
|-------|-----------|
| Secretos hardcodeados | ✅ Ninguno detectado (grep sobre patrones api_key/secret/token/password) |
| Límites de recursos candidatos | ✅ `RLIMIT_AS` via `preexec_fn` en subprocess (256 MB default), `--memory` en modo container |
| Timeouts | ✅ `timeout_sec` propagado a runners (default 10s evaluación, 60s pipeline) |
| AST SecurityVisitor | ✅ Bloquea imports peligrosos, asignaciones y calls sospechosas antes de evaluar |
| Modo aislamiento recomendado | ⚠️ `runner_mode="subprocess"` es dev-default; producción debería usar `"container"` |
| Token revocado / purga de historia | ✅ SEC-01 cerrado previamente (fuera de scope de este workflow) |

Recomendación: documentar que `container` es el modo soportado para código de terceros.

## 6. Observabilidad

| Check | Resultado |
|-------|-----------|
| Logging centralizado | ✅ `logging_setup.get_logger` → jerarquía `MutaLambda.<componente>` |
| Reproducibilidad de runs | ✅ `run_artifacts.write_run_artifacts` graba git commit + `environment_hash()` |
| Métricas de evolución | ⚠️ Sin exportador estándar (Prometheus/OTel); suficiente para uso CLI, gap si se despliega como servicio |

## 7. Estabilidad API/CLI

- Entry point funcional y verificado post-fix (sección 3).
- ~~**Mismatch de enum `ProfileMode`**~~ — **RESUELTO (2026-08-23)**: los 4 call sites
  legacy (`parallel_for_mutator.py:119`, `evolution_engine.py:412`, `muta_lambda.py:707`,
  `muta_lambda.py:860`) fueron migrados a valores válidos del enum; verificado por grep
  que ninguna ruta activa pasa ya `STRICT`/`PERMISSIVE`.

## 8. Gaps y próximos pasos (priorizados)

1. ~~**[ALTA] ProfileMode mismatch**~~ — **COMPLETADA (2026-08-23)**: call sites
   migrados a valores válidos del enum; sin fallbacks silenciosos.
2. ~~**[ALTA] Dockerfile ausente**~~ — **COMPLETADA (2026-08-22)**: imagen multi-stage
   endurecida + workflow GHCR con smokes endurecidos. **PUBLICADA (2026-08-23)** en
   `ghcr.io/adlgr87/mutalambda:{4.0.0,latest}`.
3. ~~**[MEDIA] Flaky deep-mode tests**~~ — **RESUELTA (2026-08-23)**: causa raíz
   identificada y corregida (pool fork-safe, commit `caf94e2`); no era timing sino
   fork desde proceso multi-hilo. Markers flaky mantenidos como defensa.
4. **[MEDIA] Migrar packaging a src-layout + auto-discovery** — elimina la clase entera
   de bugs "py-modules desactualizado".
5. **[BAJA] Exporter de métricas** (Prometheus/OTel) si se expone como servicio long-running.

### Estado CI al cierre (2026-08-23)

| Workflow | Commit | Resultado |
|----------|--------|-----------|
| Python package | `a0a6179` | ✅ verde en 3.10 / 3.11 / 3.12 |
| Docker image | `a0a6179` | ✅ verde, push a GHCR OK |

Empaquetado revalidado en HEAD: `python -m build` → exit 0
(`dist/mutalambda-4.0.0-py3-none-any.whl`, `dist/mutalambda-4.0.0.tar.gz`).

---

*Checklist generado por OpenHands (agente AI) como parte del workflow
`Workflow_productionready_mutalambda`.*
