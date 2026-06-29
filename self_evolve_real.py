#!/usr/bin/env python3
"""
Real self-evolution with AST mutations + LLM (codestral-latest via headroom).

Evolves MutaLambda's own hot-path functions using:
- ASTMutator for structural code mutations
- LLM for informed optimizations (optional)
- Benchmarking for fitness evaluation
- Interpretability safeguards for documentation

Targets:
1. dominates() in fitness_vector.py
2. weighted_sum() in fitness_vector.py  
3. crowding_distance() in nsga2.py
4. fast_non_dominated_sort() in nsga2.py
"""

import sys
import time
import random
import json
from pathlib import Path
from typing import Callable, Dict, List, Tuple
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))

from evolution_engine import ASTMutator
from interpretability import create_interpretability_report
from models import Individual

# Try to import LLM backend (optional)
try:
    from llm_backend import LLMBackend
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


@dataclass
class EvolutionTarget:
    """A function to evolve."""
    name: str
    code: str
    test_fn: Callable
    description: str


# ---------------------------------------------------------------------------
# Target Functions (extracted from production code)
# ---------------------------------------------------------------------------

def dominates_original(correctness, latency_p50, latency_p99, throughput,
                       memory_peak_mb, parsimony,
                       other_correctness, other_latency_p50, other_latency_p99,
                       other_throughput, other_memory_peak_mb, other_parsimony):
    """Pareto dominance check."""
    self_dims = (correctness, -latency_p50, -latency_p99,
                 throughput, -memory_peak_mb, parsimony)
    other_dims = (other_correctness, -other_latency_p50, -other_latency_p99,
                  other_throughput, -other_memory_peak_mb, other_parsimony)
    at_least_as_good = all(s >= o for s, o in zip(self_dims, other_dims))
    strictly_better = any(s > o for s, o in zip(self_dims, other_dims))
    return at_least_as_good and strictly_better


def weighted_sum_original(correctness, latency_p50, latency_p99, throughput,
                         memory_peak_mb, parsimony):
    """Weighted scalarization."""
    weights = {"correctness": 1.0, "latency_p50": -0.1, "latency_p99": -0.05,
               "throughput": 0.15, "memory_peak_mb": -0.05, "parsimony": 0.05}
    return (weights["correctness"] * correctness
            + weights["latency_p50"] * latency_p50
            + weights["latency_p99"] * latency_p99
            + weights["throughput"] * throughput
            + weights["memory_peak_mb"] * memory_peak_mb
            + weights["parsimony"] * parsimony)


def crowding_distance_original(population: List[Individual]) -> Dict[str, float]:
    """NSGA-II crowding distance."""
    n = len(population)
    if n == 0:
        return {}
    distances = {ind.id: 0.0 for ind in population}
    for obj_key in ["correctness", "latency_p50", "latency_p99",
                    "throughput", "memory_peak_mb", "parsimony"]:
        if obj_key == "correctness":
            sorted_pop = [(ind.fitness.correctness, ind.id) for ind in population]
        elif obj_key == "latency_p50":
            sorted_pop = [(-ind.fitness.latency_p50, ind.id) for ind in population]
        elif obj_key == "latency_p99":
            sorted_pop = [(-ind.fitness.latency_p99, ind.id) for ind in population]
        elif obj_key == "throughput":
            sorted_pop = [(ind.fitness.throughput, ind.id) for ind in population]
        elif obj_key == "memory_peak_mb":
            sorted_pop = [(-ind.fitness.memory_peak_mb, ind.id) for ind in population]
        else:
            sorted_pop = [(ind.fitness.parsimony, ind.id) for ind in population]
        sorted_pop.sort(key=lambda x: x[0])
        obj_range = sorted_pop[-1][0] - sorted_pop[0][0]
        if obj_range < 1e-9:
            continue
        distances[sorted_pop[0][1]] = float("inf")
        distances[sorted_pop[-1][1]] = float("inf")
        for i in range(1, n - 1):
            distances[sorted_pop[i][1]] += (
                (sorted_pop[i + 1][0] - sorted_pop[i - 1][0]) / obj_range
            )
    return distances


def fast_non_dominated_sort_original(population: List[Individual]) -> List[List[Individual]]:
    """NSGA-II fast non-dominated sort."""
    n = len(population)
    if n == 0:
        return []
    domination_count = [0] * n
    dominated_set = [[] for _ in range(n)]
    fronts = [[]]
    for i in range(n):
        for j in range(i + 1, n):
            if population[i].fitness.dominates(population[j].fitness):
                dominated_set[i].append(j)
                domination_count[j] += 1
            elif population[j].fitness.dominates(population[i].fitness):
                dominated_set[j].append(i)
                domination_count[i] += 1
        if domination_count[i] == 0:
            fronts[0].append(i)
    front_idx = 0
    while front_idx < len(fronts) and fronts[front_idx]:
        next_front = []
        for i in fronts[front_idx]:
            for j in dominated_set[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    next_front.append(j)
        front_idx += 1
        if next_front:
            fronts.append(next_front)
    return [[population[i] for i in front] for front in fronts if front]


# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------

def benchmark_dominates(func: Callable, iterations: int = 10000) -> float:
    """Benchmark dominates() function."""
    test_cases = [
        (0.9, 0.05, 0.1, 100.0, 50.0, 0.8, 0.8, 0.06, 0.12, 90.0, 55.0, 0.7),
        (0.7, 0.08, 0.15, 80.0, 60.0, 0.6, 0.8, 0.05, 0.10, 95.0, 50.0, 0.7),
        (0.85, 0.04, 0.09, 110.0, 45.0, 0.9, 0.85, 0.04, 0.09, 110.0, 45.0, 0.9),
    ]
    start = time.perf_counter()
    for _ in range(iterations):
        for case in test_cases:
            func(*case)
    return (time.perf_counter() - start) / (iterations * len(test_cases)) * 1e6


def benchmark_weighted_sum(func: Callable, iterations: int = 10000) -> float:
    """Benchmark weighted_sum() function."""
    test_cases = [
        (0.9, 0.05, 0.1, 100.0, 50.0, 0.8),
        (0.7, 0.08, 0.15, 80.0, 60.0, 0.6),
        (0.85, 0.04, 0.09, 110.0, 45.0, 0.9),
    ]
    start = time.perf_counter()
    for _ in range(iterations):
        for case in test_cases:
            func(*case)
    return (time.perf_counter() - start) / (iterations * len(test_cases)) * 1e6


def benchmark_crowding_distance(func: Callable, iterations: int = 100) -> float:
    """Benchmark crowding_distance() function."""
    from fitness_vector import FitnessVector
    # Create test population
    population = []
    for i in range(20):
        ind = Individual(code=f"code_{i}", score=0.5)
        ind.fitness = FitnessVector(
            correctness=0.5 + random.uniform(-0.2, 0.4),
            latency_p50=0.05 + random.uniform(0, 0.1),
            latency_p99=0.1 + random.uniform(0, 0.1),
            throughput=80 + random.uniform(0, 40),
            memory_peak_mb=40 + random.uniform(0, 30),
            parsimony=0.5 + random.uniform(-0.3, 0.4),
        )
        population.append(ind)
    start = time.perf_counter()
    for _ in range(iterations):
        func(population)
    return (time.perf_counter() - start) / iterations * 1e6


def benchmark_fast_non_dominated_sort(func: Callable, iterations: int = 100) -> float:
    """Benchmark fast_non_dominated_sort() function."""
    from fitness_vector import FitnessVector
    # Create test population
    population = []
    for i in range(20):
        ind = Individual(code=f"code_{i}", score=0.5)
        ind.fitness = FitnessVector(
            correctness=0.5 + random.uniform(-0.2, 0.4),
            latency_p50=0.05 + random.uniform(0, 0.1),
            latency_p99=0.1 + random.uniform(0, 0.1),
            throughput=80 + random.uniform(0, 40),
            memory_peak_mb=40 + random.uniform(0, 30),
            parsimony=0.5 + random.uniform(-0.3, 0.4),
        )
        population.append(ind)
    start = time.perf_counter()
    for _ in range(iterations):
        func(population)
    return (time.perf_counter() - start) / iterations * 1e6


# ---------------------------------------------------------------------------
# Evolution Loop
# ---------------------------------------------------------------------------

def evolve_function(
    target_name: str,
    seed_code: str,
    benchmark_fn: Callable,
    generations: int = 15,
    population_size: int = 20,
    use_llm: bool = False,
) -> Dict:
    """Evolve a function with AST mutations + optional LLM."""
    
    print(f"\n{'='*70}")
    print(f"Evolving: {target_name}")
    print(f"{'='*70}\n")
    
    # Initialize LLM if available
    llm = None
    if use_llm and LLM_AVAILABLE:
        try:
            llm = LLMBackend(provider="custom", model="codestral-latest",
                           base_url="http://127.0.0.1:8787/v1", api_key="dummy")
            print("✓ LLM connected (codestral-latest via headroom)")
        except Exception as e:
            print(f"⚠ LLM connection failed: {e}, using AST-only mutations")
    
    # Benchmark baseline
    baseline_time = benchmark_fn(eval(f"{target_name}_original"))
    print(f"Baseline: {baseline_time:.3f} µs/call\n")
    
    # Initialize population
    population = []
    for i in range(population_size):
        try:
            code = ASTMutator.apply_random_mutation(seed_code)
        except (TypeError, AttributeError, RecursionError):
            code = seed_code
        try:
            func = eval_code(code, target_name)
            exec_time = benchmark_fn(func)
            fitness = baseline_time / exec_time  # Higher is better
            population.append((code, fitness, exec_time))
        except:
            population.append((seed_code, 1.0, baseline_time))
    
    best_code = seed_code
    best_fitness = 1.0
    best_time = baseline_time
    best_gen = 0
    history = []
    
    # Evolution loop
    for gen in range(generations):
        # Sort by fitness
        population.sort(key=lambda x: x[1], reverse=True)
        
        # Keep top K
        top_k = population[:population_size // 2]
        
        # Generate offspring via mutation
        offspring = []
        for code, fitness, exec_time in top_k:
            for _ in range(3):  # 3 offspring per parent
                try:
                    mutated = ASTMutator.apply_random_mutation(code)
                except (TypeError, AttributeError, RecursionError):
                    mutated = code  # Fallback if mutation fails
                if mutated != code:
                    try:
                        func = eval_code(mutated, target_name)
                        exec_time = benchmark_fn(func)
                        new_fitness = baseline_time / exec_time
                        offspring.append((mutated, new_fitness, exec_time))
                    except:
                        pass
        
        # Combine and select
        population = top_k + offspring
        population.sort(key=lambda x: x[1], reverse=True)
        population = population[:population_size]
        
        # Track best
        if population[0][1] > best_fitness:
            best_fitness = population[0][1]
            best_code = population[0][0]
            best_time = population[0][2]
            best_gen = gen + 1
            improvement = (baseline_time - best_time) / baseline_time * 100
            print(f"Gen {gen+1:2d}: ✓ New best {best_time:.3f}µs ({improvement:+.1f}%)")
            history.append({"gen": gen+1, "time": best_time, "improvement": improvement})
        else:
            print(f"Gen {gen+1:2d}: No improvement")
    
    # Final benchmark
    final_func = eval_code(best_code, target_name)
    final_time = benchmark_fn(final_func)
    
    return {
        "name": target_name,
        "baseline_time": baseline_time,
        "evolved_time": final_time,
        "improvement_pct": (baseline_time - final_time) / baseline_time * 100,
        "best_gen": best_gen,
        "evolved_code": best_code,
        "seed_code": seed_code,
        "history": history,
    }


def eval_code(code: str, func_name: str) -> Callable:
    """Evaluate code and extract function."""
    from models import Individual
    from fitness_vector import FitnessVector
    namespace = {
        "Individual": Individual,
        "FitnessVector": FitnessVector,
        "List": list,
        "Dict": dict,
    }
    exec(code, namespace)
    # Try to find function by name
    for key, val in namespace.items():
        if callable(val) and not key.startswith("_") and key not in ("Individual", "FitnessVector", "List", "Dict"):
            return val
    raise ValueError(f"No callable function found in code")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("="*70)
    print("MutaLambda Self-Evolution: Real AST Mutations")
    print("="*70)
    print()
    
    # Define targets
    targets = [
        ("dominates", dominates_original.__doc__ or "", benchmark_dominates),
        ("weighted_sum", weighted_sum_original.__doc__ or "", benchmark_weighted_sum),
        ("crowding_distance", crowding_distance_original.__doc__ or "", benchmark_crowding_distance),
        ("fast_non_dominated_sort", fast_non_dominated_sort_original.__doc__ or "", benchmark_fast_non_dominated_sort),
    ]
    
    results = []
    
    # Evolve each target
    for target_name, description, benchmark_fn in targets:
        # Get seed code
        seed_code = f"""
def {target_name}_original{getattr(globals()[f"{target_name}_original"], "__code__").co_varnames[:getattr(globals()[f"{target_name}_original"], "__code__").co_argcount]}:
    pass
"""
        # Actually get the real code
        import inspect
        seed_code = inspect.getsource(globals()[f"{target_name}_original"])
        
        result = evolve_function(
            target_name=target_name,
            seed_code=seed_code,
            benchmark_fn=benchmark_fn,
            generations=15,
            population_size=20,
            use_llm=False,  # Start with AST-only
        )
        results.append(result)
        
        print(f"\n✅ {target_name}: {result['improvement_pct']:+.1f}% faster")
    
    # Generate reports
    print(f"\n{'='*70}")
    print("Generating Reports...")
    print(f"{'='*70}\n")
    
    reports_dir = Path(__file__).parent / "reports" / "self_evolution_real"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    for result in results:
        report_path = reports_dir / f"{result['name']}_report.md"
        report = create_interpretability_report(
            original_code=result["seed_code"],
            evolved_code=result["evolved_code"],
            generation=result["best_gen"],
            fitness_before=1.0 / result["baseline_time"],
            fitness_after=1.0 / result["evolved_time"],
            output_path=report_path,
        )
        print(f"  {result['name']}: {report_path}")
    
    # Summary
    print(f"\n{'='*70}")
    print("Summary")
    print(f"{'='*70}\n")
    
    total_improvement = 0
    for result in results:
        print(f"{result['name']}:")
        print(f"  Baseline: {result['baseline_time']:.3f} µs")
        print(f"  Evolved:  {result['evolved_time']:.3f} µs")
        print(f"  Speedup:  {result['improvement_pct']:+.1f}%")
        print()
        total_improvement += result['improvement_pct']
    
    avg_improvement = total_improvement / len(results)
    print(f"Average speedup: {avg_improvement:+.1f}%")
    print()
    print("Reports saved to: reports/self_evolution_real/")
    
    # Save JSON results
    results_path = reports_dir / "results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results JSON: {results_path}")


if __name__ == "__main__":
    main()
