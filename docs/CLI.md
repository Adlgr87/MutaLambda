# MutaLambda CLI — Guía Completa

**Versión:** 3.1.0  
**Última actualización:** 2026-06-29

---

## 📋 Índice

1. [Introducción](#introducción)
2. [Instalación](#instalación)
3. [Comandos](#comandos)
4. [Configuración](#configuración)
5. [Checkpoints](#checkpoints)
6. [Modo Interactivo](#modo-interactivo)
7. [Animaciones Retro](#animaciones-retro)
8. [Ejemplos Completos](#ejemplos-completos)

---

## Introducción

La CLI de MutaLambda proporciona una interfaz completa para ejecutar evoluciones genéticas de código Python, gestionar configuraciones, checkpoints y visualizar resultados en tiempo real con animaciones retro.

### Características Principales

✅ **8 comandos principales** para controlar todos los aspectos de la evolución  
✅ **3 plantillas de configuración** predefinidas (basic, advanced, research)  
✅ **Sistema de checkpoints** con compresión gzip para guardar/reanudar runs  
✅ **Animaciones retro** tipo Atari con ASCII art, progress bars y gráficos  
✅ **Modo interactivo REPL** para control en tiempo real  
✅ **Integración completa** con el core evolutivo de MutaLambda  

---

## Instalación

### Requisitos

- Python 3.10+
- Click 8.0+
- Rich 13.0+
- PyYAML 6.0+

### Instalar dependencias

```bash
cd MutaLambda_Proyect
pip install -r requirements.txt
```

### Verificar instalación

```bash
python cli.py --help
```

Deberías ver la ayuda con todos los comandos disponibles.

---

## Comandos

### `run` — Ejecutar Evolución

Ejecuta una corrida evolutiva completa.

```bash
python cli.py run [OPTIONS]
```

**Opciones:**

| Opción | Descripción | Default |
|--------|-------------|---------|
| `--config, -c` | Archivo de configuración YAML/JSON | Config por defecto |
| `--generations, -g` | Número de generaciones | 50 |
| `--animation, -a` | Estilo de animación: `retro`, `minimal`, `none` | `retro` |
| `--verbose, -v` | Output detallado | False |

**Ejemplos:**

```bash
# Ejecutar con configuración por defecto
python cli.py run --generations 100

# Ejecutar con configuración personalizada
python cli.py run --config config.yaml --generations 200 --animation retro

# Ejecutar con output minimal
python cli.py run --generations 50 --animation minimal
```

---

### `resume` — Reanudar desde Checkpoint

Reanuda una evolución desde un checkpoint guardado.

```bash
python cli.py resume [OPTIONS]
```

**Opciones:**

| Opción | Descripción | Default |
|--------|-------------|---------|
| `--checkpoint, -p` | Archivo de checkpoint (requerido) | - |
| `--additional-gens, -g` | Generaciones adicionales | 50 |
| `--animation, -a` | Estilo de animación | `retro` |

**Ejemplo:**

```bash
python cli.py resume --checkpoint checkpoints/checkpoint_0050.json --additional-gens 30
```

---

### `config` — Gestionar Configuraciones

#### `config create` — Crear Configuración

Crea un archivo de configuración desde una plantilla.

```bash
python cli.py config create [OPTIONS]
```

**Opciones:**

| Opción | Descripción | Default |
|--------|-------------|---------|
| `--output, -o` | Archivo de salida (requerido) | - |
| `--template, -t` | Plantilla: `basic`, `advanced`, `research` | `basic` |

**Ejemplo:**

```bash
python cli.py config create --output config.yaml --template advanced
```

#### `config validate` — Validar Configuración

Valida un archivo de configuración.

```bash
python cli.py config validate --path config.yaml
```

#### `config show` — Mostrar Configuración

Muestra un resumen de la configuración.

```bash
python cli.py config show --path config.yaml
```

---

### `stats` — Estadísticas

Muestra estadísticas de ejecuciones anteriores (checkpoints).

```bash
python cli.py stats
```

---

### `evaluate` — Evaluar Resultados

Evalúa y resume resultados de una ejecución.

```bash
python cli.py evaluate [OPTIONS]
```

**Opciones:**

| Opción | Descripción |
|--------|-------------|
| `--results, -r` | Archivo JSON con resultados |

**Ejemplo:**

```bash
python cli.py evaluate --results results.json
```

---

### `mutate` — Operaciones de Mutación

#### `mutate prompt` — Mutar Prompts

```bash
python cli.py mutate prompt --target function.py --strategy adaptive
```

#### `mutate operators` — Mutar Operadores

```bash
python cli.py mutate operators --target function.py --strategy weighted
```

#### `mutate hyperparams` — Optimizar Hiperparámetros

```bash
python cli.py mutate hyperparams --target function.py --strategy bayesian
```

---

### `interactive` — Modo Interactivo

Inicia un REPL interactivo para control en tiempo real.

```bash
python cli.py interactive
```

**Comandos disponibles en el REPL:**

| Comando | Descripción |
|---------|-------------|
| `run [gens]` | Ejecutar N generaciones |
| `status` | Ver estado actual |
| `pause` | Pausar evolución |
| `resume` | Reanudar evolución |
| `save <path>` | Guardar checkpoint |
| `quit` | Salir |

---

### `checkpoints` — Gestionar Checkpoints

Lista, limpia o gestiona checkpoints.

```bash
python cli.py checkpoints [OPTIONS]
```

**Opciones:**

| Opción | Descripción | Default |
|--------|-------------|---------|
| `--list, -l` | Listar checkpoints | False |
| `--clean, -c` | Limpiar checkpoints antiguos | False |
| `--max-age` | Edad máxima en días | 30 |

**Ejemplos:**

```bash
# Listar todos los checkpoints
python cli.py checkpoints --list

# Limpiar checkpoints mayores a 7 días
python cli.py checkpoints --clean --max-age 7
```

---

## Configuración

### Estructura del Archivo

```yaml
evolution:
  generations: 50
  num_islands: 4
  population_size: 8
  top_k: 3

migration:
  interval: 10
  migrants_per_island: 2
  topology: ring  # ring, fully_connected, random

mutation:
  rate: 0.1
  crossover_rate: 0.7

checkpoint:
  enabled: true
  interval: 10
  directory: checkpoints

early_stop:
  enabled: true
  patience: 15
  delta: 0.001
```

### Plantillas Predefinidas

#### `basic` — Configuración Mínima

```yaml
evolution:
  generations: 50
  num_islands: 4
  population_size: 8
  top_k: 3
migration:
  interval: 10
  migrants_per_island: 2
  topology: ring
```

**Uso:** Pruebas rápidas, desarrollo inicial.

#### `advanced` — Configuración de Producción

```yaml
evolution:
  generations: 100
  num_islands: 8
  population_size: 16
  top_k: 5
migration:
  interval: 5
  migrants_per_island: 3
  topology: fully_connected
mutation:
  rate: 0.15
  crossover_rate: 0.8
  strategies: [random, guided, crossover]
```

**Uso:** Ejecuciones de producción, optimización seria.

#### `research` — Configuración Experimental

```yaml
evolution:
  generations: 200
  num_islands: 12
  population_size: 24
  top_k: 8
migration:
  interval: 3
  migrants_per_island: 4
  topology: fully_connected
mutation:
  rate: 0.2
  crossover_rate: 0.85
  strategies: [random, guided, crossover, elite]
  adaptive: true
fitness:
  weights:
    correctness: 0.5
    performance: 0.35
    complexity: 0.15
  novelty_bonus: 0.1
analytics:
  track_lineage: true
  track_diversity: true
  export_interval: 10
```

**Uso:** Investigación, experimentación avanzada.

---

## Checkpoints

### Formato

Los checkpoints se guardan en formato pickle comprimido con gzip:

```
checkpoints/
├── checkpoint_0010.pkl.gz
├── checkpoint_0020.pkl.gz
├── checkpoint_0030.pkl.gz
└── checkpoint_0040.pkl.gz
```

### Contenido

Cada checkpoint incluye:

```python
{
    'version': '1.0',
    'generation': 50,
    'best_score': 87.5,
    'timestamp': '2026-06-29T14:30:00',
    'state': {
        'islands': [
            {'id': 0, 'best_score': 85.2, 'population': 8},
            {'id': 1, 'best_score': 87.5, 'population': 8},
            # ...
        ],
        'migration_bus': {...},
        'config': {...}
    }
}
```

### Gestión

```bash
# Listar checkpoints
python cli.py checkpoints --list

# Limpiar antiguos
python cli.py checkpoints --clean --max-age 7

# Reanudar desde checkpoint
python cli.py resume --checkpoint checkpoints/checkpoint_0050.pkl.gz --additional-gens 30
```

---

## Modo Interactivo

El modo interactivo proporciona un REPL para control en tiempo real:

```bash
python cli.py interactive
```

### Sesión de Ejemplo

```
███╗   ███╗██╗   ██╗████████╗ █████╗ ██╗      █████╗ ███╗   ███╗██████╗  █████╗ 
████╗ ████║██║   ██║╚══██╔══╝██╔══██╗██║     ██╔══██╗████╗ ████║██╔══██╗██╔══██╗
██╔████╔██║██║   ██║   ██║   ███████║██║     ███████║██╔████╔██║██║  ██║███████║
██║╚██╔╝██║██║   ██║   ██║   ██╔══██║██║     ██╔══██║██║╚██╔╝██║██║  ██║██╔══██║
██║ ╚═╝ ██║╚██████╔╝   ██║   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║██████╔╝██║  ██║
╚═╝     ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═════╝ ╚═╝  ╚═╝
                                                                                
              Genetic Code Evolution — Interactive Mode

Interactive Mode
Type help for commands

mutalambda> run 10
[Evolution runs for 10 generations with animations]

mutalambda> status
[Shows current generation, best score, island states]

mutalambda> pause
⏸ Paused

mutalambda> resume
▶ Resumed

mutalambda> save checkpoints/manual_checkpoint.pkl.gz
✓ Saved to checkpoints/manual_checkpoint.pkl.gz

mutalambda> quit
Goodbye!
```

---

## Animaciones Retro

La CLI incluye animaciones tipo Atari/retro que son funcionales y no estorban:

### Banner ASCII

```
███╗   ███╗██╗   ██╗████████╗ █████╗ ██╗      █████╗ ███╗   ███╗██████╗  █████╗ 
████╗ ████║██║   ██║╚══██╔══╝██╔══██╗██║     ██╔══██╗████╗ ████║██╔══██╗██╔══██╗
██╔████╔██║██║   ██║   ██║   ███████║██║     ███████║██╔████╔██║██║  ██║███████║
██║╚██╔╝██║██║   ██║   ██║   ██╔══██║██║     ██╔══██║██║╚██╔╝██║██║  ██║██╔══██║
██║ ╚═╝ ██║╚██████╔╝   ██║   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║██████╔╝██║  ██║
╚═╝     ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═════╝ ╚═╝  ╚═╝
```

### Progress Bar

```
[████████████████████░░░░░░░░░░░░░░░░░░░░] 50.0% | Gen 50/100 | Best: 87.50
```

### Island Grid

```
🏝️ Island 0: [████████░░] 82.5% (pop: 8)
🏝️ Island 1: [█████████░] 87.5% (pop: 8)
🏝️ Island 2: [███████░░░] 75.2% (pop: 8)
🏝️ Island 3: [█████████░] 85.1% (pop: 8)
```

### Fitness Graph

```
 87.5 |                    ╭──●
      |              ╭─────╯
 85.0 |         ╭────╯
      |    ╭────╯
 82.5 |────╯
      +────────────────────
        Gen 1        Gen 50
```

### Estilos de Animación

- **`retro`** — Animaciones completas con ASCII art, progress bars, gráficos
- **`minimal`** — Output compacto, una línea por generación
- **`none`** — Sin animaciones, solo resultados finales

---

## Ejemplos Completos

### Flujo de Trabajo Básico

```bash
# 1. Crear configuración
python cli.py config create --output config.yaml --template basic

# 2. Ejecutar evolución
python cli.py run --config config.yaml --generations 100 --animation retro

# 3. Ver estadísticas
python cli.py stats

# 4. Reanudar si es necesario
python cli.py resume --checkpoint checkpoints/checkpoint_0050.pkl.gz --additional-gens 50
```

### Flujo de Trabajo Avanzado

```bash
# 1. Crear configuración avanzada
python cli.py config create --output advanced.yaml --template advanced

# 2. Validar configuración
python cli.py config validate --path advanced.yaml

# 3. Ejecutar con output detallado
python cli.py run --config advanced.yaml --generations 200 --animation retro --verbose

# 4. Evaluar resultados
python cli.py evaluate --results results.json

# 5. Limpiar checkpoints antiguos
python cli.py checkpoints --clean --max-age 7
```

### Flujo de Trabajo Interactivo

```bash
# Iniciar modo interactivo
python cli.py interactive

# Dentro del REPL:
mutalambda> run 50
mutalambda> status
mutalambda> pause
mutalambda> resume
mutalambda> save checkpoints/manual.pkl.gz
mutalambda> quit
```

---

## Solución de Problemas

### Error: "No module named 'muta_lambda'"

**Solución:** Asegúrate de estar en el directorio correcto:

```bash
cd MutaLambda_Proyect
python cli.py --help
```

### Error: "Failed to load config"

**Solución:** Valida tu archivo de configuración:

```bash
python cli.py config validate --path config.yaml
```

### Error: "Checkpoint not found"

**Solución:** Lista los checkpoints disponibles:

```bash
python cli.py checkpoints --list
```

### Las animaciones no se ven correctamente

**Solución:** Usa el estilo `minimal` o `none`:

```bash
python cli.py run --generations 50 --animation minimal
```

---

## Referencia de API

### MutaLambdaCLI

Clase principal que orquesta todas las operaciones.

```python
from cli.main import MutaLambdaCLI

cli = MutaLambdaCLI()
cli.run_evolution(
    config_path='config.yaml',
    generations=100,
    animation='retro',
    verbose=False
)
```

### RetroAnimator

Clase para animaciones retro.

```python
from cli.animator import RetroAnimator

animator = RetroAnimator()
animator.print_banner()
animator.progress_bar(50, 100, 87.5)
```

### ConfigManager

Clase para gestión de configuraciones.

```python
from cli.config_manager import ConfigManager

config_mgr = ConfigManager()
config = config_mgr.load('config.yaml')
config_mgr.validate(config)
```

### CheckpointManager

Clase para gestión de checkpoints.

```python
from cli.checkpoint_manager import CheckpointManager

chk_mgr = CheckpointManager()
chk_mgr.save(generation=50, best_score=87.5, state={...})
state = chk_mgr.load('checkpoint_0050.pkl.gz')
```

---

## Licencia

MIT License — Ver [LICENSE](../LICENSE) para detalles.
