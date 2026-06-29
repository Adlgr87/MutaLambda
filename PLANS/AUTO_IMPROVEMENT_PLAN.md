# 🧬 MutaLambda — Plan de Auto-Mejora con Migración Dirigida

**Fecha:** 2026-06-29  
**Objetivo:** Modificar MutaLambda para que migre de forma asertiva (fitness-directed), luego usar MutaLambda para evolucionar sus propios módulos, documentar benchmarks empíricos, y hacer push a GitHub.

---

## 📋 FASE 0: Reconocimiento y Diagnóstico

### Estado actual del sistema de migración

| Topología | Comportamiento | Problema |
|---|---|---|
| `ring` | Cada isla envía a sus 2 vecinos fijos | Demasiado determinista, ignora fitness |
| `fully_connected` | Todos envían a todos | Ruido masivo, pérdida de diversidad |
| `mesh` | Grid 2D geométrico fijo | Arbitrario, no considera calidad |
| `spatial_grid` | Usa métricas básicas | Mejor, pero sin gradiente de fitness |
| Fallback (default) | **Random sample de 2 vecinos** | Completamente aleatorio |

**Veredicto:** Ninguna topología actual considera **hacia dónde conviene migrar**. La migración es puramente geométrica/topológica.

### Modelo de migración propuesto: **Fitness-Directed Gradient Migration**

En lugar de migrar según topología fija, la migración usa un **gradiente de fitness**:

```
Para cada isla fuente (stagnant_score < threshold):
  1. Evaluar compatibilidad genética con cada isla destino
  2. Calcular "fitness_gradient" = destino.fitness - fuente.fitness
  3. Calcular "diversity_gap" = 1 - similitud(fuente, destino)
  4. Score de migración = α × fitness_gradient + β × diversity_gap
  5. Enviar migrantes SOLO a las top-K islas con mayor score
  6. Inyectar individuos de élite (top 5% del donante) como "semillas dirigidas"
```

---

## 📋 FASE 1: Migración Fitness-Directed (MODIFICACIÓN DEL CORE)

### Archivos a modificar:

| Archivo | Cambio |
|---|---|
| `migration.py` | Añadir clase `FitnessDirectedMigration` + nueva topología `fitness_gradient` |
| `muta_lambda.py` | Integrar `FitnessDirectedMigration` en el MigrationBus |
| `config.yaml` | Añadir parámetros de migración dirigida (α, β, top_k, stagnation_threshold) |
| `tests/test_fitness_directed_migration.py` | Tests unitarios del nuevo sistema |

### Parámetros configurables:

```yaml
migration:
  topology: fitness_gradient      # Nueva topología
  gradient_alpha: 0.7             # Peso del gradiente de fitness
  gradient_beta: 0.3              # Peso del gap de diversidad
  top_k_targets: 2                # Islas destino por migración
  stagnation_threshold: 0.05      # Ratio de mejora mínima para no considerar estancada
  elite_injection: true           # Inyectar top 5% como semillas
  min_diversity_gap: 0.2          # Umbral mínimo de diversidad para migrar
```

### Lógica de migración dirigida:

```python
class FitnessDirectedMigration:
    """Migración basada en gradiente de fitness + diversidad genética."""
    
    def select_targets(self, source_island, all_islands, config):
        """Selecciona destinos basándose en fitness gradient + diversity gap."""
        source_fitness = source_island.avg_fitness
        source_code_hash = source_island.dominant_code_signature()
        
        scored_targets = []
        for target in all_islands:
            if target.id == source_island.id:
                continue
            fitness_grad = target.avg_fitness - source_fitness
            diversity_gap = 1.0 - code_similarity(source_code_hash, target.dominant_code_signature())
            score = config.alpha * fitness_grad + config.beta * diversity_gap
            scored_targets.append((score, target))
        
        return sorted(scored_targets, reverse=True)[:config.top_k]
    
    def migrate(self, source, targets, migrants):
        """Envía migrantes solo a targets seleccionados + elite injection."""
        for score, target in targets:
            for migrant in migrants:
                target.receive_migrant(copy.deepcopy(migrant))
            # Elite injection: inyectar el MEJOR individuo del donante
            if config.elite_injection and source.local_best:
                elite = copy.deepcopy(source.local_best)
                elite.tags.add("elite_injection")
                target.receive_migrant(elite)
```

---

## 📋 FASE 2: Identificar Módulos Mejorables

### Análisis de modularidad y testabilidad:

| Módulo | Autocontenido | Tests existentes | Fitness medible | **Candidato** |
|---|---|---|---|---|
| `nsga2.py` (fast_non_dominated_sort, crowding_distance) | ✅ | ✅ | ✅ Performance | ✅ **SÍ** |
| `fitness_vector.py` (FitnessVector ops) | ✅ | ✅ | ✅ Throughput | ✅ **SÍ** |
| `island.py` (mutaciones AST: ast_swap_binop, etc.) | ✅ | ✅ | ✅ Correctness+Speed | ✅ **SÍ** |
| `mutation_operators.py` (generadores LLM) | ⚠️ Depende de LLM | ✅ | ✅ Code quality | ⚠️ PARCIAL |
| `meta_evolution.py` (EvoParams evolution) | ✅ | ✅ | ✅ Convergence | ✅ **SÍ** |
| `advanced_selection.py` (UCB, Thompson, etc.) | ✅ | ✅ | ✅ Selection quality | ✅ **SÍ** |
| `prompt_evolver.py` (PromptEvolver step) | ⚠️ Requiere LLM | ✅ | ✅ Prompt quality | ⚠️ PARCIAL |
| `early_stop_monitor.py` | ✅ | ✅ | ✅ Accuracy | ✅ **SÍ** |
| `models.py` (Individual, EvoStats) | ✅ | ✅ | ✅ Serialization | ⚠️ BAJO IMPACTO |
| `sandbox.py` (Docker eval) | ❌ Requiere Docker | ✅ | ❌ | ❌ NO |
| `llm_backend.py` | ❌ Requiere API key | ❌ | ❌ | ❌ NO |
| `spatial_topology.py` | ✅ | ✅ | ✅ | ✅ **SÍ** |
| `thc_engine.py` (fragment extraction) | ✅ | ✅ | ✅ Quality | ✅ **SÍ** |
| `dialectic_engine.py` | ⚠️ Requiere LLM | ✅ | ✅ | ⚠️ PARCIAL |
| `lineage_graph.py` | ✅ | ✅ | ✅ Graph ops | ✅ **SÍ** |
| `hfc.py` (tier management) | ✅ | ✅ | ✅ Tier accuracy | ✅ **SÍ** |

### Módulos PRIORITARIOS para auto-evolución:

1. **`nsga2.py`** — Algoritmo core de selección, alto impacto en convergencia
2. **`island.py`** (mutaciones AST) — Generación de variantes, impacto directo en calidad
3. **`fitness_vector.py`** — Cálculos de fitness, impacto en evaluación
4. **`meta_evolution.py`** — Auto-optimización de parámetros
5. **`advanced_selection.py`** — Estrategias de exploración/explotación

---

## 📋 FASE 3: Selección del LLM para Mutaciones

### Modelos disponibles en el sistema:

| Provider | Modelo | Código | Razonamiento | Velocidad | Costo | **Recomendación** |
|---|---|---|---|---|---|---|
| DeepSeek | deepseek-v4-flash | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Bajo | Rápido pero limitado |
| Custom | mistral-vibe-cli-with-tools | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | Medio | Bueno para código |
| Custom | codestral-latest | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Medio | **Óptimo para código** |
| OpenCode | qwen3.6-plus | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | Alto | **Mejor razonamiento** |
| OpenCode | gemini-3.1-pro | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | Alto | Bueno |
| OpenCode | gpt-5.4 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | Alto | Excelente pero lento |

### Recomendación:

**Principal: `codestral-latest`** (vía Custom/Headroom) — Mejor balance código/velocidad para mutaciones AST informadas.

**Alternativa: `qwen3.6-plus`** (vía OpenCode) — Si se necesita razonamiento matemático más profundo para NSGA-II.

**Fallback: `deepseek-v4-flash`** — Para mutaciones rápidas de bajo costo.

### Configuración propuesta para MutaLambda:

```yaml
llm:
  primary_model: codestral-latest     # Para mutaciones informadas
  fallback_model: deepseek-v4-flash   # Para mutaciones rápidas
  provider_url: http://127.0.0.1:8787/v1  # Via Headroom proxy
  temperature: 0.7
  max_tokens: 4096
```

---

## 📋 FASE 4: Pipeline de Auto-Evolución

### Arquitectura del loop:

```
┌──────────────────────────────────────────────────────────────────┐
│                    AUTO-EVOLUTION PIPELINE                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐    ┌──────────────────┐    ┌───────────────┐   │
│  │ 1. EXTRACT  │───►│ 2. EVOLVE        │───►│ 3. VALIDATE   │   │
│  │  Module as  │    │ with MutaLambda  │    │ with pytest   │   │
│  │  seed code  │    │ (sandbox + LLM)  │    │ + benchmarks  │   │
│  └─────────────┘    └──────────────────┘    └───────────────┘   │
│         │                                          │              │
│         ▼                                          ▼              │
│  ┌─────────────┐                           ┌───────────────┐    │
│  │ 4. LEARN   │◄──────────────────────────│ 5. SELECT     │    │
│  │ GBrain     │                            │ Best variant  │    │
│  │ store facts│                            │ by fitness    │    │
│  └─────────────┘                            └───────────────┘    │
│         │                                          │              │
│         ▼                                          ▼              │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ 6. DEPLOY: Replace module if variant > baseline + δ     │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Orquestador externo (rol supervisor):

```python
# Mi rol como supervisor:
# 1. Configurar MutaLambda con los parámetros correctos
# 2. Extraer módulos como seeds
# 3. Ejecutar evolución
# 4. Validar resultados
# 5. Almacenar benchmarks en GBrain
# 6. Push a GitHub si hay mejora
```

---

## 📋 FASE 5: Benchmarks y Evidencia Empírica

### Métricas a documentar:

| Métrica | Descripción | Método |
|---|---|---|
| Convergence Speed | Generaciones hasta solución | `_global_best_history` |
| Final Fitness Score | Score del mejor individuo | `global_best.score` |
| Diversity Preservation | Diversidad intra/cross-isla | `_compute_cross_island_diversity()` |
| Migration Efficiency | % migrantes que mejoran destino | Tracking en `FitnessDirectedMigration` |
| Code Quality | Cyclomatic complexity, AST depth | Análisis estático |
| Wall Clock Time | Tiempo total de evolución | `time.perf_counter()` |
| Pareto Front Size | Tamaño del frente Pareto | `nsga2_stats` |

### Estructura de benchmarks:

```
benchmarks/
├── baseline/                    # Antes de los cambios
│   ├── migration_ring.json
│   ├── migration_fully_connected.json
│   └── migration_mesh.json
├── fitness_directed/            # Después de los cambios
│   ├── migration_gradient.json
│   ├── self_evolution_nsga2.json
│   └── self_evolution_island.json
├── comparison_report.md         # Informe comparativo
└── evidence/
    ├── convergence_plots.png
    ├── pareto_fronts.png
    └── migration_heatmap.png
```

---

## 📋 FASE 6: Push a GitHub

### Secuencia de commits:

1. **`feat: fitness-directed migration system`** — Nuevo sistema de migración
2. **`feat: self-evolution pipeline`** — Orquestador de auto-mejora  
3. **`docs: empirical benchmarks`** — Resultados de benchmarks
4. **`chore: benchmark evidence`** — Datos de evidencia

---

## 📋 ORDEN DE EJECUCIÓN

| Paso | Acción | Herramienta | Estimación |
|---|---|---|---|
| 1 | Implementar `FitnessDirectedMigration` en `migration.py` | Write/Edit | 15 min |
| 2 | Integrar en `muta_lambda.py` | Edit | 10 min |
| 3 | Crear `config.yaml` con parámetros | Write | 5 min |
| 4 | Escribir tests de migración dirigida | Write | 10 min |
| 5 | Ejecutar tests (baseline vs nueva migración) | ExecCommand | 5 min |
| 6 | Configurar LLM (codestral-latest) | Edit | 5 min |
| 7 | Extraer módulos candidatos como seeds | Python script | 10 min |
| 8 | Ejecutar auto-evolución por módulo | MutaLambda | 30-60 min |
| 9 | Validar resultados con pytest | ExecCommand | 5 min |
| 10 | Generar benchmarks comparativos | Python script | 15 min |
| 11 | Almacenar en GBrain | gbrain_put_page | 5 min |
| 12 | Commit + push a GitHub | git | 5 min |

---

## ⚠️ CRITERIOS DE ÉXITO

- [ ] Migración dirigida reduce estancamiento vs topologías fijas
- [ ] Al menos 1 módulo evoluciona con fitness > baseline
- [ ] Benchmarks documentados con métricas cuantitativas
- [ ] Tests pasan en todas las variantes
- [ ] Código pusheado a GitHub
