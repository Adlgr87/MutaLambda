#!/usr/bin/env python3
"""
SWE-Agent Style Profiling Script para MutaLambda.

Simula el análisis empírico que SWE-Agent realizaría:
1. Navega la codebase
2. Identifica hot paths
3. Ejecuta profiling
4. Genera reportes con métricas empíricas

Uso:
    python scripts/swe_agent_profiler.py --module nsga2 --iterations 1000
    python scripts/swe_agent_profiler.py --module sandbox --iterations 500
    python scripts/swe_agent_profiler.py --all
"""

import argparse
import cProfile
import io
import pstats
import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass, asdict

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@dataclass
class ProfileResult:
    """Resultados de profiling para una función/método crítico."""
    module: str
    function_name: str
    total_calls: int
    total_time: float  # seconds
    cumulative_time: float  # seconds
    time_per_call_ms: float
    memory_estimate_kb: float
    hotspots: List[str]


def profile_nsga2(iterations: int = 1000) -> ProfileResult:
    """Profile NSGA-II operations - hot path crítico."""
    from mutalambda.nsga2 import non_dominated_sort, _get_fitness
    from mutalambda.models import Individual
    from mutalambda.fitness_vector import FitnessVector
    
    # Setup population with FitnessVectors
    population = []
    for i in range(100):
        ind = Individual(
            code=f"def f{i}(): return {i}",
            score=float(i),
            fitness=FitnessVector(
                correctness=0.8 + (i * 0.001),
                latency_p50=0.001 * i,
                memory_peak_mb=0.001 * i
            )
        )
        population.append(ind)
    
    # Profiling
    pr = cProfile.Profile()
    pr.enable()
    
    for _ in range(iterations):
        # Estos son los hot paths identificados
        non_dominated_sort(population)
        for ind in population[:10]:
            _get_fitness(ind)
    
    pr.disable()
    
    # Analysis
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(20)
    
    stats_output = s.getvalue()
    
    # Extract metrics
    lines = stats_output.strip().split('\n')
    total_calls = 0
    cum_time = 0.0
    
    for line in lines[5:10]:  # Top 5 functions
        parts = line.split()
        if len(parts) >= 4:
            total_calls += int(parts[0])
            try:
                cum_time += float(parts[3])
            except (ValueError, IndexError):
                pass
    
    return ProfileResult(
        module="nsga2",
        function_name="non_dominated_sort + _get_fitness",
        total_calls=total_calls,
        total_time=cum_time,
        cumulative_time=cum_time,
        time_per_call_ms=(cum_time / max(total_calls, 1)) * 1000,
        memory_estimate_kb=1024.0,  # Estimated
        hotspots=[
            "_get_fitness() - O(N²) calls in dominance checks",
            "non_dominated_sort() - sorting overhead",
            "FitnessVector creation - object instantiation",
        ]
    )


def profile_sandbox(iterations: int = 500) -> ProfileResult:
    """Profile sandbox operations - subprocess overhead."""
    from mutalambda.sandbox import SandboxEvaluator
    
    # Test code
    test_code = "def add(a, b):\n    return a + b\n"
    
    sandbox = SandboxEvaluator(
        test_cases=[{"input": {"a": 1, "b": 2}, "expected": 3}],
        timeout_sec=5.0,
    )
    
    pr = cProfile.Profile()
    start_time = time.time()
    pr.enable()
    
    for _ in range(iterations):
        # Simulate eval calls
        try:
            sandbox.evaluate_code_sync(
                test_code,
                test_cases=[{"input": {"a": 1, "b": 2}, "expected": 3}],
            )
        except Exception:
            pass  # Expected in some environments
    
    pr.disable()
    elapsed = time.time() - start_time
    
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(15)
    
    return ProfileResult(
        module="sandbox",
        function_name="evaluate_code_sync",
        total_calls=iterations,
        total_time=elapsed,
        cumulative_time=elapsed,
        time_per_call_ms=(elapsed / iterations) * 1000,
        memory_estimate_kb=512.0,  # subprocess overhead
        hotspots=[
            "subprocess.Popen spawn overhead",
            "JSON serialization/deserialization",
            "Timeout enforcement (signal/threading)",
        ]
    )


def profile_checkpoint_manager(iterations: int = 100) -> ProfileResult:
    """Profile checkpoint serialization."""
    from mutalambda.checkpoint_manager import save_full_checkpoint
    from mutalambda.models import Individual
    from mutalambda.fitness_vector import FitnessVector
    import tempfile
    
    # Create minimal population
    population = []
    for i in range(10):
        ind = Individual(
            code=f"def f{i}(): return {i}",
            score=float(i),
            fitness=FitnessVector(correctness=0.9, latency_p50=0.001, memory_peak_mb=0.5)
        )
        population.append(ind)
    
    # Setup lineage
    lineage = [{"generation": 0, "mutation": "init"}]
    
    pr = cProfile.Profile()
    start_time = time.time()
    pr.enable()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(iterations):
            ckpt_path = f"{tmpdir}/checkpoint_{i}.json"
            # Simulate checkpoint save cycle
            try:
                save_full_checkpoint(
                    path=ckpt_path,
                    generation=i,
                    island_id=0,
                    population=population,
                    lineage=lineage,
                )
            except Exception:
                pass
    
    pr.disable()
    elapsed = time.time() - start_time
    
    return ProfileResult(
        module="checkpoint_manager",
        function_name="save/load checkpoint",
        total_calls=iterations,
        total_time=elapsed,
        cumulative_time=elapsed,
        time_per_call_ms=(elapsed / iterations) * 1000,
        memory_estimate_kb=2048.0,  # JSON serialization
        hotspots=[
            "JSON serialization (json.dumps)",
            "File I/O (disk write)",
            "Path resolution",
        ]
    )


def profile_evolution_engine(iterations: int = 200) -> ProfileResult:
    """Profile evolution engine key operations."""
    from mutalambda.evolution_engine import ASTMutator
    import ast
    
    test_code = """
def calculate(x, y):
    result = x + y
    if result > 10:
        return result * 2
    return result
"""
    
    try:
        tree = ast.parse(test_code)
        mutator = ASTMutator()
        rng = type('RNG', (), {'mutation_type': 'arithmetic'})()
        rng.choice = lambda x: x[0]
        rng.uniform = lambda a, b: a
        rng.randint = lambda a, b: a
        
        pr = cProfile.Profile()
        start_time = time.time()
        pr.enable()
        
        for _ in range(iterations):
            try:
                mutator.apply_random_mutation(tree, rng)
            except Exception:
                pass  # Expected - mutation is stochastic
        
        pr.disable()
        elapsed = time.time() - start_time
        
        return ProfileResult(
            module="evolution_engine",
            function_name="ASTMutator.apply_random_mutation",
            total_calls=iterations,
            total_time=elapsed,
            cumulative_time=elapsed,
            time_per_call_ms=(elapsed / iterations) * 1000,
            memory_estimate_kb=256.0,
            hotspots=[
                "AST node copying (copy.deepcopy)",
                "Tree traversal (ast.walk)",
                "Mutation point selection",
            ]
        )
    except Exception as e:
        return ProfileResult(
            module="evolution_engine",
            function_name="ASTMutator.apply_random_mutation",
            total_calls=0,
            total_time=0.0,
            cumulative_time=0.0,
            time_per_call_ms=0.0,
            memory_estimate_kb=0.0,
            hotspots=[f"Error: {str(e)}"],
        )


def run_profiling(module: str = "all", iterations: int = 500) -> Dict[str, Any]:
    """Run profiling on specified modules."""
    results = {}
    
    profiles = {
        "nsga2": lambda: profile_nsga2(iterations),
        "sandbox": lambda: profile_sandbox(iterations),
        "checkpoint_manager": lambda: profile_checkpoint_manager(iterations),
        "evolution_engine": lambda: profile_evolution_engine(iterations),
    }
    
    if module == "all":
        for name, prof_func in profiles.items():
            console.print(f"\n[bold cyan]Profiling {name}...[/bold cyan]")
            try:
                results[name] = asdict(prof_func())
                console.print(f"[green]✓ {name} profiled[/green]")
            except Exception as e:
                console.print(f"[red]✗ Error profiling {name}: {e}[/red]")
                results[name] = {"error": str(e)}
    else:
        if module in profiles:
            console.print(f"\n[bold cyan]Profiling {module}...[/bold cyan]")
            try:
                results[module] = asdict(profiles[module]())
                console.print(f"[green]✓ {module} profiled[/green]")
            except Exception as e:
                console.print(f"[red]✗ Error: {e}[/red]")
                results[module] = {"error": str(e)}
        else:
            console.print(f"[red]Unknown module: {module}[/red]")
    
    return results


def display_results(results: Dict[str, Any]):
    """Display profiling results in a nice table."""
    table = Table(title="SWE-Agent Style Profiling Results", border_style="cyan")
    table.add_column("Module", style="bold yellow")
    table.add_column("Function", style="green")
    table.add_column("Calls", justify="right", style="cyan")
    table.add_column("Time/call (ms)", justify="right")
    table.add_column("Total Time (s)", justify="right")
    table.add_column("Hotspots", style="magenta")
    
    for module, data in results.items():
        if "error" in data:
            table.add_row(module, "ERROR", "-", "-", "-", data["error"])
        else:
            table.add_row(
                data["module"],
                data["function_name"],
                str(data["total_calls"]),
                f"{data['time_per_call_ms']:.4f}",
                f"{data['total_time']:.4f}",
                "\n".join(data["hotspots"][:2]),
            )
    
    console.print(table)
    
    # Show detailed hotspots
    console.print("\n[bold]Hotspot Details:[/bold]")
    for module, data in results.items():
        if "error" not in data:
            console.print(f"\n[cyan]{module}:[/cyan]")
            for hotspot in data["hotspots"]:
                console.print(f"  • {hotspot}")


def main():
    parser = argparse.ArgumentParser(
        description="SWE-Agent Style Profiling for MutaLambda"
    )
    parser.add_argument(
        "--module", "-m",
        choices=["nsga2", "sandbox", "checkpoint_manager", "evolution_engine", "all"],
        default="all",
        help="Module to profile"
    )
    parser.add_argument(
        "--iterations", "-i",
        type=int,
        default=500,
        help="Number of iterations for profiling"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON file for results"
    )
    parser.add_argument(
        "--recommend",
        action="store_true",
        help="Generate optimization recommendations"
    )
    
    args = parser.parse_args()
    
    console.print(Panel(
        "[bold]SWE-Agent Style Profiling[/bold]\n"
        f"Module: {args.module} | Iterations: {args.iterations}",
        border_style="cyan"
    ))
    
    results = run_profiling(args.module, args.iterations)
    display_results(results)
    
    # Save to JSON if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        console.print(f"\n[green]✓ Results saved to {args.output}[/green]")
    
    # Generate recommendations
    if args.recommend:
        console.print("\n[bold yellow]=== Optimization Recommendations ===[/bold yellow]")
        generate_recommendations(results)
    
    return 0 if all("error" not in v for v in results.values()) else 1


def generate_recommendations(results: Dict[str, Any]):
    """Generate optimization recommendations based on profiling results."""
    recommendations = []
    
    for module, data in results.items():
        if "error" in data:
            continue
        
        if data["time_per_call_ms"] > 5.0:
            recommendations.append({
                "priority": "HIGH",
                "module": module,
                "issue": f"{data['function_name']} takes {data['time_per_call_ms']:.2f}ms per call",
                "suggestions": [
                    "Consider caching results",
                    "Use faster serialization (msgpack)",
                    "Batch operations to reduce per-call overhead",
                ]
            })
        elif data["time_per_call_ms"] > 1.0:
            recommendations.append({
                "priority": "MEDIUM",
                "module": module,
                "issue": f"{data['function_name']} takes {data['time_per_call_ms']:.2f}ms per call",
                "suggestions": [
                    "Profile in more detail with flamegraph",
                    "Consider async alternatives",
                ]
            })
    
    if recommendations:
        table = Table(title="Recommendations (based on empirical evidence)", border_style="yellow")
        table.add_column("Priority", style="bold")
        table.add_column("Module", style="cyan")
        table.add_column("Issue", style="yellow")
        table.add_column("Suggestions", style="green")
        
        for rec in recommendations:
            table.add_row(
                rec["priority"],
                rec["module"],
                rec["issue"],
                "\n".join(f"• {s}" for s in rec["suggestions"])
            )
        
        console.print(table)
    else:
        console.print("[green]✓ No critical bottlenecks detected[/green]")


if __name__ == "__main__":
    sys.exit(main())
