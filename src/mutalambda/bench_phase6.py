"""
Phase 6 empirical benchmark (AST cache + msgpack checkpoints).

Matches EMPIRICAL_EVIDENCE.md philosophy: real wall-clock timing,
3x repeats, min +/- stderr, isolated components.

Run:
  python bench_phase6.py
"""
from __future__ import annotations

import ast
import io
import json
import os
import statistics
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from mutalambda.muta_lambda import EvolveConfig, MutaLambdaAgent
# Pre-existing bug (independent of Phase 6): muta_lambda.py uses the global
# name ``_filter_mutant`` but never imports it from mutation_filters. This
# only triggers when num_islands > 1 (differentiated seeding). We inject the
# symbol at runtime so the end-to-end benchmark can run with multi-island
# populations, isolating ONLY the Phase 6 changes.
import mutalambda.muta_lambda as _ml
from mutalambda.mutation_filters import _filter_mutant
if not hasattr(_ml, "_filter_mutant"):
    _ml._filter_mutant = _filter_mutant


from mutalambda.checkpoint_manager import CheckpointData, save_full_checkpoint, load_checkpoint
try:
    from mutalambda.checkpoint_manager import MSGPACK_THRESHOLD  # Phase 6 addition
except ImportError:
    MSGPACK_THRESHOLD = None  # before phase 6 had no msgpack threshold

# ── workload: a small, self-contained seed so the run is fast & deterministic ──
SEED = (
    "import numpy as np\n"
    "def compute_stats(data):\n"
    "    n = len(data)\n"
    "    mean = 0.0\n"
    "    for i in range(n):\n"
    "        mean += data[i]\n"
    "    mean /= n\n"
    "    variance = 0.0\n"
    "    for i in range(n):\n"
    "        diff = data[i] - mean\n"
    "        variance += diff * diff\n"
    "    variance /= n\n"
    "    std = variance ** 0.5\n"
    "    return mean, std\n"
)


def mock_llm_fn(prompt: str) -> str:
    """Fast in-process 'LLM' that applies an AST mutation; avoids network/ollama."""
    from mutalambda.evolution_engine import ASTMutator
    lines = prompt.split("\n")
    code_lines = [
        l for l in lines
        if l.strip()
        and not l.startswith(("You are", "Task:", "Improve", "Return", "Instructions:", "Constraints:", "Evaluation", "Scoring"))
    ]
    code = "\n".join(code_lines).strip()
    if not code:
        return "def solution():\n    return 42\n"
    return ASTMutator.apply_random_mutation(code)


def make_config(gens=5, islands=2, pop=4):
    return EvolveConfig(
        num_islands=islands,
        generations=gens,
        population_size=pop,
        seed_codes=[SEED],
        topology="ring",
        top_k=3,
        checkpoint_enabled=False,         # isolate end-to-end gen timing
        prompt_evolution=False,            # avoid extra LLM calls
        hfc_enabled=False,
        thc_enabled=False,
        spatial_enabled=False,
        workflow_enabled=True,
        allow_untested=True,
        llm_backend="direct",
    )


def run_evolution_once(gens=5, islands=2, pop=4):
    """Run a real generation loop, silencing stdout. Returns elapsed seconds."""
    cfg = make_config(gens=gens, islands=islands, pop=pop)
    cfg.timeout_sec = cfg.__dict__.get("timeout_sec", 10.0)
    start = time.perf_counter()
    sink = io.StringIO()
    with redirect_stdout(sink):
        agent = MutaLambdaAgent(
            config=cfg,
            llm_fn=mock_llm_fn,
            test_cases=[
                {"test": "compute_stats(np.array([1,2,3,4,5]))", "pass": True}
            ],
            task="Optimize compute_stats for speed",
        )
        agent.run(task="Optimize compute_stats for speed")
        agent.shutdown()
    return time.perf_counter() - start


def bench_end_to_end(reps=3):
    """End-to-end small evolution, 3x, min + stderr."""
    samples = []
    for _ in range(reps):
        samples.append(run_evolution_once())
    return samples, statistics.mean(samples), min(samples)


# ── Parse cache isolation ─────────────────────────────────────────────

def bench_parse_cache(code: str, iters=20000, reps=3):
    """Compare ast.parse vs cached_parse in isolation.

    In the 'before' state (no cached_parse), we benchmark raw ast.parse as the
    baseline for both the 'before' and the 'no-cache' case. In the 'after' state
    we additionally measure the cached path.
    """
    import mutalambda.code_hash as code_hash
    has_cache = hasattr(code_hash, "cached_parse")

    # Baseline: raw ast.parse (the 'before' behaviour everywhere)
    raw_samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        for _ in range(iters):
            ast.parse(code)
        raw_samples.append((time.perf_counter() - t0) / iters)

    cached_cold = None
    cached_warm = None
    cached_warm_min = None
    if has_cache:
        cached_parse = code_hash.cached_parse
        clear_ast_cache = code_hash.clear_ast_cache
        # warmup
        for _ in range(100):
            cached_parse(code)
        # cold: cache cleared between reps
        cached_cold_samples = []
        for _ in range(reps):
            clear_ast_cache()
            t0 = time.perf_counter()
            for _ in range(iters):
                cached_parse(code)
            cached_cold_samples.append((time.perf_counter() - t0) / iters)
        cached_cold = (cached_cold_samples, min(cached_cold_samples))
        # warm: steady-state (the real production scenario after Phase 6)
        clear_ast_cache()
        for _ in range(iters):
            cached_parse(code)
        cached_warm_samples = []
        for _ in range(reps):
            t0 = time.perf_counter()
            for _ in range(iters):
                cached_parse(code)
            cached_warm_samples.append((time.perf_counter() - t0) / iters)
        cached_warm = (cached_warm_samples, min(cached_warm_samples))
        cached_warm_min = min(cached_warm_samples)

    return {
        "raw_ast_parse": (raw_samples, min(raw_samples)),
        "cached_cold": cached_cold,
        "cached_warm": cached_warm,
        "cached_warm_min": cached_warm_min,
        "has_cache": has_cache,
    }


# ── Checkpoint serialization isolation ────────────────────────────────

def make_checkpoint_data(n_islands=6, pop_per=80):
    """Build ~500-individual population checkpoint (matches phase-6 claim)."""
    populations = []
    for isl in range(n_islands):
        pop = []
        for ind in range(pop_per):
            pop.append({
                "id": f"ind-{isl}-{ind}",
                "code": SEED,
                "score": 0.5 + (ind % 100) / 200.0,
                "generation": ind,
                "fitness": {"primary": 0.5, "novelty": 0.1, "entropy": 0.0},
            })
        populations.append(pop)
    total = sum(len(p) for p in populations)
    cp = CheckpointData(
        generation=100,
        best_score=0.95,
        best_code=SEED,
        island_populations=populations,
        island_generations=[100] * n_islands,
        run_id="bench-run",
        task="benchmark",
        random_state=None,
        numpy_state=None,
    )
    return cp, total


def bench_checkpoint(json_bytes, msgpack_bytes, json_time, msgpack_time):
    pass


def bench_checkpoint_serialization(reps=3):
    """Save ~500-individual checkpoint as JSON vs msgpack, measure bytes + time.

    In the 'before' state msgpack is unavailable — we measure JSON only and
    report msgpack as N/A. In the 'after' state both are measured.
    """
    cp, total = make_checkpoint_data(n_islands=6, pop_per=80)
    from mutalambda.checkpoint_manager import _serialise_checkpoint
    try:
        from mutalambda.checkpoint_manager import MSGPACK_THRESHOLD
    except ImportError:
        MSGPACK_THRESHOLD = None
    serialised = _serialise_checkpoint(cp)

    # JSON (always available)
    json_times = []
    json_sizes = []
    for _ in range(reps):
        buf = io.StringIO()
        t0 = time.perf_counter()
        for _ in range(reps):
            json.dump(serialised, buf, indent=2)
        json_times.append((time.perf_counter() - t0) / reps)
        json_sizes.append(buf.tell())

    # Msgpack — only available in the 'after' state (Phase 6 added msgpack dep)
    msgpack_times = None
    msgpack_sizes = None
    try:
        import msgpack
        import zlib
        msgpack_times = []
        msgpack_sizes = []
        for _ in range(reps):
            t0 = time.perf_counter()
            for _ in range(reps):
                packed = msgpack.packb(
                    serialised, use_bin_type=True,
                    default=lambda o: o.tolist() if hasattr(o, 'tolist') else o,
                )
                compressed = zlib.compress(packed, level=6)
            msgpack_times.append((time.perf_counter() - t0) / reps)
            msgpack_sizes.append(len(compressed))
    except ImportError:
        msgpack_times = None

    return {
        "total_individuals": total,
        "MSGPACK_THRESHOLD": MSGPACK_THRESHOLD if 'MSGPACK_THRESHOLD' in globals() else None,
        "json": (json_sizes, json_times),
        "msgpack": (msgpack_sizes, msgpack_times),
    }


def main():
    label = os.environ.get("PHASE6_STATE", "after")
    print(f"\n=== Phase 6 Benchmark — STATE={label} ===")
    print(f"Python {sys.version.split()[0]}  msgpack available", end=" ")
    try:
        import msgpack; print(f"({msgpack.version})")
    except ImportError:
        print("(MISSING)")

    # 1. End-to-end
    print("\n--- 1. End-to-end evolution (5 gens × 2 islands × 4 pop) ---")
    samples, avg, mn = bench_end_to_end(reps=3)
    se = statistics.stdev(samples) / (len(samples) ** 0.5) if len(samples) > 1 else 0.0
    print(f"  samples(s): {[round(s,3) for s in samples]}")
    print(f"  min={mn:.3f}s  avg={avg:.3f}s  stderr={se:.3f}s")

    # 2. Parse cache
    print("\n--- 2. Parse cache isolation (ast.parse vs cached_parse, 20000 iters) ---")
    results = bench_parse_cache(SEED, iters=20000, reps=3)
    raw_min_us = results["raw_ast_parse"][1] * 1e6
    print(f"  raw_ast_parse    : min={raw_min_us:.2f} us/op  avg={statistics.mean(results['raw_ast_parse'][0])*1e6:.2f} us/op")
    if results["cached_warm_min"] is not None:
        cmin = results["cached_warm_min"] * 1e6
        print(f"  cached_parse(warm): min={cmin:.4f} us/op  (speedup vs raw: {raw_min_us/cmin:.0f}x)")
    else:
        print(f"  cached_parse: NOT AVAILABLE in this state (no Phase 6 AST cache)")

    # 3. Checkpoint serialization
    print("\n--- 3. Checkpoint serialization (~500-individuals) ---")
    ck_results = bench_checkpoint_serialization(reps=3)
    total = ck_results["total_individuals"]
    json_sizes, json_times = ck_results["json"]
    msgpack_sizes, msgpack_times = ck_results["msgpack"]
    print(f"  population: {total} individuals")
    print(f"  JSON   : avg_size={statistics.mean(json_sizes)/1024:.1f} KB  avg_time={statistics.mean(json_times)*1000:.3f} ms")
    if msgpack_sizes is not None:
        print(f"  Msgpack: avg_size={statistics.mean(msgpack_sizes)/1024:.1f} KB  avg_time={statistics.mean(msgpack_times)*1000:.3f} ms")
        ratio = statistics.mean(msgpack_sizes) / statistics.mean(json_sizes)
        tspeed = statistics.mean(json_times) / statistics.mean(msgpack_times) if statistics.mean(msgpack_times)>0 else 0
        print(f"  msgpack: {ratio*100:.1f}% of JSON size  |  {tspeed:.2f}x faster")
    else:
        print(f"  Msgpack: N/A (msgpack not available in this state)")

    # Persist machine-readable + machine-state summary
    print(f"\n  [state={label}] done")
    out = os.environ.get("PHASE6_OUT", "/tmp/phase6_bench.json")
    with open(out, "w") as f:
        json.dump({
            "state": label,
            "end_to_end": {"min": mn, "avg": avg, "stderr": se, "samples": samples},
            "parse": {
                "raw_ast_parse_min_us": results["raw_ast_parse"][1]*1e6,
                "cached_warm_min_us": (results["cached_warm_min"]*1e6 if results["cached_warm_min"] is not None else None),
                "has_cache": results["has_cache"],
            },
            "checkpoint": {
                "individuals": total,
                "json_avg_kb": statistics.mean(json_sizes)/1024,
                "msgpack_avg_kb": (statistics.mean(msgpack_sizes)/1024) if msgpack_sizes is not None else None,
                "json_avg_ms": statistics.mean(json_times)*1000,
                "msgpack_avg_ms": (statistics.mean(msgpack_times)*1000) if msgpack_times is not None else None,
            },
        }, f, indent=2)
    print(f"  results -> {out}")


if __name__ == "__main__":
    main()
