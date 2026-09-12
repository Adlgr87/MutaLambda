"""Demo ejecutable de la Scientific Extension."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from muta_ext.scientific.hotpath import profile_workload
from muta_ext.scientific.hotpath_types import ProfileConfig
from muta_ext.scientific.invariants import BASE_INVARIANTS, evaluate_invariants
from muta_ext.uast.call_graph import extract_call_graph_from_source
from examples.scientific.massive_kernel import run_simulation


def demo_profiling():
    """Demuestra hot-path profiling."""
    print("=" * 60)
    print("DEMO: Hot-path profiling")
    def workload():
        run_simulation(num_particles=500, steps=50)
    config = ProfileConfig(min_cumulative_pct=1.0, max_hot_functions=10)
    start = time.perf_counter()
    result = profile_workload("run_simulation", workload, config=config)
    elapsed = time.perf_counter() - start
    print(f"Profiling: {elapsed:.3f}s | Total: {result.total_time:.4f}s")
    if result.has_hot_paths:
        for hp in result.hot_paths[:5]:
            print(f"  {hp.function_name:30s} {hp.cumulative_pct:6.2f}%")


def demo_invariants():
    """Demuestra validación científica."""
    print("\n" + "=" * 60)
    print("DEMO: Scientific Validation")
    result = evaluate_invariants(
        {"total_energy": 15420.5, "mass_delta": 1e-12}, {},
        invariants=BASE_INVARIANTS
    )
    print(f"Result: {'PASS' if result.passed else 'FAIL'} (score={result.scientific_score:.4f})")


def demo_call_graph():
    """Demuestra call graph extraction."""
    print("\n" + "=" * 60)
    print("DEMO: Call graph")
    kernel = Path(__file__).resolve().parent / "massive_kernel.py"
    graph = extract_call_graph_from_source(kernel.read_text())
    if graph:
        print(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")
        for c, cl in sorted(graph.edges_set()):
            print(f"  {c} → {cl}")


if __name__ == "__main__":
    demo_profiling()
    demo_invariants()
    demo_call_graph()
    print("\n✅ Demos completadas")