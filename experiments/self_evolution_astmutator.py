"""Self-evolution chapter 2: optimizing the mutation engine's own copy path.

Target: ``evolution_engine.ASTMutator.apply_random_mutation`` — profiling
shows ``copy.deepcopy`` of the (cached) AST is **60% of total mutation time**
(26 ms/copy on nsga2.py; 38 ms on muta_lambda.py).

Candidate strategies (the role the LLM backend plays in production):
  A. re-parse:  ``ast.parse(code)`` per attempt instead of deepcopying the
                cached tree (measured 4.4-6.6x faster than deepcopy).
  B. pickle:    snapshot ``pickle.dumps(tree)`` once, ``pickle.loads`` per
                attempt (measured 5.3-6.3x faster than deepcopy).
Plus N meta-mutants: ASTMutator mutating its own ``apply_random_mutation``.

Gates (production machinery, same methodology as chapter 1):
  1. static filters, 2. security scan (profile="self"),
  3. seeded differential oracle — identical RNG seed must yield *identical
     output strings* vs baseline across a corpus of real source files,
  4. honest benchmark across 4 file sizes (34/239/377/1594 lines), accept
     only if gmean >= 1.10x and no size regresses below 0.98x.

Run:  python experiments/self_evolution_astmutator.py [--mutants 100]
"""

from __future__ import annotations

import argparse
import functools
import inspect
import json
import logging
import math
import random
import statistics
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.disable(logging.WARNING)

from mutalambda.evolution_engine import ASTMutator  # noqa: E402
import mutalambda.mutation_filters as mf  # noqa: E402

BASELINE_FN = ASTMutator.apply_random_mutation
BASELINE_SRC = inspect.getsource(BASELINE_FN)

# Fuente desindentada y sin decorador — apta para parsear/mutar standalone.
# (Lección del primer run: el source de un método viene indentado; mutarlo
# tal cual produce SyntaxError silencioso y 0 mutaciones reales.)
MUTATION_BASE = "\n".join(
    l for l in textwrap.dedent(BASELINE_SRC).splitlines()
    if l.strip() != "@classmethod"
)

# ── Candidatos ingenieriles ───────────────────────────────────────────────────

CANDIDATE_REPARSE = '''
def apply_random_mutation(cls, code: str) -> str:
    """Evolved variant A: re-parse per attempt instead of deepcopy.

    ``copy.deepcopy`` of the cached tree costs 4.4-6.6x more than a fresh
    ``ast.parse`` at every measured file size; parsing also guarantees the
    pristine-tree invariant that deepcopy existed to protect.
    """
    try:
        cached_parse(code)  # early syntax validation (keeps cache warm)
    except SyntaxError:
        return code

    mutations = [
        cls._swap_binary_ops,
        cls._replace_constant,
        cls._wrap_in_if,
        cls._negate_condition,
        cls._swap_comparison,
        cls._rename_variable,
        cls._duplicate_statement,
        cls._swap_if_else,
        cls._replace_aug_assign,
        cls._add_trivial_loop,
    ]

    random.shuffle(mutations)
    for mut_fn in mutations[:5]:
        try:
            new_tree = ast.parse(code)
            mut_fn(new_tree)
            ast.fix_missing_locations(new_tree)
            result = ast.unparse(new_tree)
            ast.parse(result)
            if result.strip() != code.strip():
                return result
        except (SyntaxError, ValueError, AttributeError, TypeError, IndexError):
            continue

    return code
'''

CANDIDATE_PICKLE = '''
def apply_random_mutation(cls, code: str) -> str:
    """Evolved variant B: pickle snapshot + loads per attempt."""
    try:
        tree = cached_parse(code)
    except SyntaxError:
        return code

    blob = pickle.dumps(tree, protocol=pickle.HIGHEST_PROTOCOL)

    mutations = [
        cls._swap_binary_ops,
        cls._replace_constant,
        cls._wrap_in_if,
        cls._negate_condition,
        cls._swap_comparison,
        cls._rename_variable,
        cls._duplicate_statement,
        cls._swap_if_else,
        cls._replace_aug_assign,
        cls._add_trivial_loop,
    ]

    random.shuffle(mutations)
    for mut_fn in mutations[:5]:
        try:
            new_tree = pickle.loads(blob)
            mut_fn(new_tree)
            ast.fix_missing_locations(new_tree)
            result = ast.unparse(new_tree)
            ast.parse(result)
            if result.strip() != code.strip():
                return result
        except (SyntaxError, ValueError, AttributeError, TypeError, IndexError):
            continue

    return code
'''

# ── Corpus del oráculo ────────────────────────────────────────────────────────

TINY = "def add(a, b):\n    return a + b\n"
LAMBDA_HEAVY = (
    "def pick(items):\n"
    "    best = max(items, key=lambda x: x.score if x.score else 0)\n"
    "    return sorted(items, key=lambda i: -i.rank), best\n"
)
BROKEN = "def broken(:\n    return ???\n"


def corpus():
    root = Path(__file__).resolve().parent.parent / "src" / "mutalambda"
    return [
        ("tiny", TINY),
        ("lambda_heavy", LAMBDA_HEAVY),
        ("broken_syntax", BROKEN),
        ("empty", ""),
        ("constants.py", (root / "constants.py").read_text()),
        ("fitness_vector.py", (root / "fitness_vector.py").read_text()),
        ("nsga2.py", (root / "nsga2.py").read_text()),
    ]


BENCH_FILES = ["constants.py", "fitness_vector.py", "nsga2.py", "muta_lambda.py"]


# ── Compilación de candidatos ─────────────────────────────────────────────────

def compile_candidate(src: str):
    """Compila una variante de apply_random_mutation y la liga a ASTMutator."""
    import ast as _ast
    import copy as _copy
    import pickle as _pickle
    from mutalambda.code_hash import cached_parse as _cached_parse

    src = textwrap.dedent(src)
    # tolera mutantes que conservan el decorador
    src = "\n".join(l for l in src.splitlines() if l.strip() != "@classmethod")
    namespace = {
        "ast": _ast, "copy": _copy, "pickle": _pickle, "random": random,
        "cached_parse": _cached_parse,
        "len": len, "enumerate": enumerate, "range": range,
    }
    try:
        exec(compile(src, "<candidate>", "exec"), namespace)  # noqa: S102
    except Exception:
        return None
    fn = namespace.get("apply_random_mutation")
    if not callable(fn):
        return None
    return functools.partial(fn, ASTMutator)


# ── Gates ─────────────────────────────────────────────────────────────────────

def gate_static(src: str):
    for check in (mf.check_empty_code(src), mf.check_syntax(textwrap.dedent(
                      "\n".join(l for l in src.splitlines()
                                if l.strip() != "@classmethod"))),
                  mf.check_max_length(src),
                  mf.check_no_critical_patterns(src, profile="self")):
        if check.blocked:
            return False, check.issues
    return True, []


def gate_correctness(fn, seeds=range(30)):
    """Oráculo diferencial sembrado: misma semilla => salida idéntica."""
    for name, code in corpus():
        for seed in seeds:
            random.seed(seed)
            expected = BASELINE_FN(code)
            random.seed(seed)
            try:
                got = fn(code)
            except Exception:
                return False
            if got != expected:
                return False
    return True


def bench(fn, repeats=5, seeds=range(8)):
    root = Path(__file__).resolve().parent.parent / "src" / "mutalambda"
    results = {}
    for fname in BENCH_FILES:
        code = (root / fname).read_text()
        random.seed(0); fn(code)  # warmup
        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            for seed in seeds:
                random.seed(seed)
                fn(code)
            times.append((time.perf_counter() - t0) / len(list(seeds)))
        results[fname] = statistics.median(times)
    return results


def decide(base_times, cand_times, min_gmean=1.10, max_regression=0.98):
    ratios = {k: base_times[k] / cand_times[k] for k in base_times}
    gmean = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
    ok = gmean >= min_gmean and all(r >= max_regression for r in ratios.values())
    return ok, gmean, ratios


# ── Experimento ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutants", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("=" * 74)
    print("Self-evolution ch.2 — target: ASTMutator.apply_random_mutation")
    print("=" * 74)

    print("\n[baseline] benchmark de referencia (ms/mutación) ...")
    base_times = bench(BASELINE_FN)
    for k, v in base_times.items():
        print(f"  {k:20} {v * 1e3:8.2f} ms")

    random.seed(args.seed)
    candidates = []
    for i in range(args.mutants):
        candidates.append((f"meta_mutant_{i:03d}",
                           ASTMutator.apply_random_mutation(MUTATION_BASE)))
    candidates.append(("engineered_reparse", CANDIDATE_REPARSE))
    candidates.append(("engineered_pickle", CANDIDATE_PICKLE))

    stats = {"total": 0, "gate_static": 0, "no_compile": 0, "identical": 0,
             "gate_correctness": 0, "gate_benchmark": 0, "accepted": []}
    fast_but_wrong = 0

    print(f"\n[pipeline] {len(candidates)} candidatos "
          f"({args.mutants} meta-mutantes + 2 reescrituras rol-LLM)\n")

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

        if src.strip() == BASELINE_SRC.strip() or src.strip() == MUTATION_BASE.strip():
            stats["identical"] += 1
            continue

        if not gate_correctness(fn):
            stats["gate_correctness"] += 1
            try:
                t = bench(fn, repeats=2, seeds=range(3))
                if t["nsga2.py"] < base_times["nsga2.py"] * 0.95:
                    fast_but_wrong += 1
            except Exception:
                pass
            continue

        cand_times = bench(fn)
        accepted, gmean, ratios = decide(base_times, cand_times)
        if not accepted:
            stats["gate_benchmark"] += 1
            print(f"  ✗ {name}: correcto pero speedup insuficiente (gmean {gmean:.2f}x)")
            continue

        stats["accepted"].append({
            "name": name,
            "gmean_speedup": round(gmean, 3),
            "ratios": {k: round(v, 3) for k, v in ratios.items()},
            "times_ms": {k: round(v * 1e3, 3) for k, v in cand_times.items()},
        })
        print(f"  ✓ {name}: ACEPTADO — gmean {gmean:.2f}x "
              f"({', '.join(f'{k}: {v:.2f}x' for k, v in ratios.items())})")

    print("\n" + "=" * 74)
    print("RESULTADOS")
    print("=" * 74)
    print(f"  candidatos totales:                  {stats['total']}")
    print(f"  rechazados por gates estáticos:      {stats['gate_static']}")
    print(f"  no compilan / no definen la función: {stats['no_compile']}")
    print(f"  idénticos al baseline:               {stats['identical']}")
    print(f"  rechazados por oráculo (semillas):   {stats['gate_correctness']}")
    print(f"    └─ 'más rápidos pero INCORRECTOS': {fast_but_wrong}")
    print(f"  correctos pero sin speedup >=1.10x:  {stats['gate_benchmark']}")
    print(f"  ACEPTADOS:                           {len(stats['accepted'])}")
    for acc in stats["accepted"]:
        print(f"    • {acc['name']}: {acc['gmean_speedup']}x")

    out = Path(__file__).parent / "self_evolution_astmutator_results.json"
    out.write_text(json.dumps({
        "target": "ASTMutator.apply_random_mutation",
        "seed": args.seed,
        "baseline_times_ms": {k: round(v * 1e3, 3) for k, v in base_times.items()},
        "stats": {k: v for k, v in stats.items() if k != "accepted"},
        "fast_but_wrong_rejected": fast_but_wrong,
        "accepted": stats["accepted"],
    }, indent=2))
    print(f"\n[json] resultados guardados en {out}")


if __name__ == "__main__":
    main()
