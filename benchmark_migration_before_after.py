#!/usr/bin/env python3
"""
Benchmark comparativo: Migración Antes vs Después

Compara empíricamente el comportamiento del sistema de migración:
- ANTES: Topologías puras (ring, mesh, fully_connected) - migración ciega
- DESPUÉS: fitness_gradient - migración dirigida por fitness

Métricas:
- Migraciones útiles (mejoran fitness del destino)
- Migraciones neutrales (sin efecto)
- Migraciones dañinas (empeoran fitness del destino)
- Tasa de éxito (% de migraciones útiles)
"""

import random
import time
from typing import List, Dict, Tuple
from unittest.mock import MagicMock


class MockIsland:
    """Isla simulada para benchmark."""
    
    def __init__(self, island_id: int, base_fitness: float = 0.5):
        self.id = island_id
        self.population = [
            {"code": f"island_{island_id}_ind_{i}", "score": base_fitness + random.gauss(0, 0.05)}
            for i in range(10)
        ]
        self.migration_bus = None
        self.incoming_migrants = []
        
    @property
    def local_best(self):
        if not self.population:
            return None
        return max(self.population, key=lambda x: x["score"])
    
    @property
    def average_fitness(self):
        if not self.population:
            return 0.0
        return sum(ind["score"] for ind in self.population) / len(self.population)
    
    def get_migrants(self, count: int) -> List[Dict]:
        """Retorna los mejores individuos como migrantes."""
        sorted_pop = sorted(self.population, key=lambda x: x["score"], reverse=True)
        return [ind.copy() for ind in sorted_pop[:count]]
    
    def receive_migrant(self, migrant: Dict):
        """Recibe un migrante."""
        self.incoming_migrants.append(migrant)
    
    def integrate_migrants(self):
        """Integra migrantes a la población."""
        for migrant in self.incoming_migrants:
            self.population.append(migrant)
        self.incoming_migrants = []


def simulate_topological_migration(islands: Dict[int, MockIsland], topology: str = "ring") -> Dict:
    """Simula migración topológica (antes de las modificaciones)."""
    
    island_list = list(islands.values())
    n_islands = len(island_list)
    
    # Determinar vecinos según topología
    neighbors = {}
    for i, island in enumerate(island_list):
        if topology == "ring":
            left = island_list[(i - 1) % n_islands]
            right = island_list[(i + 1) % n_islands]
            neighbors[island.id] = [left, right]
        elif topology == "fully_connected":
            neighbors[island.id] = [other for other in island_list if other.id != island.id]
        elif topology == "mesh":
            # Grid 2D simplificado
            neighbors[island.id] = []
            if i > 0:
                neighbors[island.id].append(island_list[i - 1])
            if i < n_islands - 1:
                neighbors[island.id].append(island_list[i + 1])
    
    # Estadísticas
    stats = {
        "total_migrations": 0,
        "useful": 0,
        "neutral": 0,
        "harmful": 0,
        "fitness_improvements": []
    }
    
    # Realizar migraciones
    for source in island_list:
        migrants = source.get_migrants(2)  # 2 migrantes por isla
        
        for target in neighbors[source.id]:
            target_fitness_before = target.average_fitness
            
            for migrant in migrants:
                target.receive_migrant(migrant)
                stats["total_migrations"] += 1
                
                # Evaluar impacto
                migrant_score = migrant["score"]
                if migrant_score > target_fitness_before:
                    stats["useful"] += 1
                    stats["fitness_improvements"].append(migrant_score - target_fitness_before)
                elif migrant_score >= target_fitness_before - 0.01:
                    stats["neutral"] += 1
                else:
                    stats["harmful"] += 1
            
            target.integrate_migrants()
    
    return stats


def simulate_fitness_directed_migration(islands: Dict[int, MockIsland]) -> Dict:
    """Simula migración dirigida por fitness (después de las modificaciones)."""
    
    island_list = list(islands.values())
    
    # Estadísticas
    stats = {
        "total_migrations": 0,
        "useful": 0,
        "neutral": 0,
        "harmful": 0,
        "fitness_improvements": [],
        "skipped_low_diversity": 0,
        "skipped_low_gradient": 0
    }
    
    # Parámetros de fitness-directed
    alpha = 0.7  # Peso del gradiente de fitness
    beta = 0.3   # Peso del gap de diversidad
    top_k = 2    # Número de destinos por migración
    min_diversity_gap = 0.1
    
    for source in island_list:
        source_fitness = source.average_fitness
        migrants = source.get_migrants(2)
        
        # Seleccionar destinos basándose en gradiente de fitness
        targets = []
        for target in island_list:
            if target.id == source.id:
                continue
            
            target_fitness = target.average_fitness
            
            # Calcular gradiente de fitness
            fitness_gradient = target_fitness - source_fitness
            
            # Calcular gap de diversidad (simplificado)
            source_best = source.local_best["score"]
            target_best = target.local_best["score"]
            diversity_gap = abs(source_best - target_best) / max(source_best, target_best, 0.001)
            
            # Filtrar por diversidad mínima
            if diversity_gap < min_diversity_gap:
                stats["skipped_low_diversity"] += 1
                continue
            
            # Score combinado
            score = alpha * fitness_gradient + beta * diversity_gap
            targets.append((score, target))
        
        # Ordenar por score y tomar top_k
        targets.sort(key=lambda x: x[0], reverse=True)
        selected_targets = [t[1] for t in targets[:top_k]]
        
        if not selected_targets:
            stats["skipped_low_gradient"] += 1
            continue
        
        # Enviar migrantes a destinos seleccionados
        for target in selected_targets:
            target_fitness_before = target.average_fitness
            
            for migrant in migrants:
                target.receive_migrant(migrant)
                stats["total_migrations"] += 1
                
                # Evaluar impacto
                migrant_score = migrant["score"]
                if migrant_score > target_fitness_before:
                    stats["useful"] += 1
                    stats["fitness_improvements"].append(migrant_score - target_fitness_before)
                elif migrant_score >= target_fitness_before - 0.01:
                    stats["neutral"] += 1
                else:
                    stats["harmful"] += 1
            
            target.integrate_migrants()
    
    return stats


def run_benchmark(n_islands: int = 8, n_runs: int = 100):
    """Ejecuta benchmark comparativo."""
    
    print("="*70)
    print("BENCHMARK: Migración Antes vs Después")
    print("="*70)
    print()
    
    # Configuración
    print(f"Configuración:")
    print(f"  Islas: {n_islands}")
    print(f"  Ejecuciones: {n_runs}")
    print(f"  Individuos por isla: 10")
    print(f"  Migrantes por isla: 2")
    print()
    
    # Resultados acumulados
    results = {
        "ring": {"useful": 0, "neutral": 0, "harmful": 0, "total": 0, "improvements": []},
        "fully_connected": {"useful": 0, "neutral": 0, "harmful": 0, "total": 0, "improvements": []},
        "mesh": {"useful": 0, "neutral": 0, "harmful": 0, "total": 0, "improvements": []},
        "fitness_directed": {"useful": 0, "neutral": 0, "harmful": 0, "total": 0, "improvements": []}
    }
    
    # Ejecutar simulaciones
    for run in range(n_runs):
        # Crear islas con fitness variado
        islands = {}
        for i in range(n_islands):
            base_fitness = 0.3 + random.random() * 0.4  # Entre 0.3 y 0.7
            islands[i] = MockIsland(i, base_fitness)
        
        # Topologías antiguas
        for topology in ["ring", "fully_connected", "mesh"]:
            stats = simulate_topological_migration(islands.copy(), topology)
            results[topology]["useful"] += stats["useful"]
            results[topology]["neutral"] += stats["neutral"]
            results[topology]["harmful"] += stats["harmful"]
            results[topology]["total"] += stats["total_migrations"]
            results[topology]["improvements"].extend(stats["fitness_improvements"])
        
        # Recrear islas para fitness-directed
        islands_fd = {}
        for i in range(n_islands):
            base_fitness = 0.3 + random.random() * 0.4
            islands_fd[i] = MockIsland(i, base_fitness)
        
        # Fitness-directed
        stats = simulate_fitness_directed_migration(islands_fd)
        results["fitness_directed"]["useful"] += stats["useful"]
        results["fitness_directed"]["neutral"] += stats["neutral"]
        results["fitness_directed"]["harmful"] += stats["harmful"]
        results["fitness_directed"]["total"] += stats["total_migrations"]
        results["fitness_directed"]["improvements"].extend(stats["fitness_improvements"])
    
    # Imprimir resultados
    print("="*70)
    print("RESULTADOS")
    print("="*70)
    print()
    
    for name, data in results.items():
        total = data["total"]
        if total == 0:
            continue
        
        useful_pct = (data["useful"] / total) * 100
        neutral_pct = (data["neutral"] / total) * 100
        harmful_pct = (data["harmful"] / total) * 100
        
        avg_improvement = 0.0
        if data["improvements"]:
            avg_improvement = sum(data["improvements"]) / len(data["improvements"])
        
        print(f"{name.upper().replace('_', ' ')}")
        print(f"  Total migraciones:    {total:6d}")
        print(f"  Útiles:               {data['useful']:6d} ({useful_pct:5.1f}%)")
        print(f"  Neutrales:            {data['neutral']:6d} ({neutral_pct:5.1f}%)")
        print(f"  Dañinas:              {data['harmful']:6d} ({harmful_pct:5.1f}%)")
        print(f"  Mejora promedio:      {avg_improvement:.4f}")
        print()
    
    # Comparación directa
    print("="*70)
    print("COMPARACIÓN: Antes (ring) vs Después (fitness-directed)")
    print("="*70)
    print()
    
    ring = results["ring"]
    fd = results["fitness_directed"]
    
    ring_success_rate = (ring["useful"] / ring["total"]) * 100
    fd_success_rate = (fd["useful"] / fd["total"]) * 100
    
    improvement = fd_success_rate - ring_success_rate
    
    print(f"Tasa de éxito (migraciones útiles):")
    print(f"  Ring (antes):              {ring_success_rate:.1f}%")
    print(f"  Fitness-directed (después): {fd_success_rate:.1f}%")
    print(f"  Mejora:                    {improvement:+.1f}%")
    print()
    
    ring_avg = sum(ring["improvements"]) / len(ring["improvements"]) if ring["improvements"] else 0
    fd_avg = sum(fd["improvements"]) / len(fd["improvements"]) if fd["improvements"] else 0
    
    print(f"Mejora promedio de fitness por migración útil:")
    print(f"  Ring (antes):              {ring_avg:.4f}")
    print(f"  Fitness-directed (después): {fd_avg:.4f}")
    print()
    
    print(f"Migraciones dañinas:")
    print(f"  Ring (antes):              {ring['harmful']} ({(ring['harmful']/ring['total']*100):.1f}%)")
    print(f"  Fitness-directed (después): {fd['harmful']} ({(fd['harmful']/fd['total']*100):.1f}%)")
    print()
    
    # Conclusión
    print("="*70)
    print("CONCLUSIÓN")
    print("="*70)
    print()
    
    if improvement > 10:
        print(f"✅ El sistema fitness-directed es SIGNIFICATIVAMENTE MEJOR")
        print(f"   Mejora del {improvement:.1f}% en tasa de éxito")
    elif improvement > 0:
        print(f"✅ El sistema fitness-directed es MEJOR")
        print(f"   Mejora del {improvement:.1f}% en tasa de éxito")
    else:
        print(f"⚠️  No hay mejora significativa")
    
    print()
    print("El sistema antiguo (topológico) enviaba migrantes aleatoriamente")
    print("sin considerar si mejorarían el fitness del destino.")
    print()
    print("El sistema nuevo (fitness-directed) selecciona destinos basándose en:")
    print("  1. Gradiente de fitness (envía a islas donde ayudará)")
    print("  2. Gap de diversidad (evita enviar clones)")
    print("  3. Inyección de élite (top 5% como semillas dirigidas)")


if __name__ == "__main__":
    random.seed(42)  # Reproducibilidad
    run_benchmark(n_islands=8, n_runs=100)
