# MutaLambda

<div align="center">

**Optimización evolutiva de código en la que puedes confiar.**

*Los LLMs proponen. Los algoritmos genéticos exploran. Los gates de correctitud deciden.*

[![Tests](https://img.shields.io/badge/tests-483%20passing-brightgreen)]()
[![Versión](https://img.shields.io/badge/versi%C3%B3n-4.0.0-blue)]()
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)]()
[![Licencia](https://img.shields.io/badge/licencia-BUSL--1.1-orange)](LICENSE)
[![Auto-Optimizado](https://img.shields.io/badge/auto--optimizado-1.49x%20%7C%201.76x-purple)](SELF_EVOLUTION_REPORT.md)

**[English](README.md)** | **Español**

</div>

---

MutaLambda es un sistema de optimización evolutiva de código: combina **candidatos generados por LLMs** con **búsqueda genética multi-objetivo (NSGA-II)** para hacer tu código más rápido — y se niega a entregar cualquier cosa que no pueda *probar* que sigue siendo correcta. **Python es el objetivo de producción**; Rust, C++ y Go tienen soporte experimental a través de una capa de AST Universal (ver [soporte de lenguajes](#soporte-de-lenguajes)).

```
tu código ─▶ Discovery ─▶ Síntesis de Tests ─▶ Modo Fast ─▶ Evolución Profunda ─▶ Patch
             profiling +   tests de propiedad   5 variantes   NSGA-II en islas      diff estilo git
             hotspots      auto-generados       LLM           paralelas             + reporte métrico

cada candidato debe sobrevivir el guantelete:
  build ▶ escaneo de seguridad ▶ sandbox (límites duros) ▶ oráculo de correctitud ▶ benchmark honesto
  ...solo entonces compite en la selección de Pareto. Un candidato rápido-pero-incorrecto
  no se "penaliza" — se descarta. La correctitud es un gate, no un puntaje.
```

## Pruebas, no promesas

Aplicamos MutaLambda a **su propio código fuente**, a través de sus propios gates de producción. Todo lo siguiente es reproducible desde [`experiments/`](experiments/):

| Objetivo auto-optimizado | Nivel función | End-to-end | Verificado por |
|---|---|---|---|
| `nsga2._crowding_distance` | **1.49×** gmean (1.88× en frentes grandes) | +5–9% ciclo NSGA-II completo | oráculo diferencial, 74 poblaciones aleatorizadas, equivalencia exacta |
| `ASTMutator.apply_random_mutation` | **1.76×** gmean | **1.48×** loop de mutación | oráculo sembrado: salidas byte-idénticas, corpus de 7 archivos × 30 semillas |

En el camino pasaron tres cosas que dicen más que los speedups:

1. **Los gates rechazaron 28 candidatos que eran *más rápidos pero incorrectos*.** Una función de fitness que solo puntúa la correctitud los habría entregado.
2. **El gate de benchmark atrapó una "victoria" de 2× que escondía una pérdida de 3.6×** en entradas pequeñas — el caso común. La optimización fusionada es un híbrido por talla porque los *datos* lo dictaron.
3. **El escáner de seguridad bloqueó a uno de nuestros propios candidatos** (una vía de copia basada en pickle — un primitivo de deserialización). Los gates mandan sobre el optimizador. Como debe ser.

Aplicado a código externo (framework de simulación multi-agente [MASSIVE](EMPIRICAL_EVIDENCE.md)): speedups de **3.6× / 2.3× / 1.5×** y una reducción de código del 25.8%, con 100% de correctitud (ε < 1e-10, 1,000 corridas por módulo, p < 0.001).

Cada experimento que corremos — incluidos los fracasos, las "optimizaciones" revertidas y los artefactos de medición que atrapamos — queda en el registro: [**SELF_EVOLUTION_REPORT.md**](SELF_EVOLUTION_REPORT.md) (ledger de victorias y derrotas) y [**EMPIRICAL_EVIDENCE.md**](EMPIRICAL_EVIDENCE.md). En este campo, el optimizador que documenta sus derrotas es al que puedes creerle sus victorias.

## ¿Por qué no usar un clon de AlphaEvolve?

Los frameworks open source estilo AlphaEvolve optimizan para *descubrir*. MutaLambda optimiza para **código de producción confiable**. La diferencia es verificación en cada paso:

| Garantía | MutaLambda | Framework típico estilo AlphaEvolve |
|---|---|---|
| **Correctitud como gate duro** — rápido-pero-incorrecto se descarta, nunca se rankea | ✅ | ❌ recompensa escalar; la correctitud es solo un puntaje |
| **Evaluación en sandbox** con timeout y límites de memoria duros por candidato | ✅ | ⚠️ varía, a menudo en el mismo proceso |
| **Filtros de seguridad de mutación** (bloquea eval/exec/subprocess/aliasing/deserialización) | ✅ | ❌ |
| **Verificación algebraica anti-alucinación** (SymPy + verificador matemático AST) | ✅ | ❌ |
| **Invariantes de dominio científico** (conservación de energía, balance de masa, monotonía) | ✅ | ❌ |
| **Gates secuenciales de workflow**: build → seguridad → sandbox → tests → perf → decisión | ✅ | ❌ |
| **Fitness Pareto multi-objetivo** (correctitud, latencia P50/P99, throughput, memoria, parsimonia) | ✅ NSGA-II | ⚠️ mayormente mono-objetivo |
| **Mutación estructural multi-lenguaje** (Rust, C++, Go vía UAST — experimental) | ⚠️ subconjunto conservador | ⚠️ mayormente solo Python |
| **Probado sobre sí mismo**, gates incluidos, derrotas documentadas | ✅ | ❌ |

Si necesitas *explorar* el espacio de algoritmos, esas herramientas están bien. Si necesitas llevar una función optimizada a producción **con evidencia de que sigue siendo correcta**, para eso está construido MutaLambda.

## Inicio rápido

```bash
git clone https://github.com/Adlgr87/MutaLambda.git
cd MutaLambda
pip install -e .            # instala la CLI `mutalambda` (layout src/)

# Optimizar un script (LLM local vía Ollama — sin API key)
python muta_lambda.py --optimize mi_script.py

# Solo modo fast: 5 variantes LLM, evaluación paralela en sandbox
python muta_lambda.py --optimize mi_script.py --mode fast

# Evolución profunda: NSGA-II en islas paralelas
python muta_lambda.py --optimize mi_script.py --mode deep

# Reanudar una corrida interrumpida desde checkpoint
python muta_lambda.py --resume checkpoints/run_xxx

# CLI interactiva (plantillas de config, checkpoints, doctor)
mutalambda --help
mutalambda doctor
```

Backends LLM intercambiables: **Ollama** (local, gratis), **OpenAI**, **Anthropic**, **OpenRouter**, **Mistral** — se cambian vía `config.yaml`, sin tocar código.

```yaml
evolution:
  islands: 4            # islas paralelas, migración ring/mesh/fully-connected
  generations: 100
  topology: ring
population:
  size: 50
  elite: 10
sandbox:
  timeout: 30           # límites duros por candidato
  workers: 4
llm:
  backend: ollama
  model: codestral
uast:
  enabled: false        # activar para objetivos Rust / C++ / Go (experimental)
  languages: [python, rust, cpp, go]
```

## Cómo funciona

### El pipeline de cinco fases

1. **Discovery** — perfila tu código y extrae las funciones hotspot principales.
2. **Síntesis de Tests** — auto-genera tests de propiedades (Hypothesis) que sirven como oráculo de correctitud cuando tu suite es delgada.
3. **Modo Fast** — el LLM propone 5 variantes optimizadas; evaluación paralela en sandbox; a menudo suficiente para una victoria rápida.
4. **Evolución Profunda** — búsqueda multi-objetivo NSGA-II en islas paralelas con migración, deduplicación semántica (FAISS) y selección adaptativa de operadores (bandit multi-brazo).
5. **Patch y Reporte** — diff estilo git más métricas comparativas. Tú revisas; nada se aplica en silencio.

### La arquitectura de confianza (la parte difícil de copiar)

- **La correctitud es binaria, no ponderada.** Los candidatos que fallan el oráculo salen del pipeline. Esta sola decisión de diseño elimina el modo de fallo clásico de la evolución: hackear la recompensa con código sutilmente incorrecto.
- **El benchmarking honesto se impone**, no se aspira: mediana de repeticiones, múltiples tallas de entrada y una **regla de no-regresión** (un candidato que gana en entradas grandes pero regresa en pequeñas se rechaza — esto atrapó a uno de nuestros propios candidatos).
- **Defensa en profundidad — con fronteras honestas**: regex + escaneo estructural AST (atrapa `import os as _o`, aliasing `f = exec`, escapes `getattr(__builtins__, ...)`) → sandbox en subproceso con rlimits → gates de workflow. Los filtros estáticos son un *gate de calidad, no una frontera de seguridad*; el subproceso contiene accidentes (loops infinitos, bombas de memoria), no atacantes deliberados. **Para entradas no confiables o multi-tenant, envuelve el loop de evaluación en aislamiento a nivel de contenedor** — el modelo de amenazas completo y la receta Docker endurecida están en [SECURITY.md](SECURITY.md).
- **Capa anti-alucinación** para código numérico: equivalencia algebraica SymPy, verificación matemática AST e invariantes de dominio opcionales (conservación de energía, balance de masa, monotonía) para cómputo científico.
- **Salvaguardas de interpretabilidad** (3 capas) y trazabilidad de linaje completa: cada individuo sobreviviente puede explicar de dónde vino.

### Maquinaria avanzada

| Componente | Qué hace |
|---|---|
| **Niveles HFC** | Hierarchical Fitness Climbing: especiación Laboratorio (100) → Fábrica (50) → Élite (10) mantiene viva la exploración sin contaminar la élite |
| **AST Universal (UAST)** | Adaptadores tree-sitter + emisores + mutadores estructurales para Rust, C++, Go (experimental — subconjunto conservador, ver Soporte de lenguajes) |
| **Evolución de prompts** | Los propios prompts de sistema del LLM evolucionan (meta-evolución) |
| **Archivo semántico** | Cache RAG con FAISS — las soluciones pasadas se recuperan, no se redescubren |
| **Checkpoints** | Snapshots MsgPack (4× más rápidos, 99% más pequeños que JSON); interrumpe y reanuda cualquier corrida |
| **Bandit de operadores** | Un bandit multi-brazo reasigna presupuesto hacia los operadores de mutación que sí funcionan |
| **Herramientas** | CLI interactiva (Click/Rich), dashboard Streamlit, servidor LSP, integración CI |

## Soporte de lenguajes

| Lenguaje | Madurez | Qué significa |
|---|---|---|
| **Python** | ✅ **Producción** | Pipeline completo: profiling, candidatos LLM, mutación AST, sandbox, oráculos, benchmarks. Con esto se produjeron los resultados de validación de arriba. |
| Rust | 🧪 Experimental | Mutaciones estructurales sobre un subconjunto conservador vía UAST (tree-sitter). Ownership/borrow, macros, traits y lifetimes se tratan como *opacos* — nunca se mutan. |
| C++ | 🧪 Experimental | Mismo enfoque conservador; templates y gestión de memoria son opacos. |
| Go | 🧪 Experimental | Adaptador + emisor con mutaciones básicas. |

Deliberadamente **no** intentamos abstraer la semántica de ownership o memoria en un AST genérico — los candidatos que tocan construcciones que el UAST no puede razonar se dejan intactos en vez de arriesgarlos. La matriz completa por lenguaje está en [muta_ext/uast/LIMITATIONS.md](src/mutalambda/muta_ext/uast/LIMITATIONS.md).

## Estructura del proyecto

```
muta_lambda.py                 Shim de compatibilidad (python muta_lambda.py sigue funcionando)
src/mutalambda/                El paquete (layout src/ estándar, instalable con pip)
├── muta_lambda.py             Orquestador
├── progressive_pipeline.py    Workflow de 5 fases
├── evolution_engine.py        Operadores de mutación AST + generación LLM
├── island.py / migration.py   Evolución por islas + topologías inter-isla
├── nsga2.py                   Selección Pareto multi-objetivo  ← auto-optimizado 1.49×
├── fitness_vector.py          Vector de fitness de 6 objetivos
├── mutation_filters.py        Gates de seguridad y calidad (incl. perfil `self`)
├── sandbox.py / runners.py    Ejecución con límites duros + escaneo AST de seguridad
├── hfc_tiers.py               Hierarchical Fitness Climbing
├── archive.py                 Cache semántica FAISS
├── llm_backend.py             Ollama / OpenAI / Anthropic / OpenRouter / Mistral
├── cli_app.py + cli/          CLI de consola (comando `mutalambda`)
└── muta_ext/uast/             AST Universal: adaptadores, emisores, mutadores
experiments/                   Experimentos de auto-evolución reproducibles + JSON
tests/                         483 tests
SECURITY.md                    Modelo de amenazas y guía de aislamiento
```

## Documentación

- [Referencia CLI](docs/CLI.md) · [Métricas de fitness](docs/FITNESS_METRICS.md) · [Guía de métricas](docs/METRICS.md)
- [Modo de optimización científica](docs/SCIENTIFIC_OPTIMIZATION_MODE.md) · [Protocolo de ejecución de tests](docs/TEST_EXECUTION_PROTOCOL.md)
- [Modelo de seguridad y fronteras de amenaza](SECURITY.md)
- [Reporte de auto-evolución — ledger de victorias y derrotas](SELF_EVOLUTION_REPORT.md)
- [Evidencia empírica](EMPIRICAL_EVIDENCE.md) · [Reporte multi-lenguaje](MULTILANGUAGE_REPORT.md)
- [Contribuir](CONTRIBUTING.md)

## Testing

```bash
python -m pytest tests/ -v          # suite completa (483 tests)
python -m pytest tests/scientific/  # invariantes del modo científico
python -m pytest -m uast            # capa multi-lenguaje
```

## 📄 Licencia

MutaLambda está licenciado bajo la **Business Source License 1.1** (BUSL-1.1) — ver [LICENSE](LICENSE).

- **Gratis** para uso personal, académico y de investigación, y para evaluación interna (90 días).
- **El uso comercial / en producción requiere una licencia comercial** — contactar al autor vía [GitHub](https://github.com/Adlgr87/MutaLambda).
- Cada versión se convierte automáticamente a **Apache 2.0** en su Change Date (2030-08-19).

> Las versiones publicadas antes del cambio de licencia conservan sus términos MIT originales.
