"""MutaLambda public benchmark harness.

Goal: produce *auditable* efficiency numbers against public benchmarks
(EffiBench, PIE, pyperformance/PolyBench, EffiBench+ with scientific
invariants, Rosetta Code cross-language, EoH) instead of self-reported
internal targets.

Design rules (see docs/BENCHMARKS.md):

1. The core (`bench.spec`, `bench.measure`, `bench.integrity`, `bench.report`)
   is **stdlib-only** so a reviewer can run it in a bare container.
2. No benchmark data is committed. Datasets are fetched on demand into a
   cache directory and hash-pinned (`bench.datasets`).
3. Every reported number carries: N repeats, mean ± std, correctness on a
   *held-out* test split, and an integrity verdict. A task whose integrity
   verdict is not ``clean`` is never counted as an improvement.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
