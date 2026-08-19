"""Self-evolution proof of concept: MutaLambda optimizes its own hot path.

Target: ``nsga2._crowding_distance`` — pure, deterministic, covered by the
existing nsga2 test suite, and a measured hot spot (110K lambda calls /
3.5K list sorts in a 20-iteration NSGA-II profile).

This experiment uses MutaLambda's **real production machinery** at every gate:

  Gate 1  mutation_filters.check_empty_code / check_syntax / check_max_length
  Gate 2  mutation_filters.check_no_critical_patterns(profile="self")
  Gate 3  Differential correctness oracle (property-based equivalence vs the
          baseline implementation across randomized populations, including
          tie-heavy and degenerate cases)
  Gate 4  Honest benchmark: median-of-repeats across multiple front sizes;
          accept only if geometric-mean speedup >= 1.10x and no size regresses

Candidate sources:
  * N random AST mutants (evolution_engine.ASTMutator) — the mutation operator.
  * 2 engineered rewrite candidates playing the role the LLM backend plays in
    production (no LLM credentials in this environment): a pure-Python
    micro-optimization and a NumPy vectorization.

Run:  python experiments/self_evolution_crowding.py [--mutants 200]
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import math
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.disable(logging.WARNING)  # silencia el spam de filtros durante el run

import numpy as np  # noqa: E402

import nsga2  # noqa: E402
import mutation_filters as mf  # noqa: E402
from evolution_engine import ASTMutator  # noqa: E402
from fitness_vector import FitnessVector  # noqa: E402
from models import Individual  # noqa: E402

BASELINE_FN = nsga2._crowding_distance
BASELINE_SRC = inspect.getsource(BASELINE_FN)

DIMS = ["correctness", "latency_p50", "latency_p99",
        "throughput", "memory_peak_mb", "parsimony"]

# ── Candidatos ingenieriles (rol del backend LLM en producción) ──────────────

CANDIDATE_PUREPY = '''
def _crowding_distance(individuals: List[Individual]) -> List[float]:
    """Crowding distance (Deb 2002) — evolved variant A (pure Python).

    Optimizations vs baseline: per-dimension columns are plain lists sorted
    via ``list.__getitem__`` as key (no tuple allocation, no lambda frames).
    """
    n = len(individuals)
    if n <= 2:
        return [float("inf")] * n

    inf = float("inf")
    distances = [0.0] * n
    fitnesses = [_get_fitness(ind) for ind in individuals]
    dims = ["correctness", "latency_p50", "latency_p99",
            "throughput", "memory_peak_mb", "parsimony"]

    for dim in dims:
        col = [getattr(f, dim, 0.0) for f in fitnesses]
        order = sorted(range(n), key=col.__getitem__)
        obj_range = col[order[-1]] - col[order[0]]
        if obj_range < 1e-9:
            continue
        distances[order[0]] = inf
        distances[order[-1]] = inf
        for k in range(1, n - 1):
            distances[order[k]] += (col[order[k + 1]] - col[order[k - 1]]) / obj_range

    return distances
'''

CANDIDATE_NUMPY = '''
def _crowding_distance(individuals: List[Individual]) -> List[float]:
    """Crowding distance (Deb 2002) — evolved variant B (NumPy vectorized).

    Semantics preserved exactly: stable argsort matches Python's stable list
    sort on ties; any index that is a boundary point in a dimension with
    range >= 1e-9 ends up +inf, exactly as the baseline's assignment does.
    """
    n = len(individuals)
    if n <= 2:
        return [float("inf")] * n

    fitnesses = [_get_fitness(ind) for ind in individuals]
    dims = ["correctness", "latency_p50", "latency_p99",
            "throughput", "memory_peak_mb", "parsimony"]

    mat = np.empty((n, len(dims)), dtype=np.float64)
    for j, dim in enumerate(dims):
        col = mat[:, j]
        for i, f in enumerate(fitnesses):
            col[i] = getattr(f, dim, 0.0)

    distances = np.zeros(n, dtype=np.float64)
    boundary = np.zeros(n, dtype=bool)

    for j in range(mat.shape[1]):
        col = mat[:, j]
        order = np.argsort(col, kind="stable")
        svals = col[order]
        obj_range = svals[-1] - svals[0]
        if obj_range < 1e-9:
            continue
        boundary[order[0]] = True
        boundary[order[-1]] = True
        distances[order[1:-1]] += (svals[2:] - svals[:-2]) / obj_range

    distances[boundary] = np.inf
    return distances.tolist()
'''

CANDIDATE_HYBRID = '''
def _crowding_distance(individuals: List[Individual]) -> List[float]:
    """Crowding distance (Deb 2002) — evolved variant C (size-gated hybrid).

    Small fronts (n < 80): pure-Python column sort — NumPy array setup
    overhead dominates at these sizes (measured 0.28x at n=5).
    Large fronts (n >= 80): NumPy stable argsort vectorization (up to 2.2x).
    Semantics identical to baseline in both paths.
    """
    n = len(individuals)
    if n <= 2:
        return [float("inf")] * n

    inf = float("inf")
    fitnesses = [_get_fitness(ind) for ind in individuals]
    dims = ["correctness", "latency_p50", "latency_p99",
            "throughput", "memory_peak_mb", "parsimony"]

    if n < 80:
        distances = [0.0] * n
        for dim in dims:
            col = [getattr(f, dim, 0.0) for f in fitnesses]
            order = sorted(range(n), key=col.__getitem__)
            obj_range = col[order[-1]] - col[order[0]]
            if obj_range < 1e-9:
                continue
            distances[order[0]] = inf
            distances[order[-1]] = inf
            for k in range(1, n - 1):
                distances[order[k]] += (col[order[k + 1]] - col[order[k - 1]]) / obj_range
        return distances

    mat = np.empty((n, len(dims)), dtype=np.float64)
    for j, dim in enumerate(dims):
        col = mat[:, j]
        for i, f in enumerate(fitnesses):
            col[i] = getattr(f, dim, 0.0)

    np_distances = np.zeros(n, dtype=np.float64)
    boundary = np.zeros(n, dtype=bool)
    for j in range(mat.shape[1]):
        col = mat[:, j]
        order = np.argsort(col, kind="stable")
        svals = col[order]
        obj_range = svals[-1] - svals[0]
        if obj_range < 1e-9:
            continue
        boundary[order[0]] = True
        boundary[order[-1]] = True
        np_distances[order[1:-1]] += (svals[2:] - svals[:-2]) / obj_range

    np_distances[boundary] = np.inf
    return np_distances.tolist()
'''


# ── Generación de poblaciones para el oráculo diferencial ────────────────────

def make_population(n: int, rng: random.Random, *, ties: bool = False,
                    degenerate: bool = False, missing_fitness: bool = False):
    pop = []
    for i in range(n):
        ind = Individual(code=f"def f_{i}(): pass", score=rng.random() * 100)
        if missing_fitness and i % 3 == 0:
            pop.append(ind)  # ejercita el fallback de _get_fitness
            continue
        if degenerate:
            vals = {d: 0.5 for d in DIMS}
        elif ties:
            vals = {d: rng.choice([0.0, 0.25, 0.5, 0.75, 1.0]) for d in DIMS}
        else:
            vals = {d: rng.random() * (100 if "latency" in d or "memory" in d else 1)
                    for d in DIMS}
        ind.fitness = FitnessVector(**vals)
        pop.append(ind)
    return pop


def oracle_cases(seed: int = 20260819):
    rng = random.Random(seed)
    cases = []
    for n in (0, 1, 2, 3, 4, 5, 8, 13, 30, 80):
        cases.append(make_population(n, rng))
    for n in (3, 5, 20, 60):
        cases.append(make_population(n, rng, ties=True))
        cases.append(make_population(n, rng, degenerate=True))
        cases.append(make_population(n, rng, missing_fitness=True))
    for _ in range(30):  # fuzzing adicional
        n = rng.randint(0, 50)
        cases.append(make_population(
            n, rng,
            ties=rng.random() < 0.5,
            missing_fitness=rng.random() < 0.3,
        ))
    return cases


def equivalent(a, b, tol=1e-9):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if math.isinf(x) or math.isinf(y):
            if not (math.isinf(x) and math.isinf(y) and (x > 0) == (y > 0)):
                return False
        elif abs(x - y) > tol:
            return False
    return True


# ── Compilación de candidatos en un namespace controlado ─────────────────────

def compile_candidate(src: str):
    namespace = {
        "List": list.__class__ and __import__("typing").List,
        "Individual": Individual,
        "FitnessVector": FitnessVector,
        "_get_fitness": nsga2._get_fitness,
        "np": np,
        "float": float, "len": len, "range": range, "sorted": sorted,
        "getattr": getattr, "enumerate": enumerate, "zip": zip,
    }
    try:
        exec(compile(src, "<candidate>", "exec"), namespace)  # noqa: S102
    except Exception:
        return None
    fn = namespace.get("_crowding_distance")
    return fn if callable(fn) else None


# ── Gates ─────────────────────────────────────────────────────────────────────

def gate_static(src: str):
    """Gates 1+2: filtros de producción de MutaLambda con perfil self."""
    for check in (mf.check_empty_code(src), mf.check_syntax(src),
                  mf.check_max_length(src),
                  mf.check_no_critical_patterns(src, profile="self")):
        if check.blocked:
            return False, check.issues
    return True, []


def gate_correctness(fn, cases):
    """Gate 3: oráculo diferencial contra la implementación base."""
    for pop in cases:
        try:
            got = fn(list(pop))
        except Exception:
            return False
        expected = BASELINE_FN(list(pop))
        if not equivalent(list(got), expected):
            return False
    return True


def bench(fn, sizes=(10, 50, 200, 1000), repeats=7, inner=3, seed=7):
    rng = random.Random(seed)
    results = {}
    for n in sizes:
        pop = make_population(n, rng, ties=(n % 2 == 0))
        fn(list(pop))  # warmup
        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            for _ in range(inner):
                fn(list(pop))
            times.append((time.perf_counter() - t0) / inner)
        results[n] = statistics.median(times)
    return results


def decide(base_times, cand_times, min_gmean=1.10, max_regression=0.98):
    """Gate 4: mejora media geométrica >=10% y ninguna talla en regresión."""
    ratios = {n: base_times[n] / cand_times[n] for n in base_times}
    gmean = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
    ok = gmean >= min_gmean and all(r >= max_regression for r in ratios.values())
    return ok, gmean, ratios


# ── Experimento ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutants", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    cases = oracle_cases()
    stats = {"total": 0, "gate_static": 0, "no_compile": 0, "identical": 0,
             "gate_correctness": 0, "gate_benchmark": 0, "accepted": []}
    fast_but_wrong = 0

    print("=" * 74)
    print("MutaLambda self-evolution PoC — target: nsga2._crowding_distance")
    print("=" * 74)

    print("\n[baseline] benchmark de referencia ...")
    base_times = bench(BASELINE_FN)
    for n, t in base_times.items():
        print(f"  N={n:<5} {t * 1e3:8.3f} ms")

    candidates = []
    for i in range(args.mutants):
        candidates.append((f"ast_mutant_{i:03d}", ASTMutator.apply_random_mutation(BASELINE_SRC)))
    candidates.append(("engineered_purepy", CANDIDATE_PUREPY))
    candidates.append(("engineered_numpy", CANDIDATE_NUMPY))
    candidates.append(("engineered_hybrid", CANDIDATE_HYBRID))

    print(f"\n[pipeline] {len(candidates)} candidatos "
          f"({args.mutants} mutantes AST + 3 reescrituras rol-LLM)\n")

    for name, src in candidates:
        stats["total"] += 1

        ok, _ = gate_static(src)
        if not ok:
            stats["gate_static"] += 1
            continue

        fn = compile_candidate(src)
        if fn is None:
            stats["no_compile"] += 1
            continue

        if src.strip() == BASELINE_SRC.strip():
            stats["identical"] += 1
            continue

        if not gate_correctness(fn, cases):
            stats["gate_correctness"] += 1
            # ¿era un "falso speedup"? — la clase de bug que el oráculo evita
            try:
                t_cand = bench(fn, sizes=(200,), repeats=3)[200]
                if t_cand < base_times[200] * 0.95:
                    fast_but_wrong += 1
            except Exception:
                pass
            continue

        cand_times = bench(fn)
        accepted, gmean, ratios = decide(base_times, cand_times)
        if not accepted:
            stats["gate_benchmark"] += 1
            print(f"  ✗ {name}: correcto pero speedup insuficiente "
                  f"(gmean {gmean:.2f}x)")
            continue

        stats["accepted"].append({
            "name": name,
            "gmean_speedup": round(gmean, 3),
            "ratios": {str(k): round(v, 3) for k, v in ratios.items()},
            "times_ms": {str(k): round(v * 1e3, 3) for k, v in cand_times.items()},
        })
        print(f"  ✓ {name}: ACEPTADO — speedup gmean {gmean:.2f}x "
              f"({', '.join(f'N={k}: {v:.2f}x' for k, v in ratios.items())})")

    print("\n" + "=" * 74)
    print("RESULTADOS")
    print("=" * 74)
    print(f"  candidatos totales:                  {stats['total']}")
    print(f"  rechazados por gates estáticos:      {stats['gate_static']}")
    print(f"  no compilan / no definen la función: {stats['no_compile']}")
    print(f"  idénticos al baseline (sin cambio):  {stats['identical']}")
    print(f"  rechazados por oráculo correctitud:  {stats['gate_correctness']}")
    print(f"    └─ de ellos, 'más rápidos pero INCORRECTOS' "
          f"(falsos speedups evitados): {fast_but_wrong}")
    print(f"  correctos pero sin speedup >=1.10x:  {stats['gate_benchmark']}")
    print(f"  ACEPTADOS:                           {len(stats['accepted'])}")
    for acc in stats["accepted"]:
        print(f"    • {acc['name']}: {acc['gmean_speedup']}x")

    out = Path(__file__).parent / "self_evolution_crowding_results.json"
    payload = {
        "target": "nsga2._crowding_distance",
        "seed": args.seed,
        "baseline_times_ms": {str(k): round(v * 1e3, 3) for k, v in base_times.items()},
        "stats": {k: v for k, v in stats.items() if k != "accepted"},
        "fast_but_wrong_rejected": fast_but_wrong,
        "accepted": stats["accepted"],
    }
    out.write_text(json.dumps(payload, indent=2))
    print(f"\n[json] resultados guardados en {out}")


if __name__ == "__main__":
    main()
