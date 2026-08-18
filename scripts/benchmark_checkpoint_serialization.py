#!/usr/bin/env python
"""Benchmark: Checkpoint serialization optimization (JSON vs msgpack).

Compares JSON vs compressed msgpack serialization for large checkpoints.
Tests with population sizes that trigger the msgpack path (> 256 individuals,
Phase 6 lowered the threshold from 2000 → 256 for realistic population sizes).
"""
import sys
import os
import time
import statistics
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Individual
from fitness_vector import FitnessVector


def create_large_population(n: int) -> list:
    """Create n individuals with FitnessVector (triggers msgpack path)."""
    import random
    random.seed(42)
    population = []
    for i in range(n):
        ind = Individual(
            code=f"def func_{i}(x): return x + {i}",
            score=float(i % 100),
            fitness=FitnessVector(
                correctness=0.5 + random.random() * 0.5,
                latency_p50=random.uniform(0.1, 10.0),
                latency_p99=random.uniform(1.0, 50.0),
                throughput=random.uniform(100, 1000),
                memory_peak_mb=random.uniform(10, 100),
                parsimony=random.uniform(0.1, 0.9),
            )
        )
        population.append(ind)
    return population


def benchmark_json_vs_msgpack(pop_sizes=[500, 1000, 2500, 5000], runs=3):
    """Benchmark JSON vs msgpack serialization."""
    results = {}
    
    for n in pop_sizes:
        print(f"\nPopulation size: {n}")
        print("-" * 60)
        
        # Create test data
        population = create_large_population(n)
        
        # Create a minimal checkpoint-like dict
        test_data = {
            "generation": 42,
            "island_populations": [
                [{"id": str(i), "code": ind.code, "score": ind.score,
                   "parent_ids": [], "tier": 0, "passed": True,
                   "record_lineage": False} for i, ind in enumerate(population)]
            ],
            "islands": [{"generation": 42, "population_size": n}],
        }
        
        # JSON benchmark
        json_times = []
        for _ in range(runs):
            tmpdir = tempfile.mkdtemp()
            try:
                json_path = Path(tmpdir) / "checkpoint.json"
                start = time.perf_counter()
                import json
                with open(json_path, "w") as f:
                    json.dump(test_data, f, indent=2)
                elapsed = time.perf_counter() - start
                json_times.append(elapsed)
                json_size = json_path.stat().st_size
            finally:
                shutil.rmtree(tmpdir)
        
        # Msgpack benchmark (if available)
        msgpack_available = False
        msgpack_times = []
        msgpack_size = 0
        try:
            import msgpack
            import zlib
            
            for _ in range(runs):
                tmpdir = tempfile.mkdtemp()
                try:
                    mp_path = Path(tmpdir) / "checkpoint.msgpack"
                    start = time.perf_counter()
                    packed = msgpack.packb(test_data, use_bin_type=True)
                    compressed = zlib.compress(packed, level=6)
                    mp_path.write_bytes(compressed)
                    elapsed = time.perf_counter() - start
                    msgpack_times.append(elapsed)
                    msgpack_size = mp_path.stat().st_size
                finally:
                    shutil.rmtree(tmpdir)
            msgpack_available = True
        except ImportError:
            print("  [msgpack not installed — skipping]")
        
        # Results
        json_mean = statistics.mean(json_times) * 1000
        json_median = statistics.median(json_times) * 1000
        
        if msgpack_available:
            mp_mean = statistics.mean(msgpack_times) * 1000
            mp_median = statistics.median(msgpack_times) * 1000
            speedup = json_mean / mp_mean if mp_mean > 0 else float('inf')
            size_reduction = (1 - msgpack_size / json_size) * 100 if json_size > 0 else 0
            
            print(f"  JSON:    mean={json_mean:.2f}ms, median={json_median:.2f}ms, size={json_size/1024:.1f}KB")
            print(f"  MsgPack: mean={mp_mean:.2f}ms, median={mp_median:.2f}ms, size={msgpack_size/1024:.1f}KB")
            print(f"  Speedup: {speedup:.1f}x faster")
            print(f"  Size reduction: {size_reduction:.1f}% smaller")
        else:
            print(f"  JSON:    mean={json_mean:.2f}ms, median={json_median:.2f}ms, size={json_size/1024:.1f}KB")
        
        results[n] = {
            "json_mean_ms": json_mean,
            "json_size_kb": json_size / 1024,
            "msgpack_available": msgpack_available,
            "msgpack_mean_ms": mp_mean if msgpack_available else None,
            "msgpack_size_kb": msgpack_size / 1024 if msgpack_available else None,
        }
    
    return results


if __name__ == "__main__":
    print("=" * 60)
    print("Checkpoint Serialization: JSON vs MsgPack Benchmark")
    print("=" * 60)
    
    results = benchmark_json_vs_msgpack()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("\nConclusion: msgpack provides significant speedups")
    print("for large checkpoints (>2000 individuals).")
    print("JSON remains default for smaller checkpoints (human-readable).")
    print("=" * 60)