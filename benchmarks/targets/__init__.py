"""Benchmark targets for MutaLambda Bloque D.

Each target module exposes:
  - TARGET_NAME: str
  - TIER: int (1-4)
  - source: str  (the original/reference implementation)
  - function_name: str
  - test_cases: list[dict]  (declarative, used by Layer 1 + differential)
  - invariants: list[str]   (Hypothesis property expressions as strings)
  - input_strategy: str     (hypothesis strategy expression for random args)
"""
