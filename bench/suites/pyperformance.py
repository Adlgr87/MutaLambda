"""``pyperformance`` — Tier 1, planned.

Why it is not implemented yet, in plain terms: pyperformance benchmarks are
*whole applications* (django templates, chameleon, tornado, sqlalchemy) driven
by a harness that owns setup, teardown and the timing loop. There is no
"function to optimize" — feeding one of its modules to an evolutionary
optimizer without a defined optimization surface would produce numbers that
look great and mean nothing.

Doing it honestly requires, in order:

1. an adapter that runs ``pyperformance run --benchmarks <b>`` to get a
   baseline distribution, in JSON, on the reviewer's own machine;
2. a *surface selector* — the specific module(s) in the benchmark's
   dependency tree the optimizer is allowed to rewrite, declared per
   benchmark and published;
3. re-running the untouched upstream harness against the patched surface, so
   the timing loop is upstream's and not ours;
4. correctness from the benchmark's own asserts plus a byte-comparison of its
   output where one exists.

Until (2) and (3) exist, this suite raises. PolyBench covers the numeric side
of the same argument today, and ``bench.suites.polybench`` is the place to
look for evidence about vectorisation.
"""

from __future__ import annotations

from typing import List, Optional

from bench.datasets import DatasetUnavailable
from bench.spec import BenchTask

SUITE = "pyperformance"
TIER = "tier1"
DATASET = "pyperformance"

PLAN = [
    "run upstream `pyperformance run --output baseline.json`",
    "declare an optimization surface per benchmark (which modules may change)",
    "re-run upstream harness against the patched surface",
    "compare with `pyperformance compare baseline.json patched.json`",
]


def load_tasks(limit: Optional[int] = None) -> List[BenchTask]:
    raise DatasetUnavailable(
        "suite 'pyperformance' is not implemented yet (status: planned).\n"
        "  It needs a declared optimization surface per benchmark before any\n"
        "  number it produces would be meaningful. Plan:\n    - "
        + "\n    - ".join(PLAN)
        + "\n  Use 'polybench' for numeric-kernel evidence in the meantime."
    )
