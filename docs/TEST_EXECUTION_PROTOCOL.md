# Protocolo de Ejecución de Tests

Este documento describe el protocolo de ejecución de tests por niveles/fases para el proyecto MutaLambda.

## Resumen

El proyecto utiliza un sistema de **fases** (también llamadas "gates") para ejecutar tests de manera ordenada y progresiva. Cada fase representa un nivel de complejidad y puede ejecutarse de forma independiente.

### Fases Disponibles

| Fase | Descripción | Archivos de test |
|------|-------------|------------------|
| `root` | Tests básicos del core | config, fitness, HFC, NSGA-II, archive, lineage |
| `scientific` | Tests de extensión científica | numerical health, tipping detection, invariants |
| `uast` | Tests del sistema UAST | core UAST, roundtrip, LLM generator |
| `benchmarks` | Tests de benchmark | benchmark matrix, evolution upgrade |
| `e2e` | Tests end-to-end | pipeline completo, workflow gates |

## Comandos de Ejecución

### Ejecutar una fase específica

```bash
# Tests básicos del core
./run_tests.sh root

# Tests de extensión científica
./run_tests.sh scientific

# Tests UAST
./run_tests.sh uast

# Tests de benchmark
./run_tests.sh benchmarks

# Tests end-to-end
./run_tests.sh e2e
```

### Ejecutar todas las fases

```bash
./run_tests.sh all
```

### Con opciones adicionales

```bash
# Generar reporte HTML y JSON
./run_tests.sh all --report

# Generar reporte de cobertura
./run_tests.sh root --coverage

# Modo verbose
./run_tests.sh scientific -v

# Timeout personalizado
./run_tests.sh all --timeout 60

# Combinar opciones
./run_tests.sh all --report --coverage -v
```

### Ayuda

```bash
./run_tests.sh --help
```

## Estructura de Reportes

Cuando se usa `--report`, se generan los siguientes archivos:

- `test_reports/report.html` — Reporte HTML autocontenido
- `test_reports/results.json` — Resultados en formato JUnit XML/JSON

Cuando se usa `--coverage`, se genera:

- `coverage/index.html` — Reporte de cobertura HTML

## Colores de Salida

| Color | Significado |
|-------|-------------|
| 🟢 Verde | Tests pasados |
| 🔴 Rojo | Tests fallidos |
| 🟡 Amarillo | Tests saltados |
| 🟣 Magenta | Errores |
| 🔵 Azul | Encabezados |
| 🩵 Cyan | Información de fase |

## Guía de Desarrollo

### Agregar un nuevo test a una fase

1. Escribe tu test en el archivo correspondiente bajo `tests/`
2. Agrega el marker pytest apropiado:

```python
import pytest

@pytest.mark.root
def test_my_feature():
    ...
```

Markers disponibles:
- `@pytest.mark.root` — Para tests del core
- `@pytest.mark.scientific` — Para tests de extensión científica
- `@pytest.mark.uast` — Para tests UAST
- `@pytest.mark.benchmarks` — Para tests de benchmark
- `@pytest.mark.e2e` — Para tests end-to-end

### Estructura de directorios de tests

```
tests/
├── test_config.py              # [root] Configuración YAML
├── test_fitness_vector.py      # [root] Vector de fitness
├── test_hfc_tiers.py           # [root] HFC tiers
├── test_nsga2.py               # [root] NSGA-II
├── test_solution_archive.py    # [root] Archive
├── test_lineage.py             # [root] Lineage
├── test_convergent_boost.py    # [root] Boost convergente
├── test_scientific_extension.py # [scientific] Extensión científica
├── scientific/                 # [scientific] Tests científicos
│   ├── test_call_graph.py
│   ├── test_domain_operators.py
│   └── ...
├── uast/                       # [uast] Tests UAST
│   ├── test_core_uast.py
│   └── ...
├── benchmarks/                 # [benchmarks] Tests de benchmark
│   └── test_evolution_upgrade_benchmark_matrix.py
├── e2e_tests.py                # [e2e] Tests end-to-end
└── test_workflow_gates_integration.py  # [e2e] Workflow gates
```

### Flujo de desarrollo recomendado

1. **Durante desarrollo**: Ejecuta `./run_tests.sh root` para validación rápida
2. **Antes de PR**: Ejecuta `./run_tests.sh all --report` para validación completa
3. **CI/CD**: Configura el pipeline para ejecutar `./run_tests.sh all --report --coverage`

## Notas Técnicas

- Todos los tests usan **pytest** con la opción `--strict-markers`
- El timeout por defecto es de **120 segundos** por prueba
- Los tests se ejecutan en el orden definido por pytest (alfabético por defecto)
- El protocolo de workflow gates (`workflow_protocol.py`) permite integración de validación secuencial
