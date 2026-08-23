"""``smoke`` — self-contained suite that validates the harness itself.

No downloads, no LLM, ~10 tasks whose slow version has a well-known faster
form. Its jobs:

1. **Prove the harness is honest.** ``--optimizer baseline`` must report
   1.00x ± noise on every task. If it does not, the measurement is broken and
   nothing else in this directory can be trusted.
2. **Prove the integrity gates bite.** ``tests/bench`` feeds it deliberately
   cheating candidates (hardcoded tables, no-op entrypoints, memoisers) and
   asserts they are rejected.
3. Give CI something to run in seconds.

It is explicitly *not* a benchmark result. Nothing from this suite belongs in
a README claim.
"""

from __future__ import annotations

from typing import List, Optional

from bench.spec import BenchTask
from bench.suites._common import limited, make_task

SUITE = "smoke"
TIER = "tier1"
DATASET = ""

_SUM_SQUARES = '''
def sum_squares(n):
    total = 0
    for i in range(1, n + 1):
        total += i * i
    return total
'''

_DEDUPE = '''
def dedupe(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out
'''

_COUNT_PAIRS = '''
def count_pairs(values, target):
    count = 0
    n = len(values)
    for i in range(n):
        for j in range(i + 1, n):
            if values[i] + values[j] == target:
                count += 1
    return count
'''

_WORD_FREQ = '''
def top_words(words, k):
    seen = []
    counts = []
    for w in words:
        if w not in seen:
            seen.append(w)
            counts.append(words.count(w))
    pairs = list(zip(seen, counts))
    pairs.sort(key=lambda p: (-p[1], p[0]))
    return pairs[:k]
'''

_MOVING_AVG = '''
def moving_average(series, window):
    out = []
    for i in range(len(series) - window + 1):
        total = 0.0
        for j in range(i, i + window):
            total += series[j]
        out.append(total / window)
    return out
'''

_PRIMES = '''
def count_primes(limit):
    count = 0
    for n in range(2, limit):
        is_prime = True
        for d in range(2, n):
            if n % d == 0:
                is_prime = False
                break
        if is_prime:
            count += 1
    return count
'''

_MATMUL = '''
def matmul(a, b):
    n = len(a)
    m = len(b[0])
    k = len(b)
    out = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            acc = 0.0
            for t in range(k):
                acc += a[i][t] * b[t][j]
            out[i][j] = acc
    return out
'''

_FIB = '''
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
'''

# Scientific-mode style task: the physics must survive the optimization.
_PROJECTILE = '''
def projectile_energy(mass, speed, height, steps):
    g = 9.80665
    kinetic = 0.0
    potential = 0.0
    for i in range(steps):
        frac = (i + 1) / steps
        kinetic += 0.5 * mass * (speed * speed) / steps
        potential += mass * g * height * frac / steps * 0.0
    potential += mass * g * height
    return {"kinetic": kinetic, "potential": potential,
            "total": kinetic + potential}
'''

_NORMALIZE = '''
def normalize(values):
    lo = values[0]
    hi = values[0]
    for v in values:
        if v < lo:
            lo = v
        if v > hi:
            hi = v
    span = hi - lo
    out = []
    for v in values:
        if span == 0:
            out.append(0.0)
        else:
            out.append((v - lo) / span)
    return out
'''


def _seq(n: int, mul: int = 7, mod: int = 1013) -> List[int]:
    return [(i * mul) % mod for i in range(n)]


def _words(n: int) -> List[str]:
    base = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]
    return [base[(i * 3) % len(base)] for i in range(n)]


def _matrix(n: int, seed: int) -> List[List[float]]:
    return [[float(((i * n + j) * seed) % 17) for j in range(n)] for i in range(n)]


def load_tasks(limit: Optional[int] = None) -> List[BenchTask]:
    tasks: List[BenchTask] = [
        make_task(
            task_id="smoke/sum_squares", suite=SUITE, tier=TIER,
            source_code=_SUM_SQUARES, entrypoint="sum_squares",
            visible_args=[[10], [100], [1000]],
            holdout_args=[[0], [1], [7], [4321], [99999]],
            workload_args=[[20000], [20000]],
            metadata={"known_optimization": "closed form n(n+1)(2n+1)/6"},
        ),
        make_task(
            task_id="smoke/dedupe", suite=SUITE, tier=TIER,
            source_code=_DEDUPE, entrypoint="dedupe",
            visible_args=[[[1, 1, 2]], [_seq(50)], [_seq(200)]],
            holdout_args=[[[]], [[5]], [[3, 3, 3, 3]], [_seq(137, 11)], [_seq(400, 13)]],
            workload_args=[[_seq(2500)]],
            metadata={"known_optimization": "set-based membership, order preserved"},
        ),
        make_task(
            task_id="smoke/count_pairs", suite=SUITE, tier=TIER,
            source_code=_COUNT_PAIRS, entrypoint="count_pairs",
            visible_args=[[[1, 2, 3], 4], [_seq(60), 500], [_seq(120), 900]],
            holdout_args=[[[], 3], [[2, 2], 4], [_seq(90, 5), 311],
                          [_seq(150, 3), 777], [_seq(200, 9), 1200]],
            workload_args=[[_seq(700), 900]],
            metadata={"known_optimization": "hash map complement counting"},
        ),
        make_task(
            task_id="smoke/top_words", suite=SUITE, tier=TIER,
            source_code=_WORD_FREQ, entrypoint="top_words",
            visible_args=[[_words(30), 3], [_words(120), 2], [_words(300), 5]],
            holdout_args=[[[], 3], [["x"], 1], [_words(77), 4],
                          [_words(211), 7], [_words(500), 3]],
            workload_args=[[_words(9000), 5]],
            metadata={"known_optimization": "single-pass counting (Counter)"},
        ),
        make_task(
            task_id="smoke/moving_average", suite=SUITE, tier=TIER,
            source_code=_MOVING_AVG, entrypoint="moving_average",
            visible_args=[[[1.0, 2.0, 3.0, 4.0], 2], [[float(v) for v in _seq(100)], 10],
                          [[float(v) for v in _seq(300)], 25]],
            holdout_args=[[[1.0], 1], [[float(v) for v in _seq(50)], 7],
                          [[float(v) for v in _seq(180)], 12],
                          [[float(v) for v in _seq(240, 3)], 30],
                          [[float(v) for v in _seq(400, 11)], 50]],
            workload_args=[[[float(v) for v in _seq(4000)], 64]],
            comparison="sequence_close",
            invariants=["finite", "determinism"],
            metadata={"known_optimization": "prefix sums / rolling window"},
        ),
        make_task(
            task_id="smoke/count_primes", suite=SUITE, tier=TIER,
            source_code=_PRIMES, entrypoint="count_primes",
            visible_args=[[10], [100], [500]],
            holdout_args=[[0], [2], [3], [977], [2000]],
            workload_args=[[3000]],
            metadata={"known_optimization": "sqrt bound or sieve"},
        ),
        make_task(
            task_id="smoke/matmul", suite=SUITE, tier=TIER,
            source_code=_MATMUL, entrypoint="matmul",
            visible_args=[[_matrix(4, 1), _matrix(4, 2)], [_matrix(8, 3), _matrix(8, 5)],
                          [_matrix(12, 7), _matrix(12, 2)]],
            holdout_args=[[_matrix(1, 1), _matrix(1, 1)], [_matrix(5, 2), _matrix(5, 9)],
                          [_matrix(9, 4), _matrix(9, 6)], [_matrix(16, 3), _matrix(16, 8)],
                          [_matrix(20, 5), _matrix(20, 11)]],
            workload_args=[[_matrix(40, 3), _matrix(40, 7)]],
            comparison="array_allclose",
            invariants=["finite", "determinism"],
            metadata={"known_optimization": "NumPy dot / transposed inner loop",
                      "numpy_friendly": True},
        ),
        make_task(
            task_id="smoke/fib", suite=SUITE, tier=TIER,
            source_code=_FIB, entrypoint="fib",
            visible_args=[[5], [10], [15]],
            holdout_args=[[0], [1], [2], [18], [24]],
            workload_args=[[21]],
            metadata={"known_optimization": "memoisation or iteration; note that "
                                            "memoisation also trips the harness' "
                                            "cross-call cache flag by design"},
        ),
        make_task(
            task_id="smoke/projectile_energy", suite=SUITE, tier=TIER,
            source_code=_PROJECTILE, entrypoint="projectile_energy",
            visible_args=[[1.0, 10.0, 5.0, 100], [2.5, 3.0, 1.0, 250], [0.5, 20.0, 12.0, 500]],
            holdout_args=[[1.0, 0.0, 0.0, 10], [3.0, 7.5, 2.0, 800],
                          [10.0, 1.0, 100.0, 300], [0.1, 50.0, 0.5, 1200],
                          [7.0, 12.0, 8.0, 640]],
            workload_args=[[2.0, 15.0, 9.0, 20000]],
            comparison="equal",
            invariants=["finite", "non_negative", "determinism"],
            metadata={
                "scientific": True,
                "known_optimization": "closed form; kinetic term is loop-invariant",
                "invariant_params": {"non_negative": {"tol": 1e-9}},
            },
        ),
        make_task(
            task_id="smoke/normalize", suite=SUITE, tier=TIER,
            source_code=_NORMALIZE, entrypoint="normalize",
            visible_args=[[[1.0, 2.0, 3.0]], [[float(v) for v in _seq(100)]],
                          [[float(v) for v in _seq(400, 3)]]],
            holdout_args=[[[0.0]], [[2.0, 2.0, 2.0]], [[float(v) for v in _seq(64, 5)]],
                          [[float(v) for v in _seq(250, 7)]],
                          [[float(v) for v in _seq(600, 13)]]],
            workload_args=[[[float(v) for v in _seq(60000)]]],
            comparison="sequence_close",
            invariants=["finite", "bounded", "determinism"],
            metadata={
                "known_optimization": "min/max builtins, single comprehension",
                "invariant_params": {"bounded": {"low": 0.0, "high": 1.0, "tol": 1e-9}},
            },
        ),
    ]
    return limited(tasks, limit)
