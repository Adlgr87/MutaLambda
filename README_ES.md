# MutaLambda: Sistema de Optimización Evolutiva de Código

<div align="center">

**Mejoras de Rendimiento Validadas mediante Optimización Evolutiva**

[![Rendimiento](https://img.shields.io/badge/Rendimiento-50--263%25%20speedup-blue)]()
[![Módulos](https://img.shields.io/badge/Módulos-5%20optimizados-orange)]()
[![Correctitud](https://img.shields.io/badge/Correctitud-149%2F149%20tests-green)]()
[![CLI](https://img.shields.io/badge/CLI-v3.1.0-orange)]()
[![Estado](https://img.shields.io/badge/Estado-Listo%20para%20Producción-success)]()

**[English](README.md)** | **Español**

</div>

---

## 🎯 Descripción General

MutaLambda es un sistema de optimización evolutiva de código que utiliza Modelos de Lenguaje Grande (LLMs) para mejorar automáticamente componentes críticos de rendimiento en software científico. El sistema emplea algoritmos genéticos con mutaciones basadas en AST para evolucionar funciones Python hacia mejor rendimiento manteniendo la correctitud.

### Logros Clave

✅ **Integración con MASSIVE Framework** — 50-263% de speedup en 4 módulos científicos, 100% correctitud
✅ **Optimización de `_get_fitness()`** — +10.2% de speedup validado con 149/149 tests pasando
✅ **CLI Interactiva** — Interfaz de línea de comandos completa con animaciones retro
✅ **Sistema de Checkpoints** — Guarda y reanuda ejecuciones evolutivas sin problemas

---

## 📊 Optimizaciones Validadas

### MASSIVE Framework — 50-263% de speedup

MutaLambda fue aplicado exitosamente al framework de simulación cosmológica **MASSIVE**, logrando mejoras significativas de rendimiento manteniendo el 100% de correctitud científica.

| Módulo | Speedup | Impacto |
|--------|---------|---------|
| **utility_logic** | **3.6x más rápido** | Cálculos de presión social |
| **energy_engine_pure** | **2.3x más rápido** | Motor termodinámico de energía |
| **social_architect_pure** | **1.5x más rápido** | Análisis de polarización |
| **intervention_optimizer** | **25.8% más simple** | Optimización de estrategias (reducción de código) |

**Impacto en el mundo real:**
- **35% más rápido** runtime de simulación (10K+ agentes)
- **60% más rápido** experimentos a gran escala (50K agentes)
- **50% más rápido** analítica en tiempo real

**Rigor estadístico:**
- Nivel de confianza: 95%
- P-value: < 0.001 para todas las mejoras
- Tamaño del efecto: Grande (Cohen's d > 0.8)
- Iteraciones: 1,000 ejecuciones por módulo

**Metodología de validación:**
- Equivalencia numérica: ε < 1e-10
- Unit tests: 100% tasa de éxito
- Testing de integración: Resultados de simulación idénticos
- Revisión por pares: Aprobación de experto de dominio

### `_get_fitness()` — +10.2% de speedup

**Problema:** La función auxiliar `_get_fitness()` se llama O(N²) veces durante la selección NSGA-II. Extrae un `FitnessVector` de un `Individual`, verificando si existe el atributo `.fitness`.

**Solución:** Reemplazar la verificación `hasattr()` con `getattr()` usando `None` por defecto. Esto evita el overhead de doble búsqueda de atributo.

```python
# Antes
def _get_fitness(ind: Individual) -> FitnessVector:
    if hasattr(ind, 'fitness') and ind.fitness is not None:
        return ind.fitness
    return FitnessVector(
        correctness=max(0.0, min(1.0, ind.score / 100.0)),
        parsimony=0.5,
    )

# Después
def _get_fitness(ind: Individual) -> FitnessVector:
    fitness = getattr(ind, 'fitness', None)
    if fitness is not None:
        return fitness
    return FitnessVector(
        correctness=max(0.0, min(1.0, ind.score / 100.0)),
        parsimony=0.5,
    )
```

**Impacto:** ~17 segundos ahorrados por ejecución evolutiva típica (50 generaciones, 4 islas, 32 individuos).

**Validación:** 13/13 tests de nsga2, 14/14 tests de fitness_vector, 149/149 tests totales ✅

---

## 🏗️ Arquitectura

```
cli.py                         Punto de entrada CLI (Click)
└── cli/                       Paquete CLI
    ├── main.py                Lógica principal: MutaLambdaCLI, InteractiveREPL
    ├── animator.py            Animaciones retro (ASCII art, barras de progreso)
    ├── config_manager.py      Gestión de configuraciones (plantillas: basic/advanced/research)
    └── checkpoint_manager.py  Gestión de checkpoints (pickle + gzip)

muta_lambda.py                 Orquestador principal — conecta todos los módulos
├── models.py                  Datos: Individual, FitnessVector, LineageGraph, PromptGenome
├── evolution_engine.py        Mutaciones AST + generación LLM (ASTMutator, CoreEvolutionEngine)
├── island.py                  Unidad de evolución por isla (población + workflow protocolar)
├── island_evolution.py        Coordinador paralelo: IslandPool (hilos/procesos), IslandDiversity
├── migration.py               Bus de migración inter-islas (ring, fully_connected, mesh)
├── sandbox.py                 Evaluación en subproceso con límites duros (timeout, memoria)
├── archive.py                 SolutionArchive (deduplicación semántica con FAISS, opcional)
├── nsga2.py                   Selección multi-objetivo NSGA-II (frentes Pareto + distancia crowding)
├── fitness_vector.py          Vector 6 objetivos: correctness, latency_p50, latency_p99, throughput,
│                                  memory_peak_mb, parsimony
├── hfc_tiers.py               Especiación HFC por niveles: Laboratorio → Fábrica → Élite
├── workflow_protocol.py       Gates secuenciales: build → security → sandbox → tests → perf → decisión
├── interpretability.py        Salvaguardas de interpretabilidad (3 capas) para código auto-evolucionado
├── llm_backend.py             Adaptadores LLM: ollama, openai, anthropic, openrouter, mistral
├── prompt_evolver.py          Evolución básica de PromptGenome
├── prompt_evolution.py        RichPromptEvolver — 15 operadores de mutación + crossover
├── config_loader.py           Cargador declarativo de configuración YAML con validación
├── checkpoint_manager.py      Guardado y reanudación de checkpoints (pickle + gzip)
└── property_testing.py        Harness de property-based testing

muta_ext/                      Extensiones y subsistemas avanzados
├── advanced_selection.py      Selección multi-armed bandit: UCB, Thompson Sampling, ε-greedy
├── dialectic_engine.py        Filtro LLM pre-sandbox: Tesis → Crítica → Síntesis
├── pattern_memory.py          Memoria de patrones AST reutilizables
├── spatial_topology.py        Grid 2D (Moore/Von Neumann) para migración local estructurada
├── thc_engine.py              Transferencia Horizontal de Código (extracción + inyección de fragmentos)
├── config/
│   └── scientific_extension.py  Config de extensión científica
├── diagnostics/
│   ├── evolution_report.py    Entropía de Shannon, exponente de Lyapunov, estabilidad espectral
│   └── tipping.py             Detección de tipping points / transiciones de fase
├── evaluation/
│   ├── cache.py               Caché de evaluación por hash AST canónico
│   └── numerical_health.py    Comprobaciones de salud numérica
├── lineage/
│   └── compression.py         Compresión del DAG genealógico para runs largos
└── mutation/
    └── stepper_protocol.py    Protocolo de steppers de mutación composables (patrón Strategy)

tests/
├── benchmarks/                Suite de benchmarks de rendimiento
└── test_*.py                  Tests unitarios (149 en total)
```

---

## 🔄 Flujo de Ejecución

### Workflow protocolar por candidato

Cada candidato generado pasa por un pipeline obligatorio antes de ser promovido:

```text
seleccionar padre(s) élite
  -> generar candidato (mutación AST o prompt LLM)
  -> gate de build (parse + compilación)
  -> gate de seguridad (bloquea eval/exec/compile/os.system/subprocess.*)
  -> evaluación en sandbox (subproceso con límite de tiempo y memoria)
  -> gate de tests/correctitud (umbral configurable, por defecto 100%)
  -> gate de rendimiento
  -> gate de decisión (promover / reintentar / rechazar)
```

Notas operacionales:
- cada ejecución tiene un `run_id`; trazas recientes disponibles en `agent.get_metrics()["protocol"]`
- fallos reintentables vuelven automáticamente a una mutación AST más segura
- el gate de seguridad bloquea `eval`, `exec`, `compile`, `__import__`, `os.system` y `subprocess.*`
- el workflow se configura con la clave `workflow:` en `config.yaml`

---

## ⚙️ Funcionalidades Avanzadas

### HFC — Competencia Jerárquica (`hfc_tiers.py`)

Especiación en tres niveles para evitar convergencia prematura:

| Nivel | Nombre | Rol |
|-------|--------|-----|
| 1 | **Laboratorio** | Exploración caótica — crossover LLM + mutación AST completa |
| 2 | **Fábrica** | Reproducción bacteriana (1 → λ clones) con micro-mutadores |
| 3 | **Élite** | Frontera de Pareto estática — solo por promoción |

La destilación top-down extrae conceptos élite y los reinyecta en el Laboratorio. La promoción exige 100% de correctitud por defecto.

### Convergent Evolution Boost

Cuando varias islas convergen en código similar (similitud coseno ≥ umbral), el sistema amplifica el score multiplicativamente (`score *= 1 + factor × similitud`).

### Resurrección — Backtracking Temporal

Tras N generaciones estancadas, el motor revive la mejor rama abandonada del DAG genealógico. Máximo 3 intentos por ejecución (configurable).

### Crossover entre Ramas

Individuos separados ≥ 3 saltos genealógicos pueden cruzarse, inyectando diversidad. Probabilidad: 5% por descendiente.

### THC — Transferencia Horizontal de Código (`muta_ext/thc_engine.py`)

Extrae fragmentos AST de individuos de alto rendimiento y los inyecta en individuos no relacionados (análogo a la transferencia génica horizontal bacteriana).

### Motor Dialéctico (`muta_ext/dialectic_engine.py`)

Antes del sandbox, el código candidato pasa por:
1. **Tesis** — mutación propuesta
2. **Crítica** — el LLM identifica problemas de correctitud / seguridad
3. **Síntesis** — el LLM reescribe incorporando la crítica

Ahorra llamadas al sandbox rechazando candidatos inválidos sintácticamente de forma temprana.

### Selección Avanzada (`muta_ext/advanced_selection.py`)

Estrategias multi-armed bandit para selección de operadores por isla:
- **UCB** (Upper Confidence Bound)
- **Thompson Sampling**
- **ε-greedy**

Combina scores de fitness + novedad + entropía + descubrimiento.

### Topología Espacial (`muta_ext/spatial_topology.py`)

Organiza las islas en un grid 2D. La migración solo ocurre entre vecinos geográficos (vecindad Moore o Von Neumann).

### Caché de Evaluación (`muta_ext/evaluation/cache.py`)

Cachea resultados de fitness por hash AST canónico (independiente de nombres de variables y espaciado). Si una mutación produce código estructuralmente idéntico a uno ya evaluado, devuelve el `FitnessVector` cacheado sin ejecutar el sandbox.

---

## 🤖 Backends LLM

MutaLambda soporta múltiples proveedores LLM, configurados con `llm.backend` en `config.yaml` o variables de entorno `MUTALAMBDA_*`:

| Backend | Clave | Notas |
|---------|-------|-------|
| **Ollama** | `ollama` | Por defecto — servidor de modelos local |
| **OpenAI** | `openai` | Requiere `OPENAI_API_KEY` |
| **Anthropic** | `anthropic` | Requiere `ANTHROPIC_API_KEY` |
| **OpenRouter** | `openrouter` | Requiere `OPENROUTER_API_KEY` |
| **Mistral** | `mistral` | Requiere `MISTRAL_API_KEY` |

Variables de entorno: `MUTALAMBDA_OLLAMA_URL`, `MUTALAMBDA_OPENAI_URL`, `MUTALAMBDA_LLM_TIMEOUT_SEC`, `MUTALAMBDA_LLM_TEMPERATURE`.

## 📚 Lecciones Aprendidas

### 1. Medir Antes y Después

Nunca asumas que una optimización ayuda — haz benchmark. Intentamos varias optimizaciones que en realidad **degradaron** el rendimiento:

- Loop unrolling de `dominates()`: **-15.6%** rendimiento (revertido)
- Fast path de `weighted_sum()`: **-13.4%** rendimiento (revertido)
- Migración dirigida por fitness: **57.6%** tasa de éxito vs **92.2%** de topología ring (revertido)

### 2. La Simplicidad Vence a la Complejidad

La topología ring (92.2% éxito) superó a nuestro sistema de migración basado en gradientes (57.6%). El algoritmo más simple fue más efectivo porque:

- Flujo genético predecible
- Sin overhead de lógica de selección compleja
- Mejor preservación de diversidad

### 3. Los Built-ins de Python Son Rápidos

`zip()`, `all()`, `any()` están implementados en C y suelen ser más rápidos que alternativas manuales. Nuestros intentos de "optimizar" `dominates()` con asignaciones explícitas de variables en realidad agregaron overhead.

### 4. La Validación Es No-Negociable

La medición de rendimiento sin validación de correctitud produce falsos positivos. Vimos mutaciones AST producir **speedups de +97% y +100%** que en realidad eran bugs semánticos:

- Errores off-by-one que hacían funciones retornar temprano
- Individuos faltantes en frentes de población
- Relaciones de dominancia incorrectas

### 5. Las Mejoras Pequeñas Se Acumulan

Un speedup de 10.2% en un hot path ahorra 17 segundos por ejecución evolutiva. En 100 ejecuciones, son **28 minutos ahorrados**. Las mejoras pequeñas y validadas valen la pena.

---

## 🚀 Inicio Rápido

### Instalación

```bash
git clone https://github.com/Adlgr87/MutaLambda
cd MutaLambda
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Ejecutar Tests

```bash
python -m pytest tests/ -v
```

Todos los 149 tests deben pasar.

### Ejecutar CLI

```bash
# Ver ayuda general
python cli.py --help

# Ejecutar evolución con configuración
python cli.py run --config config.yaml --generations 50

# Crear configuración desde plantilla
python cli.py config create --output config.yaml --template basic

# Reanudar desde checkpoint
python cli.py resume --checkpoint checkpoints/gen_50.json --additional-gens 30

# Modo interactivo
python cli.py interactive
```

---

## 🖥️ Interfaz de Línea de Comandos (CLI)

MutaLambda incluye una CLI completa con animaciones retro, gestión de configuraciones y checkpoints.

### Comandos Disponibles

| Comando | Descripción |
|---------|-------------|
| `run` | Ejecutar corrida evolutiva completa |
| `resume` | Reanudar evolución desde checkpoint |
| `config create` | Crear configuración desde plantilla |
| `config validate` | Validar archivo de configuración |
| `config show` | Mostrar resumen de configuración |
| `stats` | Mostrar estadísticas de ejecuciones anteriores |
| `evaluate` | Evaluar y resumir resultados |
| `mutate` | Operaciones de mutación (prompts, operadores, hiperparámetros) |
| `interactive` | Modo interactivo tipo REPL |
| `checkpoints` | Gestionar checkpoints |

### Ejemplos de Uso

**Ejecutar evolución con animaciones retro:**
```bash
python cli.py run --config config.yaml --generations 100 --animation retro
```

**Crear configuración avanzada:**
```bash
python cli.py config create --output advanced.yaml --template advanced
```

**Reanudar desde checkpoint:**
```bash
python cli.py resume --checkpoint checkpoints/checkpoint_0050.json --additional-gens 50
```

**Modo interactivo:**
```bash
python cli.py interactive
```

### Plantillas de Configuración

La CLI incluye tres plantillas predefinidas:

- **basic** — Configuración mínima para pruebas rápidas (50 generaciones, 4 islas)
- **advanced** — Configuración para producción (100 generaciones, 8 islas, fully_connected)
- **research** — Configuración experimental (200 generaciones, 12 islas, tracking completo)

### Gestión de Checkpoints

Los checkpoints se guardan automáticamente cada N generaciones (configurable):

```bash
# Listar checkpoints disponibles
python cli.py checkpoints --list

# Limpiar checkpoints antiguos
python cli.py checkpoints --clean --max-age 7

# Reanudar desde checkpoint específico
python cli.py resume --checkpoint checkpoints/checkpoint_0050.json --additional-gens 30
```

**Documentación completa:** [docs/CLI.md](docs/CLI.md)

---

## 🔬 Metodología

### Proceso de Optimización

1. **Identificar hot paths** — Perfilar código para encontrar funciones llamadas frecuentemente
2. **Benchmark baseline** — Medir rendimiento actual con rigor estadístico
3. **Aplicar mutaciones** — Usar transformaciones AST (loop unrolling, variable inlining, etc.)
4. **Validar correctitud** — Asegurar que outputs sean idénticos (ε < 1e-10)
5. **Medir mejora** — Solo integrar si el speedup es real y validado

### Requisitos de Validación

- ✅ Equivalencia numérica: ε < 1e-10
- ✅ Unit tests: 100% tasa de éxito
- ✅ Testing de integración: Resultados idénticos
- ✅ Mejora de rendimiento: Estadísticamente significativa (p < 0.05)

---

## 📖 Documentación

### Documentación de Usuario

- **[docs/CLI.md](docs/CLI.md)** — Guía completa de la CLI: comandos, configuración, checkpoints, modo interactivo
- **[docs/METRICS.md](docs/METRICS.md)** — Métricas de rendimiento, benchmarks validados y análisis de eficiencia

### Documentación del Núcleo

- **[EMPIRICAL_EVIDENCE.md](EMPIRICAL_EVIDENCE.md)** — Reporte comprensivo de optimizaciones validadas y experimentos fallidos
- **[PLANS/AUTO_IMPROVEMENT_PLAN.md](PLANS/AUTO_IMPROVEMENT_PLAN.md)** — Plan de auto-mejora en 6 fases

### Documentación del Código

- **`nsga2.py`** — Selección multi-objetivo NSGA-II con `_get_fitness()` optimizado
- **`fitness_vector.py`** — 6 objetivos de fitness: correctness, latency_p50, latency_p99, throughput, memory_peak_mb, parsimony
- **`interpretability.py`** — Salvaguardas de 3 capas contra "código alienígena" de auto-mejora recursiva
- **`workflow_protocol.py`** — Gates protocolar, `ProtocolWorkflow`, `ProtocolTrace`, escáner de seguridad
- **`hfc_tiers.py`** — Especiación HFC en tres niveles (Laboratorio / Fábrica / Élite)
- **`island_evolution.py`** — Coordinador paralelo `IslandPool` con métricas de diversidad
- **`cli/main.py`** — Lógica principal de la CLI con integración al core evolutivo

---

## 🎓 Ideas Clave

### Qué Funciona

✅ **Optimizaciones pequeñas y dirigidas** en hot paths
✅ **`getattr()` en vez de `hasattr()`** para acceso a atributos
✅ **Algoritmos simples** (topología ring) sobre complejos (migración por gradientes)
✅ **Validación rigurosa** antes de integración
✅ **Benchmarking honesto** con mediciones antes/después

### Qué No Funciona

❌ **Mutaciones AST agresivas** sin validación semántica
❌ **Sistemas complejos "inteligentes"** que superan alternativas simples
❌ **Loop unrolling** en Python (optimizaciones de nivel C no aplican)
❌ **Optimización prematura** sin medición
❌ **Despliegue automático** de código evolucionado sin revisión humana

---

## 🤝 Contribuir

### Agregar Optimizaciones

1. Identificar un hot path con profiling
2. Benchmark del rendimiento baseline
3. Aplicar optimización
4. Validar correctitud (todos los tests deben pasar)
5. Medir mejora (debe ser estadísticamente significativa)
6. Actualizar EMPIRICAL_EVIDENCE.md con resultados
7. Enviar pull request con benchmarks

### Reportar Problemas

Si encuentras una regresión de rendimiento o problema de correctitud:

1. Ejecutar `python -m pytest tests/ -v` para confirmar
2. Verificar EMPIRICAL_EVIDENCE.md para limitaciones conocidas
3. Abrir issue con pasos de reproducción

---

## 📄 Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para detalles.

---

## 🙏 Agradecimientos

- **Algoritmo NSGA-II** — Deb et al., 2002
- **Módulo AST de Python** — Librería estándar
- **Framework Pytest** — Infraestructura de testing
- **Docker** — Ejecución en sandbox seguro
- **Framework Click** — Infraestructura CLI
- **Librería Rich** — Componentes de UI de terminal

---

## 📊 Estado del Proyecto

**Versión:** 3.1.0 (CLI)
**Última Actualización:** 2026-07-12
**Mantenedor:** Equipo de Desarrollo MutaLambda

### Capacidades Actuales

✅ **Evolución multi-objetivo** con selección NSGA-II (6 objetivos: correctness, latency_p50, latency_p99, throughput, memory_peak_mb, parsimony)
✅ **Evaluación en sandbox seguro** con aislamiento en subproceso con límites duros
✅ **CLI interactiva** con animaciones retro y gestión de checkpoints
✅ **Optimizaciones validadas** con cobertura de tests comprehensiva (149/149 tests)
✅ **Salvaguardas de interpretabilidad** para trabajo futuro de auto-evolución
✅ **Sistema de checkpoints** para reanudar ejecuciones largas
✅ **Plantillas de configuración** para diferentes casos de uso (basic/advanced/research)
✅ **Workflow protocolar** con gates secuenciales (build → security → sandbox → tests → perf)
✅ **Niveles HFC** — especiación Laboratorio / Fábrica / Élite (opt-in)
✅ **Convergent Evolution Boost** — amplificación de score para islas convergentes
✅ **Resurrección** — backtracking temporal para revivir ramas del linaje abandonadas
✅ **Crossover entre ramas** — inyección de diversidad desde individuos genealógicamente distantes
✅ **Múltiples backends LLM** — ollama, openai, anthropic, openrouter, mistral
✅ **Motor Dialéctico** — filtro tesis/crítica/síntesis pre-sandbox (opt-in)
✅ **Transferencia Horizontal de Código (THC)** — extracción e inyección de fragmentos (opt-in)
✅ **Caché de evaluación** — caché por hash AST canónico para evitar llamadas redundantes al sandbox

### Mejoras de Rendimiento Validadas

| Componente | Optimización | Speedup | Estado |
|-----------|-------------|---------|--------|
| **MASSIVE Framework** | 4 módulos optimizados | **50-263%** | ✅ Producción |
| `_get_fitness()` | `getattr()` en vez de `hasattr()` | **+10.2%** | ✅ Producción |
| Topología ring | Patrón de migración simple | **92.2% éxito** | ✅ Producción |
| Selección NSGA-II | Hot paths optimizados | **Validado** | ✅ Producción |

### Experimentos Fallidos (Revertidos)

❌ Migración dirigida por fitness (57.6% éxito vs 92.2% ring)
❌ Loop unrolling de `dominates()` (-15.6% rendimiento)
❌ Fast path de `weighted_sum()` (-13.4% rendimiento)
❌ Mutaciones AST agresivas (bugs semánticos)

### Roadmap

- [ ] Testing de integración con funciones Python del mundo real
- [ ] Suite de benchmarks extendida para workloads diversos
- [ ] Dashboard web para monitoreo de ejecuciones evolutivas
- [ ] Evolución distribuida entre múltiples máquinas

---

## 🌐 Soporte Multi-Lenguaje (UAST)

MutaLambda soporta optimización evolutiva para múltiples lenguajes a través de la capa de abstracción Universal AST (UAST).

### Lenguajes Soportados

| Lenguaje | Adaptador | Emisor | Handler | Estado |
|----------|-----------|--------|---------|--------|
| Python   | ✅        | ✅     | ✅      | Producción |
| Rust     | ✅        | ✅     | ✅      | Beta |
| C++      | ✅        | ✅     | ✅      | Beta |

### Inicio Rápido

```bash
# Optimizar código Python
python cli.py uast run --config muta_ext/uast/config/python_uast_template.yaml \
    --code mi_codigo.py --generations 50

# Optimizar código Rust
python cli.py uast run --config muta_ext/uast/config/rust_template.yaml \
    --code mi_codigo.rs --generations 50

# Optimizar código C++
python cli.py uast run --config muta_ext/uast/config/cpp_template.yaml \
    --code mi_codigo.cpp --generations 50
```

### Nuevos Nodos CoreUAST

- `TryExcept` / `ExceptClause` — Manejo de excepciones
- `StructDef` / `FieldDef` — Definiciones de struct/clase
- `TypeAnnotation` — Anotaciones de tipo
- `Match` / `MatchArm` — Coincidencia de patrones
- `Reference` — Referencias y punteros

### Limitaciones

Ver [muta_ext/uast/LIMITATIONS.md](muta_ext/uast/LIMITATIONS.md) para limitaciones detalladas por lenguaje.

---

## 📈 Resumen de Métricas

**Total de optimizaciones intentadas:** 11
**Mejoras validadas:** 5 (MASSIVE: 4 módulos, Core: 1 función)
**Experimentos fallidos:** 4 (revertidos)
**Tests pasando:** 252/252 (100%) - *Actualizado con soporte multi-lenguaje UAST*

**Impacto en ejecuciones de producción:**
- MASSIVE: **35-60% más rápido** runtime de simulación
- Core: Ahorra ~17 segundos por ejecución evolutiva (50 generaciones, 4 islas, 32 individuos)
- En 100 ejecuciones: **28 minutos ahorrados**
- Se acumula en todos los experimentos evolutivos futuros

**Métricas detalladas:** [docs/METRICS.md](docs/METRICS.md)

**Impacto en ejecuciones de producción:**
- MASSIVE: **35-60% más rápido** runtime de simulación
- Core: Ahorra ~17 segundos por ejecución evolutiva (50 generaciones, 4 islas, 32 individuos)
- En 100 ejecuciones: **28 minutos ahorrados**
- Se acumula en todos los experimentos evolutivos futuros

**Métricas detalladas:** [docs/METRICS.md](docs/METRICS.md)

---

<div align="center">

**Construido con algoritmos evolutivos, validado con evidencia empírica.**

[Reportar Bug](https://github.com/Adlgr87/MutaLambda/issues) · [Solicitar Funcionalidad](https://github.com/Adlgr87/MutaLambda/issues)

</div>
