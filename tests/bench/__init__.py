"""Tests for the benchmark harness.

Two things are being asserted here, and they matter more than the harness'
features:

1. **The measurement is unbiased** — an identity "optimization" must not
   produce a speedup.
2. **The cheats are caught** — hardcoded answer tables, no-op entrypoints,
   forbidden imports, held-out failures and clock tampering must all be
   rejected, because every one of them is a way to publish a fake 10x.
"""
