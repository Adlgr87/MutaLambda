"""``polybench`` — Tier 1. Thirty numerical kernels, the NumPy mutators' home turf.

PolyBench kernels (gemm, jacobi-2d, seidel-2d, correlation, ...) are pure
loop nests over dense arrays. They are where a claim like "our UAST-level
vectorisation is not marketing" either shows up as a 10-50x or does not show
up at all — there is nowhere to hide, because the reference NumPy formulation
of each kernel is well known.

The adapter reads the PolyBench/Python distribution from the dataset cache and
extracts each kernel's ``kernel_*`` function into a standalone task with a
deterministic array initialiser, so the harness can call it directly.

Kernels are run at a reduced dataset size by default (``MINI``/``SMALL``);
publication runs should use ``--size medium`` and say which size they used,
because speedups on these kernels are strongly size-dependent.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from bench.datasets import DatasetUnavailable, require
from bench.spec import BenchTask, Workload
from bench.suites._common import expected_for, limited, split_tests

SUITE = "polybench"
TIER = "tier1"
DATASET = "polybench-python"

SIZES = {"mini": 16, "small": 32, "medium": 64, "large": 128}

_HARNESS = '''
def _init_matrix(rows, cols, seed):
    return [[float(((i * cols + j + seed) % 13) + 1) / 13.0 for j in range(cols)]
            for i in range(rows)]


def _init_vector(n, seed):
    return [float(((i + seed) % 11) + 1) / 11.0 for i in range(n)]
'''


def _kernel_sources(root: Path) -> Dict[str, str]:
    """Extract ``def kernel(...)`` bodies from the PolyBench/Python tree."""
    kernels: Dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        if "test" in path.parts or path.name.startswith("_"):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("kernel"):
                try:
                    segment = ast.get_source_segment(source, node)
                except Exception:
                    segment = None
                if not segment or "self" in (node.args.args[0].arg if node.args.args else ""):
                    continue
                name = path.stem.replace("-", "_")
                kernels.setdefault(name, segment)
    return kernels


def _synthetic_kernels(n: int) -> Dict[str, str]:
    """Reference formulations used when the upstream tree is not cached.

    These are the textbook PolyBench kernels written in plain Python. They are
    *not* a substitute for the real distribution in a published run — the
    runner marks tasks built this way with ``metadata['synthetic'] = True`` and
    the report shows it.
    """
    return {
        "gemm": '''
def gemm(A, B, C, alpha, beta):
    ni = len(A); nk = len(B); nj = len(B[0])
    out = [[0.0] * nj for _ in range(ni)]
    for i in range(ni):
        for j in range(nj):
            acc = beta * C[i][j]
            for k in range(nk):
                acc += alpha * A[i][k] * B[k][j]
            out[i][j] = acc
    return out
''',
        "jacobi_1d": '''
def jacobi_1d(A, B, steps):
    n = len(A)
    A = list(A); B = list(B)
    for _ in range(steps):
        for i in range(1, n - 1):
            B[i] = 0.33333 * (A[i - 1] + A[i] + A[i + 1])
        for i in range(1, n - 1):
            A[i] = 0.33333 * (B[i - 1] + B[i] + B[i + 1])
    return A
''',
        "atax": '''
def atax(A, x):
    m = len(A); n = len(A[0])
    y = [0.0] * n
    tmp = [0.0] * m
    for i in range(m):
        acc = 0.0
        for j in range(n):
            acc += A[i][j] * x[j]
        tmp[i] = acc
    for i in range(m):
        for j in range(n):
            y[j] += A[i][j] * tmp[i]
    return y
''',
        "correlation": '''
def correlation(data):
    n = len(data); m = len(data[0])
    mean = [0.0] * m
    for j in range(m):
        acc = 0.0
        for i in range(n):
            acc += data[i][j]
        mean[j] = acc / n
    stddev = [0.0] * m
    for j in range(m):
        acc = 0.0
        for i in range(n):
            d = data[i][j] - mean[j]
            acc += d * d
        stddev[j] = (acc / n) ** 0.5 or 1.0
    corr = [[0.0] * m for _ in range(m)]
    for i in range(m):
        for j in range(m):
            acc = 0.0
            for k in range(n):
                acc += ((data[k][i] - mean[i]) / stddev[i]) * \
                       ((data[k][j] - mean[j]) / stddev[j])
            corr[i][j] = acc / n
    return corr
''',
    }


def _tasks_from_synthetic(size: int) -> List[BenchTask]:
    kernels = _synthetic_kernels(size)
    tasks: List[BenchTask] = []

    def matrix(rows: int, cols: int, seed: int) -> List[List[float]]:
        return [[float(((i * cols + j + seed) % 13) + 1) / 13.0 for j in range(cols)]
                for i in range(rows)]

    def vector(n: int, seed: int) -> List[float]:
        return [float(((i + seed) % 11) + 1) / 11.0 for i in range(n)]

    args_by_kernel: Dict[str, Dict[str, List[List[Any]]]] = {
        "gemm": {
            "visible": [[matrix(4, 4, 1), matrix(4, 4, 2), matrix(4, 4, 3), 1.5, 0.5],
                        [matrix(6, 5, 4), matrix(5, 7, 2), matrix(6, 7, 1), 0.9, 1.1]],
            "holdout": [[matrix(3, 8, 5), matrix(8, 2, 6), matrix(3, 2, 7), 2.0, 0.25],
                        [matrix(7, 7, 8), matrix(7, 7, 9), matrix(7, 7, 3), 0.1, 3.0],
                        [matrix(9, 4, 2), matrix(4, 6, 4), matrix(9, 6, 6), 1.0, 1.0]],
            "workload": [[matrix(size, size, 1), matrix(size, size, 2),
                          matrix(size, size, 3), 1.5, 0.5]],
        },
        "jacobi_1d": {
            "visible": [[vector(16, 1), vector(16, 2), 3], [vector(24, 3), vector(24, 4), 2]],
            "holdout": [[vector(8, 5), vector(8, 6), 1], [vector(32, 7), vector(32, 8), 4],
                        [vector(40, 9), vector(40, 1), 2]],
            "workload": [[vector(size * 8, 1), vector(size * 8, 2), 12]],
        },
        "atax": {
            "visible": [[matrix(6, 6, 1), vector(6, 2)], [matrix(8, 5, 3), vector(5, 4)]],
            "holdout": [[matrix(4, 9, 5), vector(9, 6)], [matrix(10, 10, 7), vector(10, 8)],
                        [matrix(12, 3, 9), vector(3, 1)]],
            "workload": [[matrix(size * 2, size * 2, 1), vector(size * 2, 2)]],
        },
        "correlation": {
            "visible": [[matrix(6, 4, 1)], [matrix(9, 5, 2)]],
            "holdout": [[matrix(4, 4, 3)], [matrix(12, 6, 4)], [matrix(15, 3, 5)]],
            "workload": [[matrix(size * 2, max(8, size // 2), 1)]],
        },
    }

    for name, code in kernels.items():
        spec = args_by_kernel[name]
        tests_visible = expected_for(code, name, spec["visible"], comparison="array_allclose")
        tests_holdout = expected_for(code, name, spec["holdout"], comparison="array_allclose")
        tasks.append(BenchTask(
            task_id=f"polybench/{name}",
            suite=SUITE,
            tier=TIER,
            source_code=code,
            entrypoint=name,
            workload=Workload(calls=[[a, {}] for a in spec["workload"]],
                              warmups=1, samples=7, timeout_sec=180.0),
            visible_tests=tests_visible,
            holdout_tests=tests_holdout,
            invariants=["finite", "determinism"],
            metadata={
                "source": "PolyBench kernels (reference formulation)",
                "synthetic": True,
                "size": size,
                "numpy_friendly": True,
                "note": "upstream PolyBench/Python not cached; textbook formulation used",
            },
        ))
    return tasks


def load_tasks(limit: Optional[int] = None, size: str = "medium",
               allow_synthetic: bool = True) -> List[BenchTask]:
    n = SIZES.get(size, SIZES["medium"])
    try:
        root = require(DATASET, SUITE)
    except DatasetUnavailable:
        if not allow_synthetic:
            raise
        return limited(_tasks_from_synthetic(n), limit)

    kernels = _kernel_sources(root)
    if not kernels:
        if not allow_synthetic:
            raise DatasetUnavailable(
                f"no kernels extracted from {root}; upstream layout changed"
            )
        return limited(_tasks_from_synthetic(n), limit)

    # Upstream kernels mutate arrays in place through a class; wiring every one
    # of the 30 automatically is future work, so the extracted set is exposed
    # only when it can be called standalone.
    tasks: List[BenchTask] = []
    for name, code in kernels.items():
        if re.search(r"\bself\b", code):
            continue
        tasks.append(BenchTask(
            task_id=f"polybench/{name}",
            suite=SUITE, tier=TIER,
            source_code=code + _HARNESS,
            entrypoint=name,
            workload=Workload(calls=[], warmups=1, samples=5, timeout_sec=180.0),
            metadata={"source": "PolyBench/Python", "size": size, "needs_wiring": True},
        ))
    usable = [t for t in tasks if t.workload.calls]
    if not usable and allow_synthetic:
        return limited(_tasks_from_synthetic(n), limit)
    return limited(usable, limit)
