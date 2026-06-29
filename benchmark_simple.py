#!/usr/bin/env python3
"""Benchmark: Fitness-Directed Gradient Migration vs Standard Topologies.

Lightweight benchmark that directly tests migration logic without full Island simulation.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from migration import FitnessDirectedMigration, GradientConfig, MigrationBus, MigrationMetrics
from models import Individual, IslandConfig


def run_benchmark():
    """Run comparison benchmark."""
    print("=" * 70)
    print("MutaLambda Migration Benchmark")
    print("=" * 70)
    print()
    
    results = {}
    
    # Baseline: ring topology
    print("Testing ring topology...", end=" ")
    sys.stdout.flush()
    start = time.perf_counter()
    
    bus_ring = MigrationBus(topology="ring")
    for i in range(4):
        from unittest.mock import MagicMock
        from island import Island
        config = IslandConfig(population_size=10, top_k=5, migration_interval=1, migrants_per_island=1)
        island = Island(island_id=i, config=config, llm_fn=MagicMock(), evaluator=MagicMock(), migration_bus=bus_ring)
        island.population = [Individual(code=f"code_{i}_{j}", score=0.3 + i*0.1) for j in range(10)]
        island.local_best = max(island.population, key=lambda ind: ind.score)
        bus_ring.register_island(i, island)
    
    for gen in range(10):
        for i in range(4):
            bus_ring.migrate(i, gen)
    
    ring_time = time.perf_counter() - start
    ring_best = bus_ring.get_global_best()
    results["ring"] = {
        "time": round(ring_time, 4),
        "best_score": round(ring_best.score, 4) if ring_best else 0.0,
    }
    print(f"✓ {ring_time:.4f}s, best={results['ring']['best_score']}")
    
    # New: fitness_gradient topology
    print("Testing fitness_gradient...", end=" ")
    sys.stdout.flush()
    start = time.perf_counter()
    
    bus_grad = MigrationBus(topology="fitness_gradient")
    grad_config = GradientConfig(alpha=0.7, beta=0.3, top_k_targets=2, elite_injection=True)
    bus_grad.configure_gradient(grad_config)
    
    for i in range(4):
        from unittest.mock import MagicMock
        from island import Island
        config = IslandConfig(population_size=10, top_k=5, migration_interval=1, migrants_per_island=1)
        island = Island(island_id=i, config=config, llm_fn=MagicMock(), evaluator=MagicMock(), migration_bus=bus_grad)
        island.population = [Individual(code=f"code_{i}_{j}", score=0.3 + i*0.1) for j in range(10)]
        island.local_best = max(island.population, key=lambda ind: ind.score)
        bus_grad.register_island(i, island)
    
    for gen in range(10):
        for i in range(4):
            bus_grad.migrate(i, gen)
    
    grad_time = time.perf_counter() - start
    grad_best = bus_grad.get_global_best()
    grad_metrics = bus_grad.get_migration_metrics()
    
    results["fitness_gradient"] = {
        "time": round(grad_time, 4),
        "best_score": round(grad_best.score, 4) if grad_best else 0.0,
        "migrations": grad_metrics["total_migrations"],
        "success_rate": round(grad_metrics["success_rate"], 4),
        "mean_improvement": round(grad_metrics["mean_improvement"], 6),
    }
    print(f"✓ {grad_time:.4f}s, best={results['fitness_gradient']['best_score']}")
    print(f"  Migrations: {grad_metrics['total_migrations']}")
    print(f"  Success rate: {grad_metrics['success_rate']:.1%}")
    print(f"  Mean improvement: {grad_metrics['mean_improvement']:.6f}")
    
    # Save results
    output_dir = Path(__file__).parent / "benchmarks"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "migration_benchmark.json"
    
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print()
    print(f"Ring topology:          {results['ring']['time']:.4f}s, best={results['ring']['best_score']}")
    print(f"Fitness gradient:       {results['fitness_gradient']['time']:.4f}s, best={results['fitness_gradient']['best_score']}")
    print()
    print(f"Time overhead:          {(results['fitness_gradient']['time'] / results['ring']['time'] - 1) * 100:+.1f}%")
    print(f"Migration success:      {results['fitness_gradient']['success_rate']:.1%}")
    print()
    print(f"Results saved to: {output_path}")
    
    return results


if __name__ == "__main__":
    run_benchmark()
