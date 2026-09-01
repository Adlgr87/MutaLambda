# Manus Observations — Transcribed from Manus_observations.jpg

OCR of `~/Descargas/Manus_observations.jpg` (tesseract, 2026-09-01).

## Priority matrix

| # | Priority | Area |
|---|----------|------|
| 1 | P1 | Security de ejecución |
| 2 | P1 | Reproducibilidad y calidad de evaluación |
| 3 | P1 | Integración real del flujo completo |
| 4 | P1 | UAST multilenguaje |
| 5 | P1 | Fitness y NSGA-II |
| 6 | P1 | Paralelismo |
| 7 | P1 | Observabilidad end-to-end |
| 8 | P2 | Documentación y releases |
| 9 | P2 | Benchmark público |
| 10 | P2 | Eficiencia del ciclo evolutivo |
| 11 | P2 | Robustez del backend LLM |
| 12 | P2 | Mantenibilidad |

## 12 optimization points (verbatim transcription, OCR-corrected)

1. **Cambiar el modo predeterminado de subprocess por contenedores endurecidos para código generado.** El subprocess limita tiempo y memoria, pero no es un sandbox de seguridad. Completar o eliminar el MicroVMRunner mientras siga siendo un stub.
   → FIX 2.4 owner.

2. **Exigir evaluadores más amplios y configurables:** tests de regresión, casos aleatorios/property-based, múltiples repeticiones de benchmark y validación contra overfitting. El fitness solo es tan bueno como los tests que recibe.

3. **Conectar de verdad GPU, Ray, benchmarks, métricas y UAST con MutaLambdaAgent.** Actualmente varios módulos existen y tienen tests, pero operan como subsistemas separados del camino principal.

4. **Decidir entre reducir la promesa o completar el pipeline.** Hoy hay parseo parcial para Python/Rust/Go/C++, pero el emisor está fijado esencialmente a Python y muchos nodos terminan como Opaque. Para soportar otros lenguajes hacen falta emisores, compilación, tests y runners específicos por lenguaje.

5. **Documentar y simplificar la relación entre los tres objetivos reales —corrección, latencia P50 y memoria— y las métricas legacy como P99, throughput y parsimony.** También convendría permitir estrategias configurables: hard gate de corrección para producción, pero ranking gradual durante exploración.

6. **El fallback serial evita el desastre, pero puede ocultar que la ejecución dejó de ser paralela.** Debería reportarse claramente el modo efectivo usado.
   → Manus P1 (observability).

7. **Cablear el exportador Prometheus/OpenTelemetry al agente real y probar una corrida completa, no solamente los helpers del módulo.** Registrar automáticamente generaciones, llamadas LLM, rechazos por gate, evaluaciones cacheadas, migraciones, coste y motivo de descarte.

8. **Alinear README, versión declarada, número de tests, nombres de archivos y capacidades reales.** Publicar releases versionadas, changelog confiable y una matriz explícita de funciones: "integrado", "experimental", "stub" y "no soportado".

9. **Crear un benchmark reproducible contra OpenEvolve y ShinkaEvolve** con la misma tarea, seed, modelo, número de llamadas LLM, generaciones, workers, hardware y timeout. Medir calidad, coste, tiempo, memoria, validez sintáctica y tasa de candidatos útiles; no solo el mejor speedup.

10. **Reducir llamadas innútiles al LLM** mediante mejores filtros previos, deduplicación semántica, prompts de reparación más pequeños, selección adaptativa de operadores y reutilización más agresiva de resultados. También conviene medir cuánto presupuesto se pierde en candidatos inválidos.

11. **Mejorar recuperación ante respuestas incompletas, código con Markdown, cambios de API, timeouts y modelos que no siguen el formato.** Mantener replay determinista y separar claramente coste estimado, coste real y número de tokens.

12. **Reducir módulos experimentales no conectados, marcar APIs legacy, eliminar warnings de pytest y deprecaciones, registrar correctamente marcas como flaky y añadir pruebas de integración entre componentes, no solo pruebas unitarias aisladas.**

## Status of implementation

- Point 6 (last_mode observability): DONE commit `16cc222`.
- Point 1 (FIX 2.4 MicroVMRunner): DONE (2026-09-01).

## FIX 2.4 — MicroVMRunner hardening summary

**Status:** done. `MicroVMRunner` (bwrap namespace sandbox) hardened for
cross-language transfer blocking + robustness.

**Changes (`runners.py`):**
1. **Removed filesystem egress hole** — dropped the writable `--bind /tmp /tmp`
   mount. `/tmp` is now a private `--tmpfs /tmp` and the run workdir is
   `--ro-bind` mounted read-only at `/work`. No host directory is writable
   from inside the sandbox, blocking cross-namespace file transfer to the host.
2. **Network egress blocked** — `--unshare-net` removes all network interfaces
   (no loopback, no outbound). Kept `--unshare-pid`, `--unshare-ipc`,
   `--unshare-user`, `--unshare-uts` and `--cap-drop ALL`.
3. **In-sandbox memory ceiling** — `build_wrapper_source` now accepts
   `memory_mb` and prepends `resource.setrlimit(RLIMIT_AS, ...)` before the
   candidate is exec'd, since bwrap has no native `--rlimit` flag.
4. **Robustness** — `--die-with-parent` for teardown, conditional mounting of
   system dirs (skip if absent), workdir passed into `_build_sandbox` for
   per-run isolation.

**Tests (`tests/test_microvm_runner.py`), all 15 passing:**
- Existing: basic pass, factory, quick task, AST-scan block import/exec,
  AST disabled, bwrap-missing graceful error, expression tests, multi-case,
  EvaluationService.last_mode (cache-only / microvm-serial / pool-parallel).
- New (P1 hardening, cross-language transfer blocking):
  - `test_microvm_blocks_host_filesystem_write` — candidate cannot open a
    host path; correctness must be 0 (FS egress blocked).
  - `test_microvm_blocks_network_egress` — `socket.connect` fails because the
    net namespace has no interfaces (net egress blocked).
  - `test_microvm_build_sandbox_has_no_writable_host_bind` — static check
    that the sandbox command contains no writable `--bind` of host paths.

**Verification:** `python -m pytest tests/test_microvm_runner.py -q` → 15 passed.
Full suite: only pre-existing unrelated `test_gpu_optimizer.py` failures
(`gpu_stats["acceleration"] == 'cpu'` vs expected `'none'` in an untouched
GPU/NSGA2 module), not caused by this change.
