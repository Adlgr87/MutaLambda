# MutaLambda

> **MutaLambda v5.0.0** — Framework de optimización evolutiva multi-isla para
> código: optimiza programas simultáneamente en **calidad, eficiencia y
> seguridad** (NSGA-II), con mutación semántica sobre un AST neutral
> multi-lenguaje (UAST v2), aceleración GPU/Ray opcional y una capa de
> optimización de costo totalmente desactivable.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/Adlgr87/MutaLambda/actions/workflows/mutalambda-pr-gate.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
[![Docker](https://github.com/Adlgr87/MutaLambda/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Adlgr87/MutaLambda/actions)
[![License: BSL-1.1](https://img.shields.io/badge/License-BSL--1.1-orange.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-60%25-orange)](docs/testing_guide.md)

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

## Características

### 1. 🧬 Optimización evolutiva multi-objetivo (NSGA-II)
Optimiza código simultáneamente en **calidad, eficiencia y seguridad**.
Punto de entrada público: `mutalambda run` / `MutaLambdaCLI.run_evolution`
(`cli/main.py`); el motor interno `CoreEvolutionEngine` vive en
`mutalambda_core/evolution_engine.py`.

### 2. 🎮 GPU y paralelismo (opcional)
NSGA-II en CUDA vía PyTorch con escalado distribuido mediante Ray:
- **`gpu_optimizer.py`**: NSGA-II en GPU con mixed precision
- **`ray_scheduler.py`**: batch processing distribuido en cluster
- **Auto fallback**: detecta GPU disponible y degrada grácilmente a CPU

### 3. 🛡️ Code Intelligence — UAST v2
MutaLambda convierte código a un **UAST neutral** (nodos `Function`/`BinaryOp`/
`LiteralNode`…, el mismo esquema en Python, Rust, C++ y Go) y muta ahí, no en
el texto. Sobre los parsers específicos de cada lenguaje (`ast` de Python,
tree-sitter para el resto) se apoya el motor **UAST v2**, activable con una
sola bandera y con rollback trivial (`uast.engine: legacy`):

```yaml
uast:
  engine: v2      # legacy (por defecto) | v2
  shadow: true    # compara ambos motores y registra diffs (nunca falla)
  verify: true    # verificación tras cada nanopass (con rollback atómico)
```

- **Mutación in-situ**: arena con ids estables y parent pointers; los nanopasses
  escriben en el slot, sin reconstruir el árbol.
- **Nanopasses con verificación**: estructura, esquema, parent links, validador
  legacy, sanidad numérica, puerta de seguridad y fidelidad aritmética. Las
  guardas baratas se aplican solo al subárbol tocado (**27.7× más barato** que
  verificar el documento entero).
- **Hashes incrementales (Merkle)**: editar una hoja y re-hashear cuesta ~40×
  menos que el hash completo; clonar + re-hashear un candidato es **5.5× más
  rápido** que `deepcopy` + hash del motor legacy.
- **Persistencia plana**: msgpack + slab de referencias enteras → **4.0× más
  rápido** que JSON legacy y **0.44×** su tamaño (sin comprimir).
- **Paridad verificable**: `uast2 check` compara legacy vs v2 sobre un corpus y
  sale con código 2 si hay diferencias.

```bash
python mutalambda_cli.py uast2 check examples            # paridad legacy vs v2
python mutalambda_cli.py uast2 parse examples/target.py  # árbol + canonical_hash
python mutalambda_cli.py uast2 mutate examples/target.py --seed 42
python bench_uast2.py --reps 3                           # gates de rendimiento
```

Detalles, contrato de nanopasses y benchmarks: **[docs/uast2.md](docs/uast2.md)**.

### 4. 🔬 Validación Científica (SVL) + Hot-Path (opt-in)
La **Scientific Validation Layer (SVL)** es un **gate opt-in** del
`ProtocolWorkflow` que valida invariantes científicas antes del gate de
rendimiento. **Off por defecto** (`scientific.enabled: false` → PASS inmediato).
Familia de invariantes en `muta_ext/scientific/invariants.py`
(`BASE_INVARIANTS`; el score 0–1 se escribe en `EvalResult.scientific_score`):

- **Hard** (rechazan el candidato): `energy_non_negative` (E ≥ −1e-9),
  `mass_conservation` (|Δmass| < 1e-8), `numerical_stability` (NaN/Inf/overflow).
- **Soft** (penalan): `physical_bounds`, `monotonicity_trend` (entropía no
  decreciente).

**Orden de gates:**
`generate_candidate → build_gate → security_gate → api_gate → evaluate_candidate (sandbox) → tests_gate → differential_gate → scientific_validation → performance_gate → decision_gate`

- **Activación**:
  ```bash
  mutalambda run --source examples/target.py --tests examples/target_tests.json --scientific
  mutalambda run --config config.scientific.yaml -g 5
  mutalambda run --scientific --hotpath --scientific-strength 0.3 -g 50   # hotpath + dominio (cProfile)
  mutalambda scientific examples/target.py   # preset dedicado (SVL activo)
  ```
- **Config** (bloque `scientific:`, default `{}`). Plantilla incluida:
  `config.scientific.yaml`. Ver detalle en
  **[Scientific Optimization Mode](docs/SCIENTIFIC_OPTIMIZATION_MODE.md)**.
- **Cobertura de tests**: 84 funciones de test SVL (74 unitarios + 4
  integración + 6 extensión).

### 5. 📊 Benchmarking científico
Pipeline extendido de benchmarking (`bench_phase6.py`, `benchmarks/`):
evaluación multi-generación, reportes JSON reproducibles y comparación
GPU vs CPU con testing estadístico.

### 6. 📈 Meta-evolución
Capa de auto-mejora que evoluciona la propia configuración del sistema:
- **`prompt_evolution.py`** (`RichPromptEvolver`): metaevolución de poblaciones
  `PromptGenome`.
- **`mutalambda_engines/hfc_tiers.py`**: tiering horizontal de transferencia
  (HFC) y micro-mutadores memoizados.

### 7. 🌐 Orquestación multi-isla
Arquitectura multi-isla con transferencia horizontal y topologías configurables
(ring, fully connected, random, mesh, spatial grid):
- **`muta_lambda/agent.py`** (`MutaLambdaAgent.step_generation`): API de
  generación compartida (CLI/dashboard/núcleo).
- **`mutalambda_core/island_evolution.py`** (`IslandPool`): coordinación
  multi-isla con HFC.
- Integración con sistemas de observabilidad (OTel/Prometheus).

### 8. 🔬 Reproducibilidad
- Resultados reproducibles con seeds fijos (`rng_session.py`).
- Tracking de evolución en JSON y lineage de cada individuo.
- Validación cross-benchmark.

### 9. 💸 Capa de optimización de costo (Headroom)
Reducción de costo (tokens LLM + GPU) con **medición before/after obligatoria**
y **todas las palancas desactivables** por flag:

```yaml
# config/optimization.yaml  (override: MUTALAMBDA_OPT_<SECCION>__<CLAVE>=1|0)
# Solo la infraestructura de medición va activa por defecto (no cambia
# calidad ni costo); todas las palancas de costo/calidad están desactivadas.
optimization:
  cost_ledger:        { enabled: true,  gpu_hour_usd: 0.5 }   # tokens $ + GPU $
  checkpoint:         { every: 5 }                            # --resume-from
  fitness_cache:      { enabled: true, backend: sqlite }      # hash canónico
  deterministic_prompt:{ enabled: true }                     # gemelas byte-idénticas
  headroom:
    smart_crusher:    { enabled: false }      # tracebacks/logs → SmartCrusher/LogCompressor
    ast_stubs:        { enabled: false }      # stubs + headroom_retrieve(stub_id)
    json_schema_output:{ enabled: false }     # op_type/location/unified_diff/rationale
    batching:         { enabled: false, batch_size: 5 }  # N mutaciones por llamada
    bandit:           { enabled: false }      # reward = Δfitness/tokens (UCB)
  profiling_filter:                          # escalera de evaluación N1/N2/N3
    enabled:          false                  # off = comportamiento sin escalera
    profile_seconds:  10                     # profiling bajo carga ~10 s
    min_cpu_pct:      0.5                    # excluye funciones con <0.5% CPU
    nanopass_check:   { enabled: true }      # N1: guard UAST en memoria (<1 ms)
    test_subset:      { enabled: true, by_coverage: true, max_tests: 0 }  # N2 + set cover
    sandbox_top_pct:  20.0                   # N3: solo top ~20% → Docker + Ray
    api_policy:       strict
    uast2_enabled:    false
    ray_profile:      { enabled: false }
  economic_gate:
    enabled:            false
    delta_h_threshold:  0.005              # ΔH normalizado mínimo por generación
    stall_generations:  5                  # generaciones consecutivas → early stop
    gpu_seconds_per_generation: 0.0        # >0 activa el criterio de costo $GPU
    production_cpu_savings_hour_usd: 0.0   # $CPU/h que ahorra el candidato
  bandit_reward_usd:  { enabled: false }   # reward en $ reales (ledger)
  pareto_archive:
    enabled: false
    dir: "pareto_archive"
    warm_start: true           # --no-warm-start lo desactiva
    max_size: 50
```

- **Ledger de costo** (`cost_ledger.py`): interceptado centralmente en el
  wrapper LLM, el sandbox y la regression gate; `dump_json` por ejecución.
- **Medición (LLM simulado, 200 candidatos)**: input tokens **−95.5%**, output
  tokens **−55.5%**, reparación **±0pp** vs baseline, **100%** de propuestas con
  schema válido, **−80%** de llamadas (batching N=5). Ver
  `bench_headroom_fase1.py`.
- **Medición (120 mutantes, suite real de 12 tests, sandbox subprocess real)**:
  la escalera N1 → N2 → N3 reduce el tiempo de evaluación **−79.5% por
  mutante** (21.1 → 4.3 ms), las evaluaciones de sandbox **120 → 18** (solo
  **15%** toca N3, ≤20%), **0 falsos positivos** y N1 promedia **0.52 ms**
  (<1 ms). Ver `bench_headroom_fase2.py`.
  - `AmdahlHeadroomFilter` (`hotspot_profiler.py`): profiling bajo carga
    (~10 s) y exclusión de funciones con <0.5% de CPU de las regiones
    mutables. Fail-open: sin perfil, se incluye todo.
  - N1 (`tiered_evaluator.py`): nanopass en memoria — parse + fingerprint de
    API (strict/relaxed) + walk de seguridad sobre el mismo árbol (<1 ms).
  - N2: subset mínimo de tests por set cover / crecimiento guiado por
    cobertura, in-process si es puro, subprocess endurecido si I/O.
  - N3: solo el top ~20% de sobrevivientes de N2 paga el sandbox completo
    (Docker si hay engine, fail-closed a subprocess) + Ray opcional.
- **Medición (run_evolution real + evaluación subprocess real)**: el gate
  económico detuvo la corrida en **6 de 40 generaciones** (estancamiento de ΔH)
  con **−0.0% de pérdida de hipervolumen** (gate ≤2%); el warm-start del
  Pareto archive redujo las generaciones para converger **50%** en función
  similar (gate ≥30%); costo total acumulado de las palancas: **−97.2%** vs
  baseline (gate ≥60%; modelo compuesto de mediciones por palanca, documentado
  en el bench). Ver `bench_headroom_fase3.py`. `roi_report.json` por corrida:
  costo total (ledger), palancas activas, stop reason, hipervolumen final,
  warm-start y caché.

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MutaLambda v5.0.0                                │
├─────────────────────────────────────────────────────────────────────┤
│  CLI: mutalambda (Click, mutalambda_cli.py)                          │
│  ├── run / resume / mutate / uast2 / config / checkpoints          │
│  └── production / scientific / numpy / doctor / dashboard / ...      │
├─────────────────────────────────────────────────────────────────────┤
│  Paquetes núcleo (mutalambda_*)                                      │
│  ├── mutalambda_core/      — models, Island, evolución, filtros,     │
│  │                           differential, event bus, checkpoint     │
│  ├── mutalambda_engines/   — NSGA-II, fitness vector, tiered eval,   │
│  │                           archive, HFC tiers                      │
│  ├── mutalambda_config/    — MutaLambdaConfig (Pydantic), config     │
│  │                           loader, checkpoint manager              │
│  ├── mutalambda_security/  — api fingerprint, diagnostics            │
│  ├── muta_lambda/          — EvolveConfig + MutaLambdaAgent          │
│  ├── muta_ext/             — optimizer, UAST/UASTv2, scientific/     │
│  ├── cli/                  — entrypoints de la CLI                   │
│  └── lsp/                  — Language Server (VS Code / Neovim)      │
├─────────────────────────────────────────────────────────────────────┤
│  Módulos raíz (shims de compatibilidad + servicios)                  │
│  ├── sandbox.py            — evaluador con límites (subproc/ctr/mvm) │
│  ├── secure_exec.py        — pre-scan AST + builtins restringidos    │
│  ├── mutation_filters.py   — SecurityVisitor + filtros               │
│  ├── runners.py            — runners hardened                        │
│  ├── gpu_optimizer.py      — NSGA-II CUDA (PyTorch)                  │
│  ├── ray_scheduler.py      — batch distribuido (Ray)                 │
│  ├── cost_ledger.py        — ledger de costo $ tokens + GPU          │
│  ├── economic_gate.py      — gate económico (hipervolumen/costo)     │
│  ├── metrics_exporter.py   — Prometheus / OTel                       │
│  └── ... (ver pyproject.toml → [tool.setuptools])                    │
├─────────────────────────────────────────────────────────────────────┤
│  Infraestructura                                                     │
│  ├── tests/                 — ~1,040 funciones de test               │
│  ├── scripts/               — deploy, install, monitoring            │
│  ├── benchmarks/            — EffiBench, market-comparison, etc.     │
│  ├── presets/               — quick / production / scientific / numpy│
│  ├── config.scientific.yaml — plantilla SVL                          │
│  └── docs/                  — documentación                           │
└─────────────────────────────────────────────────────────────────────┘
```

## 🔐 Seguridad y Configuración

- **Sandbox fail-closed**: `sandbox.runner=microvm` exige `bwrap` y
  `sandbox.runner=container` exige Docker/Podman; si el motor no está
  disponible, la ejecución **aborta** (no degrada a un camino sin
  aislamiento). Con `MUTALAMBDA_REQUIRE_ISOLATION=1` el modo `subprocess`
  también queda prohibido.
- **Ejecución guardada**: los caminos `exec`/`eval`/`pickle` del proceso
  principal (diferencial, metrics-injector, benchmarks, scheduler Ray) pasan
  por `secure_exec.py`: pre-scan AST + builtins restringidos. El límite de
  aislamiento real sigue siendo el runner subprocess/container/microvm.
- **SCA bloqueante**: `pip-audit` audita el entorno en el PR gate y el
  workflow de package; Trivy escanea la imagen Docker antes del push.
- **Redacción de secretos en prompts**: `llm_backend.redact_prompt` elimina
  patrones de claves/tokens antes de enviar a un proveedor externo, y
  `privacy.allow_external_llm=false` impide inicializar backends externos.
- **API keys**: se pasan vía variables de entorno, nunca hardcodeadas en el
  repo.
- Ver detalle en [COMMERCIAL.md](COMMERCIAL.md) (modelo comercial y checklist
  de producción) y en [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md).

## 💻 CLI

La CLI principal es `mutalambda` (Click, `mutalambda_cli:cli` en
`pyproject.toml`). Los comandos canónicos:

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

Alternativas: `python -m muta_ext` (argparse) y `python -m muta_lambda`
(legacy). Ver `mutalambda_cli.py` para la lista de comandos/flags completa.

## Testing

```bash
# Suite principal
uv sync --extra cli --extra uast --extra dev
uv run pytest tests/ -q

# Lint & format (los mismos gates que CI)
uv run flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
uv run black --check . --line-length 100

# Coverage
uv run pytest tests/ --cov --cov-report=html

# E2E (script, no directorio)
MUTALAMBDA_E2E_SERIAL=1 python tests/e2e_tests.py --fast
```

**Estado**: suite verde en Python 3.10/3.11/3.12 (lint + tests + smoke en CI).
~1,040 funciones de test (ver `docs/ARTIFACTS/test_count.txt`; ~1,120 items
coleccionados incluyendo parametrización). La CI ejecuta la suite completa en
cada push/PR.

## 📊 Benchmarking Científico

MutaLambda valida su rendimiento contra benchmarks públicos reconocidos y
realiza comparativas de mercado.

### EffiBench Harness (TIER 1)
Pipeline reproducible con el dataset EffiBench (1000 tasks; 891 convertibles a
Python).
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
- **Métricas**: `ratio_to_canonical` (1.0 = baseline canónico), `%Opt`,
  `mean_speedup`, `correctness_rate`. El candidato queda gated por
  `correctness == 1.0` antes de contar speedup (`benchmarks/SMOKY_TESTS.md`).

### Market Comparison Harness
Integra providers LLM OpenAI-compatible (Agnes AI, Poolside) y herramientas de
mercado (Copilot, CodeWhisperer) para comparar MutaLambda head-to-head.
- **Smoke (sin keys)**:
  ```bash
  MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/market_comparison_harness.py --smoke --tasks 5 --tools mutalambda copilot codewhisperer
  ```
- **Con OpenRouter** (requiere `OPENROUTER_API_KEY`):
  ```bash
  export OPENROUTER_API_KEY="sk-or-v1-..."
  python benchmarks/market_comparison_harness.py --tasks 20 --tools mutalambda openrouter-gpt4o openrouter-claude copilot
  ```
- **Nota de reproducibilidad**: la métrica `ratio_to_canonical` no es
  determinista entre runs del mismo provider/seed (varianza del LLM, no del
  engine). El harness sí es reproducible: mismas tasks, mismos comandos.
- **Reportes**: `benchmarks/results_*.json` (gitignored, se regeneran en cada
  run). Ver `benchmarks/SMOKY_TESTS.md` para validación completa y
  `benchmarks/BENCHMARK_STRATEGY.md` para la metodología.

## Componentes

| Componente | Estado | Dónde |
|---|---|---|
| Optimizador multi-isla (NSGA-II) | ✅ | `mutalambda_core/`, `mutalambda_engines/` |
| Motor UAST v2 (opt-in, shadow parity) | ✅ | `muta_ext/uast2/`, [docs/uast2.md](docs/uast2.md) |
| SVL + hotpath (opt-in) | ✅ | `muta_ext/scientific/` |
| Capa Headroom (palancas desactivables) | ✅ | `config/optimization.yaml`, `cost_ledger.py` |
| Sandbox fail-closed (container/microvm) | ✅ | `sandbox.py`, `secure_exec.py` |
| GPU (PyTorch) + Ray (distribuido) | ✅ opcional | `gpu_optimizer.py`, `ray_scheduler.py` |
| CLI `mutalambda` (Click) | ✅ | `mutalambda_cli.py`, `cli/` |
| LSP server (VS Code / Neovim) | ✅ | `lsp/` |
| Metrics exporter (Prometheus/OTel) | ✅ opt-in | `metrics_exporter.py`, [docs/metrics-exporter.md](docs/metrics-exporter.md) |
| Imagen Docker multi-stage + SLSA provenance | ✅ | `Dockerfile`, `.github/workflows/` |

## Documentación

- [Getting started — primera optimización](docs/getting-started/first-optimization.md)
- [Arquitectura v2](docs/architecture_v2.md)
- [UAST v2 (motor de mutación in-situ)](docs/uast2.md)
- [Scientific Optimization Mode (SVL)](docs/SCIENTIFIC_OPTIMIZATION_MODE.md)
- [Fitness metrics](docs/FITNESS_METRICS.md)
- [Metrics](docs/METRICS.md) · [Metrics exporter](docs/metrics-exporter.md)
- [GPU Integration](docs/gpu_integration.md)
- [Config reference](docs/config-reference.md) · [API reference](docs/api-reference.md) · [Advanced usage](docs/advanced-usage.md)
- [Pipeline](docs/pipeline.md) · [Migration guide](docs/migration_guide.md)
- [Testing guide](docs/testing_guide.md) · [Test execution protocol](docs/TEST_EXECUTION_PROTOCOL.md)
- [Troubleshooting](docs/troubleshooting.md) · [Deployment guide](docs/deployment_guide.md)
- [Production checklist](docs/PRODUCTION_CHECKLIST.md)
- [CLI reference](docs/CLI.md) (también `mutalambda <cmd> --help`)
- [Decision records (ADR)](docs/decisions/)

## Roadmap

- [ ] Graduación de UAST v2: `uast.engine: v2` como motor por defecto del pipeline evolutivo
- [ ] Migración a src-layout (el layout plano actual se mantiene por compatibilidad de imports)
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
  title = {MutaLambda: Evolutionary Multi-Island Code Optimization Framework},
  year = {2026},
  url = {https://github.com/Adlgr87/MutaLambda},
  version = {5.0.0}
}
```
