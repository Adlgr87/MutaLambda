# MutaLambda — Optimized Multi-Agent Evolutionary System

> **MutaLambda v5.0.0**: Sistema de optimización evolutiva multi-agente con integración GPU, pipeline CI/CD completo, benchmarking científico, motor **UAST v2** (mutación in-situ con verificación por nanopass), capa **Headroom** de optimización de costo (F0–F3), **SVL** (validación científica con invariantes, gate opt-in) y 1,038 funciones de test ([`docs/ARTIFACTS/test_count.txt`](docs/ARTIFACTS/test_count.txt)) bajo CI verde.
> Un framework de alta performance para optimización de código asistida por IA con aceleración hardware.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/Adlgr87/MutaLambda/actions/workflows/mutualambda-optimization-pipeline.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
[![Docker](https://github.com/Adlgr87/MutaLambda/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
[![License: BSL-1.1](https://img.shields.io/badge/License-BSL--1.1-orange.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-61%25-orange)](https://github.com/Adlgr87/MutaLambda/actions)
[![GPU Ready](https://img.shields.io/badge/GPU-ready-orange)]()
[![Tag](https://img.shields.io/badge/tag-v5.0.0--phase7--8-blue)]()
[![Status](https://img.shields.io/badge/status-beta-lightgrey)]()
[![Benchmarks](https://img.shields.io/badge/benchmarks-EffiBench%20%7C%20Market%20Comparison-blue)]()

## 🚀 Estado Actual

| Métrica | Valor | Estado | Última verificación |
|---------|-------|--------|---------------------|
| Tests | **CI verde** (Lint & Tests & Smoke + builds, 3.10/3.11/3.12) | ✅ 1,038 funciones ([`test_count.txt`](docs/ARTIFACTS/test_count.txt)) | 2026-09-11 |
| SVL | scientific_validation gate (opt-in) | ✅ 84 funciones SVL (74 unitarios + 4 integración + 6 extensión) | 2026-09-11 |
| Cobertura | **61%** | ✅ FASE 8 completada | 2026-09-02 |
| Versión git | **v5.0.0-phase7-8** | ✅ Tag oficial | 2026-08-23 |
| Fases completadas | **FASE 0–8 + UAST v2 (F1–F3) + Headroom (F0–F3) + SVL** | ✅ Workflow cerrado | 2026-09-11 |
| Lockfile | **`uv.lock` sincronizado** | ✅ `uv sync --locked` | 2026-09-10 |
| Hardening producción | **ML-001…ML-016** | ✅ Remediation aplicada | 2026-09-10 |
| UAST v2 | **opt-in (`uast.engine: v2`)** | ✅ Paridad shadow 0 diffs | 2026-09-10 |
| Imagen | ghcr.io/adlgr87/mutalambda:{4.0.0,latest} | ✅ Docker | — |

> 🔒 **Nota de seguridad (producción).** MutaLambda ejecuta código generado como
> parte de su función central. Para entradas **no confiables** usa
> `sandbox.runner=container` (Docker/Podman) o `sandbox.runner=microvm` (bwrap):
> ambos **fallan cerrado** si el motor de aislamiento no está disponible. El modo
> `subprocess` es solo para desarrollo local. Ver [Seguridad](#-seguridad-y-configuracin)
> y `docs/deployment_guide.md`.

## Quick Start

```bash
git clone https://github.com/Adlgr87/MutaLambda.git && cd MutaLambda
uv sync --extra cli --extra uast --extra dev   # single source of truth: uv.lock

uv run mutalambda init                         # asistente interactivo → config.yaml
uv run mutalambda run --source examples/target.py --tests examples/target_tests.json -g 5

# SVL activo (validación científica + hotpath):
uv run mutalambda run --source examples/target.py --tests examples/target_tests.json --scientific --hotpath

# Producción (aislamiento endurecido, falla-cerrado):
MUTALAMBDA_REQUIRE_ISOLATION=1 uv run mutalambda run --config presets/scientific.yaml

# GPU:
CUDA_VISIBLE_DEVICES=0 uv run mutalambda run --config presets/scientific.yaml
```

## Áreas Vanguardistas

### 1. 🧬 Optimización Evolutiva con NSGA-II
Sistema multi-objetivo que optimiza código simultáneamente en **calidad, eficiencia y seguridad** (NSGA-II). Punto de entrada público: `mutalambda run` / `MutaLambdaCLI.run_evolution` (`cli/main.py`); la clase interna `CoreEvolutionEngine` en `evolution_engine.py`.

### 2. 🎮 GPU-Accelerated Evolution (FASE 4-5)
NSGA-II en CUDA vía PyTorch con escalado distribuido mediante Ray:
- **`gpu_optimizer.py`**: NSGA-II en GPU con mixed precision
- **`ray_scheduler.py`**: Batch processing distribuido en cluster
- **Auto fallback**: detecta GPU disponible y degradea graceful a CPU

### 3. 🛡️ Code Intelligence — UAST v2 (nuevo)

MutaLambda convierte código a un **UAST neutral** (nodos `Function`/`BinaryOp`/`LiteralNode`…, el mismo esquema en Python, Rust, C++ y Go) y muta ahí, no en el texto. Sobre los parsers específicos de cada lenguaje (`ast` de Python, tree-sitter para el resto) se apoya el motor **UAST v2**, activable con una sola bandera y con rollback trivial (`uast.engine: legacy`):

```yaml
uast:
  engine: v2      # legacy (por defecto) | v2
  shadow: true    # compara ambos motores y registra diffs (nunca falla)
  verify: true    # verificación tras cada nanopass (con rollback atómico)
```

- **Mutación in-situ**: arena con ids estables y parent pointers; los nanopasses escriben en el slot, sin reconstruir el árbol.
- **Nanopasses con verificación**: estructura, esquema, parent links, validador legacy, sanidad numérica, puerta de seguridad y fidelad aritmética. Las guardas baratas se aplican solo al subárbol tocado (**27.7× más barato** que verificar el documento entero).
- **Hashes incrementales (Merkle)**: editar una hoja y re-hashear cuesta ~40× menos que el hash completo; clonar + re-hashear un candidato es **5.5× más rápido** que `deepcopy` + hash del motor legacy.
- **Persistencia plana**: msgpack + slab de referencias enteras → **4.0× más rápido** que JSON legacy y **0.44×** su tamaño (sin comprimir).
- **Paridad verificable**: `uast2 check` compara legacy vs v2 sobre un corpus y sale con código 2 si hay diferencias. Hoy: **0 diffs / 0 errores** sobre `examples/`.

```bash
python mutalambda_cli.py uast2 check examples            # paridad legacy vs v2
python mutalambda_cli.py uast2 parse examples/target.py  # árbol + canonical_hash
python mutalambda_cli.py uast2 mutate examples/target.py --seed 42
python mutalambda_cli.py run --source examples/target.py --uast-engine v2 --uast-verify
python bench_uast2.py --reps 3                           # gates de rendimiento
```

Detalles, contrato de nanopasses y benchmarks: **[docs/uast2.md](docs/uast2.md)**.

- Invariant detection para code quality assurance
- Estrategias de mutación semánticas (no solo texto)

### 4. 📊 Benchmarking Científico (FASE 6)
Pipeline extendido de benchmarking:
- **`bench_phase6.py`**: evaluación completa multi-generación
- Reportes automatizados (JSON) por corrida
- Comparación GPU vs CPU con testing estadístico

## 🔬 Validación Científica (SVL) + Hot-Path (opt-in)

MutaLambda incluye la **Scientific Validation Layer (SVL)**, un **gate opt-in**
(del `ProtocolWorkflow` en `island.py`) que valida invariantes científicas antes
del gate de rendimiento. **Off por defecto** (`scientific: {}`/`::enabled: false` →
PASS inmediato, score 1.0). Familia de invariantes en `muta_ext/scientific/invariants.py:104` (`BASE_INVARIANTS`; el score 0–1 se escribe en `EvalResult.scientific_score`, `models.py:355`):

- **Hard** (rechazan el candidato): `energy_non_negative` (E ≥ −1e-9), `mass_conservation` (|Δmass| < 1e-8), `numerical_stability` (NaN/Inf/overflow).
- **Soft** (penalan): `physical_bounds`, `monotonicity_trend` (entropía no decreciente).

**Orden de gates (Flujo A, Tier 1 — `island.py:667`):**
`generate_candidate → build_gate → security_gate → api_gate → evaluate_candidate (sandbox) → tests_gate → differential_gate → scientific_validation → performance_gate → decision_gate`

> Los mutantes **AST-only** siguen el flujo reducido (`build → security → decision`) y omiten SVL, por lo que su overhead es ~0. La SVL se inyecta entre `differential_gate` y `performance_gate` (`muta_ext/scientific/validation.py:163`; `workflow/protocol_extensions.py:89`).

- **Activación** (CLI `mutalambda run`, `mutalambda_cli.py:69-71` + `cli/main.py:82-89`):
  ```bash
  mutalambda run --source examples/target.py --tests examples/target_tests.json --scientific
  mutalambda run --config config.scientific.yaml -g 5
  mutalambda run --scientific --hotpath --scientific-strength 0.3 -g 50   # hotpath + dominio (cProfile)
  mutalambda scientific examples/target.py   # preset dedicado (SVL activo)
  ```
  Flags: `--scientific` (SVL), `--hotpath` (perfilado cProfile + mutación inter-procedural), `--scientific-strength 0.0-1.0` (cuánto teclea el dominio sobre el hotpath).
- **Config** (bloque `scientific:`, default `{}`):
  ```yaml
  scientific:
    enabled: true
    validation: { invariants: true, numerical_stability: true, conservation_checks: true, property_based: true }
    hotpath: { enabled: true, profiler: cprofile, min_cumulative_pct: 5.0 }
    domain_operators: { enabled: true, strength: 0.3 }
  ```
  Plantilla incluida: `config.scientific.yaml`. Ver detalle en **[Scientific Optimization Mode](docs/SCIENTIFIC_OPTIMIZATION_MODE.md)**.
- **Verificado**: 4 tests de integración (`tests/test_scientific_validation_integration.py`) + 74 tests unitarios (`tests/scientific/`: invariants, validation, hotpath, domain_operators, interprocedural, multifile, call_graph) + 6 de extensión (`tests/test_scientific_extension.py`) = **84 funciones de test SVL**; CI Lint & Tests & Smoke + builds verde. 0 regresiones.

### 5. 🔧 Pipeline de Migración Segura
Sistema de refactorización automatizada con rollback:
- **`migration.py`**: pipeline seguro de transformación de código
- Generación de PRs con cambios validados
- Testing post-migración automático

### 6. 📈 Meta-Evolución
Capa de auto-mejora que evoluciona la propia configuración del sistema:
- **`prompt_evolution.py`** (`RichPromptEvolver`): metaevolución de poblaciones `PromptGenome`.
- **`hfc_tiers.py`**: tiering horizontal de transferencia (HFC) y micro-mutadores memoizados.

### 7. 🌐 Multi-Agent Orchestration
Arquitectura multi-isla con transferencia horizontal para ejecución multi-agente:
- **`muta_lambda/agent.py`** (`MutaLambdaAgent.step_generation`): API de generación compartida (CLI/dashboard/núcleo).
- **`island_evolution.py`**: modelo multi-isla (topología anelada/anillo) con HFC.
- Flujos definidos por YAML/JSON; integración con sistemas de observabilidad (OTel/Prometheus).

### 8. 🔬 Research & Reproducibility
Enfoque científico con trazabilidad completa:
- Resultados reproducibles con seeds fijos (`rng_session.py`)
- Tracking de evolución en JSON
- Validación cross-benchmark

### 9. 💸 Capa de Optimización de Costo (Headroom)

Capa de reducción de costo (tokens LLM + GPU) con **medición before/after obligatoria**
y **todas las palancas desactivables** por flag:

```yaml
# config/optimization.yaml  (override: MUTALAMBDA_OPT_<SECCION>__<CLAVE>=1|0)
# Solo la infraestructura FASE 0 va activa por defecto (no cambia calidad ni
# costo); todas las palancas de costo/calidad de F1–F3 están desactivadas.
optimization:
  cost_ledger:        { enabled: true,  gpu_hour_usd: 0.5 }   # F0/A5: tokens $ + GPU $
  checkpoint:         { every: 5 }                            # F0/A5: --resume-from
  fitness_cache:      { enabled: true, backend: sqlite }      # F0/A2: hash canónico
  deterministic_prompt:{ enabled: true }                     # F0/O2: gemelas byte-idénticas
  headroom:
    smart_crusher:    { enabled: false }      # O1: tracebacks/logs → SmartCrusher/LogCompressor
    ast_stubs:        { enabled: false }      # O3: stubs + headroom_retrieve(stub_id)
    json_schema_output:{ enabled: false }     # A1: op_type/location/unified_diff/rationale
    batching:         { enabled: false, batch_size: 5 }  # A3: N mutaciones por llamada
    bandit:           { enabled: false }      # A3: reward = Δfitness/tokens (UCB)
  profiling_filter:                          # FASE 2 (escalera de evaluación)
    enabled:          false                  # paraguas: off = comportamiento pre-Fase-2
    profile_seconds:  10                     # O4: profiling bajo carga ~10 s
    min_cpu_pct:      0.5                    # O4: excluye funciones con <0.5% CPU
    nanopass_check:   { enabled: true }      # O6 N1: guard UAST en memoria (<1 ms)
    test_subset:      { enabled: true, by_coverage: true, max_tests: 0 }  # O6 N2 + A4
    sandbox_top_pct:  20.0                   # O6 N3: solo top ~20% → Docker + Ray
    api_policy:       strict
    uast2_enabled:    false
    ray_profile:      { enabled: false }
  economic_gate:                          # FASE 3 (O5)
    enabled:            false
    delta_h_threshold:  0.005              # ΔH normalizado mínimo por generación
    stall_generations:  5                  # generaciones consecutivas → early stop
    gpu_seconds_per_generation: 0.0        # >0 activa el criterio de costo $GPU
    production_cpu_savings_hour_usd: 0.0   # $CPU/h que ahorra el candidato
  bandit_reward_usd:  { enabled: false }   # FASE 3 (A3): reward en $ reales (ledger)
  pareto_archive:                           # FASE 3 (A5)
    enabled: false
    dir: "pareto_archive"
    warm_start: true           # --no-warm-start lo desactiva (el archivo sigue escribiéndose)
    max_size: 50
```

- **Ledger de costo** (`cost_ledger.py`): interceptado centralmente en el wrapper LLM, el sandbox y la regression gate; `dump_json` por ejecución.
- **FASE 0** (infraestructura de medición, activa por defecto): cost ledger (`A5`), fitness cache por hash canónico (`A2`), resume desde checkpoint (`--resume-from`) y prompts deterministas (`O2`). No cambia calidad ni costo (verificable en `roi_report.json`); su valor es habilitar la medición before/after de F1–F3 y el cacheo de fitness entre generaciones.
- **Medición de la Fase 1** (LLM simulado, 200 candidatos): input tokens **−95.5%**, output tokens **−55.5%**, reparación **±0pp** vs baseline, **100%** de propuestas con schema válido, **−80%** llamadas (batching N=5). Ver `bench_headroom_fase1.py`.
- **Medición de la Fase 2** (120 mutantes, suite real de 12 tests, sandbox subprocess real): escalera N1 → N2 → N3 reduce el tiempo de evaluación **−79.5% por mutante** (21.1 → 4.3 ms; gate ≥60%), las evaluaciones de sandbox **120 → 18** (solo **15%** toca N3, ≤20%), **0 falsos positivos** (ningún mutante correcto es rechazado) y N1 promedia **0.52 ms** (<1 ms). Ver `bench_headroom_fase2.py`.
  - O4 `AmdahlHeadroomFilter` (`hotspot_profiler.py`): profiling bajo carga (~10 s) y exclusión de funciones con <0.5% de CPU de las regiones mutables (`select_code_regions`). Fail-open: sin perfil, se incluye todo.
  - O6 N1 (`tiered_evaluator.py`): nanopass en memoria — parse + fingerprint de API (strict/relaxed) + walk de seguridad sobre el mismo árbol (<1 ms).
  - O6 N2 + A4: subset mínimo de tests por set cover / crecimiento guiado por cobertura (`trace`), in-process si es puro, subprocess endurecido si I/O.
  - O6 N3: solo el top ~20% de sobrevivientes de N2 paga el sandbox completo (Docker si hay engine, fail-closed a subprocess) + Ray opcional.
- **Medición de la Fase 3** (`run_evolution` real + búsqueda con evaluación subprocess real): O5 detuvo la corrida en **6 de 40 generaciones** (estancamiento de ΔH) con **−0.0% de pérdida de hipervolumen** (gate ≤2%); A5 warm-start (índice por hash de firma de API) redujo las generaciones para converger **50%** en función similar (gate ≥30%); costo total acumulado de las palancas F1+F2+F3: **−97.2%** vs baseline (gate ≥60%; modelo compuesto de mediciones por palanca, documentado en el bench). Ver `bench_headroom_fase3.py`. `roi_report.json` por corrida (`run_evolution` y flujos HFC): costo total (ledger), palancas activas, stop reason, hipervolumen final, warm-start y caché.
  - O5 `EconomicHeadroomGate` (`economic_gate.py`): hipervolumen 3D exacto (barrido) normalizado a [0,1]; parada por estancamiento (ΔH < umbral × N generaciones) o por costo (GPU restante > ahorro CPU en producción); cada parada se loguea en el cost ledger.
  - A5 `ParetoArchive` (`pareto_archive.py`): mejor individuo por hash de firma de API (`api_fingerprint`); warm-start inyecta el archivo como semilla (siempre re-evaluado, nunca confiado a ciegas); `--no-warm-start`.
  - A3 reward en $ reales (`operator_bandit.compute_usd_aware_reward`) con precios del ledger, flag `bandit_reward_usd.enabled`; `--mutation-strategy auto` resuelve llm|ast según backend disponible.

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MutaLambda Optimized v5.0.0                      │
├─────────────────────────────────────────────────────────────────────┤
│  CLI: mutalambda (Click, mutalambda_cli.py)                          │
│  ├── run / resume / mutate / uast2 / config / checkpoints          │
│  └── production / scientific / numpy / doctor / dashboard / ...      │
├─────────────────────────────────────────────────────────────────────┤
│  Core modules                                                        │
│  ├── island.py             — Island + ProtocolWorkflow + SVL gate    │
│  ├── evolution_engine.py   — CoreEvolutionEngine (NSGA-II + ASTMutator)│
│  ├── muta_config.py        — MutaLambdaConfig (Pydantic)             │
│  ├── muta_lambda/          — EvolveConfig + MutaLambdaAgent          │
│  ├── muta_ext/             — optimizer, HFC, uast, scientific/       │
│  ├── island_evolution.py   — evolución multi-isla (HFC)              │
│  ├── migration.py          — pipeline de migración segura            │
│  ├── mutation_filters.py   — SecurityVisitor + filtros de mutación   │
│  ├── runners.py            — SecurityVisitor + sandbox (subproc/ctr) │
│  ├── secure_exec.py        — pre-scan AST + builtins restringidos    │
│  ├── gpu_optimizer.py      — NSGA-II CUDA (PyTorch)                  │
│  ├── ray_scheduler.py      — batch distribuido (Ray)                │
│  ├── benchmark_runner.py   — benchmarking científico                 │
│  └── performance_monitor.py — monitoreo en tiempo real             │
├─────────────────────────────────────────────────────────────────────┤
│  UAST (representación neutral multi-lenguaje)                       │
│  ├── muta_ext/uast/           — motor legacy (congelado)            │
│  └── muta_ext/uast2/          — v2 opt-in: arena+Merkle, nanopasses │
│                                 con verificación, msgpack, shadow     │
├─────────────────────────────────────────────────────────────────────┤
│  Infraestructura                                                     │
│  ├── tests/                 — ~1,038 funciones (unit/integration)     │
│  ├── scripts/               — deploy, install, monitoring            │
│  ├── benchmarks/            — EffiBench, market-comparison, etc.     │
│  ├── presets/               — quick / production / scientific / numpy│
│  ├── config.scientific.yaml — plantilla SVL (Flujo A)                │
│  ├── docs/                  — documentación (25 entradas)             │
│  └── plans/                 — documentación de workflows              │
├─────────────────────────────────────────────────────────────────────┤
│  GPU Acceleration (Optional)                                         │
│  ├── gpu_optimizer.py — NSGA-II CUDA (PyTorch)                       │
│  ├── ray_scheduler.py — batch distribuido (Ray)                     │
│  └── Auto fallback a CPU cuando no hay GPU                           │
└─────────────────────────────────────────────────────────────────────┘
```

## 🔐 Seguridad y Configuración

- **Sandbox fail-closed (ML-002)**: `sandbox.runner=microvm` exige `bwrap` y
  `sandbox.runner=container` exige Docker/Podman; si el motor no está disponible,
  la ejecución **aborta** (no degrade a un camino sin aislamiento). Con
  `MUTALAMBDA_REQUIRE_ISOLATION=1` el modo `subprocess` también queda prohibido.
- **Ejecución guardada (ML-001)**: los caminos `exec`/`eval`/`pickle` del proceso
  principal (diferencial, metrics-injector, benchmarks, scheduler Ray) pasan por
  `secure_exec.py`: pre-scan AST + builtins restringidos. El límite de aislamiento
  real sigue siendo el runner subprocess/container/microvm.
- **SCA bloqueante (ML-003)**: `pip-audit` audita el entorno bloqueado en el PR
  gate y el workflow de package; Trivy escanea la imagen Docker antes del push.
- **Redacción de secretos en prompts (ML-014)**: `llm_backend.redact_prompt`
  elimina patrones de claves/tokens antes de enviar a un proveedor externo, y
  `privacy.allow_external_llm=false` impide inicializar backends externos.
- **API keys**: se pasan vía variables de entorno, nunca hardcodeadas en el repo. `benchmarks/market_comparison_harness.py` consume `OPENROUTER_API_KEY`, `AGNES_API_KEY`, `POOLSIDE_API_KEY`, `GITHUB_TOKEN` (Copilot), `GITLAB_TOKEN` (CodeWhisperer) según el tool configurado en `TOOL_REGISTRY`.
- **.gitignore**: incluye patrones `benchmarks/results_*.json` y `benchmarks/output/` para no commitear artefactos de runs ni tokens logs.
- **Auditoría de secretos**: validada con gitleaks (workflow `secret-scan`) → GREEN en rama principal.
- Ver detalle en [AGENTS.md](AGENTS.md) → secciones `## Security` y `## Phase 7 — Security Hardening`, y en [COMMERCIAL.md](COMMERCIAL.md) (modelo comercial y checklist de producción ML-001…ML-016).

## 💻 CLI

La CLI principal es `mutalambda` (Click, `pyproject.toml:76` → `mutalambda_cli:cli`).
Los comandos canónicos:

| Comando | Descripción |
|---|---|
| `mutalambda run --config <yaml> [--source/-c ...]` | Ejecuta evolución (flags: `--generations/-g`, `--animation/-a`, `--verbose/-v`, `--source`, `--tests`, `--scientific`, `--hotpath`, `--scientific-strength`, `--uast-engine{legacy,v2}`, `--uast-*`, `--allow-untested`) |
| `mutalambda init` | Asistente interactiva de configuración (`--output/-o`) → `config.yaml` |
| `mutalambda production <file>` / `mutalambda scientific <file>` / `mutalambda numpy <file>` | Presets (SVL activo en `scientific`) |
| `mutalambda resume` / `mutalambda stats` / `mutalambda evaluate` | Reanuda / estadísticas / evalúa |
| `mutalambda mutate -t <file> {prompt\|operators\|hyperparams}` | Mutaciones estructurales/LLM |
| `mutalambda uast2 {check\|parse\|mutate}` | Motor UAST v2 |
| `mutalambda checkpoints` (`--list`/`--clean`) / `migrate-checkpoints --format` | Checkpoints |
| `mutalambda doctor [--fix]` / `mutalambda quick` / `mutalambda dashboard [--text]` | Diagnóstico / rápido / dashboard |
| `mutalambda generate-mutator` / `mutalambda explain-run <id> [--full]` / `mutalambda compare` | Generación / explicación / comparación |

Alternativas: `python -m muta_ext` (argparse) y `python -m muta_lambda` (legacy). Ver
`mutalambda_cli.py` para la lista de comandos/flags completa.

## Testing

```bash
# Suite principal (entorno bloqueado, recomendado por AGENTS.md)
uv sync --extra cli --extra uast --extra dev
uv run pytest tests/ -q --deselect tests/test_hfc_tiers.py::test_hfc_deduplicates_demoted_elite_duplicate_in_factory

# Lint & format (los mismos gates que CI)
uv run flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
uv run black --check . --line-length 100

# Coverage
uv run pytest tests/ --cov=muta_lambda --cov-report=html

# E2E (script, no directorio)
MUTALAMBDA_E2E_SERIAL=1 python tests/e2e_tests.py --fast
```

**Resultados**: CI verde en Python 3.10/3.11/3.12 (Lint & Tests & Smoke + builds);
1,038 funciones de test coleccionadas localmente (ver `docs/ARTIFACTS/test_count.txt`, incl. 84 SVL). La CI ejecuta la
suite completa en cada push/PR.

## 📊 Benchmarking Científico

MutaLambda valida su rendimiento contra benchmarks públicos reconocidos y realiza comparativas de mercado.

### EffiBench Harness (TIER 1)
Pipeline reproducible con el dataset EffiBench (1000 tasks; 891 convertibles a Python).
- **Dataset**: `/tmp/effibench_train.parquet` (pyarrow)
- **Smoke tests (sin API keys)**:
  ```bash
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 20 --baseline-only   # correctness + timing
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 10                   # identity mode (ratio = 1.0)
  ```
- **LLM mode (con Ollama / OpenRouter)**:
  ```bash
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 8 --llm --samples 3 --warmups 1
  ```
- **Métricas**: `ratio_to_canonical` (1.0 = baseline canónico), `%Opt`, `mean_speedup`, `correctness_rate`. Candidate gated por `correctness == 1.0` antes de contar speedup (`benchmarks/SMOKY_TESTS.md`).
- **Status**: ✅ SMOKE PASS validado. Reporte: `benchmarks/results_effibench.json` (gitignored).

### Market Comparison Harness
Integra providers LLM OpenAI-compatible (Agnes AI, Poolside) y herramientas de mercado (Copilot, CodeWhisperer) para comparar MutaLambda head-to-head.
- **Smoke (sin keys)**:
  ```bash
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/market_comparison_harness.py --smoke --tasks 5 --tools mutalambda copilot codewhisperer
  ```
- **Con OpenRouter** (requiere `OPENROUTER_API_KEY`):
  ```bash
  export OPENROUTER_API_KEY="sk-or-v1-..."
  python benchmarks/market_comparison_harness.py --tasks 20 --tools mutalambda openrouter-gpt4o openrouter-claude copilot
  ```
- **Providers OpenAI-compatible verificados**:
  - `agnes-ai` (Flash 2.0): reproducible, ratio 1.3–1.8× speedup, 100% correctness en validación.
  - `poolside-laguna` (Laguna XS 2.1): funciona pero API lenta (5–45s+/request, spikes >120s) — no recomendado para runs multi-task repetibles.
  - `openrouter-*` (gpt4o, claude, dots3): base_url corregido a `https://openrouter.ai/api`; configuración completa pero pendiente de validación live por falta de key.
- **Reproducibility nota**: la métrica `ratio_to_canonical` no es determinista entre runs del mismo provider/seed (ej. Agnes ratio 0.56–0.77 para el mismo task) — varianza introducida por el LLM, no por el engine. El harness sí es reproducible: mismas tasks, mismos comandos.
- **Reporte**: `benchmarks/results_market_comparison.json` (gitignored). Ver `benchmarks/SMOKY_TESTS.md` para validación completa y `benchmarks/BENCHMARK_STRATEGY.md` para la metodología.

> 📌 Los artefactos `*_results.json` están en `.gitignore` (se regeneran en cada run).

## Workflows Completados

| Fase | Descripción | Estado | Archivos clave | Tests |
|------|-------------|--------|----------------|-------|
| FASE 0 | Análisis Inicial | ✅ | Coverage report, architecture analysis | — |
| FASE 1 | Sistema de Pruebas | ✅ | 641 tests, CI pipelines → 664/670 | 664 passed, 6 skipped |
| FASE 2 | Refactorización | ✅ | ASTMutator, migration pipeline | — |
| FASE 3 | Análisis Pre-GPU | ✅ | optimization_workflow.md | — |
| FASE 4 | GPU Pilot (NSGA-II) | ✅ | gpu_optimizer.py, ray_scheduler.py | — |
| FASE 5 | GPU Expansión (Batch) | ✅ | Distributed batch processing | — |
| FASE 6 | Benchmarking Científico | ✅ | bench_phase6.py, cached_parse, msgpack | — |
| FASE 7 | Documentación y Deploy | ✅ | 25 docs, install scripts, CI/CD | — |
| FASE 8 | Metrics Exporter (OTel/Prometheus) | ✅ | metrics_exporter.py | — |
| ML-Hardening | Producción: sandbox fail-closed, exec guardado, SCA, CI bloqueante | ✅ | secure_exec.py, runners.py, workflows | — |
| UAST v2 — F1 | Núcleo: nodos+arena+visitantes+convertidores+adaptadores | ✅ | muta_ext/uast2/core.py, arena.py, convert.py | 126 tests |
| UAST v2 — F2 | Rendimiento: Merkle incremental, serialización plana, coordenadas | ✅ | merkle.py, serialize.py, bench_uast2.py | 50 tests |
| UAST v2 — F3 | Nanopasses + verificación + rollback atómico + CLI/flags | ✅ | passes.py, verify.py, mutators.py, engine.py | 71 tests |
| Headroom — F0 | Infra de medición: cost ledger, fitness cache, resume, prompts deterministas | ✅ | cost_ledger.py, fitness_cache.py, evolution_engine.py | 17 tests |
| Headroom — F1 | Trace compress, AST stubs, schema output, batching+bandit | ✅ | headroom_integration.py, ast_stubs.py, structured_ops.py, llm_backend.py | 110 tests |
| Headroom — F2 | Amdahl filter, escalera N1/N2/N3, coverage subset | ✅ | hotspot_profiler.py, tiered_evaluator.py, api_fingerprint.py | 44 tests |
| Headroom — F3 | Economic gate, pareto archive warm-start, reward $ real | ✅ | economic_gate.py, pareto_archive.py, operator_bandit.py | 26 tests |
| **SVL** | **Scientific Validation Layer (gate opt-in, invariantes hard/soft)** | ✅ | `muta_ext/scientific/`, `island.py`, `cli/main.py`, `config.scientific.yaml` | **84 tests** |

## Documentación

- [Fitness metrics](docs/FITNESS_METRICS.md)
- [Metrics](docs/METRICS.md)
- [Scientific Optimization Mode](docs/SCIENTIFIC_OPTIMIZATION_MODE.md)
- [UAST v2 (motor de mutación in-situ)](docs/uast2.md)
- [Test Execution Protocol](docs/TEST_EXECUTION_PROTOCOL.md)
- [Production checklist](docs/PRODUCTION_CHECKLIST.md)
- [First optimization walkthrough](docs/getting-started/first-optimization.md)
- [Architecture v2](docs/architecture_v2.md)
- [GPU Integration](docs/gpu_integration.md)
- [Testing Guide](docs/testing_guide.md)
- [Performance Report](docs/performance_report.md)
- [Migration Guide](docs/migration_guide.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Deployment Guide](docs/deployment_guide.md)
- CLI: ver [CLI reference](docs/CLI.md) (también `mutalambda <cmd> --help`); el README incluye la tabla de comandos canónica arriba.

## Roadmap

- [x] FASES 0–7: Pipeline completo con GPU, benchmarking y documentación
- [x] FASE 6: Benchmarking científico (EffiBench smoke + identity validation)
- [x] FASE 8: Metrics exporter (Prometheus/OTel) para despliegues en producción
- [x] Hardening de producción (ML-001…ML-016): sandbox fail-closed, exec guardado, `uv sync --locked`, SCA bloqueante, black/unit-tests obligatorios en CI
- [x] UAST v2 (Fases 1–3): motor in-situ con nanopasses verificados, Merkle incremental y serialización msgpack — opt-in y con paridad shadow 0 diffs (2026-09-10)
- [x] Capa Headroom (F0–F3): reducción de costo LLM+GPU con medición before/after obligatoria y palancas desactivables — input −95.5 %, output −55.5 %, evaluación −79.5 %/mutante, costo total −97.2 %; early-stop sin pérdida de hipervolumen; warm-start −50 % generaciones (2026-09-10)
- [x] **SVL — Scientific Validation Layer** (gate opt-in, invariantes hard/soft + hotpath): orden Flujo A `build→security→sandbox→tests→scientific_validation→perf→decision`, flags `--scientific`/`--hotpath`/`--scientific-strength`, config `config.scientific.yaml` (2026-09-11)
- [ ] Graduación de UAST v2: `uast.engine: v2` como motor por defecto del pipeline evolutivo
- [ ] src-layout packaging migration
- [x] Market-comparison harness: Agnes AI + Poolside integrados (2026-09-02)
- [ ] Reducir deuda de estilo restante (F401/E402/E741) y ratchetear complejidad C901 < 20
- [ ] Soporte para más lenguajes (Java, Kotlin, Swift)
- [ ] Integración con plataformas de MLOps (MLflow, Weights & Biases)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

BSL-1.1 License - see [LICENSE](LICENSE) for details.

## Citation

```bibtex
@software{mutalambda2026,
  author = {Adlgr87},
  title = {MutaLambda: Optimized Multi-Agent Evolutionary System},
  year = {2026},
  url = {https://github.com/Adlgr87/MutaLambda},
  version = {5.0.0}
}
```
