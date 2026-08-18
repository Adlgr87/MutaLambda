# MutaLambda Feature Implementation Plan

## Overview
Este documento detalla los planes funcionales para implementar las nuevas características de MutaLambda, basándose en el análisis del código existente y los requisitos del proyecto.

---

## Feature 1: Go Language Support (UAST)

### Prioridad: Alta
### Estado: No implementado

#### Especificación
Crear soporte completo para el lenguaje Go dentro del layer UAST de MutaLambda, incluyendo:
- **Adapter**: Parser de código Go a CoreUAST usando tree-sitter-go
- **Emitter**: Generador de código Go desde CoreUAST con formatting automático via `gofmt`
- **Handler**: Procesador específico para mutaciones y optimizaciones en Go
- **Configuración**: Template YAML para configuración específica de Go

#### Arquitectura
```
muta_ext/uast/
├── adapters/
│   └── go_adapter.py          # NUEVO: Go → CoreUAST
├── emitters/
│   └── go_emitter.py          # NUEVO: CoreUAST → Go
├── handlers/
│   └── go_handler.py          # NUEVO: Procesamiento de mutaciones Go
└── config/
    └── go_config.yaml         # NUEVO: Configuración Go
```

#### Nodos CoreUAST Específicos para Go
- `GoInterface`: Definición de interfaces (Go es fuertemente tipado)
- `GoChannel`: Operaciones con canales
- `GoGoKeyword`: Expressión `go func()`
- `GoStructMethod`: Método de struct
- `GoPointer`: Referencias/pointers (*T, &v)

#### Mutaciones Específicas para Go
1. **Concurrency Mutations**:
   - Convertir loops secuenciales a goroutines con canales
   - Optimizar patrones de locking (mutex → channels)
   - Detectar race conditions potenciales

2. **Memory Mutations**:
   - Eliminar allocations innecesarias
   - Usar pools de objetos (*sync.Pool*)
   - Optimizar slice growth patterns

3. **Algorithmic Mutations**:
   - Reemplazar linear search con map lookup
   - Optimizar string concatenation
   - Inline funciones pequeñas

#### Dependencies Nuevas
```
tree-sitter-go>=0.23.0
```

#### Integration Points
- Registrar en `muta_ext/uast/adapters/__init__.py`
- Registrar en `muta_ext/uast/emitters/__init__.py`
- Agregar a `config.yaml` bajo `languages.go`
- Agregar a `requirements.txt`

#### Testing Strategy
- Tests unitarios para el adapter (parsing correcto)
- Tests de round-trip (parse → mutate → emit)
- Tests de integración con `gofmt`
- Benchmarks de performance vs código optimizado manualmente

---

## Feature 2: Multi-file/Project Optimization

### Prioridad: Alta
### Estado: No implementado

#### Especificación
Expandir el pipeline de MutaLambda para analizar módulos completos en lugar de funciones aisladas, detectando:
- Hotspots de llamadas cruzadas
- Oportunidades de inlining interprocedural
- Redundancia de lógica entre archivos

#### Arquitectura
```
muta_ext/
└── project_optimizer.py       # NUEVO: Análisis a nivel de proyecto
```

#### Componentes
1. **ProjectAnalyzer**: Escanea directorios, construye grafo de llamadas
2. **CallGraphBuilder**: Construye grafo de dependencias entre funciones
3. **CrossFileHotspotDetector**: Encuentra patrones de llamada recurrentes
4. **InliningOpportunityFinder**: Identifica funciones candidatos a inline
5. **RedundancyDetector**: Encuentra lógica duplicada entre archivos

#### Integration Points
- Extender `progressive_pipeline.py` para modo multi-archivo
- Agregar flag `--project-mode` al CLI
- Modificar `hotspot_profiler.py` para soportar análisis cross-file

#### Configuration
```yaml
project_optimizer:
  enabled: true
  max_files: 100
  call_graph_depth: 3
  redundancy_threshold: 0.7
  inline_max_size: 50  # líneas
```

#### Testing Strategy
- Tests con proyectos de ejemplo multi-módulo
- Validación de grafo de llamadas
- Benchmarks de optimización cross-file

---

## Feature 3: Explainable Optimization Mode

### Prioridad: Media-Alta
### Estado: No implementado

#### Especificación
Agregar explicaciones LLM-generadas para cada mutación propuesta:
- **Justificación**: Por qué se propone la optimización
- **Complejidad**: Análisis de complejidad temporal/espacial
- **Riesgos**: Impacto en legibilidad, maintainability, memory
- **Alternativas**: Otras opciones consideradas

#### Arquitectura
```
muta_ext/
└── explainable_optimizer.py   # NUEVO: Generador de explicaciones
```

#### Componentes
1. **ExplanationGenerator**: Usa LLM para generar justificaciones
2. **RiskAnalyzer**: Evalúa riesgos de cada optimización
3. **ComplexityAnalyzer**: Analiza complejidad antes/después
4. **ExplanationFormatter**: Formatea salidas para el usuario

#### Output Format
```json
{
  "optimization": "vectorization",
  "justification": "Este bucle es O(n²) porque busca linealmente. Se propone un hash map para O(1).",
  "risk": "medium",
  "risk_details": "Aumenta uso de memoria en ~15% debido a la tabla hash.",
  "complexity_before": {"time": "O(n²)", "space": "O(1)"},
  "complexity_after": {"time": "O(n)", "space": "O(n)"},
  "alternatives_considered": ["binary_search", "sorting"],
  "confidence": 0.92
}
```

#### Integration Points
- Integrar con `evolution_engine.py` para explicar mutaciones
- Agregar opción `--explain` al CLI
- Extender `models.py` con clase `OptimizationExplanation`

#### Testing Strategy
- Tests de generación de explicaciones
- Validación humana de calidad de explicaciones
- Benchmarks de precisión

---

## Feature 4: LSP/IDE Integration

### Prioridad: Media
### Estado: No implementado

#### Especificación
Convertir MutaLambda en un plugin de VS Code/Neovim que sugiera optimizaciones inline mientras se escribe código.

#### Arquitectura
```
lsp/
├── server.py                  # NUEVO: LSP Server principal
├── handlers.py                # NUEVO: Handlers de mensajes LSP
├── extensions/
│   ├── vscode/                # NUEVO: Extensión VS Code
│   └── neovim/                # NUEVO: Plugin Neovim
└── protocol/
    └── types.py               # NUEVO: Tipos del protocolo
```

#### Features LSP
- `textDocument/diagnostic`: Mostrar optimizaciones propuestas
- `textDocument/codeAction`: Aplicar optimización con un click
- `textDocument/inlayHint`: Mostrar métricas de performance inline
- `workspace/symbol`: Navegar a funciones optimizables

#### Flow
```
1. Usuario escribe código
2. LSP detecta función nueva/compleja
3. LSP corre fast mode en background
4. Muestra diff optimizado en editor
5. Usuario acepta/rechaza con code action
```

#### Integration Points
- Extender `llm_backend.py` para respuestas rápidas (fast mode)
- Modificar `progressive_pipeline.py` para modo LSP (sin sandbox pesado)
- Agregar config LSP en `config.yaml`

#### Testing Strategy
- Tests con language-client-neovim
- Tests con VS Code Extension Test Host
- Validación de tiempos de respuesta (<500ms para fast mode)

---

## Feature 5: GPU/Auto-Parallelism Support

### Prioridad: Media
### Estado: No implementado

#### Especificación
Detectar patrones paralelizables en el UAST y emitir variantes que usen:
- CUDA/OpenCL para C++/Python
- Goroutines con canales para Go
- SIMD intrinsics

#### Arquitectura
```
muta_ext/
└── gpu_optimizer.py           # NUEVO: Optimizador GPU/paralelismo
```

#### Componentes
1. **ParallelPatternDetector**: Detecta loops paralelizables en UAST
2. **CUDAGenerator**: Genera kernels CUDA desde UAST
3. **OpenCLGenerator**: Genera kernels OpenCL
4. **SIMDGenerator**: Genera código con intrinsics SIMD
5. **GoroutineOptimizer**: Optimiza concurrencia en Go

#### Integration Points
- Extender `evolution_engine.py` con mutadores GPU
- Agregar `fitness_vector` dimension: throughput paralelo
- Modificar `sandbox.py` para soportar executors GPU

#### Configuration
```yaml
gpu_optimizer:
  enabled: false
  target: cuda  # cuda, opencl, simd, goroutine
  max_threads: 256
  auto_detect: true
```

#### Testing Strategy
- Tests con CUDA simulado (sin GPU disponible)
- Benchmarks de speedup vs CPU
- Validación de correctness

---

## Feature 6: CI/CD Regression Mode

### Prioridad: Media
### Estado: No implementado

#### Especificación
Modo donde MutaLambda se ejecuta en pull requests para:
- Detectar degradaciones de performance
- Proponer optimizaciones antes del merge
- Guardar baseline de fitness por función

#### Arquitectura
```
ci_mode/
├── runner.py                  # NUEVO: Runner para CI
├── baseline.py                # NUEVO: Gestión de baselines
├── github_action.py           # NUEVO: GitHub Action wrapper
└── report/
    └── formatter.py           # NUEVO: Formateador de reportes
```

#### Features
- **Baseline Storage**: Guarda fitness de cada función en `.mutalambda/baseline.json`
- **PR Detection**: Hook en eventos de pull request
- **Regression Check**: Compara fitness nuevo vs baseline
- **Optimization Proposal**: Sugiere mejoras antes del merge
- **Report Generation**: Genera reporte de diff de performance

#### Integration Points
- Agregar `ci_mode.py` al CLI
- Extender `checkpoint_manager.py` para baselines
- Crear GitHub Action `MutaLambda/regression-check`

#### Testing Strategy
- Tests con GitHub Actions mock
- Simulación de PRs
- Validación de formato de reporte

---

## Feature 7: Git Sync & PR

### Prioridad: Baja (automático)
### Estado: No implementado

#### Especificación
Sincronizar repositorios locales y crear PRs automatizados.

#### Steps
1. Verificar estado de cada repositorio
2. Identificar cambios no sync
3. Crear branch de feature
4. Commit de cambios
5. Push a origin
6. Crear PR con descripción
7. Merge tras revisión

---

## Priority Matrix

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| Go Language | Medium | High | P1 |
| Multi-file | Medium | High | P1 |
| Explainable | Low | High | P2 |
| LSP | High | Medium | P2 |
| GPU | High | Medium | P3 |
| CI/CD | Medium | Medium | P3 |

---

## Implementation Order

1. **Go Language Support** - Foundation para otros lenguajes
2. **Multi-file Optimization** - Escala el valor existente
3. **Explainable Mode** - Diferenciador clave
4. **LSP Integration** - Cambio de modelo de uso
5. **GPU/Parallelism** - Posicionamiento nicho
6. **CI/CD Mode** - Enterprise adoption

---

## Success Metrics

- [ ] Go adapter parse率达到 95%+ para código idiomatic Go
- [ ] Multi-file optimization mejora performance 10%+ en benchmarks
- [ ] Explainable mode generated explanations rated >4/5 by engineers
- [ ] LSP response time <500ms para fast mode
- [ ] GPU mode 2x+ speedup en kernels paralelizables
- [ ] CI/CD mode integrado en flujo de PR sin fricción
