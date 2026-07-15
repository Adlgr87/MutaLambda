# 🔧 WORKFLOW DE OPTIMIZACIÓN Y CORRECCIÓN: MutLambda

## 📋 METADATA

| Campo | Valor |
|-------|-------|
| **Proyecto** | MutaLambda |
| **Versión** | 1.0.0 |
| **Fecha** | 2026-07-15 |
| **Repositorio** | https://github.com/Adlgr87/MutaLambda |
| **Archivos Python** | 75+ |
| **Líneas de código** | ~14,913 |
| **Clases dataclass** | 62 |
| **Puntuación calidad** | 6.5/10 |

---

## 🎯 PRIORIDADES DE EJECUCIÓN

```
FASE 1: CRÍTICAS    → Semana 1 (Inmediato)
FASE 2: ALTA        → Semana 2-3
FASE 3: MEDIA       → Semana 4
FASE 4: BAJA        → Semana 5
```

---

## ═══════════════════════════════════════════════════════════════════
# FASE 1: CRÍTICAS — Hacer Ahora
## ═══════════════════════════════════════════════════════════════════

---

### 🐛 FIX 1.1: Función Duplicada stable_code_hash

**Problema**: `stable_code_hash()` está definida en 2 lugares.

**Archivos afectados**:
- `runners.py:74`
- `models.py:18`

**Verificación**:

```bash
grep -rn "def stable_code_hash" --include="*.py"
```

**Solución**: Crear módulo centralizado.

```python
# mutalambda/core/utils/hash.py
"""Utilidades de hash para código estable."""

from hashlib import sha256
from typing import Optional

def stable_code_hash(code: str, salt: Optional[str] = None) -> str:
    """Genera hash SHA-256 estable para código.
    
    Args:
        code: Código fuente a hashear
        salt: Salt opcional para variation
    
    Returns:
        Hash hexadecimal de 64 caracteres
    """
    content = code if salt is None else f"{salt}:{code}"
    return sha256(content.encode()).hexdigest()
```

**Pasos**:
1. [ ] Crear `mutalambda/core/utils/hash.py`:
   ```bash
   mkdir -p mutalambda/core/utils
   ```
2. [ ] Mover función a utils/hash.py
3. [ ] Actualizar `runners.py`:
   ```python
   from mutalambda.core.utils.hash import stable_code_hash
   ```
4. [ ] Eliminar de `models.py`
5. [ ] Verificar con `grep -rn "stable_code_hash" --include="*.py"`

---

### 🔀 FIX 1.2: Renombrar Clases Ambiguas Checkpoint

**Problema**: Conflicto de nombres entre `Checkpoint` y `CheckpointManager`.

**Archivos afectados**:
- `checkpoint_manager.py:46` → define `Checkpoint` (dataclass)
- `cli/checkpoint_manager.py:22` → archivo con `CheckpointManager`

**Solución**:

```python
# checkpoint_manager.py (antes)
@dataclass
class Checkpoint:  # ← Nombre conflictivo
    timestamp: float
    generation: int
    data: dict

# checkpoint_manager.py (después)
@dataclass
class CheckpointData:  # ← Nombre único
    timestamp: float
    generation: int
    data: dict

class CheckpointManager:
    """Gestor de checkpoints de sesión."""
    
    def save_checkpoint(self, checkpoint: CheckpointData) -> str:
        ...
```

**Script de renombrado**:

```python
# rename_checkpoints.py
import re
from pathlib import Path

def rename_checkpoints():
    """Renombra Checkpoint -> CheckpointData."""
    
    files_to_update = [
        "mutalambda/checkpoint_manager.py",
        "mutalambda/core/checkpoint.py",
    ]
    
    for file in files_to_update:
        p = Path(file)
        if p.exists():
            content = p.read_text()
            
            # Renombrar clase
            content = re.sub(
                r'class Checkpoint\b',
                'class CheckpointData',
                content
            )
            
            # Renombrar referencias
            content = re.sub(
                r':\s*Checkpoint\b',
                ': CheckpointData',
                content
            )
            content = re.sub(
                r'Checkpoint\)',
                'CheckpointData)',
                content
            )
            content = re.sub(
                r'List\[Checkpoint\]',
                'List[CheckpointData]',
                content
            )
            
            p.write_text(content)
            print(f"✅ Actualizado: {file}")

if __name__ == "__main__":
    rename_checkpoints()
```

**Pasos**:
1. [ ] Ejecutar script de renombrado
2. [ ] Buscar todas las referencias: `grep -rn "Checkpoint" --include="*.py"`
3. [ ] Actualizar imports en archivos que usen `Checkpoint`
4. [ ] Verificar que CLI funcione correctamente

---

### 🚫 FIX 1.3: Reemplazar Try-Except Desnudos

**Problema**: `except:` o `except Exception:` sin manejo específico.

**Archivos afectados**:
- `cli/config_manager.py:163`
- `checkpoint_manager.py:214,223,234`

**Patrón problemático**:

```python
# ANTES (malo)
try:
    result = risky_operation()
except:  # ← Captura TODO
    pass

# DESPUÉS (correcto)
import logging

logger = logging.getLogger(__name__)

try:
    result = risky_operation()
except FileNotFoundError as e:
    logger.warning(f"Archivo no encontrado: {e}")
    raise  # Re-lanzar si es crítico
except PermissionError as e:
    logger.error(f"Sin permisos: {e}")
    raise
except Exception as e:
    logger.exception(f"Error inesperado: {e}")
    raise
```

**Script detector de try-except desnudos**:

```python
# detect_bare_excepts.py
import ast
import re
from pathlib import Path
from dataclasses import dataclass

@dataclass
class BareExcept:
    file: str
    line: int
    code: str

def detect_bare_excepts(directory: Path) -> list[BareExcept]:
    """Detecta todos los except desnudos."""
    findings = []
    
    for py_file in directory.rglob("*.py"):
        if "test" in py_file.name:
            continue
            
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:  # except: sin tipo
                    findings.append(BareExcept(
                        file=str(py_file),
                        line=node.lineno,
                        code=ast.unparse(node)
                    ))
    
    return findings

if __name__ == "__main__":
    findings = detect_bare_excepts(Path("mutalambda"))
    
    print(f"🚨 Encontrados {len(findings)} except desnudos\n")
    
    for f in findings:
        print(f"📁 {f.file}:{f.line}")
        print(f"   ❌ {f.code}\n")
```

**Plantilla de fix por archivo**:

```python
# cli/config_manager.py (línea ~163)

# ANTES:
try:
    config = yaml.safe_load(f)
except:
    pass  # Silenciado

# DESPUÉS:
try:
    config = yaml.safe_load(f)
except yaml.YAMLError as e:
    logger.error(f"Error parseando YAML: {e}")
    raise ConfigError(f"YAML inválido: {e}") from e
except Exception as e:
    logger.exception(f"Error inesperado cargando config: {e}")
    raise
```

**Pasos**:
1. [ ] Ejecutar script detector
2. [ ] Documentar cada except desnudo
3. [ ] Reemplazar con manejo específico
4. [ ] Añadir logging donde sea necesario

---

## ═══════════════════════════════════════════════════════════════════
# FASE 2: ALTA PRIORIDAD — Semana 2-3
## ═══════════════════════════════════════════════════════════════════

---

### 🎲 FIX 2.1: Centralizar Uso de Random con Seed

**Problema**: 90+ usos de `random.` sin seed centralizado.

**Comando de detección**:

```bash
grep -rn "random\." --include="*.py" mutalambda/ | grep -v "rng" | head -40
```

**Módulo centralizado de RNG**:

```python
# mutalambda/core/rng_session.py
"""Gestor centralizado de números aleatorios."""

from __future__ import annotations

import random
from typing import Optional
from dataclasses import dataclass, field
from contextlib import contextmanager

@dataclass(frozen=True)
class RNGConfig:
    """Configuración del RNG."""
    seed: int = 42
    algorithm: str = "Xorshift256+"

@dataclass
class RNGSession:
    """Sesión de random con reproducibilidad garantizada."""
    _seed: int = field(default=42)
    _rng: random.Random = field(init=False)
    
    def __post_init__(self):
        self._rng = random.Random(self._seed)
    
    @property
    def rng(self) -> random.Random:
        """Obtiene el RNG de esta sesión."""
        return self._rng
    
    def randint(self, a: int, b: int) -> int:
        """Entero aleatorio en [a, b]."""
        return self._rng.randint(a, b)
    
    def uniform(self, a: float, b: float) -> float:
        """Float aleatorio en [a, b]."""
        return self._rng.uniform(a, b)
    
    def choice(self, seq: list) -> any:
        """Elemento aleatorio de secuencia."""
        return self._rng.choice(seq)
    
    def shuffle(self, seq: list) -> None:
        """Mezcla secuencia in-place."""
        self._rng.shuffle(seq)
    
    def sample(self, population: list, k: int) -> list:
        """Muestra sin reemplazo."""
        return self._rng.sample(population, k)
    
    def get_state(self) -> dict:
        """Guarda estado para reproducibilidad."""
        return {"seed": self._seed}
    
    @classmethod
    def from_state(cls, state: dict) -> RNGSession:
        """Restaura sesión desde estado."""
        return cls(_seed=state.get("seed", 42))

# Instancia global por defecto
_default_session = RNGSession()

# Exports convenientes
def get_rng() -> RNGSession:
    """Obtiene la sesión RNG por defecto."""
    return _default_session

def reset_seed(seed: int) -> None:
    """Reinicia el RNG global."""
    global _default_session
    _default_session = RNGSession(_seed=seed)
```

**Pasos**:
1. [ ] Crear `mutalambda/core/rng_session.py`
2. [ ] Identificar todos los `random.` en el codebase:
   ```bash
   grep -rn "random\." mutalambda/ --include="*.py" > rng_usages.txt
   ```
3. [ ] Reemplazar uno por uno:
   ```python
   # ANTES:
   import random
   x = random.randint(0, 10)
   
   # DESPUÉS:
   from mutalambda.core.rng_session import get_rng
   x = get_rng().randint(0, 10)
   ```
4. [ ] Verificar reproducibilidad en tests

---

### 🔧 FIX 2.2: Consolidar compare_values

**Problema**: Lógica duplicada en `compare_values`.

**Archivos afectados**:
- `runners.py:47-72`
- `differential.py` (lógica similar)

**Solución centralizada**:

```python
# mutalambda/core/comparison.py
"""Comparaciones para validación de soluciones."""

from dataclasses import dataclass
from typing import Optional, Union
import numpy as np

@dataclass(frozen=True)
class ComparisonResult:
    """Resultado de una comparación."""
    equal: bool
    difference: float
    relative_diff: Optional[float] = None
    absolute_tolerance: float = 1e-10
    relative_tolerance: float = 1e-8

def compare_values(
    expected: Union[float, np.ndarray, list],
    actual: Union[float, np.ndarray, list],
    *,
    atol: float = 1e-10,
    rtol: float = 1e-8,
    verbose: bool = False
) -> ComparisonResult:
    """Compara valores esperados vs actuales.
    
    Args:
        expected: Valor esperado
        actual: Valor actual
        atol: Tolerancia absoluta
        rtol: Tolerancia relativa
        verbose: Imprimir detalles
    
    Returns:
        ComparisonResult con análisis completo
    """
    # Convertir a numpy arrays
    exp_arr = np.asarray(expected)
    act_arr = np.asarray(actual)
    
    # Calcular diferencia
    diff = np.abs(exp_arr - act_arr)
    diff_scalar = float(np.max(diff)) if diff.size > 1 else float(diff)
    
    # Diferencia relativa
    with np.errstate(divide='ignore', invalid='ignore'):
        rel_diff = np.where(
            exp_arr != 0,
            diff / np.abs(exp_arr),
            diff
        )
        rel_diff_scalar = float(np.max(rel_diff)) if rel_diff.size > 1 else float(rel_diff)
    
    # Verificar igual
    equal = bool(diff_scalar <= atol) or bool(rel_diff_scalar <= rtol)
    
    if verbose and not equal:
        print(f"⚠️  Diff: {diff_scalar:.2e}, Rel: {rel_diff_scalar:.2e}")
    
    return ComparisonResult(
        equal=equal,
        difference=diff_scalar,
        relative_diff=rel_diff_scalar,
        absolute_tolerance=atol,
        relative_tolerance=rtol
    )
```

**Pasos**:
1. [ ] Crear `mutalambda/core/comparison.py`
2. [ ] Importar en `runners.py`
3. [ ] Importar en `differential.py`
4. [ ] Eliminar definiciones locales

---

### 📝 FIX 2.3: Logging Centralizado

**Problema**: Logging inconsistente entre módulos.

**Solución**:

```python
# mutalambda/core/logging.py
"""Configuración centralizada de logging."""

import logging
import logging.config
from pathlib import Path

# Logger base para el proyecto
LOGGER_NAME = "MutaLambda"

DEFAULT_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detailed": {
            "format": "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s"
        },
        "simple": {
            "format": "%(levelname)-8s | %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "stream": "ext://sys.stdout"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/mutalambda.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 3,
            "formatter": "detailed"
        }
    },
    "loggers": {
        LOGGER_NAME: {
            "level": "INFO",
            "handlers": ["console", "file"],
            "propagate": False
        }
    },
    "root": {
        "level": "WARNING",
        "handlers": ["console"]
    }
}

_loggers: dict[str, logging.Logger] = {}

def setup_logging(
    log_level: str = "INFO",
    log_file: Path | None = None,
    config_file: Path | None = None
) -> None:
    """Configura logging centralizado."""
    # Crear directorio de logs
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    if config_file and config_file.exists():
        logging.config.fileConfig(config_file)
    else:
        config = DEFAULT_CONFIG.copy()
        
        # Override config
        config["loggers"][LOGGER_NAME]["level"] = log_level
        
        if log_file:
            config["handlers"]["file"]["filename"] = str(log_file)
        
        logging.config.dictConfig(config)
    
    # Limpiar cache de loggers
    _loggers.clear()

def get_logger(name: str) -> logging.Logger:
    """Obtiene logger para el módulo especificado.
    
    Args:
        name: Nombre del submódulo (ej: "evolver", "checkpoint")
    
    Returns:
        Logger configurado
    
    Example:
        >>> logger = get_logger("evolver")
        >>> logger.info("Starting evolution")
        2026-07-15 | MutaLambda.evolver    | INFO     | Starting evolution
    """
    full_name = f"{LOGGER_NAME}.{name}"
    
    if full_name not in _loggers:
        _loggers[full_name] = logging.getLogger(full_name)
    
    return _loggers[full_name]

# Exportar instancia por defecto
def getMutaLambdaLogger() -> logging.Logger:
    """Alias para get_logger sin argumento."""
    return get_logger("MutaLambda")
```

**Pasos**:
1. [ ] Crear `mutalambda/core/logging.py`
2. [ ] Actualizar imports en todos los módulos:
   ```python
   # ANTES:
   import logging
   logger = logging.getLogger("MutaLambda")
   
   # DESPUÉS:
   from mutalambda.core.logging import get_logger
   logger = get_logger(__name__)  # Usa el nombre del módulo automáticamente
   ```
3. [ ] Eliminar definiciones locales de logging

---

### 🚧 FIX 2.4: Completar Métodos con pass

**Problema**: 25+ métodos con solo `pass`.

**Comando de detección**:

```bash
grep -rn "^\s*pass\s*$" --include="*.py" mutalambda/ | grep -B2 "def "
```

**Módulos más afectados**:
- `muta_ext/diagnostics/tipping.py`
- `muta_ext/visualization/` (posibles stubs)

**Template de implementación**:

```python
# ANTES (stub):
def calculate_tipping_point(self, state: State) -> float:
    """Calcular punto de tipping."""
    pass

# DESPUÉS (implementado):
def calculate_tipping_point(self, state: State) -> float:
    """Calcular punto de tipping según teoría de sistemas dinámicos.
    
    El punto de tipping se define como el estado donde pequeñas
    perturbaciones causan cambios de fase irreversibles.
    
    Args:
        state: Estado actual del sistema
    
    Returns:
        Float con el valor del tipping point (0.0 si no hay tipping)
    
    Raises:
        ValueError: Si state es inválido
    """
    if state is None:
        raise ValueError("state no puede ser None")
    
    # Verificar临界 threshold
    critical_threshold = self._get_critical_threshold(state)
    
    if state.energy < critical_threshold:
        return 0.0  # No hay tipping
    
    # Calcular distancia al tipping point
    instability_metric = self._compute_instability(state)
    
    if instability_metric > self.tipping_threshold:
        return instability_metric
    
    return 0.0

def _get_critical_threshold(self, state: State) -> float:
    """Obtiene el threshold crítico para el estado dado."""
    return state.baseline_energy * self.sensitivity_factor

def _compute_instability(self, state: State) -> float:
    """Computa métrica de inestabilidad."""
    return abs(state.gradient_magnitude) / (state.baseline_energy + 1e-10)
```

**Pasos**:
1. [ ] Listar todos los métodos con `pass`
2. [ ] Clasificar: stubs futuros vs código real faltante
3. [ ] Implementar los que tienen lógica clara
4. [ ] Los que no se puedan implementar → `raise NotImplementedError()`

---

### 🛤️ FIX 2.5: Eliminar sys.path Manipulation

**Problema**: `sys.path.insert` en `cli.py` y tests.

**Archivos afectados**:
- `cli.py:22-23`
- `tests/e2e_tests.py`

**Solución**:

```python
# ANTES (cli.py):
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))  # ← Evitar esto

# DESPUÉS:
# Usar instalación del paquete o imports relativos
# 1. Instalar el paquete: pip install -e .
# 2. O usar: from mutalambda.cli.main import main

# Si es necesario para desarrollo:
if __name__ == "__main__" and "mutalambda" not in sys.modules:
    import importlib.util
    # Cargar módulos localmente para desarrollo
    pass
```

**Script de detección y fix**:

```bash
# Encontrar sys.path manipulation
grep -rn "sys.path" --include="*.py" mutalambda/ | grep -v "import sys\|sys.version\|sys.path_"

# Solución: Instalar en modo desarrollo
pip install -e ./mutalambda
```

**Pasos**:
1. [ ] Eliminar `sys.path.insert` de `cli.py`
2. [ ] Eliminar de `tests/e2e_tests.py`
3. [ ] Asegurar que el paquete esté instalado: `pip install -e .`
4. [ ] Verificar que CLI funcione

---

### ✅ FIX 2.6: Validación de Config YAML

**Problema**: Sin validación de estructura de config YAML.

**Solución con Pydantic**:

```python
# mutalambda/core/config/schema.py
"""Schemas de validación para configuración YAML."""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from pathlib import Path

class EvolutionConfig(BaseModel):
    """Configuración de evolución."""
    population_size: int = Field(100, ge=10, le=10000)
    generations: int = Field(1000, ge=1)
    mutation_rate: float = Field(0.1, ge=0.0, le=1.0)
    crossover_rate: float = Field(0.7, ge=0.0, le=1.0)
    elite_size: int = Field(5, ge=0)
    
    @field_validator("mutation_rate")
    @classmethod
    def validate_mutation_rate(cls, v):
        if v <= 0:
            raise ValueError("mutation_rate debe ser > 0")
        return v

class CheckpointConfig(BaseModel):
    """Configuración de checkpoints."""
    enabled: bool = True
    interval: int = Field(10, ge=1)
    max_checkpoints: int = Field(50, ge=1)
    storage_path: Optional[Path] = None

class LoggingConfig(BaseModel):
    """Configuración de logging."""
    level: str = "INFO"
    file: Optional[Path] = None
    console: bool = True

class MutalambdaConfig(BaseModel):
    """Configuración principal de Mutalambda."""
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    checkpoint: CheckpointConfig = Field(default_factory=CheckpointConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    
    @classmethod
    def from_yaml(cls, path: Path) -> "MutalambdaConfig":
        """Carga config desde YAML con validación."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
    
    def to_yaml(self, path: Path) -> None:
        """Guarda config validado a YAML."""
        import yaml
        with open(path, "w") as f:
            yaml.safe_dump(self.model_dump(), f, default_flow_style=False)
```

**Pasos**:
1. [ ] Crear `mutalambda/core/config/schema.py`
2. [ ] Actualizar `cli/config_manager.py` para usar validación
3. [ ] Añadir schema por defecto para nuevos usuarios

---

### ⚠️ FIX 2.7: Especificar Excepciones Genéricas

**Problema**: `except Exception` sin acción específica.

**Script detector**:

```python
# detect_generic_exceptions.py
import ast
from pathlib import Path
from dataclasses import dataclass

@dataclass
class GenericExcept:
    file: str
    line: int
    handler_type: str

def detect_generic_exceptions(directory: Path) -> list[GenericExcept]:
    """Detecta except Exception sin manejo específico."""
    findings = []
    
    for py_file in directory.rglob("*.py"):
        if "test" in py_file.name:
            continue
        
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                type_name = ast.unparse(node.type) if node.type else "bare"
                
                if type_name in ("Exception", "BaseException"):
                    findings.append(GenericExcept(
                        file=str(py_file),
                        line=node.lineno,
                        handler_type=type_name
                    ))
    
    return findings

if __name__ == "__main__":
    findings = detect_generic_exceptions(Path("mutalambda"))
    
    print(f"🚨 {len(findings)} except Exception genéricos\n")
    for f in findings:
        print(f"📁 {f.file}:{f.line} - {f.handler_type}")
```

**Pasos**:
1. [ ] Ejecutar detector
2. [ ] Para cada caso, decidir:
   - ¿Se puede ser más específico? → Especificar excepción
   - ¿El logging es suficiente? → Añadir logging
   - ¿Se necesita re-lanzar? → Añadir `raise`

---

## ═══════════════════════════════════════════════════════════════════
# FASE 3: MEDIA PRIORIDAD — Semana 4
## ═══════════════════════════════════════════════════════════════════

---

### 📦 FIX 3.1: Limpiar __init__.py Vacíos

**Comando de detección**:

```bash
for f in $(find mutalambda -name "__init__.py"); do
    lines=$(wc -l < "$f")
    if [ $lines -le 3 ]; then
        echo "$f ($lines líneas)"
    fi
done
```

**7 paquetes con __init__.py vacíos**.

**Pasos**:
1. [ ] Listar todos los __init__.py
2. [ ] Evaluar cada uno:
   - ¿Exporta algo útil? → Mantener con `__all__`
   - ¿No exporta nada? → Eliminar

```python
# Ejemplo de __init__.py útil:
# mutalambda/evolution/__init__.py

from .population import Population, Individual
from .selectors import Selector, TournamentSelector
from .crossovers import CrossoverOperator

__all__ = [
    "Population",
    "Individual", 
    "Selector",
    "TournamentSelector",
    "CrossoverOperator",
]
```

---

### 📜 FIX 3.2: Limpiar Legacy Code

**Problema**: ~724 líneas de código legacy sin uso.

**Ubicación**: `legacy/` (directorio completo)

**Script de análisis de uso**:

```python
# analyze_legacy_usage.py
import ast
from pathlib import Path
from collections import defaultdict

def find_imports_legacy(directory: Path) -> dict[str, list[str]]:
    """Encuentra qué archivos importan desde legacy/."""
    imports = defaultdict(list)
    
    for py_file in directory.rglob("*.py"):
        if "legacy" in str(py_file):
            continue
        
        try:
            content = py_file.read_text()
            tree = ast.parse(content)
        except SyntaxError:
            continue
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "legacy" in node.module:
                    for alias in node.names:
                        imports[py_file.name].append(
                            f"{node.module}.{alias.name}"
                        )
    
    return imports

if __name__ == "__main__":
    # Buscar imports de legacy
    root = Path("mutalambda")
    imports = find_imports_legacy(root)
    
    if imports:
        print("⚠️  Archivos que dependen de legacy/:\n")
        for file, items in imports.items():
            print(f"  📁 {file}")
            for item in items:
                print(f"     └── {item}")
    else:
        print("✅ No hay dependencias de legacy/")
```

**Pasos**:
1. [ ] Analizar uso de legacy/
2. [ ] Migrar funcionalidad si es necesaria
3. [ ] Archivar en repo separado si no:
   ```bash
   mv legacy/ ../mutalambda-legacy-archive/
   git add -A && git commit -m "chore: archive legacy code"
   ```

---

### 📝 FIX 3.3: Estandarizar Naming

**Problema**: Inconsistencias en nombres de clases.

**Mapeo de correcciones**:

| Antes | Después | Razón |
|-------|---------|-------|
| `_FakeEvaluator` | `_MockEvaluator` | "Mock" es el término estándar |
| `TestCanonicalCache` | `TestCanonicalCache` | OK, pero verificar si necesario |
| Clases internas sin underscore | `_ClassName` | PEP 8: privados |
| `calculate_` prefix | `_calculate_` | Si es privado |

**Script de renombrado**:

```python
# standardize_naming.py
import re
from pathlib import Path

RENAMES = {
    # Clases privadas: _FakeEvaluator -> _MockEvaluator
    "_FakeEvaluator": "_MockEvaluator",
    "_fake_evaluator": "_mock_evaluator",
    
    # Métodos privados: calculate_* -> _calculate_*
    "def calculate_": "def _calculate_",
    
    # Constantes: UPPERCASE
    "max_iterations": "MAX_ITERATIONS",
    "default_timeout": "DEFAULT_TIMEOUT",
}

def apply_renames(directory: Path) -> int:
    count = 0
    for py_file in directory.rglob("*.py"):
        if "test" in py_file.name:
            continue
        
        content = py_file.read_text()
        original = content
        
        for old, new in RENAMES.items():
            if old in content:
                content = content.replace(old, new)
                count += content.count(new) - content.count(old)
        
        if content != original:
            py_file.write_text(content)
            print(f"✅ {py_file}")
    
    return count

if __name__ == "__main__":
    count = apply_renames(Path("mutalambda"))
    print(f"\n📊 {count} cambios aplicados")
```

**Pasos**:
1. [ ] Ejecutar script de renombrado
2. [ ] Actualizar tests relacionados
3. [ ] Verificar que todo funcione

---

### 🔧 FIX 3.4: Consolidar Configuración

**Archivos de configuración actuales**:
- `config.yaml` (raíz)
- `repomix.config.json`
- `pyproject.toml`

**Solución**: Consolidar en `pyproject.toml` y `config.yaml` unificado.

```toml
# pyproject.toml (completado)

[project]
name = "mutalambda"
version = "1.0.0"
description = "Framework de optimización evolutiva"

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1",
]

[tool.mutalambda.config]
# Configuración por defecto integrada
[tool.mutalambda.config.evolution]
population_size = 100
generations = 1000
mutation_rate = 0.1

[tool.mutalambda.config.checkpoint]
enabled = true
interval = 10

[tool.mutalambda.config.logging]
level = "INFO"
```

**Pasos**:
1. [ ] Mover config dispersos a `pyproject.toml`
2. [ ] Crear `config.yaml` unificado para runtime
3. [ ] Eliminar `repomix.config.json`

---

### 🔢 FIX 3.5: Centralizar Constantes Mágicas

**Problema**: Números mágicos sin explicación.

**Constantes a extraer**:

```python
# mutalambda/core/constants.py
"""Constantes del proyecto."""

from typing import Final

# Evolución
MAX_POPULATION_SIZE: Final[int] = 10000
MIN_POPULATION_SIZE: Final[int] = 10
DEFAULT_POPULATION_SIZE: Final[int] = 100

DEFAULT_MUTATION_RATE: Final[float] = 0.1
DEFAULT_CROSSOVER_RATE: Final[float] = 0.7
DEFAULT_ELITE_SIZE: Final[int] = 5

# Convergencia
DEFAULT_TOLERANCE: Final[float] = 1e-8
ABSOLUTE_TOLERANCE: Final[float] = 1e-10
RELATIVE_TOLERANCE: Final[float] = 1e-8
MAX_GENERATIONS_NO_IMPROVEMENT: Final[int] = 50

# Checkpoints
DEFAULT_CHECKPOINT_INTERVAL: Final[int] = 10
MAX_CHECKPOINTS: Final[int] = 50

# Hashing
HASH_ALGORITHM: Final[str] = "sha256"
CODE_HASH_LENGTH: Final[int] = 64

# Logging
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
LOG_FILE_MAX_BYTES: Final[int] = 10_485_760  # 10MB
LOG_FILE_BACKUP_COUNT: Final[int] = 3

# Nombres de archivos
CHECKPOINT_FILENAME: Final[str] = "checkpoint_{id}.pkl"
LOG_FILENAME: Final[str] = "mutalambda.log"
ARCHIVE_SUBDIR: Final[str] = "archive"
```

**Pasos**:
1. [ ] Crear `mutalambda/core/constants.py`
2. [ ] Reemplazar números mágicos en todo el codebase
3. [ ] Verificar que tests pasen

---

## ═══════════════════════════════════════════════════════════════════
# FASE 4: BAJA PRIORIDAD — Semana 5
## ═══════════════════════════════════════════════════════════════════

---

### 🧪 FIX 4.1: Consolidar Tests Redundantes

**Tests que podrían combinarse**:
- `tests/test_solution_archive.py`
- `tests/test_nsga2.py`

**Criterios**:
- Misma clase probada → misma clase de test
- Mismo fixture → compartir

```python
# tests/test_archive_and_nsga2.py
import pytest

class TestSolutionArchive:
    """Tests para SolutionArchive."""
    
    @pytest.fixture
    def archive(self):
        return SolutionArchive()
    
    def test_add_solution(self, archive):
        ...

class TestNSGA2:
    """Tests para NSGA2."""
    
    @pytest.fixture
    def nsga2(self):
        return NSGA2()
    
    def test_pareto_front(self, nsga2):
        ...
```

**Pasos**:
1. [ ] Identificar tests redundantes
2. [ ] Consolidar en clases lógicas
3. [ ] Eliminar duplicados

---

### 📊 FIX 4.2: Documentar Métricas Sin Uso

**Revisar `fitness_vector.py`**:
- ¿Qué métricas están definidas?
- ¿Cuáles se usan?
- ¿Cuáles deben documentarse?

```python
# fitness_vector.py - Documentación añadir

class FitnessVector:
    """Vector de fitness multi-objetivo.
    
    Attributes:
        objectives: Lista de objetivos
        weights: Pesos para cada objetivo
        normalized: Si el vector está normalizado
    
    Note:
        Las métricas disponibles son:
        - hypervolume: Indicador de calidad de Pareto
        - spread: Distribución del frente de Pareto
        - epsilon: Calidad de aproximación
        
        Usar evaluate() para computar fitness real.
    """
    
    def __init__(self, objectives: list[str]):
        self.objectives = objectives
```

---

## 🚀 SCRIPT DE EJECUCIÓN COMPLETO

```bash
#!/bin/bash
# run_workflow.sh - Ejecutar workflow completo de MutaLambda

set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  WORKFLOW MutLambda - OPTIMIZACIÓN Y CORRECCIÓN         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Verificar dependencias
echo "📦 Verificando dependencias..."
pip install pydantic pyyaml pytest pytest-cov ruff --quiet

# FASE 1: Críticas
echo ""
echo "══════════════════════════════════════════════════════════"
echo "FASE 1: CRÍTICAS"
echo "══════════════════════════════════════════════════════════"

echo "1.1 🔧 Consolidando stable_code_hash()..."
mkdir -p mutalambda/core/utils
python << 'EOF'
# Crear archivo de hash centralizado
EOF

echo "1.2 🔀 Renombrando Checkpoint ambiguo..."
python rename_checkpoints.py

echo "1.3 🚫 Reemplazando try-except desnudos..."
python detect_bare_excepts.py > bare_excepts.txt
# Revisar y reemplazar manualmente

# FASE 2: Alta
echo ""
echo "══════════════════════════════════════════════════════════"
echo "FASE 2: ALTA PRIORIDAD"
echo "══════════════════════════════════════════════════════════"

echo "2.1 🎲 Centralizando RNG..."
mkdir -p mutalambda/core
python << 'EOF'
# Crear rng_session.py
EOF

echo "2.2 🔧 Consolidando compare_values..."
python << 'EOF'
# Crear comparison.py
EOF

echo "2.3 📝 Implementando logging centralizado..."
python << 'EOF'
# Crear logging.py
EOF

echo "2.4 🚧 Completando métodos con pass..."
# Investigar y completar uno por uno

echo "2.5 🛤️  Eliminando sys.path manipulation..."
pip install -e .  # Instalar en modo desarrollo

echo "2.6 ✅ Añadiendo validación de config..."
python << 'EOF'
# Crear config/schema.py
EOF

# FASE 3: Media
echo ""
echo "══════════════════════════════════════════════════════════"
echo "FASE 3: MEDIA PRIORIDAD"
echo "══════════════════════════════════════════════════════════"

echo "3.1 📦 Limpiando __init__.py vacíos..."
# Identificar y limpiar

echo "3.2 📜 Archivando legacy code..."
# Mover a repositorio separado si no se usa

echo "3.3 📝 Estandarizando naming..."
python standardize_naming.py

echo "3.4 🔧 Consolidando config..."
# Integrar en pyproject.toml

echo "3.5 🔢 Centralizando constantes..."
python << 'EOF'
# Crear constants.py
EOF

# FASE 4: Baja
echo ""
echo "══════════════════════════════════════════════════════════"
echo "FASE 4: BAJA PRIORIDAD"
echo "══════════════════════════════════════════════════════════"

echo "4.1 🧪 Consolidando tests..."
# Combinar tests relacionados

echo "4.2 📊 Documentando métricas..."
# Documentar fitness_vector

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅ WORKFLOW COMPLETADO                                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
```

---

## 📊 CHECKLIST DE VERIFICACIÓN

```markdown
## ✅ Checklist de Completitud - MutLambda

### FASE 1: Críticas
- [ ] FIX 1.1: stable_code_hash() centralizado en utils/hash.py
- [ ] FIX 1.1: Eliminada duplicación de models.py
- [ ] FIX 1.2: Checkpoint -> CheckpointData renombrado
- [ ] FIX 1.3: Try-except desnudos reemplazados

### FASE 2: Alta
- [ ] FIX 2.1: RNG centralizado con RNGSession
- [ ] FIX 2.1: 90+ random. reemplazados
- [ ] FIX 2.2: compare_values() consolidado
- [ ] FIX 2.3: Logging centralizado
- [ ] FIX 2.4: Métodos con pass implementados o con NotImplementedError
- [ ] FIX 2.5: sys.path.insert eliminado
- [ ] FIX 2.6: Validación YAML con Pydantic
- [ ] FIX 2.7: Excepciones genéricas especificadas

### FASE 3: Media
- [ ] FIX 3.1: __init__.py vacíos limpiados
- [ ] FIX 3.2: legacy/ archivado o eliminado
- [ ] FIX 3.3: Naming estandarizado
- [ ] FIX 3.4: Configuración consolidada en pyproject.toml
- [ ] FIX 3.5: Constantes centralizadas en constants.py

### FASE 4: Baja
- [ ] FIX 4.1: Tests redundantes consolidados
- [ ] FIX 4.2: Métricas documentadas

### Geral
- [ ] Todos los tests pasan: `pytest -x`
- [ ] Sin errores de linting: `ruff check .`
- [ ] Sin warnings: `python -W all -c "import mutalambda"`
- [ ] Documentación actualizada
```

---

## 📈 MÉTRICAS DE ÉXITO

| Métrica | Antes | Después | Meta |
|---------|-------|---------|------|
| Duplicación stable_hash | 2 | 1 | 0 |
| Except desnudos | 5+ | 0 | 0 |
| random. calls | 90+ | 0 | 0 |
| Logging centralizado | parcial | completo | completo |
| Métodos con pass | 25+ | 0 | 0 |
| sys.path manipulation | 2 | 0 | 0 |
| __init__.py vacíos | 7 | 0 | 0 |
| Legacy code | ~724 líneas | 0 | 0 |

---

## 📋 SCRIPTS AUXILIARES

### Script 1: Detección de Problemas

```python
# diagnose_mutalambda.py
"""Script de diagnóstico completo de Mutalambda."""

import subprocess
from pathlib import Path

def run_diagnostics():
    """Ejecuta todas las diagnóstico checks."""
    
    checks = [
        ("Duplicados stable_code_hash", 
         "grep -rn 'def stable_code_hash' --include='*.py'"),
        ("Except desnudos",
         "python detect_bare_excepts.py"),
        ("sys.path manipulation",
         "grep -rn 'sys.path.insert' --include='*.py'"),
        ("Métodos con pass",
         "grep -rn '^\\s*pass\\s*$' --include='*.py'"),
        ("Constantes mágicas",
         "grep -rn '\\b0\\.\\d\\+\\|1000\\|42\\b' --include='*.py' | head -20"),
    ]
    
    print("# 🔍 Diagnóstico de Mutalambda\n")
    
    for name, cmd in checks:
        print(f"## {name}")
        print(f"```bash\n{cmd}\n```")
        print()
        
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout)
        print()

if __name__ == "__main__":
    run_diagnostics()
```

### Script 2: Generador de Reporte de Calidad

```python
# quality_report.py
"""Genera reporte de calidad del codebase."""

import ast
from pathlib import Path
from dataclasses import dataclass

@dataclass
class QualityMetrics:
    total_files: int = 0
    total_lines: int = 0
    functions: int = 0
    classes: int = 0
    dataclasses: int = 0
    with_type_hints: int = 0
    with_docstrings: int = 0

def analyze_file(path: Path) -> QualityMetrics:
    """Analiza un archivo Python."""
    metrics = QualityMetrics()
    
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return metrics
    
    metrics.total_files = 1
    
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            metrics.functions += 1
            if node.returns:
                metrics.with_type_hints += 1
            if ast.get_docstring(node):
                metrics.with_docstrings += 1
        elif isinstance(node, ast.ClassDef):
            metrics.classes += 1
            if any(isinstance(n, ast.AnnAssign) and 
                   any(isinstance(b, ast.Name) and b.id == 'dataclass' 
                       for b in ast.walk(n.annotation))
                   for n in node.decorator_list if isinstance(n, ast.Call)):
                metrics.dataclasses += 1
    
    return metrics

def main():
    """Genera reporte completo."""
    root = Path("mutalambda")
    total = QualityMetrics()
    
    for py_file in root.rglob("*.py"):
        if "test" not in py_file.name and "__pycache__" not in str(py_file):
            m = analyze_file(py_file)
            for attr in ['total_files', 'total_lines', 'functions', 
                        'classes', 'dataclasses', 'with_type_hints',
                        'with_docstrings']:
                setattr(total, attr, getattr(total, attr) + getattr(m, attr))
    
    print("# 📊 Reporte de Calidad - Mutalambda\n")
    print(f"| Métrica | Valor |")
    print(f"|---------|-------|")
    print(f"| Archivos | {total.total_files} |")
    print(f"| Funciones | {total.functions} |")
    print(f"| Clases | {total.classes} |")
    print(f"| Dataclasses | {total.dataclasses} |")
    print(f"| Con type hints | {total.with_type_hints} ({100*total.with_type_hints//max(1,total.functions)}%) |")
    print(f"| Con docstrings | {total.with_docstrings} ({100*total.with_docstrings//max(1,total.functions)}%) |")

if __name__ == "__main__":
    main()
```

---

*Generado: 2026-07-15 | Proyecto: MutLambda v1.0.0*