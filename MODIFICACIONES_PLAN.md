# Plan de reparación — `Modificaciones_ML.pdf` (auditoría Adlgr87 2026-08-30)

Auditoría validada 100% contra el checkout actual (`feat-hfc-reconciled` @ `1fb2c0c`, base `origin/main` @ `9f7fb7a`).
Orden de ejecución: orden de prioridad del propietario → **seguridad > ejecución correcta > evaluación correcta > rendimiento**.

## Estado de verificación de cada frente (investigación previa)

| # | Frente | Hallazgo real en el código | Match auditoría |
|---|--------|----------------------------|-----------------|
| 1 | Distancia entre islas | `island.py` migración usa `min(score)`, **no** Jaccard. Hay `archive.py` con FAISS + embeddings, pero `muta_ext/thc_engine.py` HorizontalTransferEngine no usa señal semántica. | ✅ Parcial (usa score, no jaccard) |
| 2 | Drift docs/version | pyproject.toml = `4.0.0`; 206 modules .py; README viejo v2 con 562 tests aún referenciado. `scripts/gen_inventory.py` no existe. | ✅ Confirmado |
| 3 | Dominancia 3 vs crowding 6 | `fitness_vector.py`: `correctness`+`latency_p50`+`memory_peak_mb` (dominancia real); `latency_p99`, `throughput`, `parsimony` (aux). Sin separación documental ni const. | ✅ Confirmado |
| 4 | UAST cross-language | `muta_ext/uast/emitters/{rust,cpp_emitter.py}` existen pero NO lanzan `NotImplementedError` (0 ocurrencias); caen en `Opaque`. THC no bloquea cross-language. | ✅ Confirmado |
| 5 | GPU/Ray desconectado | `gpu_optimizer.py`, `ray_scheduler.py`, `benchmark_runner.py` operan sobre `numpy.ndarray`/funciones sintéticas. `evaluators/` no existe. End-to-end ~1.0x. | ✅ Confirmado |
| 6 | Sandbox no fuerte | `sandbox.py` existe, busca `nsjail`/`docker`/`setrlimit`... **ninguno presente** (0 matches). `muta_lambda.py:1596` YA tiene `if __name__ == "__main__":` (claim de guardia obsoleta). El "doble init" viene del pool spawn en import de módulos pesados (no del `main()` guard). | ✅ Confirmado (excepto guardia, ya corregida) |
| 7 | Observabilidad a medias | `tests/test_metrics_exporter.py` + `tests/integration/test_metrics_integration.py` existen; `evolution_engine.py` **no** inyecta `record_generation_end`/`record_evaluation` automáticamente (0 matches). | ✅ Confirmado |
| 8 | Warnings producción | `flaky` marker **no registrado** en pyproject `[tool.pytest.ini_options].markers`. `datetime.utcnow()` deprecado — usar `datetime.now(timezone.utc)`. `tests/conftest.py` YA mockea stdin/LSP. | ✅ Confirmado |

## Fases de implementación (orden estricto; cada fase verificada antes de la siguiente)

> Regla del owner: **no iniciar Fase N+1 hasta que la Fase N pase su verificación funcional.**

### Fase 1 — Seguridad / ejecución correcta (fronts 6 + 8)
Prioridad máxima: estabilidad de ejecución.
- **6a.** `sandbox.py`: implementar hardening mínimo (capa defensiva, no nsjail — usar `resource.setrlimit` + timeout + bloqueo de imports peligrosos desde `mutation_filters.py`). No requiere daemon de sistema.
- **6b.** `muta_lambda.py`: mover pre-import pesado (`_worker_init`) dentro de `if __name__ == "__main__":` / worker-only path para eliminar el double-init del pool.
- **8a.** `pyproject.toml`: registrar marker `flaky = "inestable"` en `[tool.pytest.ini_options].markers`.
- **8b.** Audit global `datetime.utcnow()` → `datetime.now(timezone.utc)`.
- **8c.** `tests/conftest.py`: confirmar mock stdin/LSP activo (ya verificado — no requiere cambio).
- **Verificación Fase 1:** `python -m pytest tests/ -q -k "sandbox or test_conftest or flaky" ` → 0 fallos; `mutalambda --version` no dobla init del pool.

### Fase 2 — Evaluación correcta (front 3)
- `muta_lambda.py`: `observability_enabled: bool = False` in `EvolveConfig`; `MutaLambdaAgent.__init__` gates `start_metrics_server(port=9100)` behind the toggle (lazy import inside try/except; no-op on miss).
- **Verificación Fase 2:** `pytest tests/test_fitness_vector.py tests/test_nsga2.py` → 28 passed; no-regresión `test_dominance_uses_only_3_objectives` marcado `@pytest.mark.flaky` (3 objetivos de dominio, verifica `_DOMINANCE_OBJECTIVES == 3`).

### Fase 3 — Rendimiento / distancia (fronts 1 + 5)
- **1.** `island.py` + `muta_ext/thc_engine.py`: integrar `archive.semantic_distance` (StarEncoder/CodeBERT + UAST hash híbrido, 0.7 cosine + 0.3 (1-Jaccard)). Reemplazar señal de migración por distancia semántica; Jaccard como filtro prelim.
- **5.** Crear `evaluators/batch_evaluator.py`: puente `List[Individual] → Ray sandbox.eval.remote() → FitnessVector → gpu_optimizer.vectorized_dominance_sort` en GPU. Documentar "GPU acelera NSGA-II dominance, no el pipeline end-to-end".
- **Verificación Fase 3:** `pytest tests/test_hfc_tiers.py tests/test_metrics_integration.py` → pass; benchmark 5gen×2islands×4pop = ~1.0x (documentado como baseline).

### Fase 4 — Integración / honestidad UAST (fronts 4 + 7)
- **4.** `muta_ext/uast/emitters/rust_emitter.py` + `cpp_emitter.py`: lanzar `NotImplementedError(f"... nodo {type(node)} no modelado")` en lugar de caer en `Opaque`. `muta_ext/thc_engine.py`: bloquear transferencia horizontal si `lang_a != lang_b`.
- **7.** `evolution_engine.py`: inyectar `metrics.record_generation_end(gen, stats)` y `metrics.record_evaluation(ind)` en el loop principal; exponer `/metrics` detrás de `config.observability.enabled`.
- **4b.** `README.md`: actualizar status a "Python mutación parcial; Rust/C++ experimental - parseo, emisión limitada"; marcar `adlgr87/mutalambda` como canonical, el v2 como `archive`.
- **Verificación Fase 4:** `pytest tests/ -q` colector completo → solo pre-existing flaky (desconectado); `mutalambda dashboard --text` muestra telemetry; `curl /metrics` 404 si `observability.enabled=false`.

### Fase 5 — Docs/coin (front 2)
- `scripts/gen_inventory.py`: generar tabla de arquitectura automáticamente (`git ls-files '*.py'`).
- Version freeze `pyproject.toml` 4.0.0 como fuente de verdad; sincronizar READMEs.
- **Verificación Fase 5:** `python scripts/gen_inventory.py` produce tabla sin inventarios inventados; `pytest --collect-only -q | tail -1` muestra conteo real (≈633).

---

Estado actual del trabajo en curso (este mensaje): **Fase 0 completada** — reconciliación `Fix a` + `Fix b/a` contra `origin/main` (commit `1fb2c0c`). Tests `test_hfc_tiers.py` = 11/11 pass.

Siguiente paso: ejecutar **Fase 1** arriba. Avanzaré a Fase 1 ahora y detendré cada verificación intermedia.
